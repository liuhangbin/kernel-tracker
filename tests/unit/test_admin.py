"""Tests for the tree admin actions."""

from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from kernel_tracker.models import Tree


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

    def test_another_running_update_refuses_to_start_one(self):
        with (
            mock.patch("kernel_tracker.processing.is_running", return_value=True),
            mock.patch("kernel_tracker.admin.subprocess.Popen") as popen,
        ):
            self.run_action("linux")

        popen.assert_not_called()
