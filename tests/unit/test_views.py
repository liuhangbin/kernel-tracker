"""Smoke tests for the web views."""

import os
import shutil
import tempfile

from django.test import TestCase, override_settings

from kernel_tracker import models
from kernel_tracker.repository import repository
from tests.gitrepo import SourceRepo


class FirstUseTest(TestCase):
    """The index page before any tree has been configured."""

    def test_index_without_trees_shows_firstuse(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Welcome!")
        self.assertContains(response, "tree add -u -V")


class ViewTest(TestCase):
    """Views listing trees, commits, series, paths and single commits."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.src = SourceRepo(os.path.join(self.tmp, "source"))
        self.src.commit("one", "Initial commit", "a.txt")
        self.oid = self.src.oids["one"]

        self.override = override_settings(GIT_REPO=self.src.path)
        self.override.enable()
        repository.reset()
        self.addCleanup(repository.reset)
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

        self.linux = models.Tree.objects.create(
            name="linux",
            url="https://example.com/linux.git",
            kind=models.Tree.UPSTREAM,
            is_vanilla=True,
        )
        self.commit = models.Commit.objects.create(oid=self.oid)
        self.commit.trees.add(self.linux)
        self.a_file = models.File.objects.create(path="a.txt")
        self.commit.files.add(self.a_file)
        self.series = models.Series.objects.create(
            head=self.oid, kind=models.Series.PATCHSET, name="first series"
        )
        self.commit.series = self.series
        self.commit.save()

    def test_index_lists_trees(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "linux")

    def test_tree_commit_list(self):
        response = self.client.get(f"/tree/{self.linux.name}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.oid[:12])

    def test_all_trees_commit_list(self):
        self.assertEqual(self.client.get("/tree/all/").status_code, 200)

    def test_filter_view(self):
        self.assertEqual(self.client.get("/filter/").status_code, 200)
        response = self.client.get("/filter/?tree=linux&path=a.txt")
        self.assertEqual(response.status_code, 200)
        # The tree switcher is a dropdown filled by tree.js, not a <select>.
        self.assertContains(response, 'type="hidden" name="tree" value="linux"')

    def test_path_view(self):
        response = self.client.get(f"/path/{self.linux.name}/a.txt/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.oid[:12])

    def test_series_view(self):
        response = self.client.get(f"/series/{self.series.pk}/")
        self.assertEqual(response.status_code, 200)

    def test_commit_view(self):
        response = self.client.get(f"/commit/{self.oid}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Initial commit")

    def test_unknown_commit_is_404(self):
        self.assertEqual(self.client.get(f"/commit/{'0' * 40}/").status_code, 404)

    def test_author_view_redirects_until_person_model_exists(self):
        response = self.client.get("/author/someone@example.org/")
        self.assertEqual(response.status_code, 302)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertIn("version", response.json())
