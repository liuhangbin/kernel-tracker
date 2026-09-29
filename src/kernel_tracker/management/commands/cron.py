"""Management command for scheduled tasks.

Usage:
  manage.py cron update [-v] [tree ...]
"""

from django.core.management.base import BaseCommand, CommandError, CommandParser

from kernel_tracker import processing
from kernel_tracker.models import Tree


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
