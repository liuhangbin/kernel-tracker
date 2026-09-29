"""Shared data manipulation functions for web and RPC frontends.

Provides commit_list() which constructs filtered, annotated querysets
used by both the web views and the JSON-RPC API.
"""

from django.db.models import Count, Prefetch, Q

from kernel_tracker.models import Commit, File, Fix, Tree


class DataViewError(Exception):
    pass


def commit_list(clist, **kwargs):
    """Construct a filtered commit list from a prebuilt queryset.

    kwargs may include:
      tree (Tree): commit must be in this tree.
      notin (Tree): commit must NOT be in this tree.
      tree_special (str): 'UPSTREAM' for any upstream tree.
      notin_special (str): 'UPSTREAM' to exclude all upstream trees.
      path (str): regex filter on file paths.
      excl (str): regex to exclude from path matches.
      fixes (bool): only include commits with fixes to pick.
      unfixed (bool): only include commits needing a fix.
      partial (bool): only include partial backports.
      author (str): regex filter on author email.
    """
    if clist is None:
        return None

    tree_kind = None
    if kwargs.get("tree_special"):
        if kwargs["tree_special"] == "UPSTREAM":
            clist = clist.filter(trees__kind=Tree.UPSTREAM)
            tree_kind = Tree.UPSTREAM
        else:
            raise DataViewError(f"Unknown value for tree: {kwargs['tree_special']}")
    elif kwargs.get("tree"):
        clist = clist.filter(trees=kwargs["tree"])
        tree_kind = kwargs["tree"].kind

    if kwargs.get("notin") or kwargs.get("notin_special"):
        notin = kwargs.get("notin")
        if notin:
            notin_kind = notin.kind
        notin_special = kwargs.get("notin_special")
        any_upstream = False
        if notin_special == "UPSTREAM":
            any_upstream = True
            notin_kind = Tree.UPSTREAM
        elif notin_special:
            raise DataViewError(f"Unknown value for excluded tree: {notin_special}")

        if tree_kind == Tree.UPSTREAM and notin_kind == Tree.UPSTREAM:
            if any_upstream:
                clist = clist.exclude(trees__kind=Tree.UPSTREAM)
            else:
                clist = clist.exclude(trees=notin)
            if kwargs.get("fixes"):
                clist = clist.exclude(fixed_by_info__isnull=True)
        elif tree_kind == Tree.DOWNSTREAM and notin_kind == Tree.DOWNSTREAM:
            clist = clist.exclude(upstream=None)
            clist = clist.exclude(upstream__downstream__trees=notin)
            clist = clist.exclude(upstream__version__pk__lte=notin.origin.pk)
            if kwargs.get("fixes"):
                clist = clist.filter(
                    upstream__fixed_by_info__fixed_by__downstream__trees=notin
                )
        elif (
            tree_kind == Tree.UPSTREAM or tree_kind is None
        ) and notin_kind == Tree.DOWNSTREAM:
            if tree_kind is None:
                clist = clist.filter(trees__kind=Tree.UPSTREAM)
            if kwargs.get("partial"):
                q = Q(trees=notin) & ~Commit.partial_backport_Q()
                clist = clist.exclude(downstream__in=Commit.objects.filter(q))
                del kwargs["partial"]
            else:
                clist = clist.exclude(downstream__trees=notin)
            if kwargs.get("fixes"):
                q = Q(fixed_by_info__fixed_by__downstream__trees=notin)
                if notin.origin:
                    q = q | Q(fixed_by_info__fixed_by__version__pk__lte=notin.origin.pk)
                clist = clist.filter(q)
        elif (
            tree_kind == Tree.DOWNSTREAM or tree_kind is None
        ) and notin_kind == Tree.UPSTREAM:
            if tree_kind is None:
                clist = clist.filter(trees__kind=Tree.DOWNSTREAM)
            if any_upstream:
                clist = clist.exclude(upstream__trees__kind=Tree.UPSTREAM)
            else:
                clist = clist.exclude(upstream__trees=notin)
            if kwargs.get("fixes"):
                clist = clist.exclude(upstream__fixed_by_info__isnull=True)

        if notin_kind == Tree.DOWNSTREAM and notin.origin:
            clist = clist.exclude(version__pk__lte=notin.origin.pk)
    elif kwargs.get("fixes"):
        if tree_kind == Tree.DOWNSTREAM:
            clist = clist.exclude(upstream__fixed_by_info__isnull=True)
        elif tree_kind == Tree.UPSTREAM:
            clist = clist.exclude(fixed_by_info__isnull=True)
        else:
            q = Q(fixed_by_info__isnull=False) | Q(
                upstream__fixed_by_info__isnull=False
            )
            clist = clist.filter(q)

    if kwargs.get("unfixed"):
        clist = clist.exclude(missing_upstream_fixes__isnull=True)
    if kwargs.get("partial"):
        clist = clist.filter(Commit.partial_backport_Q())

    if kwargs.get("excl"):
        files = File.objects.all()
        if kwargs.get("path"):
            files = files.filter(path__regex=kwargs["path"])
        files = files.exclude(path__regex=kwargs["excl"])
        clist = clist.filter(files__in=files)
    elif kwargs.get("path"):
        clist = clist.filter(files__path__regex=kwargs["path"])

    if kwargs.get("author"):
        clist = clist.filter(author__email__regex=kwargs["author"])

    clist = (
        clist.order_by("-pk")
        .annotate(missing=Count("missing_upstream_fixes"))
        .prefetch_related("upstream", "downstream", "series")
        .prefetch_related(
            Prefetch(
                "fixed_by_info",
                queryset=Fix.objects.filter(kind=Fix.REVERT),
                to_attr="reverted_by",
            )
        )
    )
    return clist
