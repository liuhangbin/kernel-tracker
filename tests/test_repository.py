"""Tests for the shared git repository singleton.

The repository is created on first access, so nothing has to initialize it by
hand before `tree add` can be used.
"""

import os
import shutil
import tempfile

import pygit2
from django.test import TestCase, override_settings

from kernel_tracker.repository import repository


class RepositoryInitTest(TestCase):
    """Opening the repository creates it when it does not exist yet."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.repo_path = os.path.join(self.tmp, "data.git")
        self.override = override_settings(GIT_REPO=self.repo_path)
        self.override.enable()
        repository.reset()
        self.addCleanup(repository.reset)
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_missing_repository_is_created_bare(self):
        self.assertFalse(os.path.exists(self.repo_path))

        self.assertTrue(repository.is_bare)
        self.assertTrue(pygit2.Repository(self.repo_path).is_bare)

    def test_automatic_gc_is_off(self):
        self.assertEqual(repository.config["gc.auto"], "0")

    def test_existing_repository_is_left_alone(self):
        repo = pygit2.init_repository(self.repo_path, bare=True)
        repo.config["gc.auto"] = "1"

        # The singleton must open that repository, not reset its config
        self.assertEqual(repository.config["gc.auto"], "1")
