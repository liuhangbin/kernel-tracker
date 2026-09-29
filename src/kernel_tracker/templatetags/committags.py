"""Template tags and filters for rendering commits, trees, and series."""

import re

from django import template
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import escape, format_html, format_html_join
from django.utils.safestring import mark_safe

from kernel_tracker import models, utils

register = template.Library()


@register.filter
def c_abbrev(commit):
    return utils.abbrev(commit)


@register.filter
def c_author_name(commit):
    return commit.data.author.name


@register.filter
def c_author_email(commit):
    return commit.data.author.email


@register.filter
def c_author(commit):
    return utils.sig_email(commit.data.author)


@register.filter
def c_date(commit):
    return utils.sig_date(commit.data.author)


@register.filter
def c_committer(commit):
    return utils.sig_email(commit.data.committer)


@register.filter
def c_commit_date(commit):
    return utils.sig_date(commit.data.committer)


@register.filter
def c_tree_links(commit, dest=None):
    """HTML links to the trees a commit belongs to."""
    return mark_safe(" ".join(t_link(tree, dest) for tree in commit.cached_trees))


@register.filter
def c_tree_selflinks(commit):
    """HTML links to the commit itself, labeled with tree names."""
    return c_tree_links(commit, reverse("commit", args=(commit.oid,)))


@register.filter
def c_trees(commit):
    """HTML list of tree names with icons."""
    return format_html_join(
        " ",
        '{} <span class="tree_name">{}</span>',
        ((t_icon(tree, "tree_icon"), tree.name) for tree in commit.cached_trees),
    )


@register.filter
def c_tree_link_first(commit, dest=None):
    """HTML link to the main tree a commit belongs to."""
    return t_link(commit.main_tree(), dest)


@register.filter
def c_tree_selflink_first(commit):
    """HTML link to the commit in its main tree."""
    return t_link(commit.main_tree(), reverse("commit", args=(commit.oid,)))


@register.filter
def c_downstream_links(commit, prefix=""):
    """HTML links to downstream backports of an upstream commit."""
    res = [
        c_tree_link_first(c, reverse("commit", args=(c.oid,)))
        for c in commit.downstream.all()
    ]
    if not res:
        return ""
    return mark_safe(escape(prefix) + " ".join(res))


@register.filter
def c_upstream_links(commit, prefix=""):
    """HTML links to upstream commits."""
    res = [
        c_tree_links(c, reverse("commit", args=(c.oid,))) for c in commit.upstream.all()
    ]
    if not res:
        return ""
    return mark_safe(escape(prefix) + " ".join(res))


@register.filter
def s_icon(series):
    """Return an icon character for the series kind."""
    if series.kind == models.Series.PATCHSET:
        return mark_safe("&#128279;")
    if series.kind == models.Series.GITLAB_MR:
        return mark_safe('<span style="letter-spacing: -0.2em;">&#10991;&#8624;</span>')
    return "#"


@register.filter
def t_icon(tree, cls="tree_icon"):
    """Return an icon image tag for the tree kind."""
    if tree.kind == models.Tree.UPSTREAM:
        src = "kernel_tracker/upstream.svg"
    elif tree.kind == models.Tree.DOWNSTREAM:
        src = "kernel_tracker/downstream.svg"
    else:
        return ""
    cls_str = format_html(' class="{}"', cls) if cls else ""
    return format_html('<img src="{}" alt=""{}>', static(src), cls_str)


@register.filter
def t_name(tree):
    """HTML icon and name for a tree."""
    return format_html('{} <span class="tree_name">{}</span>', t_icon(tree), tree.name)


@register.filter
def t_link(tree, dest=None):
    """HTML link to a tree's commit list."""
    if not tree:
        return ""
    return format_html(
        '<a href="{}" class="tree_link{}">{}</a>',
        reverse("tree", args=(tree.name,)) if not dest else dest,
        " to_tree" if not dest else "",
        t_name(tree),
    )


@register.filter
def t_link_path(tree, path):
    """HTML link to a path in a tree."""
    return t_link(tree, reverse("path", args=(tree.name, path)))


@register.filter
def t_list_links(tree_list, prefix=""):
    """HTML links from a list of (commit, tree) tuples."""
    res = [t_link(t, reverse("commit", args=(c.oid,))) for (c, t) in tree_list]
    if not res:
        return ""
    return mark_safe(escape(prefix) + " ".join(res))


re_bz = re.compile(
    r"https?://bugzilla\.redhat\.com/(?:show_bug\.cgi\?id=)?([0-9]+)\b",
    re.MULTILINE,
)
re_mr = re.compile(r"https?://gitlab\.com/([a-z/-]+/-/merge_requests/[0-9]+)\b")


@register.filter
def message_links(commit):
    """Format commit message with auto-linked URLs."""
    if not commit.is_downstream:
        return commit.data.message
    msg = escape(commit.data.message)
    msg = re_bz.sub(r'<a href="https://bugzilla.redhat.com/\1">\g<0></a>', msg)
    msg = re_mr.sub(r'<a href="https://gitlab.com/\1">\g<0></a>', msg)
    return mark_safe(msg)
