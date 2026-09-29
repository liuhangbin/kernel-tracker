"""Git tree processing pipeline.

Fetches from configured git remotes, walks new commits, and applies
a chain of "searchers" to extract fix references, reverts, series,
and file paths.
"""

import errno
import fcntl
import os
import re
import time

import pygit2
from django.conf import settings
from django.db import transaction

from kernel_tracker import utils
from kernel_tracker.models import (
    Commit,
    File,
    Fix,
    Series,
    Tree,
    VanillaVersion,
)
from kernel_tracker.repository import repository

# Maximum seconds between commits to be considered part of the same series
SERIES_AUTHOR_TIMESPAN = 300
SERIES_COMMIT_TIMESPAN = 300


class NullProgress:
    """Silent progress reporter."""

    def __init__(self, tree):
        self.tree = tree

    def message(self, msg):
        pass

    def progress(self, done, total):
        pass

    def done(self):
        pass


class SearchProgress(NullProgress):
    """Verbose progress reporter with ETA display."""

    def __init__(self, tree):
        super().__init__(tree)
        self.start = time.time()
        self.last = self.start

    def message(self, msg):
        utils.message(msg)

    def progress(self, done, total):
        cur = time.time()
        if cur >= self.last:
            utils.message(
                f"Updating {self.tree.name} {utils.percent(done, total)}% "
                f"({done}/{total}), ETA {utils.eta(done, total, self.start, cur)}"
            )
            self.last = cur + 1

    def done(self):
        utils.message(f"Updated {self.tree.name}.", True)


class BaseCommitSearcher:
    """Abstract base class for commit processing searchers."""

    def __init__(self, tree):
        self.tree = tree
        self.first_use = tree and tree.is_fresh()

    def record(self, commit, dbcommit, patch_data):
        """Process a single commit. Override in subclasses."""

    def finish(self):
        """Called after all commits are processed. Override to flush buffers."""


class BaseReferenceSearcher(BaseCommitSearcher):
    """Searches for commit hash references in commit messages.

    Verifies that referenced commits exist in some repository.
    """

    def __init__(self, tree, kind=None):
        super().__init__(tree)
        self.kind = kind

    def filter(self, commit, refs, verify=None):
        """Filter a list of referenced commits, expanding abbreviated hashes."""
        result = []
        if refs is None:
            return result
        for c in set(refs):
            if not isinstance(c, Commit):
                fh = utils.full_hash(c)
                if not fh:
                    continue
                c = Commit.getc(fh)
                if not c:
                    continue
                if self.kind and not c.trees.filter(kind=self.kind).exists():
                    continue
            if verify and not verify(commit, c.oid):
                continue
            result.append(c)
        return result

    def find_refs(self, commit):
        """Override: find all valid references in a commit message."""
        return []


class ReferenceSearcher(BaseReferenceSearcher):
    """Detects 'Fixes:' tags and commit hash mentions in commit messages."""

    re_fix = re.compile(r"^Fixes: ([0-9a-f]{8,40})", re.MULTILINE)
    re_mention = re.compile(r"\b([0-9a-f]{8,40})\b")

    def __init__(self, tree):
        super().__init__(tree, tree.kind)

    def find_refs(self, commit, regex):
        return self.filter(commit, (m.group(1) for m in regex.finditer(commit.message)))

    def record(self, commit, dbcommit, patch_data):
        fixes = self.find_refs(commit, self.re_fix)
        for ref in fixes:
            self._record_fix(dbcommit, ref, Fix.EXPLICIT_FIX)
        mentions = self.find_refs(commit, self.re_mention)
        for ref in mentions:
            if ref not in fixes:
                self._record_fix(dbcommit, ref, Fix.MENTION)

    def _record_fix(self, dbcommit, fixed, kind):
        """Record that dbcommit fixes `fixed` and flag missing backports.

        `fixed` is the referenced (buggy) commit, dbcommit is the commit
        carrying the Fixes: tag or the hash mention.
        """
        Fix.objects.get_or_create(
            fixing=fixed, fixed_by=dbcommit, defaults={"kind": kind}
        )
        # Downstream backports of the buggy commit are missing this fix.
        for ds in fixed.downstream.all():
            ds.record_upstream_fix(dbcommit)


class RevertSearcher(BaseCommitSearcher):
    """Detects reverts via commit message patterns."""

    re_revert = re.compile(r"This reverts commit ([0-9a-f]{40})", re.IGNORECASE)

    def record(self, commit, dbcommit, patch_data):
        match = self.re_revert.search(commit.message)
        if not match:
            return
        reverted_oid = match.group(1)
        reverted = Commit.getc(reverted_oid)
        if not reverted:
            return
        Fix.objects.get_or_create(
            fixing=reverted, fixed_by=dbcommit, defaults={"kind": Fix.REVERT}
        )


