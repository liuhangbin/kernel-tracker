"""Tests for the update schedule edited in the admin.

Scheduled updates are off until someone enables them, and the cron
expression is read in the configured timezone.
"""

import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from kernel_tracker.models import UpdateSchedule

UTC = datetime.UTC


class SingleRowTest(TestCase):
    """There is exactly one schedule, whichever way it is reached."""

    def test_get_creates_the_row_once(self):
        schedule = UpdateSchedule.get()

        self.assertEqual(schedule.pk, 1)
        self.assertEqual(UpdateSchedule.get().pk, 1)

    def test_saving_another_instance_updates_the_only_row(self):
        UpdateSchedule(schedule="*/5 * * * *").save()

        self.assertEqual(UpdateSchedule.objects.count(), 1)
        self.assertEqual(UpdateSchedule.objects.get().schedule, "*/5 * * * *")

    def test_defaults_are_disabled_and_hourly(self):
        schedule = UpdateSchedule.get()

        self.assertFalse(schedule.enabled)
        self.assertEqual(schedule.schedule, "0 * * * *")
        self.assertIsNone(schedule.last_run)


class ScheduleTest(TestCase):
    """Cron expressions are turned into due times."""

    def setUp(self):
        super().setUp()
        self.schedule = UpdateSchedule.get()

    def test_next_run_is_the_top_of_the_next_hour(self):
        self.schedule.last_run = datetime.datetime(2026, 10, 4, 8, 30, tzinfo=UTC)

        upcoming = self.schedule.next_run()

        self.assertEqual(
            upcoming.astimezone(UTC), datetime.datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
        )

    def test_next_run_is_in_the_configured_timezone(self):
        # 00:30 UTC is 08:30 in Shanghai, so the 09:00 slot is one offset
        # later: 01:00 UTC. Interpreting the expression in UTC instead would
        # have given 09:00 UTC, eight hours away.
        self.schedule.schedule = "0 9 * * *"
        self.schedule.last_run = datetime.datetime(2026, 10, 4, 0, 30, tzinfo=UTC)
        with override_settings(TIME_ZONE="Asia/Shanghai"):
            upcoming = self.schedule.next_run()

        self.assertEqual(upcoming.utcoffset(), datetime.timedelta(hours=8))
        self.assertEqual(
            upcoming.astimezone(UTC), datetime.datetime(2026, 10, 4, 1, 0, tzinfo=UTC)
        )

    def test_nothing_run_yet_is_due(self):
        self.assertTrue(self.schedule.due())

    def test_it_is_due_again_once_the_interval_passes(self):
        self.schedule.record_run()
        self.assertFalse(self.schedule.due())

        later = timezone.localtime() + datetime.timedelta(hours=1)
        self.assertTrue(self.schedule.due(now=later))

    def test_an_invalid_expression_is_rejected(self):
        self.schedule.schedule = "every now and then"

        with self.assertRaises(ValidationError) as caught:
            self.schedule.full_clean()

        self.assertIn("schedule", caught.exception.message_dict)
