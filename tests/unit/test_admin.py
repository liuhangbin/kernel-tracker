"""Tests for the tree admin actions."""

import os
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from kernel_tracker.models import Tree, UpdateSchedule


class UpdateTreesActionTest(TestCase):
    """The action starts `cron update` for the selected trees."""

    def setUp(self):
        super().setUp()
        self.client.force_login(
            User.objects.create_superuser("boss", "boss@example.com", "pw")
        )
        self.tree = Tree.objects.create(
            name="linux",
            url="file:///tmp/linux",
            kind=Tree.UPSTREAM,
            is_vanilla=True,
        )

    def run_action(self, *names):
        """Select the given trees and run the action on them."""
        selected = Tree.objects.filter(name__in=names or ["linux"])
        return self.client.post(
            "/admin/kernel_tracker/tree/",
            {
                "action": "update_trees",
                "_selected_action": [str(t.pk) for t in selected],
            },
            follow=True,
        )

    def test_selected_trees_are_updated_in_a_detached_process(self):
        with mock.patch("kernel_tracker.admin.subprocess.Popen") as popen:
            self.run_action("linux")

        popen.assert_called_once()
        args = popen.call_args.args[0]
        self.assertEqual(args[-3:], ["cron", "update", "linux"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_progress_goes_to_the_update_log(self):
        """The detached process has no terminal, so it writes to that file."""
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "update.log")
            with (
                override_settings(UPDATE_LOG=log),
                mock.patch("kernel_tracker.admin.subprocess.Popen") as popen,
            ):
                self.run_action("linux")

        stdout = popen.call_args.kwargs["stdout"]
        self.assertEqual(stdout.name, log)
        self.assertIs(popen.call_args.kwargs["stderr"], stdout)

    def test_without_an_update_log_the_output_is_inherited(self):
        with (
            override_settings(UPDATE_LOG=""),
            mock.patch("kernel_tracker.admin.subprocess.Popen") as popen,
        ):
            self.run_action("linux")

        self.assertIsNone(popen.call_args.kwargs["stdout"])

    def test_another_running_update_refuses_to_start_one(self):
        with (
            mock.patch("kernel_tracker.processing.is_running", return_value=True),
            mock.patch("kernel_tracker.admin.subprocess.Popen") as popen,
        ):
            self.run_action("linux")

        popen.assert_not_called()

    def test_the_update_runs_unbuffered(self):
        """Its output goes to a file, so it has to be written right away."""
        with mock.patch("kernel_tracker.admin.subprocess.Popen") as popen:
            self.run_action("linux")

        self.assertEqual(popen.call_args.args[0][1], "-u")


class UpdateLogTest(TestCase):
    """The update schedule page shows the end of the update log."""

    def setUp(self):
        super().setUp()
        self.client.force_login(
            User.objects.create_superuser("boss", "boss@example.com", "pw")
        )
        UpdateSchedule.get()

    def page(self):
        return self.client.get(
            reverse("admin:kernel_tracker_updateschedule_change", args=[1])
        )

    def write_log(self, directory, text):
        path = os.path.join(directory, "update.log")
        with open(path, "w") as log:
            log.write(text)
        return path

    def test_the_tail_of_the_log_is_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_log(tmp, "Fetching and processing linux\nUp to date.\n")
            with override_settings(UPDATE_LOG=path):
                self.assertContains(self.page(), "Up to date.")

    def test_only_the_tail_is_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_log(tmp, "start\n" + "x" * 8192 + "\nfinish\n")
            with override_settings(UPDATE_LOG=path):
                page = self.page()

        self.assertContains(page, "finish")
        self.assertNotContains(page, "start\n")

    def test_an_empty_log_says_so(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            override_settings(UPDATE_LOG=os.path.join(tmp, "update.log")),
        ):
            self.assertContains(self.page(), "Nothing written yet.")
