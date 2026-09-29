"""Tests for the dataview commit_list filter logic."""

from django.test import TestCase

from kernel_tracker import dataview, models


class CommitListTest(TestCase):
    """Filter combinations shared by the web UI and the RPC API."""

    def setUp(self):
        self.linux = models.Tree.objects.create(
            name="linux",
            url="https://example.com/linux.git",
            kind=models.Tree.UPSTREAM,
            is_vanilla=True,
        )
        self.net = models.Tree.objects.create(
            name="net",
            url="https://example.com/net.git",
            kind=models.Tree.UPSTREAM,
        )
        self.c1 = self._commit("a", [self.linux], ["drivers/net/foo.c"])
        self.c2 = self._commit("b", [self.linux, self.net], ["drivers/net/bar.c"])
        self.c3 = self._commit("c", [self.net], ["fs/baz.c"])

    def _commit(self, char, trees, paths):
        commit = models.Commit.objects.create(oid=char * 40)
        commit.trees.add(*trees)
        for path in paths:
            commit.files.add(models.File.objects.create(path=path))
        return commit

    def _oids(self, **kwargs):
        clist = dataview.commit_list(models.Commit.objects.all(), **kwargs)
        return [c.oid for c in clist]

    def test_no_filter_returns_everything(self):
        self.assertEqual(len(self._oids()), 3)

    def test_tree_filter(self):
        self.assertEqual(self._oids(tree=self.linux), [self.c2.oid, self.c1.oid])

    def test_tree_and_notin_filters(self):
        self.assertEqual(self._oids(tree=self.linux, notin=self.net), [self.c1.oid])

    def test_tree_special_upstream(self):
        self.assertEqual(
            self._oids(tree_special="UPSTREAM"),
            [self.c3.oid, self.c2.oid, self.c1.oid],
        )

    def test_unknown_tree_special_raises(self):
        with self.assertRaises(dataview.DataViewError):
            self._oids(tree_special="DOWNSTREAM")

    def test_path_regex_filter(self):
        self.assertEqual(self._oids(path="drivers/net"), [self.c2.oid, self.c1.oid])
        self.assertEqual(self._oids(path="^fs/"), [self.c3.oid])

    def test_excl_removes_matching_paths(self):
        self.assertEqual(self._oids(path="drivers", excl="bar"), [self.c1.oid])

    def test_fixes_flag_returns_commits_with_a_fix(self):
        models.Fix.objects.create(
            fixing=self.c1, fixed_by=self.c2, kind=models.Fix.EXPLICIT_FIX
        )
        self.assertEqual(self._oids(tree=self.linux, fixes=True), [self.c1.oid])
        # Without the flag the filter is not applied.
        self.assertEqual(self._oids(tree=self.linux), [self.c2.oid, self.c1.oid])

    def test_result_is_ordered_and_annotated(self):
        clist = dataview.commit_list(models.Commit.objects.all())
        self.assertEqual([c.pk for c in clist], [self.c3.pk, self.c2.pk, self.c1.pk])
        self.assertEqual([c.missing for c in clist], [0, 0, 0])

    def test_missing_fixes_are_counted(self):
        models.MissingFix.objects.create(fixing=self.c3, fixed_by=self.c1)
        clist = dataview.commit_list(models.Commit.objects.all())
        self.assertEqual(clist[0].missing, 1)

    def test_none_queryset_is_passed_through(self):
        self.assertIsNone(dataview.commit_list(None, tree=self.linux))
