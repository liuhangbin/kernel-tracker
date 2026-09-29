"""Singleton access to the pygit2 Repository.

The repository path is configured via settings.GIT_REPO.
"""

import pygit2
from django.conf import settings


def _get_repository():
    """Return the pygit2 Repository instance, creating it if needed."""
    try:
        repo = pygit2.Repository(settings.GIT_REPO)
    except pygit2.GitError:
        repo = pygit2.init_repository(settings.GIT_REPO, bare=True)
        # Background repacking would drop objects that long-lived processes
        # such as the gunicorn workers still have open.
        repo.config["gc.auto"] = 0
    return repo


class _RepositoryProxy:
    """Lazy proxy that initializes the repository on first access."""

    def __init__(self):
        self._repo = None

    def _ensure(self):
        if self._repo is None:
            self._repo = _get_repository()

    def __getattr__(self, name):
        self._ensure()
        return getattr(self._repo, name)

    def __getitem__(self, oid):
        self._ensure()
        return self._repo[oid]

    def __contains__(self, oid):
        self._ensure()
        return oid in self._repo

    def reset(self):
        """Reset the cached repository (useful for testing)."""
        self._repo = None


# Module-level singleton
repository = _RepositoryProxy()
