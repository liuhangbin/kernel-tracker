"""Tests for kernel_tracker models."""

from django.test import TestCase

from kernel_tracker.models import Commit, File, Fix, Series, Tree, VanillaVersion


class TestTreeModel(TestCase):
    """Test the Tree model."""

    def test_tree_str_without_head(self):
        """Tree.__str__ without head should show just the name."""
        tree = Tree(name="linux", url="https://example.com", kind=Tree.UPSTREAM)
        assert str(tree) == "linux"

    def test_remote_url_default_branch(self):
        """remote_url() should not append branch for 'main'."""
        tree = Tree(name="linux", url="https://example.com/repo.git", branch="main")
        assert tree.remote_url() == "https://example.com/repo.git"

    def test_remote_url_custom_branch(self):
        """remote_url() should append #branch for non-main branches."""
        tree = Tree(name="net", url="https://example.com/repo.git", branch="net-next")
        assert tree.remote_url() == "https://example.com/repo.git#net-next"

    def test_remote_branch(self):
        """remote_branch() should return name/branch."""
        tree = Tree(name="linux", url="https://example.com", branch="main")
        assert tree.remote_branch() == "linux/main"

    def test_is_fresh_without_head(self):
        """is_fresh() should return True when head is empty."""
        tree = Tree(name="linux", url="https://example.com", kind=Tree.UPSTREAM)
        assert tree.is_fresh() is True

    def test_is_current_without_head(self):
        """is_current() should return False when head is empty."""
        tree = Tree(name="linux", url="https://example.com", kind=Tree.UPSTREAM)
        assert tree.is_current() is False


class TestCommitModel(TestCase):
    """Test the Commit model."""

    def test_commit_str(self):
        """Commit.__str__ should return abbreviated OID."""
        commit = Commit(oid="a" * 40, is_merge=False)
        assert str(commit) == "a" * 12

    def test_getc_returns_none_for_none(self):
        """getc(None) should return None."""
        assert Commit.getc(None) is None

    def test_getc_returns_none_for_missing(self):
        """getc() should return None for non-existent OID."""
        assert Commit.getc("f" * 40) is None


class TestFixModel(TestCase):
    """Test the Fix model."""

    def test_fix_kind_choices(self):
        """Verify fix kind constants are correct."""
        assert Fix.MENTION == ""
        assert Fix.EXPLICIT_FIX == "f"
        assert Fix.REVERT == "r"


class TestSeriesModel(TestCase):
    """Test the Series model."""

    def test_series_description_patchset(self):
        """description should return 'patchset' for PATCHSET kind."""
        series = Series(head="a" * 40, kind=Series.PATCHSET)
        assert series.description == "patchset"

    def test_series_description_mr(self):
        """description should return 'merge request' for GITLAB_MR kind."""
        series = Series(head="a" * 40, kind=Series.GITLAB_MR)
        assert series.description == "merge request"


class TestVanillaVersionModel(TestCase):
    """Test the VanillaVersion model."""

    def test_version_str(self):
        """VanillaVersion.__str__ should return the version string."""
        v = VanillaVersion(version="v6.12")
        assert str(v) == "v6.12"


class TestFileModel(TestCase):
    """Test the File model."""

    def test_file_str(self):
        """File.__str__ should return the path."""
        f = File(path="drivers/net/e1000e/netdev.c")
        assert str(f) == "drivers/net/e1000e/netdev.c"