class SeriesSearcher(BaseCommitSearcher):
    """Groups commits into series by author identity and time proximity.

    Also detects Message-Id: headers for series linking.
    """

    re_message_id = re.compile(r"^Message-id: (.*)$", re.MULTILINE)

    def __init__(self, tree):
        super().__init__(tree)
        self.last_commit = None
        self.last_author = None
        self.series = []

    def _same_series(self, commit):
        """Check if commit belongs to the same series as the last one."""
        if self.last_commit is None:
            return False
        if not utils.sigeq(commit.author, self.last_author):
            return False
        if not utils.sigtimenear(
            self.last_author, commit.author, SERIES_AUTHOR_TIMESPAN
        ):
            return False
        return utils.sigtimenear(
            self.last_commit.committer, commit.committer, SERIES_COMMIT_TIMESPAN
        )

    def record(self, commit, dbcommit, patch_data):
        if self._same_series(commit):
            self.series.append(dbcommit)
        else:
            self._flush()
            self.series = [dbcommit]
        self.last_commit = commit
        self.last_author = commit.author

    def finish(self):
        self._flush()

    def _flush(self):
        """Save the current series if it has more than one commit."""
        if len(self.series) < 2:
            self.series = []
            return
        # Check for Message-Id in the first commit
        name = ""
        link = ""
        message_id = self.re_message_id.search(self.series[0].data.message)
        if message_id:
            link = message_id.group(1).strip()
        series = Series(
            head=self.series[-1].oid,
            kind=Series.PATCHSET,
            name=name,
            link=link,
        )
        series.save()
        for i, commit in enumerate(self.series):
            commit.series = series
            commit.position = i
            commit.save()
        self.series = []


class FilesSearcher(BaseCommitSearcher):
    """Records file paths touched by each commit."""

    def record(self, commit, dbcommit, patch_data):
        if not patch_data:
            return
        for diff_file in patch_data:
            for name in (diff_file.name, diff_file.new_name):
                if name and name != "/dev/null":
                    file_obj, _ = File.objects.get_or_create(path=name)
                    dbcommit.files.add(file_obj)


class MultiSearcher:
    """Applies multiple searchers to each commit."""

    def __init__(self, tree):
        self.tree = tree
        self.searchers = []

    def add(self, searcher_class):
        self.searchers.append(searcher_class(self.tree))

    def record(self, commit, dbcommit, patch_data):
        for searcher in self.searchers:
            searcher.record(commit, dbcommit, patch_data)

    def finish(self):
        for searcher in self.searchers:
            searcher.finish()


def process_commit(tree, commit, searcher):
    """Process a single commit: create/update DB record, apply searchers."""
    patch_data = None
    try:
        with transaction.atomic():
            dbcommit = Commit.getc(commit.id)
            if dbcommit is None:
                dbcommit = Commit(
                    oid=str(commit.id),
                    is_merge=len(commit.parent_ids) > 1,
                )
                dbcommit.save()
            dbcommit.trees.add(tree)
            try:
                patch_data = utils.commit_to_patch(commit)
            except Exception:  # noqa: BLE001 - best effort: any diff/parse
                # failure means this commit simply has no patch data.
                patch_data = None
            searcher.record(commit, dbcommit, patch_data)
    except Exception:
        utils.message(f"Error processing commit {commit.id}", True)
        raise


