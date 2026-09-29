"""Management command for database consistency checks.

Usage:
  manage.py fsck
"""

from django.core.management.base import BaseCommand

from kernel_tracker import models, processing, utils


class Command(BaseCommand):
    help = "Attempts to fix some database errors."

    def check_stale_series(self):
        """Remove series with no commits or invalid heads."""
        fixed = 0
        count = models.Series.objects.all().count()
        for i, s in enumerate(models.Series.objects.all()):
            if i % 1024 == 0:
                utils.message(f"{i * 100 // count}%")
            if s.commits.count() == 0:
                utils.message(f"-> removing stale series {s.head}", True)
                s.delete()
                fixed += 1
                continue
            commit = models.Commit.getc(s.head)
            if commit is None:
                new_head = list(s.commits.order_by("-position")[:2])
                if len(new_head) < 2:
                    utils.message(f"-> removing stale series {s.head}", True)
                    s.delete()
                else:
                    new_oid = new_head[0].oid
                    utils.message(f"-> fixing stale series {s.head} -> {new_oid}", True)
                    s.head = new_oid
                    s.save()
                fixed += 1
            elif commit.series is None:
                utils.message(
                    f"-> ERROR: mismatched series {s.head}. Not fixing.", True
                )
        return fixed

    def remove_duplicate_aliases(self):
        """Remove duplicate tree aliases."""
        all_aliases = models.TreeAlias.objects.all()
        seen = []
        removed = 0
        for alias in all_aliases:
            url = alias.remote_url()
            if url not in seen:
                seen.append(url)
            else:
                alias.delete()
                removed += 1
        return removed

    def handle(self, **options):
        if processing.check_running():
            utils.message("Cannot check now: cron is running.", True)
            return
        fixed = 0
        try:
            utils.message("Checking for stale series...", True)
            fixed += self.check_stale_series()
            utils.message("Cleaning up duplicate aliases...", True)
            fixed += self.remove_duplicate_aliases()
        finally:
            processing.remove_lock_file()
        utils.message(f"Done. Fixed {fixed} problems.", True)
