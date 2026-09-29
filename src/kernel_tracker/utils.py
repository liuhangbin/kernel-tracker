"""Git utility functions.

Provides helpers for fetching, walking, diffing, and formatting
git objects. Some operations can use either pygit2 directly or
external git commands (controlled by settings.PYGIT_WORKAROUNDS).
"""

import datetime
import re
import subprocess
import sys
import urllib.parse

import pygit2
from django.conf import settings
from pygit2.enums import ObjectType

from kernel_tracker.patch import PatchParser
from kernel_tracker.repository import repository


def abbrev(commit_id):
    """Return the first 12 characters of a commit ID."""
    return str(commit_id)[:12]


def normalize(rev):
    """Resolve a revision to a pygit2 Oid.

    Accepts pygit2.Oid, pygit2.Commit, or a string (ref, tag, hash).
    """
    if not rev:
        return None
    if isinstance(rev, pygit2.Oid):
        return rev
    if isinstance(rev, pygit2.Commit):
        return rev.id
    if isinstance(rev, str):
        obj = repository.revparse_single(rev)
        if obj.type == ObjectType.TAG:
            obj = obj.peel(None)
        return obj.id
    raise TypeError(f"unknown type ({rev.__class__.__name__})")


def message(msg, terminate=False):
    """Write a progress message to stdout (overwrites current line)."""
    sys.stdout.write(f"\x1b[K{msg}{'\\n' if terminate else '\\r'}")


def percent(done, total):
    """Return the percentage of done/total as an integer."""
    try:
        return done * 100 // total
    except ZeroDivisionError:
        return 0


def eta(done, total, start, now):
    """Return a human-readable ETA string."""
    try:
        sec = (now - start) / done * (total - done)
    except ZeroDivisionError:
        return "unknown"
    if sec <= 120:
        return f"{int(sec)}s"
    m = sec / 60
    h = int(m / 60)
    m = int(m) % 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def fetch(remote, fetch_tags, output):
    """Fetch from a git remote using the git command.

    Uses subprocess because pygit2's fetch has limitations with
    some authentication methods and proxy configurations.
    """
    args = ["git", "--git-dir", settings.GIT_REPO, "fetch"]
    if not fetch_tags:
        args.append("--no-tags")
    if not output:
        args.append("--quiet")
    args.append(remote.name)
    subprocess.run(args, check=True)
    if output:
        sys.stdout.write("Fetched.\n")


def _describe_internal(commit_id):
    return repository.describe(commit_id, always_use_long_format=True)


def _describe_external(commit_id):
    args = [
        "git",
        "--git-dir",
        settings.GIT_REPO,
        "describe",
        "--long",
        commit_id,
    ]
    p = subprocess.run(args, check=False, stdout=subprocess.PIPE, errors="ignore")
    return p.stdout.strip()


describe = globals()[
    f"_describe_{'external' if settings.PYGIT_WORKAROUNDS else 'internal'}"
]


def _diff_internal(pygit2_commit):
    """Generate a unified diff using pygit2."""
    if len(pygit2_commit.parents) > 1:
        return ""
    if len(pygit2_commit.parents) == 0:
        diff = pygit2_commit.tree.diff_to_tree(swap=True)
    else:
        diff = pygit2_commit.parents[0].tree.diff_to_tree(pygit2_commit.tree)
    if len(diff) >= 1000:
        # Very large commit — skip to avoid OOM
        return ""
    diff.find_similar()
    return diff.patch


def _diff_external(pygit2_commit):
    """Generate a unified diff using the git command."""
    args = [
        "git",
        "--git-dir",
        settings.GIT_REPO,
        "show",
        "-p",
        str(pygit2_commit.id),
    ]
    p = subprocess.run(args, check=False, stdout=subprocess.PIPE, errors="ignore")
    return p.stdout


diff = globals()[f"_diff_{'external' if settings.PYGIT_WORKAROUNDS else 'internal'}"]


def commit_to_patch(pygit2_commit):
    """Parse a commit's diff into a Patch object."""
    return PatchParser(abbrev(pygit2_commit.id), diff(pygit2_commit)).parse()


