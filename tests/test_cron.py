"""Tests for the `cron` management command.

`cron update` processes every tree, or only the ones named on the command
line, which is what the admin action runs in the background.
"""

import os
import shutil
import tempfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from kernel_tracker import models
from kernel_tracker.repository import repository
from tests.gitrepo import SourceRepo, init_tracker_repo


class CronUpdateTest(TestCase):
    """Update all trees, or only the named ones."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.override = override_settings(
            GIT_REPO=os.path.join(self.tmp, "data.git"),
            PROCESSING_LOCK_FILE=os.path.join(self.tmp, "processing.lock"),
        )
        self.override.enable()
        init_tracker_repo(self.override.options["GIT_REPO"])
        repository.reset()
        self.addCleanup(repository.reset)
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

        self.linux = SourceRepo(os.path.join(self.tmp, "linux"))
        self.linux.commit("base", "Initial commit", "a.txt")
        self.other = SourceRepo(os.path.join(self.tmp, "other"))
        self.other.commit("base", "Initial commit", "b.txt")
        self.third = SourceRepo(os.path.join(self.tmp, "third"))
        self.third.commit("base", "Initial commit", "c.txt")
        call_command("tree", "add", "-u", "-V", "linux", self.linux.url)
        call_command("tree", "add", "-u", "other", self.other.url)
        call_command("tree", "add", "-u", "third", self.third.url)

    def commits(self, tree):
        return models.Commit.objects.filter(trees__name=tree).count()

    def test_every_tree_is_processed_without_names(self):
        call_command("cron", "update")

        self.assertEqual(self.commits("linux"), 1)
        self.assertEqual(self.commits("other"), 1)

    def test_only_the_named_tree_is_processed(self):
        call_command("cron", "update", "other")

        self.assertEqual(self.commits("other"), 1)
        self.assertEqual(self.commits("third"), 0)

    def test_the_vanilla_tree_comes_along_as_a_fork_point(self):
        call_command("cron", "update", "other")

        # Not selected, but the other trees are resolved against it
        self.assertEqual(self.commits("linux"), 1)

    def test_unknown_tree_is_an_error(self):
        with self.assertRaises(CommandError):
            call_command("cron", "update", "nope")
