"""Tests for the `ensure_admin` management command."""

from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings


class EnsureAdminTest(TestCase):
    """Create the administrator, but only when there is none yet."""

    def ensure_admin(self):
        """Run the command and return everything it printed."""
        out = StringIO()
        call_command("ensure_admin", stdout=out)
        return out.getvalue()

    @override_settings(ADMIN_NAME="boss", ADMIN_EMAIL="boss@example.com")
    def test_creates_the_first_superuser(self):
        output = self.ensure_admin()

        user = User.objects.get(username="boss")
        self.assertTrue(user.is_superuser)
        self.assertEqual(user.email, "boss@example.com")
        password = output.strip().rsplit(" ", 1)[-1]
        self.assertTrue(user.check_password(password))

    def test_password_comes_from_the_settings_when_set(self):
        with override_settings(ADMIN_NAME="boss", ADMIN_PASSWORD="s3cret"):
            output = self.ensure_admin()

        self.assertTrue(User.objects.get(username="boss").check_password("s3cret"))
        self.assertIn("s3cret", output)

    @override_settings(ADMIN_NAME="boss")
    def test_nothing_happens_when_an_administrator_exists(self):
        self.ensure_admin()

        output = self.ensure_admin()

        self.assertEqual(output, "")
        self.assertEqual(User.objects.filter(is_superuser=True).count(), 1)

    @override_settings(ADMIN_NAME="boss")
    def test_existing_user_of_another_kind_is_an_error(self):
        User.objects.create_user("boss", "boss@example.com", "nope")

        with self.assertRaises(CommandError):
            self.ensure_admin()

        self.assertFalse(User.objects.get(username="boss").is_superuser)
