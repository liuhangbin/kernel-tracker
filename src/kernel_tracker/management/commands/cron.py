"""Management command for scheduled tasks.

Usage:
  manage.py cron update [-v] [tree ...]
  manage.py cron daemon [-v] [--once]
"""

import time
import traceback

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import close_old_connections

from kernel_tracker import processing
from kernel_tracker.models import Tree, UpdateSchedule
from kernel_tracker.repository import repository

# How often the daemon reads the schedule back from the database, so that a
# change made in the admin takes effect without restarting anything.
RECHECK = 60


class Command(BaseCommand):
    help = "Cron commands. Updates trees, etc."
    missing_args_message = "please specify a subcommand"

    def add_arguments(self, parser):
        class SubParser(CommandParser):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)

        subparsers = parser.add_subparsers(
            title="Cron commands", parser_class=SubParser
        )

        parser_update = subparsers.add_parser(
            "update", help="update all trees, or only the ones named"
        )
        parser_update.set_defaults(func=self.handle_update)
        self.add_arguments_update(parser_update)

        parser_daemon = subparsers.add_parser(
            "daemon",
            help="keep updating all trees on the schedule set in the admin",
        )
        parser_daemon.set_defaults(func=self.handle_daemon)
        self.add_arguments_daemon(parser_daemon)

    def add_arguments_update(self, parser):
        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            default=False,
            help="display progress",
        )
        parser.add_argument(
            "trees",
            nargs="*",
            help="names of the trees to update, all of them if none are given",
        )

    def add_arguments_daemon(self, parser):
        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            default=False,
            help="display progress",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            default=False,
            help="exit after one update instead of staying on schedule",
        )

    def handle(self, **options):
        options["func"](**options)

    def handle_update(self, **options):
        trees = options["trees"]
        if trees:
            known = Tree.objects.filter(name__in=trees).values_list("name", flat=True)
            unknown = sorted(set(trees) - set(known))
            if unknown:
                raise CommandError(f"Unknown tree(s): {', '.join(unknown)}")
        processing.fetch_and_process_all(options["verbose"], trees)

    def handle_daemon(self, **options):
        self.run_scheduled(options["verbose"], forever=not options["once"])

    def run_scheduled(self, verbose, forever):
        """Run an update whenever the schedule stored in the database says so.

        Nothing happens until it is enabled in the admin. Each round is
        independent: a failure in one of them is logged and leaves the
        schedule running.
        """
        while True:
            # Read the schedule back every round: it can be changed in the
            # admin while this is running.
            self.update_if_due(verbose)
            if not forever:
                return
            # Nothing keeps this connection alive over hours of sleeping.
            close_old_connections()
            time.sleep(RECHECK)

    def update_if_due(self, verbose):
        """Update once if the schedule says so, reporting instead of raising.

        One failed update must not stop the ones after it, so nothing here
        is allowed to escape.
        """
        schedule = UpdateSchedule.get()
        try:
            if schedule.enabled and schedule.due():
                self.update_once(verbose)
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    def update_once(self, verbose):
        schedule = UpdateSchedule.get()
        try:
            if processing.is_running():
                self.stdout.write("Another update is already running, skipping.")
                return
            # Unlike a one-off `cron update`, this process may have read
            # through the repository before. Reopen it so the objects its
            # own fetch brings in are visible.
            repository.reset()
            processing.fetch_and_process_all(verbose, None)
        finally:
            schedule.record_run()
