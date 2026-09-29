"""Unified diff parser.

Parses unified diff output into structured Patch/File/Hunk/Line objects
for display in the web UI. The Levenshtein-based hunk comparison for
detecting partial/unclean backports is deferred to Phase 2.
"""

import enum
import re


class EncapsulatedList:
    """Base class providing list-like access with encapsulated storage."""

    def __init__(self):
        self._list = []

    def __len__(self):
        return len(self._list)

    def __getitem__(self, key):
        return self._list[key]

    def __iter__(self):
        return iter(self._list)

    def append(self, item):
        self._list.append(item)


class Patch(EncapsulatedList):
    """A parsed diff containing a list of DiffFile objects."""

    def __init__(self, identifier):
        super().__init__()
        self.identifier = identifier

    def postprocess(self):
        self._list.sort()
        if len(self._list) > 0:
            self.max_changes = max(self._list, key=lambda x: x.changes).changes
        else:
            self.max_changes = 0

    def get_line(self, path, line_no, old, count):
        """Return the given line and up to (count-1) previous lines.

        The line is identified by path and line number.
        If old == True, uses old path and removed line numbers.
        If old == False, uses new path and added line numbers.
        Returns None if no such line could be found.
        """
        for f in self:
            if (old and f.name == path) or (not old and f.new_name == path):
                break
        else:
            return None
        stat_index = 0 if old else 1
        for h in f:
            start = h.stat[stat_index]
            end = h.stat[stat_index + 2] + start
            if line_no >= start and line_no < end:
                break
        else:
            return None
        last = None
        for i, line in enumerate(h):
            if (old and line.old_pos == line_no) or (
                not old and line.new_pos == line_no
            ):
                last = i
            elif last is not None:
                break
        return h[max(0, last - count + 1) : last + 1]


class DiffFile(EncapsulatedList):
    """A single file within a diff, containing a list of Hunks."""

    def __init__(self):
        super().__init__()
        self.name = ""
        self.new_name = ""
        self.old_null = False
        self.new_null = False
        self.headers = []
        self.file_id = 0

    def set_names(self, old_name, new_name):
        if old_name is not None:
            self.old_null = old_name == "/dev/null"
            self.name = old_name.removeprefix("a/")
        if new_name is not None:
            self.new_null = new_name == "/dev/null"
            self.new_name = new_name.removeprefix("b/")

    @property
    def added(self):
        return sum(1 for h in self for l in h if l.origin == "+")

    @property
    def removed(self):
        return sum(1 for h in self for l in h if l.origin == "-")

    @property
    def changes(self):
        return self.added + self.removed

    def __lt__(self, other):
        return self.name < other.name

    def postprocess(self):
        self._list.sort()


class Hunk(EncapsulatedList):
    """A single hunk within a file diff."""

    def __init__(self):
        super().__init__()
        self.header = ""
        self.stat = (0, 0, 0, 0)  # (old_start, new_start, old_count, new_count)
        self.counted = {"\\": False}
        self.old_pos = 0
        self.new_pos = 0

    def append_line(self, origin, content):
        self.counted["\\"] = origin == "\\"
        line = DiffLine(origin, content)
        if origin == "-":
            line.old_pos = self.old_pos
            self.old_pos += 1
        elif origin == "+":
            line.new_pos = self.new_pos
            self.new_pos += 1
        elif origin == " ":
            line.old_pos = self.old_pos
            line.new_pos = self.new_pos
            self.old_pos += 1
            self.new_pos += 1
        elif origin == "\\":
            pass
        self.append(line)

    def __lt__(self, other):
        return self.stat < other.stat


class DiffLine:
    """A single line within a hunk."""

    __slots__ = ("content", "new_pos", "old_pos", "origin")

    def __init__(self, origin, content):
        self.origin = origin
        self.content = content
        self.old_pos = 0
        self.new_pos = 0


class State(enum.IntEnum):
    """Parser state machine states."""

    DESCRIPTION = 0
    FILE_HEADER = 1
    PRE_HUNK = 2
    HUNK = 3
    POST_HUNK = 4
    FINISHED = 5


class _Eof(Exception):
    pass


