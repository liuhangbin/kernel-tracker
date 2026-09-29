"""End-to-end pipeline test against a real git repository.

Exercises what the management commands do in production: add a tree
pointing at a real remote, fetch it, walk the new commits and run the
searchers that record fixes, series, files and vanilla versions.
"""

import os
import shutil
import tempfile

from django.core.management import call_command
from django.test import TestCase, override_settings

from kernel_tracker import models
from kernel_tracker.repository import repository
from tests.gitrepo import SourceRepo, init_tracker_repo


class PipelineTest(TestCase):
    """Run `tree add` and `cron update` against a local git repository."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.src = SourceRepo(os.path.join(self.tmp, "source"))
        tracker = os.path.join(self.tmp, "data.git")

        # Commits are more than SERIES_AUTHOR_TIMESPAN apart except for the
        # buggy/fix pair, so only those two end up in the same series.
        self.src.commit("base", "Initial commit", "a.txt")
        self.src.commit("buggy", "Add a buggy feature", "b.txt", offset=1000)
        self.src.commit(
            "fix",
            f"Fix the buggy feature\n\nFixes: {self.src.oids['buggy']}\n",
            "b.txt",
            content="fixed\n",
            offset=1010,
        )
        self.src.commit("next", "Add another file", "c.txt", offset=2000)
        self.src.tag("v6.12", "next", offset=2010)

        init_tracker_repo(tracker)
        self.override = override_settings(
            GIT_REPO=tracker,
            PROCESSING_LOCK_FILE=os.path.join(self.tmp, "processing.lock"),
        )
        self.override.enable()
        repository.reset()
        self.addCleanup(repository.reset)
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_tree_add_and_cron_update(self):
        call_command("tree", "add", "-u", "-V", "linux", self.src.url)
        call_command("cron", "update")

        tree = models.Tree.objects.get(name="linux")
        self.assertEqual(str(tree.head), self.src.oids["next"])
        self.assertTrue(tree.is_current())

        self.assertEqual(models.Commit.objects.count(), 4)
        for key, oid in self.src.oids.items():
            commit = models.Commit.objects.get(oid=oid)
            self.assertIn(tree, commit.trees.all(), key)

    def test_fixes_are_recorded(self):
        call_command("tree", "add", "-u", "-V", "linux", self.src.url)
        call_command("cron", "update")

        fix = models.Fix.objects.get(kind=models.Fix.EXPLICIT_FIX)
        self.assertEqual(fix.fixing.oid, self.src.oids["buggy"])
        self.assertEqual(fix.fixed_by.oid, self.src.oids["fix"])

    def test_files_are_recorded(self):
        call_command("tree", "add", "-u", "-V", "linux", self.src.url)
        call_command("cron", "update")

        paths = set(models.File.objects.values_list("path", flat=True))
        self.assertEqual(paths, {"a.txt", "b.txt", "c.txt"})
        commit = models.Commit.objects.get(oid=self.src.oids["fix"])
        self.assertEqual([f.path for f in commit.files.all()], ["b.txt"])

    def test_series_is_detected(self):
        call_command("tree", "add", "-u", "-V", "linux", self.src.url)
        call_command("cron", "update")

        series = models.Series.objects.get()
        commits = series.commits.order_by("position")
        self.assertEqual(
            [c.oid for c in commits], [self.src.oids["buggy"], self.src.oids["fix"]]
        )
        self.assertEqual(series.head, self.src.oids["fix"])

    def test_vanilla_versions_are_assigned(self):
        call_command("tree", "add", "-u", "-V", "linux", self.src.url)
        call_command("cron", "update")

        version = models.VanillaVersion.objects.get(version="v6.12")
        self.assertEqual(version.commit.oid, self.src.oids["next"])
        # Every commit reachable from the tag is part of that version.
        for oid in self.src.oids.values():
            self.assertEqual(models.Commit.objects.get(oid=oid).version, version)

    def test_second_update_is_a_noop(self):
        call_command("tree", "add", "-u", "-V", "linux", self.src.url)
        call_command("cron", "update")
        call_command("cron", "update")

        self.assertEqual(models.Commit.objects.count(), 4)
        self.assertEqual(models.Series.objects.count(), 1)

    def test_a_second_tree_does_not_recreate_vanilla_versions(self):
        other = SourceRepo(os.path.join(self.tmp, "other"))
        other.commit("base", "Initial commit", "a.txt")
        call_command("tree", "add", "-u", "-V", "linux", self.src.url)
        call_command("tree", "add", "-u", "next", other.url)
        call_command("cron", "update")

        # The tags of every tree live in one shared namespace, so a tree that
        # does not own them must not turn them into versions of its own.
        self.assertEqual(models.VanillaVersion.objects.count(), 1)

    def test_a_tree_without_a_git_remote_is_fetchable(self):
        call_command("tree", "add", "-u", "-V", "linux", self.src.url)
        # A tree added through the admin (or any other ORM caller) has a
        # database row but no git remote, which is what fetch() looks up.
        models.Tree.objects.create(
            name="next", url=self.src.path, kind=models.Tree.UPSTREAM
        )
        call_command("cron", "update")

        self.assertIn("next", repository.remotes.names())

    def test_a_new_tag_only_claims_the_commits_that_follow_it(self):
        call_command("tree", "add", "-u", "-V", "linux", self.src.url)
        call_command("cron", "update")

        self.src.commit("later", "One more commit", "d.txt", offset=3000)
        self.src.tag("v6.13", "later", offset=3010)
        call_command("cron", "update")

        version = models.VanillaVersion.objects.get(version="v6.13")
        self.assertEqual(version.commit.oid, self.src.oids["later"])
        self.assertEqual(
            models.Commit.objects.get(oid=self.src.oids["buggy"]).version.version,
            "v6.12",
        )
