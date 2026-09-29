"""Django admin registrations for kernel_tracker models."""

import os
import subprocess
import sys

from django.contrib import admin, messages

from kernel_tracker import models, processing
from kernel_tracker.models import (
    Commit,
    File,
    Fix,
    MissingFix,
    Series,
    Tree,
    TreeAlias,
    VanillaVersion,
)
from kernel_tracker.repository import repository


@admin.register(Tree)
class TreeAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "is_vanilla", "url", "branch", "head"]
    list_filter = ["kind", "is_vanilla"]
    search_fields = ["name", "url"]
    actions = ["update_trees"]

    @admin.action(description="Fetch and process selected trees in the background")
    def update_trees(self, request, queryset):
        """Update the selected trees in a process of their own.

        The work takes as long as `cron update` does, so it is started
        detached and the page comes back immediately.
        """
        names = list(queryset.values_list("name", flat=True))
        if processing.is_running():
            self.message_user(
                request, "Another update is already running.", messages.WARNING
            )
            return
        subprocess.Popen(
            [
                sys.executable,
                os.path.join(os.path.dirname(__file__), "manage.py"),
                "cron",
                "update",
                *names,
            ],
            start_new_session=True,
        )
        self.message_user(
            request, f"Updating {', '.join(names)} in the background.", messages.SUCCESS
        )

    def save_model(self, request, obj, form, change):
        """Keep the git remote in sync, the way `tree add`/`tree change` do."""
        old_name = models.Tree.objects.get(pk=obj.pk).name if change else None
        super().save_model(request, obj, form, change)
        if old_name and old_name != obj.name and old_name in repository.remotes.names():
            repository.remotes.rename(old_name, obj.name)
        obj.ensure_remote()
        if obj.url != repository.remotes[obj.name].url:
            repository.remotes.set_url(obj.name, obj.url)

    def delete_model(self, request, obj):
        """Drop the git remote along with the tree row."""
        name = obj.name
        super().delete_model(request, obj)
        if name in repository.remotes.names():
            repository.remotes.delete(name)

    def delete_queryset(self, request, queryset):
        """Delete trees one by one so that each git remote is dropped too."""
        for obj in queryset:
            self.delete_model(request, obj)


@admin.register(Commit)
class CommitAdmin(admin.ModelAdmin):
    list_display = ["oid", "is_merge", "created_at"]
    search_fields = ["oid"]
    list_filter = ["is_merge"]


@admin.register(Fix)
class FixAdmin(admin.ModelAdmin):
    list_display = ["fixing", "fixed_by", "kind"]
    list_filter = ["kind"]


@admin.register(Series)
class SeriesAdmin(admin.ModelAdmin):
    list_display = ["head", "kind", "name", "link"]
    list_filter = ["kind"]


@admin.register(VanillaVersion)
class VanillaVersionAdmin(admin.ModelAdmin):
    list_display = ["version", "commit"]


@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    list_display = ["path"]
    search_fields = ["path"]


@admin.register(TreeAlias)
class TreeAliasAdmin(admin.ModelAdmin):
    list_display = ["tree", "url", "branch"]


@admin.register(MissingFix)
class MissingFixAdmin(admin.ModelAdmin):
    list_display = ["fixing", "fixed_by", "is_reported"]