class PatchParser:
    """Parses unified diff text into a Patch object."""

    def __init__(self, identifier, text):
        self.patch = Patch(identifier)
        self.state = State.DESCRIPTION
        self.file = DiffFile()
        self.hunk = Hunk()
        self.description = []
        self._lines = text.split("\n") if text else []
        self._pos = 0
        self._file_id = 0

    def readline(self):
        if self._pos >= len(self._lines):
            raise _Eof()
        line = self._lines[self._pos]
        self._pos += 1
        return line

    def peakline(self):
        if self._pos >= len(self._lines):
            return ""
        return self._lines[self._pos]

    def ensure_state(self, msg, *states):
        if self.state not in states:
            raise self.error(msg)

    def error(self, msg):
        return ValueError(f"{msg} (line {self._pos})")

    def strip_path(self, path):
        """Strip a/ or b/ prefix from a diff path."""
        for prefix in ("a/", "b/"):
            if path.startswith(prefix):
                return path[len(prefix) :]
        # Handle /dev/null and other paths
        return path

    def ship_hunk(self):
        if len(self.hunk) > 0 or self.hunk.header:
            self.file.append(self.hunk)
        self.hunk = Hunk()

    def ship_file(self):
        self.ship_hunk()
        if len(self.file) > 0 or self.file.headers:
            self.file.postprocess()
            self.patch.append(self.file)
        self.file = DiffFile()

    def check_hunk_complete(self):
        old_count = self.hunk.stat[2]
        new_count = self.hunk.stat[3]
        actual_old = sum(1 for l in self.hunk if l.origin in ("-", " "))
        actual_new = sum(1 for l in self.hunk if l.origin in ("+", " "))
        return actual_old >= old_count and actual_new >= new_count

    def parse_step(self, line):
        if line.startswith("diff --git "):
            parts = line.split(maxsplit=4)
            if len(parts) >= 4:
                first = parts[2]
                second = parts[3]
                if first.find("/") >= 0 and second.find("/") >= 0:
                    self.ensure_state(
                        "Invalid diff header",
                        State.DESCRIPTION,
                        State.FILE_HEADER,
                        State.PRE_HUNK,
                        State.HUNK,
                        State.POST_HUNK,
                    )
                    self.ship_file()
                    self.file.headers = [line]
                    self._file_id += 1
                    self.file.file_id = self._file_id
                    self.file.set_names(self.strip_path(first), self.strip_path(second))
                    self.state = State.FILE_HEADER
                    return

        if (
            line.startswith("--- ")
            and line.find("/") >= 0
            and (self.state != State.HUNK or self.check_hunk_complete())
        ):
            self.ensure_state(
                "Invalid file header format",
                State.DESCRIPTION,
                State.FILE_HEADER,
                State.HUNK,
                State.POST_HUNK,
            )
            if self.state != State.FILE_HEADER:
                self.ship_file()
                self._file_id += 1
                self.file.file_id = self._file_id
            old_path = self.strip_path(line[4:])
            line = self.readline()
            if not line.startswith("+++ "):
                raise self.error("Invalid file header format")
            new_path = self.strip_path(line[4:])
            self.file.set_names(old_path, new_path)
            self.state = State.PRE_HUNK
            return

        if self.state == State.FILE_HEADER:
            self.file.headers.append(line)
            if line.startswith("rename from "):
                self.file.set_names(line[12:], None)
            elif line.startswith("rename to "):
                self.file.set_names(None, line[10:])
            elif line.startswith("new file "):
                self.file.set_names("/dev/null", None)
            elif line.startswith("deleted file "):
                self.file.set_names(None, "/dev/null")
            elif line.startswith("Binary files "):
                m = re.match(r"Binary files (.*) and (.*) differ", line)
                if m:
                    self.file.set_names(
                        self.strip_path(m.group(1)),
                        self.strip_path(m.group(2)),
                    )
            return

        if (
            line.startswith("@@ ")
            and self.state >= State.PRE_HUNK
            and self.state < State.FINISHED
        ):
            self.ship_hunk()
            components = line.split(maxsplit=4)
            if (
                len(components) < 4
                or components[3] != "@@"
                or not components[1].startswith("-")
                or not components[2].startswith("+")
            ):
                raise self.error("Invalid hunk header format")
            src = components[1][1:].split(",", maxsplit=1)
            dst = components[2][1:].split(",", maxsplit=1)
            if len(src) == 1:
                src.append(1)
            if len(dst) == 1:
                dst.append(1)
            try:
                self.hunk.stat = (int(src[0]), int(dst[0]), int(src[1]), int(dst[1]))
                self.hunk.old_pos = int(src[0])
                self.hunk.new_pos = int(dst[0])
            except IndexError, ValueError:
                raise self.error("Invalid hunk header format") from None
            self.hunk.header = line
            self.state = State.HUNK
            return

        if self.state == State.HUNK:
            if not line or line[0] not in ("+", "-", " ", "\\"):
                raise self.error("Garbage in patch content")
            if line[0] == " " and self.hunk.counted["\\"]:
                raise self.error("Context line present after a no-newline indicator")
            self.hunk.append_line(line[0], line[1:])
            if self.check_hunk_complete():
                next_line = self.peakline()
                if next_line.startswith("\\"):
                    self.hunk.append_line(next_line[0], next_line[1:])
                    self.readline()
                self.state = State.POST_HUNK
            return

        if self.state == State.DESCRIPTION:
            self.description.append(line)
            return

        if self.state >= State.POST_HUNK:
            self.state = State.FINISHED
            return

        raise self.error("Garbage in patch content")

    def parse(self):
        """Parse the diff text and return a Patch object."""
        try:
            while True:
                line = self.readline()
                self.parse_step(line)
        except _Eof:
            pass
        self.ship_file()
        self.patch.description = "\n".join(self.description).rstrip("\n")
        self.patch.postprocess()
        return self.patch
