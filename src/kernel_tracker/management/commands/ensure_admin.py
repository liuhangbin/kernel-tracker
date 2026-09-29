"""Management command creating the administrator account.

Usage:
  manage.py ensure_admin
"""

import secrets

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create the administrator account unless there already is one."

    def handle(self, **options):
        if User.objects.filter(is_superuser=True).exists():
            # Nothing to report: the container runs this on every start and
            # only the run that creates the account has a password to show.
            return
        if User.objects.filter(username=settings.ADMIN_NAME).exists():
            raise CommandError(f'User "{settings.ADMIN_NAME}" already exists.')
        password = settings.ADMIN_PASSWORD or secrets.token_urlsafe(16)
        User.objects.create_superuser(
            settings.ADMIN_NAME, settings.ADMIN_EMAIL, password
        )
        self.stdout.write(
            f'Created administrator "{settings.ADMIN_NAME}" '
            f"with password: {password}"
        )
