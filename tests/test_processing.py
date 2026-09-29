"""Tests for the processing lock that keeps updates from overlapping."""

import os
import shutil
import subprocess
import sys
import tempfile
import time

from django.conf import settings
from django.test import TestCase, override_settings

from kernel_tracker import processing

# Holds the lock the way a running update does. Django is deliberately not
# imported: the child only needs to lock a file.
HOLD_LOCK = """\
import fcntl, sys, time
with open(sys.argv[1], "w") as f:
    fcntl.lockf(f, fcntl.LOCK_EX)
    time.sleep(5)
"""


class IsRunningTest(TestCase):
    """`is_running` reports whether another process holds the lock."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.override = override_settings(
            PROCESSING_LOCK_FILE=os.path.join(self.tmp, "processing.lock")
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_without_a_lock_nothing_is_running(self):
        self.assertFalse(processing.is_running())

    def test_a_lock_held_by_another_process_is_seen(self):
        holder = subprocess.Popen(
            [sys.executable, "-c", HOLD_LOCK, settings.PROCESSING_LOCK_FILE]
        )
        self.addCleanup(holder.kill)

        for _ in range(100):
            if processing.is_running():
                break
            time.sleep(0.05)
        self.assertTrue(processing.is_running())