def process_tags(tree, output=False):
    """Process git tags and create VanillaVersion entries."""
    if not tree.is_vanilla:
        # Tags of every tree end up in the same refs/tags/ namespace of the
        # shared repository and version names are unique across trees, so
        # only the vanilla tree may turn them into VanillaVersion entries.
        return False
    # Look up by name, not by tree: a version is stored even when its commit
    # is missing (tags older than the tracked history have no commit in the
    # database) and such a tag must not be inserted again on the next run.
    known = set(VanillaVersion.objects.values_list("version", flat=True))
    targets_lookup = set()
    new_tags = []
    for ref in repository.references:
        if not ref.startswith("refs/tags/"):
            continue
        tag = ref.removeprefix("refs/tags/")
        if tag in known:
            continue
        try:
            obj = repository.revparse_single(ref)
        except KeyError:
            continue
        # Annotated tags point to their target, lightweight tags resolve
        # directly to the commit.
        target = getattr(obj, "target", None) or obj.id
        try:
            if not isinstance(repository[target], pygit2.Commit):
                continue
        except AttributeError:
            continue
        new_tags.append({"tag": tag, "target": target})
    if not new_tags:
        return False
    if len(new_tags) > 1:
        new_tags.sort(key=lambda x: utils.sig_date(repository[x["target"]].committer))
    # Continue where the previous run stopped. Starting from scratch would
    # re-attribute every older commit to the newest tag.
    previous = VanillaVersion.objects.exclude(commit=None).last()
    last_oid = previous.commit.oid if previous else None
    for ref in new_tags:
        if output:
            print(f"Processing new tag {ref['tag']}")
        with transaction.atomic():
            v = VanillaVersion(version=ref["tag"], commit=Commit.getc(ref["target"]))
            v.save()
            if str(ref["target"]) in targets_lookup:
                continue
            targets_lookup.add(str(ref["target"]))
            oids = [str(c.id) for c in utils.walker(last_oid, ref["target"], False)]
            Commit.objects.filter(oid__in=oids).update(version=v)
        last_oid = ref["target"]
    return True


def process_tree(tree, output=False):
    """Fetch and process a single tree."""
    if output:
        print(f"Fetching and processing {tree.name}")
    tree.fetch(output)

    if tree.is_current():
        if process_tags(tree, output) or not tree.origin:
            tree.record_fetch()
        if output:
            print("Up to date.")
        return

    if output:
        progress = SearchProgress(tree)
        progress.message("Getting commit count")
        cnt = tree.count()
    else:
        progress = NullProgress(tree)
        cnt = 0

    searcher = MultiSearcher(tree)
    if tree.kind == Tree.UPSTREAM:
        searcher.add(ReferenceSearcher)
        searcher.add(RevertSearcher)
        searcher.add(SeriesSearcher)
        searcher.add(FilesSearcher)
    else:
        # Downstream searchers (Phase 2) would go here
        searcher.add(RevertSearcher)

    progress.message("Sorting commits")
    for i, commit in enumerate(tree.walk()):
        progress.progress(i + 1, cnt)
        process_commit(tree, commit, searcher)
    searcher.finish()

    progress.done()
    process_tags(tree, output)
    tree.record_fetch()


def find_message_id(commit):
    """Extract Message-Id from a commit message."""
    g = re.search(r"^Message-id: (.*)$", commit.message, re.MULTILINE)
    if not g:
        return None
    return g.group(1)


lock_file = None


def check_running():
    """Check if another processing instance is already running."""
    global lock_file
    # Left open on purpose: the lock is held for the lifetime of the process,
    # so a context manager would release it immediately.
    lock_file = open(settings.PROCESSING_LOCK_FILE, "w")  # noqa: SIM115
    try:
        fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        if e.errno == errno.EAGAIN:
            return True
        raise
    return False


def is_running():
    """Check whether another instance holds the processing lock."""
    try:
        # Unlike check_running, this must not hold the lock. The file has to
        # be opened for writing: an exclusive fcntl lock needs a writable
        # descriptor.
        with open(settings.PROCESSING_LOCK_FILE, "r+") as probe:
            fcntl.lockf(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        if e.errno in (errno.EAGAIN, errno.EACCES):
            return True
        if e.errno == errno.ENOENT:
            return False
        raise
    return False


def remove_lock_file():
    """Remove the processing lock file."""
    if lock_file:
        lock_file.close()
        try:
            os.remove(settings.PROCESSING_LOCK_FILE)
        except FileNotFoundError:
            pass


def ordered_trees():
    """Return every tree, vanilla first, then upstream, then downstream."""
    trees = list(Tree.objects.filter(is_vanilla=True))
    trees += list(Tree.objects.filter(kind=Tree.UPSTREAM, is_vanilla=False))
    trees += list(Tree.objects.filter(kind=Tree.DOWNSTREAM))
    return trees


def fetch_and_process_all(output=False, trees=None):
    """Fetch and process the given trees, or all of them.

    Trees are processed in order: vanilla first, then other upstream,
    then downstream. Tags and fork points depend on that order.
    """
    if check_running():
        utils.message("Another instance is already running.", True)
        return
    try:
        selected = ordered_trees()
        if trees:
            # Every other tree needs the vanilla one to find its fork point,
            # so it comes along with whatever was selected.
            selected = [t for t in selected if t.name in trees or t.is_vanilla]
        for t in selected:
            process_tree(t, output)
    finally:
        remove_lock_file()
