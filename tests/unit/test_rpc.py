"""Tests for the JSON-RPC methods that build fix and series graphs."""

import json
import os
import shutil
import tempfile

from django.test import TestCase, override_settings

from kernel_tracker import models, rpc
from kernel_tracker.repository import repository
from tests.gitrepo import SourceRepo


class RpcTest(TestCase):
    """Graph building for the get_missing_fixes / get_missing_series calls."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.src = SourceRepo(os.path.join(self.tmp, "source"))
        self.src.commit("buggy", "Add a buggy feature", "a.txt")
        self.src.commit(
            "fix",
            f"Fix the buggy feature\n\nFixes: {self.src.oids['buggy']}\n",
            "a.txt",
            content="fixed\n",
            offset=100,
        )

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
        self.buggy = self._commit("buggy")
        self.fix = self._commit("fix")
        models.Fix.objects.create(
            fixing=self.buggy, fixed_by=self.fix, kind=models.Fix.EXPLICIT_FIX
        )

    def _commit(self, key):
        commit = models.Commit.objects.create(oid=self.src.oids[key])
        commit.trees.add(self.linux)
        return commit

    def test_get_missing_fixes_walks_the_graph(self):
        result = rpc.get_missing_fixes([self.buggy])

        # The requested commit plus the fix that was found for it.
        self.assertEqual([r.data.oid for r in result], [self.buggy.oid, self.fix.oid])
        self.assertFalse(result[0].extra["added"])
        self.assertTrue(result[1].extra["added"])
        self.assertEqual(result[1].extra["fixing"], [self.buggy.oid])

    def test_get_missing_fixes_skips_fixes_already_in_the_tree(self):
        # The fix is part of the tree we ask about, so it is not missing.
        result = rpc.get_missing_fixes([self.buggy], tree=self.linux)
        self.assertEqual([r.data.oid for r in result], [self.buggy.oid])

    def test_get_missing_fixes_without_commits(self):
        self.assertEqual(rpc.get_missing_fixes([]), [])

    def test_get_missing_series_groups_by_series(self):
        series = models.Series.objects.create(
            head=self.fix.oid, kind=models.Series.PATCHSET
        )
        for position, commit in enumerate((self.buggy, self.fix)):
            commit.series = series
            commit.position = position
            commit.save()

        result = rpc.get_missing_series([self.buggy, self.fix], tree=self.linux)

        self.assertEqual(len(result), 2)
        self.assertEqual([r.extra["series"] for r in result], [0, 0])
        self.assertTrue(all(r.extra["included"] for r in result))

    def test_get_missing_series_handles_commits_without_a_series(self):
        result = rpc.get_missing_series([self.buggy])
        self.assertEqual([r.data.oid for r in result], [self.buggy.oid])


class RpcEndpointTest(TestCase):
    """The /rpc/<method>/ HTTP dispatcher."""

    def setUp(self):
        super().setUp()
        models.Tree.objects.create(
            name="linux",
            url="https://example.com/linux.git",
            kind=models.Tree.UPSTREAM,
            is_vanilla=True,
        )

    def _post(self, cmd, payload):
        return self.client.post(
            f"/rpc/{cmd}/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_get_trees(self):
        response = self._post("get_trees", {})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["vanilla"], "linux")
        self.assertEqual([t["name"] for t in data["result"]], ["linux"])

    def test_unknown_method_is_404(self):
        self.assertEqual(self._post("no_such_method", {}).status_code, 404)

    def test_invalid_json_reports_an_error(self):
        response = self.client.post(
            "/rpc/get_trees/", data="not json", content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("error", response.json())
