"""JSON-RPC API methods.

Each decorated function becomes an RPC endpoint at /rpc/<function_name>/.
"""

from django.http import Http404
from django.views.decorators.csrf import csrf_exempt

from kernel_tracker import dataview, models, utils
from kernel_tracker.pages import Pages
from kernel_tracker.repository import repository
from kernel_tracker.rpctranslate import DataWrapper, RpcError, check_regex, json_call


@json_call
def get_trees():
    """Return a list of all configured trees."""
    return list(models.Tree.objects.order_by("name"))


@json_call
def get_tree(commit: models.Commit):
    """Return the trees a commit belongs to."""
    if not commit:
        return []
    return list(commit.trees.all())


@json_call
def get_downstream(commit: models.Commit, tree: models.Tree | None = None):
    """Return downstream backports of an upstream commit.

    Phase 2: requires downstream tree support.
    """
    raise RpcError("downstream tracking not yet implemented")


@json_call
def get_upstream(commit: models.Commit):
    """Return the upstream counterpart of a downstream commit.

    Phase 2: requires downstream tree support.
    """
    raise RpcError("downstream tracking not yet implemented")


@json_call
def get_diff(commit: models.Commit):
    """Return the raw unified diff for a commit."""
    return utils.diff(repository[commit.oid])


@json_call
def get_series(commit: models.Commit):
    """Return the series a commit belongs to."""
    series = commit.series
    if not series:
        raise RpcError("not a part of a series")
    if series.kind != models.Series.GITLAB_MR:
        raise RpcError("not a part of a merge request")
    return series


@json_call
def filter_backported(
    commits: list[models.Commit],
    tree: models.Tree,
    extended: bool = False,
):
    """Return upstream commits not yet backported to the given tree.

    Phase 2: currently returns all commits unchanged.
    """
    return commits


@json_call
def get_missing_fixes(commits: list[models.Commit], tree: models.Tree | None = None):
    """Return fix dependency graph for the given commits.

    Resolves upstream references and builds a directed graph of
    fix relationships.
    """
    if not commits:
        return []

    def update_kind(the_dict, key, kind):
        if the_dict.get(key, "") == "":
            the_dict[key] = kind

    def get_node(key):
        if key not in nodes:
            nodes[key] = {"edges": {}, "indegree": 0}
        return nodes[key]

    def add_edge(start, end, kind):
        start_node = get_node(start)
        end_node = get_node(end)
        if end in start_node["edges"]:
            update_kind(start_node["edges"], end, kind)
            return
        start_node["edges"][end] = kind
        end_node["indegree"] += 1

    # Resolve commits to their upstream counterparts
    orig_references = {}
    upstream_commits = []
    for c in commits:
        up = c.upstream.all()
        if up:
            upstream_commits.extend(up)
            for u in up:
                orig_references[u.oid] = c
        else:
            upstream_commits.append(c)
    commits = upstream_commits

    # Build directed graph of fix relationships
    nodes = {}
    for c in commits:
        add_edge(c.oid, "root", "i")
    unprocessed = set(commits)
    processed = set()
    while unprocessed:
        c = unprocessed.pop()
        if c.oid in processed:
            continue
        processed.add(c.oid)
        for fc_info in c.fixed_by_info.all().select_related("fixed_by"):
            fc = fc_info.fixed_by
            if tree and fc.trees.filter(pk=tree.pk).exists():
                continue
            add_edge(c.oid, fc.oid, fc_info.kind)
            if fc.oid not in processed:
                unprocessed.add(fc)

    all_commits = {}
    for oid, node in nodes.items():
        if oid == "root":
            continue
        all_commits[oid] = {
            "commit": models.Commit.getc(oid),
            "added": oid not in {c.oid for c in commits},
            "fixing": [],
        }
    for c in commits:
        if c.oid in all_commits:
            all_commits[c.oid]["added"] = False

    for oid, node in nodes.items():
        if oid == "root":
            continue
        for fix_oid in node["edges"]:
            if fix_oid == "root":
                continue
            if fix_oid in all_commits:
                all_commits[fix_oid]["fixing"].append(oid)

    def sorted_oids(oid_list):
        return sorted(
            oid_list,
            key=lambda x: repository[x].author.time if repository else 0,
        )

    result = []
    for oid in sorted_oids(all_commits.keys()):
        data = all_commits[oid]
        result.append(
            DataWrapper(
                data["commit"],
                added=data["added"],
                fixing=sorted_oids(data["fixing"]),
            )
        )
    return result


@json_call
def get_missing_series(commits: list[models.Commit], tree: models.Tree | None = None):
    """Return series with inclusion status for the given commits."""
    processed_series = []
    found = []
    for c in commits:
        if not c.series:
            found.append([c])
            continue
        if c.series in processed_series:
            continue
        processed_series.append(c.series)
        found.append(list(c.series.commits.order_by("position")))

    def series_time(commits_in_series):
        """Author time of the first commit, or 0 if it is not in the repository."""
        try:
            return repository[commits_in_series[0].oid].author.time
        except KeyError, ValueError:
            return 0

    found.sort(key=series_time)
    result = []
    for cnt, s in enumerate(found):
        for c in s:
            included = c.trees.filter(pk=tree.pk).exists() if tree else False
            result.append(
                DataWrapper(c, series=cnt, added=c not in commits, included=included)
            )
    return result


@json_call
@check_regex
def commit_list(
    tree: models.Tree | None = None,
    notin: models.Tree | None = None,
    tree_special: str = "",
    notin_special: str = "",
    top: models.Commit | None = None,
    next: models.Commit | None = None,
    author: str = "",
    path: str = "",
    excl: str = "",
    options: list[str] | None = None,
):
    """Return a paginated, filtered commit list.

    Parameters:
      top: newest commit to return (auto-filters to its trees if no tree given).
      next: cursor for pagination (last commit from previous batch).
      options: filter flags ('fixes', 'unfixed', 'partial').
    """
    options = options or []
    clist = models.Commit.objects.all()

    if top and tree and tree not in top.cached_trees:
        raise RpcError("the given commit is not part of the given tree")
    if top:
        clist = clist.filter(pk__lte=top.pk)
    if top and not tree:
        clist = clist.filter(trees__in=top.cached_trees)

    filters = {
        "tree": tree,
        "notin": notin,
        "tree_special": tree_special,
        "notin_special": notin_special,
        "author": author,
        "path": path,
        "excl": excl,
    }
    for option in options:
        if option not in ("fixes", "unfixed", "partial"):
            raise RpcError(f'unknown flag "{option}"')
        filters[option] = True

    try:
        clist = dataview.commit_list(clist, **filters)
    except dataview.DataViewError as e:
        raise RpcError(str(e))

    result = []
    for commit in Pages(clist, next_pk=next.pk if next else None, desc=True):
        extra = {
            "in_series": bool(commit.series),
            "upstream": commit.upstream_tree_names(),
            "downstream": commit.downstream_tree_names(),
            "missing_fixes": commit.missing,
        }
        result.append(DataWrapper(commit, **extra))
    return result


@csrf_exempt
def handle_rpc(request, cmd):
    """Dispatch an RPC request to the appropriate handler."""
    try:
        f = globals()[cmd].json_wrapper
    except KeyError, AttributeError:
        raise Http404()
    return f(request)
