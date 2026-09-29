"""Simple utility template filters."""

from django import template

register = template.Library()


@register.filter
def match(s, parm):
    """Return the string if it matches the parameter, else empty string."""
    return s if s == parm else ""


@register.filter
def replace(s, result):
    """Replace non-empty string with the given result."""
    return result if s else ""
