"""Data models for kernel-tracker.

Core entities:
- Tree: a git remote to poll
- Commit: a git commit (identified by OID)
- Fix: explicit fix relationships found in commit messages
- MissingFix: a fix that exists upstream but is missing downstream
- Series: groups of related commits (patchsets, merge requests)
- File: file paths touched by commits
- VanillaVersion: maps git tags to commits
- TreeAlias: alternate URLs for a tree
- UpdateSchedule: when the trees are updated on their own
"""

from datetime import datetime

from croniter import croniter
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property

from kernel_tracker import utils
from kernel_tracker.fields import OidField
from kernel_tracker.repository import repository


class VanillaVersion(models.Model):
    """Maps a git tag (e.g. v6.12, release-2024-11) to a commit.

    Every tag found in a tree is recorded here, so "version" means "git tag"
    and is never parsed as a version number.
    """

    version = models.CharField("version", max_length=60, unique=True)
    commit = models.ForeignKey(
        "Commit",
        blank=True,
        null=True,
        related_name="tags",
        on_delete=models.PROTECT,
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.version


class Tree(models.Model):
    """A git remote to poll for new commits."""

    UPSTREAM = "u"
    DOWNSTREAM = "d"
    TREE_KINDS = (
        (UPSTREAM, "upstream"),
        (DOWNSTREAM, "downstream"),
    )

    name = models.SlugField("tree name", unique=True)
    url = models.CharField("tree URL", max_length=200)
    branch = models.CharField("remote branch", max_length=64, default="main")
    origin = models.ForeignKey(
        VanillaVersion,
        verbose_name="forked from",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="origins",
    )
    head = OidField("last processed commit", blank=True)
    kind = models.CharField("tree kind", max_length=1, choices=TREE_KINDS)
    is_vanilla = models.BooleanField("is this the vanilla tree?", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "git tree"
        ordering = ["id"]

    def __str__(self):
        if self.head:
            return f"{self.name} at {utils.abbrev(self.head)}"
        return self.name

    def get_absolute_url(self):
        return reverse("tree", args=(self.name,))

    def remote_url(self):
        """Return the full remote URL including branch if non-default."""
        branch = f"#{self.branch}" if self.branch != "main" else ""
        return self.url + branch

    def remote_branch(self):
        """Return the refspec like 'linux/main'."""
        return f"{self.name}/{self.branch}"

    def _check_save(self):
        """Validate tree constraints before saving."""
        if self.pk:
            return
        if self.is_vanilla:
            if self.kind != self.UPSTREAM:
                raise ValueError("Only an upstream tree can be vanilla.")
            try:
                current = Tree.objects.get(is_vanilla=True)
                if current != self:
                    raise ValueError(
                        f"Only one vanilla repository is allowed "
                        f"('{current.name}' already set as vanilla)."
                    )
            except Tree.DoesNotExist:
                pass
        else:
            if not Tree.objects.filter(is_vanilla=True).exists():
                raise ValueError(
                    "Non-vanilla tree can only be added after a vanilla tree exists."
                )

    def save(self, *args, **kwargs):
        with transaction.atomic():
            self._check_save()
            super().save(*args, **kwargs)

    def is_fresh(self):
        """Return True if this tree has never been processed."""
        return not self.head

    def ensure_remote(self):
        """Create the git remote if this tree does not have one yet.

        The remote is looked up by tree name, so a tree created outside of
        `manage tree add` (the admin, or any other ORM caller) has none and
        cannot be fetched until it is created here.
        """
        if self.name not in repository.remotes.names():
            repository.remotes.create(self.name, self.url)

    def fetch(self, output=False):
        """Fetch from the remote tree.

        Does not advance head. If the repository got rebased, rewinds
        the current head to the last common commit and marks orphaned
        commits.
        """
        self.ensure_remote()
        fetch_tags = self.is_vanilla or self.kind == self.DOWNSTREAM
        remote = repository.remotes[self.name]
        utils.fetch(remote, fetch_tags, output)
        if not self.head:
            return
        base = utils.base(self.head, self.remote_branch())
        if str(base) == self.head:
            # fast-forward, everything is fine
            return
        # The repository got rebased — mark orphaned commits
        for c in utils.walker(base, self.head, False):
            with transaction.atomic():
                commit = Commit.getc(c.id)
                if commit:
                    commit.set_orphan(self)
        # Save the new head only after all commits are marked as orphaned
        self.head = str(base)
        self.save()

    def record_fetch(self):
        """Advance head to the remote branch tip after processing."""
        self.head = str(utils.normalize(self.remote_branch()))
        if not self.origin and self.kind == self.DOWNSTREAM:
            # On first fetch of downstream tree, try to resolve the fork point
            oid = self._get_head(force_base=True)
            if oid:
                commit = Commit.getc(oid)
                if commit:
                    self.origin = commit.version
        self.save()

    def _get_head(self, force_base=False):
        if not force_base and self.head:
            return self.head
        if not self.is_vanilla:
            return utils.base(
                self.remote_branch(),
                Tree.objects.get(is_vanilla=True).remote_branch(),
            )
        return None

    def walk(self, ordered=True):
        """Walk commits from head to the remote branch tip."""
        yield from utils.walker(self._get_head(), self.remote_branch(), ordered)

    def count(self):
        """Count unprocessed commits."""
        return sum(1 for _ in self.walk())

    def is_current(self):
        """Return True if head matches the remote branch tip."""
        if not self.head:
            return False
        return str(self.head) == str(utils.normalize(self.remote_branch()))

    @classmethod
    def all_sorted(cls):
        """Return all trees sorted by kind then name."""
        return sorted(cls.objects.all(), key=lambda t: (t.kind, t.name))

    def set_orphan(self, tree):
        """Remove this tree from the commit's tree membership."""
        self.trees.remove(tree)


class CommitManager(models.Manager):
    def get_by_oid(self, oid):
        """Get a commit by its OID string."""
        try:
            return self.get(oid=str(oid))
        except self.model.DoesNotExist:
            return None


class Commit(models.Model):
    """A git commit, identified by its OID.

    A single commit can appear in multiple trees (e.g., merged into
    linux, net, and net-next).
    """

    oid = OidField("commit OID", unique=True)
    is_merge = models.BooleanField(default=False)
    trees = models.ManyToManyField(Tree, related_name="commits", blank=True)
    # Phase 2: upstream/downstream backport tracking
    upstream = models.ManyToManyField(
        "self",
        symmetrical=False,
        related_name="downstream",
        blank=True,
    )
    version = models.ForeignKey(
        VanillaVersion,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="commits",
    )
    series = models.ForeignKey(
        "Series",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="commits",
    )
    position = models.PositiveSmallIntegerField("position in series", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CommitManager()

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return utils.abbrev(self.oid)

    @classmethod
    def getc(cls, oid):
        """Get or None by OID (pygit2 Oid or string)."""
        if oid is None:
            return None
        oid_str = str(oid)
        try:
            return cls.objects.prefetch_related("upstream").get(oid=oid_str)
        except cls.DoesNotExist:
            return None

    @cached_property
    def cached_trees(self):
        return list(self.trees.all())

    def tree_names(self):
        return [t.name for t in self.cached_trees]

    def check_tree_kind(self, kind):
        return any(t.kind == kind for t in self.cached_trees)

    def main_tree(self):
        """Return the top-most tree in the dependency chain."""
        if not self.cached_trees:
            return None
        return self.cached_trees[0]

    def main_tree_name(self):
        tree = self.main_tree()
        return tree.name if tree else "all"

    def upstream_tree_names(self):
        return sorted(
            {t.name for commit in self.upstream.all() for t in commit.cached_trees}
        )

    def downstream_tree_names(self):
        return sorted({commit.main_tree_name() for commit in self.downstream.all()})

    def set_orphan(self, tree):
        """Remove this tree from the commit's tree membership."""
        self.trees.remove(tree)

    @cached_property
    def is_downstream(self):
        return self.check_tree_kind(Tree.DOWNSTREAM)

    def needs_upstream_fix(self, fix):
        """Check whether the given upstream fix is needed for this commit."""
        return (
            not fix.downstream.filter(trees__in=self.cached_trees).exists()
            and not self.missing_upstream_fixes.filter(fixed_by=fix).exists()
        )

    def record_upstream_fix(self, fix, report=True):
        """Record a missing upstream fix if it's needed."""
        if self.needs_upstream_fix(fix):
            miss = MissingFix(fixing=self, fixed_by=fix, reported=not report)
            miss.save()

    @cached_property
    def data(self):
        """Return the pygit2 commit object."""
        return repository[self.oid]

    @cached_property
    def subject(self):
        """Return the first line of the commit message."""
        return self.data.message.split("\n", 1)[0]

    @cached_property
    def describe(self):
        """Return a human-readable version description."""
        if self.version:
            return self.version.version
        v = utils.describe(str(self))
        if not v:
            return ""
        v = v.rsplit("-", maxsplit=2)
        if v[1] == "0":
            return v[0]
        return f"post {v[0]}"


class Fix(models.Model):
    """An explicit fix relationship found in commit messages.

    Detected from 'Fixes: <hash>' tags, commit hash mentions, and
    revert patterns.
    """

    MENTION = ""
    EXPLICIT_FIX = "f"
    REVERT = "r"
    FIX_KIND = (
        (MENTION, "mention"),
        (EXPLICIT_FIX, "explicit fix"),
        (REVERT, "revert"),
    )

    fixing = models.ForeignKey(
        Commit,
        related_name="fixed_by_info",
        on_delete=models.CASCADE,
    )
    fixed_by = models.ForeignKey(
        Commit,
        related_name="fixing_info",
        on_delete=models.CASCADE,
    )
    kind = models.CharField("fix type", max_length=1, choices=FIX_KIND, blank=True)

    class Meta:
        unique_together = ("fixing", "fixed_by")


class MissingFix(models.Model):
    """A fix that exists upstream but is missing in a downstream tree.

    Populated only during Phase 2 (downstream tracking).
    """

    fixing = models.ForeignKey(
        Commit, related_name="missing_upstream_fixes", on_delete=models.CASCADE
    )
    fixed_by = models.ForeignKey(Commit, related_name="+", on_delete=models.CASCADE)
    is_reported = models.BooleanField(default=False)


class Series(models.Model):
    """A group of related commits (patchset or merge request)."""

    PATCHSET = "p"
    GITLAB_MR = "m"
    SERIES_KIND = (
        (PATCHSET, "patchset"),
        (GITLAB_MR, "merge request"),
    )

    head = OidField("series head OID")
    kind = models.CharField("series kind", max_length=1, choices=SERIES_KIND)
    name = models.CharField("series name", max_length=200, blank=True)
    link = models.URLField("series link", blank=True)

    class Meta:
        verbose_name_plural = "series"
        ordering = ["id"]

    def __str__(self):
        return self.name or utils.abbrev(self.head)

    @property
    def description(self):
        """Return a human-readable description of the series kind."""
        return self.get_kind_display()


class SeriesCommit(models.Model):
    """Through table linking Series to Commits with ordering."""

    series = models.ForeignKey(
        Series, on_delete=models.CASCADE, related_name="series_commits"
    )
    commit = models.ForeignKey(
        Commit, on_delete=models.CASCADE, related_name="commit_series"
    )
    position = models.PositiveSmallIntegerField("position in series", default=0)

    class Meta:
        unique_together = ("series", "commit")
        ordering = ["position"]


class File(models.Model):
    """A file path touched by one or more commits."""

    path = models.CharField("file path", max_length=512, unique=True)
    commits = models.ManyToManyField(Commit, related_name="files", blank=True)

    class Meta:
        ordering = ["path"]

    def __str__(self):
        return self.path


class UpdateSchedule(models.Model):
    """When the trees are fetched and processed on their own.

    A single row, edited in the admin: scheduled updates are off until
    someone enables them there. `manage cron update` and the update action
    on the tree list are unaffected and still work on demand.
    """

    enabled = models.BooleanField("enable scheduled updates", default=False)
    schedule = models.CharField(
        "cron expression",
        max_length=100,
        default="0 * * * *",
        help_text="every hour by default, in the configured timezone",
    )
    last_run = models.DateTimeField("last update", blank=True, null=True)

    class Meta:
        verbose_name = "update schedule"

    def __str__(self):
        if not self.enabled:
            return f"{self.schedule} (scheduled updates disabled)"
        return self.schedule

    @classmethod
    def get(cls):
        """Return the only schedule row, creating it with defaults."""
        schedule, _ = cls.objects.get_or_create(pk=1)
        return schedule

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if not croniter.is_valid(self.schedule):
            raise ValidationError(
                {"schedule": f"'{self.schedule}' is not a valid cron expression."}
            )

    def next_run(self):
        """Return the first scheduled time after the last update.

        Times are in the configured timezone, so `0 3 * * *` means three in
        the morning there, not in UTC.
        """
        start = timezone.localtime(self.last_run or timezone.now())
        upcoming = croniter(self.schedule, start).get_next(datetime)
        if timezone.is_naive(upcoming):
            return timezone.make_aware(upcoming, timezone.get_current_timezone())
        return upcoming

    def due(self, now=None):
        """Return True if an update is owed."""
        if self.last_run is None:
            return True
        return (now or timezone.localtime()) >= self.next_run()

    def record_run(self):
        """Remember that a scheduled cycle fired.

        Called even when the update failed or was skipped, so that the next
        attempt happens on schedule instead of every polling round.
        """
        self.last_run = timezone.now()
        self.save()


class TreeAlias(models.Model):
    """An alternate URL for a tree (e.g., a mirror)."""

    tree = models.ForeignKey(Tree, related_name="aliases", on_delete=models.CASCADE)
    url = models.CharField("alias URL", max_length=200)
    branch = models.CharField("alias branch", max_length=64, default="main")

    class Meta:
        unique_together = ("tree", "url", "branch")

    def __str__(self):
        return f"{self.tree.name} -> {self.url}"

    def remote_url(self):
        branch = f"#{self.branch}" if self.branch != "main" else ""
        return self.url + branch
