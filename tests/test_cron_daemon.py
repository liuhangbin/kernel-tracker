"""Tests for `cron daemon`.

The command sits in a loop that updates the trees whenever the schedule
from the admin says so. Every test drives it without waiting: the work is
patched out and `time.sleep` is what stops the loop, except for the last
one, which really processes a repository.
"""

import os
import shutil
import tempfile
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from kernel_tracker import models
from kernel_tracker.models import UpdateSchedule
from kernel_tracker.repository import repository
from tests.gitrepo import SourceRepo, init_tracker_repo


class CronDaemonTest(TestCase):
    """Nothing happens until the schedule is enabled, then on time."""

    def enable(self, **fields):
        schedule = UpdateSchedule.get()
        for name, value in fields.items():
            setattr(schedule, name, value)
        schedule.save()
        return schedule

    def test_disabled_by_default(self):
        with mock.patch("kernel_tracker.processing.fetch_and_process_all") as update:
            call_command("cron", "daemon", "--once")

        update.assert_not_called()
        self.assertIsNone(UpdateSchedule.get().last_run)

    def test_an_enabled_schedule_updates_once(self):
        self.enable(enabled=True)
        with mock.patch("kernel_tracker.processing.fetch_and_process_all") as update:
            call_command("cron", "daemon", "--once")

        update.assert_called_once_with(False, None)
        self.assertIsNotNone(UpdateSchedule.get().last_run)

    def test_an_update_is_not_repeated_before_it_is_due(self):
        self.enable(enabled=True)
        with mock.patch("kernel_tracker.processing.fetch_and_process_all") as update:
            call_command("cron", "daemon", "--once")
            call_command("cron", "daemon", "--once")

        update.assert_called_once()

    def test_an_update_already_running_is_skipped(self):
        self.enable(enabled=True)
        with (
            mock.patch("kernel_tracker.processing.fetch_and_process_all") as update,
            mock.patch("kernel_tracker.processing.is_running", return_value=True),
        ):
            call_command("cron", "daemon", "--once")

        update.assert_not_called()
        # Stamped anyway, so that a busy tracker is not retried every round
        self.assertIsNotNone(UpdateSchedule.get().last_run)

    def test_the_repository_is_reopened_before_every_update(self):
        self.enable(enabled=True)
        with (
            mock.patch("kernel_tracker.processing.fetch_and_process_all"),
            mock.patch("kernel_tracker.management.commands.cron.repository") as repo,
        ):
            call_command("cron", "daemon", "--once")

        repo.reset.assert_called_once_with()

    def test_a_failing_update_does_not_stop_the_loop(self):
        self.enable(enabled=True)
        rounds = []

        def sleep(_seconds):
            rounds.append(1)
            if len(rounds) == 3:
                raise StopIteration

        with (
            mock.patch(
                "kernel_tracker.processing.fetch_and_process_all",
                side_effect=RuntimeError("fetch failed"),
            ) as update,
            mock.patch(
                "kernel_tracker.management.commands.cron.time.sleep", side_effect=sleep
            ),
            # Patched out so that the update stays due and the loop keeps
            # going without waiting an hour between rounds.
            mock.patch.object(UpdateSchedule, "record_run"),
            self.assertRaises(StopIteration),
        ):
            call_command("cron", "daemon")

        self.assertEqual(update.call_count, 3)


class CronDaemonUpdateTest(TestCase):
    """A scheduled cycle processes real commits, not just a mock."""

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

        self.src = SourceRepo(os.path.join(self.tmp, "source"))
        self.src.commit("base", "Initial commit", "a.txt")
        call_command("tree", "add", "-u", "-V", "linux", self.src.url)

    def test_a_due_update_processes_the_tree(self):
        schedule = UpdateSchedule.get()
        schedule.enabled = True
        schedule.save()

        call_command("cron", "daemon", "--once")

        tree = models.Tree.objects.get(name="linux")
        self.assertEqual(models.Commit.objects.filter(trees=tree).count(), 1)
        self.assertEqual(str(tree.head), self.src.oids["base"])
        self.assertIsNotNone(UpdateSchedule.get().last_run)
