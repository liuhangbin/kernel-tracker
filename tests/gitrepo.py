"""Helpers for building throwaway git repositories in tests."""

import os
import subprocess

import pygit2

BRANCH = "main"


class SourceRepo:
    """A git repository that tests can commit to and be fetched from."""

    def __init__(self, path, base_time=1700000000):
        self.path = path
        self.repo = pygit2.init_repository(path)
        if self.repo.head_is_unborn:
            self.repo.set_head(f"refs/heads/{BRANCH}")
        self.base_time = base_time
        self.oids = {}

    @property
    def url(self):
        return f"file://{self.path}#{BRANCH}"

    def _signature(self, offset):
        return pygit2.Signature(
            "Test User", "test@example.org", self.base_time + offset, 0
        )

    def commit(self, key, message, filename, content=None, offset=0):
        """Create a commit touching filename and remember it as key."""
        with open(os.path.join(self.path, filename), "w") as f:
            f.write(content if content is not None else f"{filename}\n")
        self.repo.index.add_all()
        self.repo.index.write()
        tree = self.repo.index.write_tree()
        sig = self._signature(offset)
        parents = [] if self.repo.head_is_unborn else [self.repo.head.target]
        oid = str(
            self.repo.create_commit(
                f"refs/heads/{BRANCH}", sig, sig, message, tree, parents
            )
        )
        self.oids[key] = oid
        return oid

    def tag(self, name, key, offset=0):
        """Create an annotated tag on the commit stored as key."""
        when = f"{self.base_time + offset} +0000"
        subprocess.run(
            [
                "git",
                "-C",
                self.path,
                "tag",
                "-a",
                name,
                "-m",
                f"tag {name}",
                self.oids[key],
            ],
            check=True,
            env=dict(os.environ, GIT_COMMITTER_DATE=when, GIT_AUTHOR_DATE=when),
        )
        return name


def init_tracker_repo(path):
    """Create the bare repository the tracker fetches into."""
    return pygit2.init_repository(path, bare=True)
