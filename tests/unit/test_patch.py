"""Tests for the unified diff parser."""

from kernel_tracker.patch import PatchParser

SIMPLE_DIFF = """\
diff --git a/README.md b/README.md
index 1234567..abcdef0 100644
--- a/README.md
+++ b/README.md
@@ -1,3 +1,4 @@
 Hello
+World
 Goodbye
 End
"""

MULTI_FILE_DIFF = """\
diff --git a/file1.py b/file1.py
index 1111111..2222222 100644
--- a/file1.py
+++ b/file1.py
@@ -1,2 +1,3 @@
 line1
+added
 line2
diff --git a/file2.py b/file2.py
index 3333333..4444444 100644
--- a/file2.py
+++ b/file2.py
@@ -1,3 +1,2 @@
 line_a
-line_b
 line_c
"""

RENAME_DIFF = """\
diff --git a/old_name.py b/new_name.py
similarity index 100%
rename from old_name.py
rename to new_name.py
"""

EMPTY_DIFF = ""

DELETE_DIFF = """\
diff --git a/deleted.py b/deleted.py
deleted file mode 100644
index 1234567..0000000
--- a/deleted.py
+++ /dev/null
@@ -1,3 +0,0 @@
-line1
-line2
-line3
"""


class TestPatchParser:
    """Test the unified diff parser."""

    def test_simple_diff(self):
        """Parse a simple single-file diff."""
        patch = PatchParser("abc123", SIMPLE_DIFF).parse()
        assert len(patch) == 1
        assert patch[0].name == "README.md"
        assert patch[0].new_name == "README.md"
        assert patch[0].added == 1
        assert patch[0].removed == 0

    def test_multi_file_diff(self):
        """Parse a diff with multiple files."""
        patch = PatchParser("abc123", MULTI_FILE_DIFF).parse()
        assert len(patch) == 2
        names = sorted(f.name for f in patch)
        assert names == ["file1.py", "file2.py"]

    def test_multi_file_changes(self):
        """Verify added/removed counts in multi-file diff."""
        patch = PatchParser("abc123", MULTI_FILE_DIFF).parse()
        f1 = next(f for f in patch if f.name == "file1.py")
        f2 = next(f for f in patch if f.name == "file2.py")
        assert f1.added == 1
        assert f1.removed == 0
        assert f2.added == 0
        assert f2.removed == 1

    def test_rename_diff(self):
        """Parse a rename diff."""
        patch = PatchParser("abc123", RENAME_DIFF).parse()
        assert len(patch) == 1
        assert patch[0].name == "old_name.py"
        assert patch[0].new_name == "new_name.py"

    def test_empty_diff(self):
        """An empty diff should produce an empty patch."""
        patch = PatchParser("abc123", EMPTY_DIFF).parse()
        assert len(patch) == 0

    def test_delete_diff(self):
        """Parse a file deletion diff."""
        patch = PatchParser("abc123", DELETE_DIFF).parse()
        assert len(patch) == 1
        assert patch[0].name == "deleted.py"
        assert patch[0].new_null is True
        assert patch[0].removed == 3
        assert patch[0].added == 0

    def test_hunk_header(self):
        """Verify hunk headers are preserved."""
        patch = PatchParser("abc123", SIMPLE_DIFF).parse()
        hunk = patch[0][0]
        assert hunk.header.startswith("@@")
        assert hunk.stat[0] == 1  # old start
        assert hunk.stat[1] == 1  # new start

    def test_diff_lines(self):
        """Verify individual diff lines are parsed correctly."""
        patch = PatchParser("abc123", SIMPLE_DIFF).parse()
        hunk = patch[0][0]
        lines = list(hunk)
        # Should have: "Hello" (context), "+World" (added), "Goodbye" (context), "End" (context)
        assert len(lines) == 4
        assert lines[0].origin == " "
        assert lines[0].content == "Hello"
        assert lines[1].origin == "+"
        assert lines[1].content == "World"
        assert lines[2].origin == " "
        assert lines[2].content == "Goodbye"

    def test_max_changes(self):
        """Verify max_changes is computed correctly."""
        patch = PatchParser("abc123", MULTI_FILE_DIFF).parse()
        assert patch.max_changes == max(f.changes for f in patch)

    def test_file_sorting(self):
        """Files should be sorted by name."""
        patch = PatchParser("abc123", MULTI_FILE_DIFF).parse()
        names = [f.name for f in patch]
        assert names == sorted(names)
