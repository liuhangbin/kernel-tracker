"""Django views for the kernel-tracker web UI."""

from functools import wraps

from django import http
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from kernel_tracker import dataview, models, utils
from kernel_tracker.pages import RequestPages


def with_tree(f):
    @wraps(f)
    def wrapper(request, tree, **kwargs):
        if tree == "all":
            return f(request, tree=None, **kwargs)
        return f(request, tree=get_object_or_404(models.Tree, name=tree), **kwargs)

    return wrapper


def with_series(f):
    @wraps(f)
    def wrapper(request, series_id, **kwargs):
        if len(series_id) <= 6:
            try:
                pk = int(series_id)
            except ValueError:
                pk = 0
            if pk > 0:
                q = models.Series.objects.filter(pk=pk)
                if len(q) == 1:
                    return f(request, q[0], **kwargs)
        commit = str(utils.normalize(series_id))
        return f(
            request,
            get_object_or_404(models.Series, commits__oid=commit),
            **kwargs,
        )

    return wrapper


def with_person_email(f):
    @wraps(f)
    def wrapper(request, email, **kwargs):
        return f(request, email=email, **kwargs)

    return wrapper


def with_path(f):
    @wraps(f)
    def wrapper(request, path, **kwargs):
        return f(request, file=get_object_or_404(models.File, path=path), **kwargs)

    return wrapper


def with_commit(f):
    @wraps(f)
    def wrapper(request, commit, **kwargs):
        try:
            c = models.Commit.getc(utils.normalize(commit))
        except KeyError:
            c = None
        if not c:
            raise http.Http404(f"Unknown commit {commit}")
        return f(request, c, **kwargs)

    return wrapper


def main_page(request):
    trees = models.Tree.all_sorted()
    if len(trees) == 0:
        return render(request, "kernel_tracker/firstuse.html")
    return render(request, "kernel_tracker/index.html", {"trees": trees})


def show_commit_list(request, clist, template_args, **kwargs):
    data = {"tree": None}
    try:
        clist = dataview.commit_list(clist, **kwargs)
    except dataview.DataViewError as e:
        clist = None
        data["error"] = str(e)
    try:
        data["commits"] = RequestPages(request, clist, desc=True)
    except Exception as e:
        if not utils.is_db_regex_exception(e):
            raise
        data["commits"] = None
        data["error"] = "Invalid regex."
    data["trees"] = models.Tree.all_sorted()
    data.update(kwargs)
    data.update(template_args)
    return render(request, "kernel_tracker/commit_list.html", data)


@with_tree
def commit_list(request, tree):
    return show_commit_list(request, models.Commit.objects.all(), {}, tree=tree)


@with_series
def commit_series(request, series):
    return show_commit_list(request, series.commits, {"series": series})


@with_person_email
def commit_list_author(request, email):
    # Phase 2: requires Person model for author-based filtering
    # For now, redirect to the index page
    from django.shortcuts import redirect

    return redirect("index")


@with_tree
@with_path
def commit_list_path(request, tree, file):
    return show_commit_list(request, file.commits.all(), {"path": file}, tree=tree)


def commit_list_filter(request):
    parms = {}
    for p in ("tree", "notin", "path", "excl", "fixes", "unfixed", "partial"):
        parms[p] = request.GET.get(p)

    form_add_tree = (
        utils.dict_to_object(
            name="any upstream", form_value="UPSTREAM", kind=models.Tree.UPSTREAM
        ),
    )
    if parms["tree"]:
        for f in form_add_tree:
            if f.form_value == parms["tree"]:
                parms["tree"] = f
                parms["tree_special"] = f.form_value
                break
        if "tree_special" not in parms:
            parms["tree"] = get_object_or_404(models.Tree, name=parms["tree"])
        clist = models.Commit.objects.all()
    else:
        parms["tree"] = models.Tree.objects.get(is_vanilla=True)
        clist = None

    form_add_notin = (
        utils.dict_to_object(name="(nothing)", form_value="", kind=None),
        utils.dict_to_object(
            name="any upstream", form_value="UPSTREAM", kind=models.Tree.UPSTREAM
        ),
    )
    if parms["notin"]:
        for f in form_add_notin:
            if f.form_value == parms["notin"]:
                parms["notin"] = f
                parms["notin_special"] = f.form_value
                break
        if "notin_special" not in parms:
            parms["notin"] = get_object_or_404(models.Tree, name=parms["notin"])
    else:
        parms["notin"] = None

    return show_commit_list(
        request,
        clist,
        {
            "filter": True,
            "form_add_tree": form_add_tree,
            "form_add_notin": form_add_notin,
        },
        **parms,
    )


@with_commit
def commit_view(request, commit):
    patch_data = utils.commit_to_patch(commit.data)
    fixed_by = [
        {
            "missing": False,
            "commit": c.fixed_by,
            "downstream": [(d, d.main_tree()) for d in c.fixed_by.downstream.all()],
            "kind": c.kind,
        }
        for c in commit.fixed_by_info.all()
        .select_related("fixed_by")
        .prefetch_related("fixed_by__downstream")
    ]
    return render(
        request,
        "kernel_tracker/commit_view.html",
        {
            "commit": commit,
            "fixed_by": fixed_by,
            "patch": patch_data,
        },
    )


def health(request):
    """Simple health check endpoint."""
    return JsonResponse({"version": settings.VERSION}, status=200)
