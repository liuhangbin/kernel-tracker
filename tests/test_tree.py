"""Tests for the `tree` management command.

Adding a tree is covered by the pipeline test; this module covers deleting,
which is the only subcommand with confirmation prompts and cross-tree
constraints of its own.
"""

import os
import shutil
import tempfile
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from kernel_tracker import models
from kernel_tracker.repository import repository
from tests.gitrepo import SourceRepo, init_tracker_repo


class TreeDeleteTest(TestCase):
    """Delete a tracked tree and its git remote."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.src = SourceRepo(os.path.join(self.tmp, "source"))
        self.src.commit("base", "Initial commit", "a.txt")

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

        call_command("tree", "add", "-u", "-V", "linux", self.src.url)

    def delete_tree(self, name, answer=None, subcommand="delete"):
        """Run `tree delete` answering the confirmation prompt with answer."""
        with mock.patch("builtins.input", return_value=answer or name):
            call_command("tree", subcommand, name)

    def test_delete_removes_the_tree_and_its_remote(self):
        self.assertIn("linux", repository.remotes.names())

        self.delete_tree("linux")

        self.assertFalse(models.Tree.objects.exists())
        self.assertEqual(list(repository.remotes.names()), [])

    def test_delete_is_confirmed_by_retyping_the_name(self):
        with self.assertRaises(CommandError):
            self.delete_tree("linux", answer="something else")

        self.assertTrue(models.Tree.objects.filter(name="linux").exists())
        self.assertIn("linux", repository.remotes.names())

    def test_delete_keeps_the_commits(self):
        call_command("cron", "update")

        self.delete_tree("linux")

        self.assertEqual(models.Commit.objects.count(), 1)
        self.assertFalse(models.Tree.objects.exists())

    def test_delete_unknown_tree(self):
        with self.assertRaises(CommandError):
            self.delete_tree("nonexistent")

    def test_vanilla_tree_cannot_be_deleted_while_others_exist(self):
        call_command("tree", "add", "-d", "downstream", self.src.url)

        with self.assertRaises(CommandError):
            self.delete_tree("linux")

        self.assertTrue(models.Tree.objects.filter(name="linux").exists())

    def test_delete_works_through_the_aliases(self):
        for alias in ("rm", "remove"):
            with self.subTest(alias=alias):
                call_command("tree", "add", "-d", alias, self.src.url)
                self.delete_tree(alias, subcommand=alias)
                self.assertFalse(models.Tree.objects.filter(name=alias).exists())