def walker(rev1, rev2, ordered):
    """Walk commits from rev1 to rev2.

    If rev1 is None, walks from the beginning.
    If ordered is True, sorts topologically in reverse.
    """
    rev1 = normalize(rev1)
    rev2 = normalize(rev2)
    w = repository.walk(rev2)
    if isinstance(ordered, bool) and ordered:
        w.sort(pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_REVERSE)
    elif ordered == "topo":
        w.sort(pygit2.GIT_SORT_TOPOLOGICAL)
    if rev1:
        w.hide(rev1)
    return w


def full_hash(rev):
    """Resolve a revision to its full 40-char hex hash, or None."""
    try:
        rev = normalize(rev)
    except KeyError, ValueError:
        return None
    if not rev:
        return None
    return str(rev)


def base(rev1, rev2):
    """Return the merge base between two revisions as a pygit2.Oid."""
    return repository.merge_base(normalize(rev1), normalize(rev2))


def commit_name(commit):
    """Return the first line of a commit message."""
    try:
        return commit.message[: commit.message.index("\n")]
    except ValueError:
        return commit.message


def sig_email(sig):
    """Format a signature as 'Name <email>'."""
    return f"{sig.name} <{sig.email}>"


def sig_first_name(sig):
    """Return the first name from a signature."""
    return sig.name.split()[0]


def sig_date(sig):
    """Return a datetime from a pygit2 Signature."""
    tz = datetime.timezone(datetime.timedelta(minutes=sig.offset))
    return datetime.datetime.fromtimestamp(sig.time, tz)


def sig_date_str(sig):
    """Return a formatted date string from a pygit2 Signature."""
    return sig_date(sig).strftime("%c %z")


def sigeq(sig1, sig2):
    """Compare two signatures by name and email."""
    return sig1.name == sig2.name and sig1.email == sig2.email


def sigtimenear(sig_older, sig_newer, maxdiff):
    """Return True if sig_newer is at most maxdiff seconds newer than sig_older."""
    return sig_newer.time >= sig_older.time and (
        sig_newer.time - sig_older.time <= maxdiff
    )


def git_show(commit):
    """Format a commit like 'git show' output."""
    msg = commit.message
    msg = msg.removesuffix("\n")
    msg = re.sub("^", "    ", msg, flags=re.MULTILINE)
    merge = ""
    if len(commit.parent_ids) > 1:
        merge = "Merge: {}\n".format(" ".join(abbrev(p) for p in commit.parent_ids))
    return (
        f"commit {commit.id}\n"
        f"{merge}Author: {sig_email(commit.author)}\n"
        f"Date:   {sig_date_str(commit.author)}\n"
        f"\n{msg}"
    )


def normalize_git_url(url):
    """Normalize a git URL. Currently handles gitlab.com specially."""
    if url.startswith("http"):
        parsed = urllib.parse.urlsplit(url)
        if parsed.netloc == "gitlab.com":
            return f"git@gitlab.com:{parsed.path.removeprefix('/').removesuffix('.git')}.git"
    else:
        try:
            server, path = url.split(":")
            _login, server = server.split("@")
            if server == "gitlab.com":
                return f"git@gitlab.com:{path.removesuffix('.git')}.git"
        except ValueError:
            pass
    return url


def is_db_regex_exception(e):
    """Return True if the exception is a database regex error."""
    from django.db import DatabaseError

    if not isinstance(e, DatabaseError):
        return False
    for a in e.args:
        if "regex" in str(a):
            return True
    return False


def dict_to_object(**kwargs):
    """Create a simple object from keyword arguments."""

    class DictObject:
        def __init__(self, d):
            self.__dict__ = d

    return DictObject(kwargs)


def natural_sort(data, key):
    """Sort a list of objects naturally (e.g., 'v2' before 'v10')."""
    nums = re.compile(r"([0-9]+)")
    names = []
    for d in data:
        name = [
            int(comp) if i & 1 else comp for i, comp in enumerate(nums.split(key(d)))
        ]
        names.append((name, d))
    names.sort(key=lambda x: x[0])
    return [d for _, d in names]
