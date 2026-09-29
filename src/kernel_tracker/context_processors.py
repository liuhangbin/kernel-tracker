"""Django template context processors."""

from django.conf import settings


def version_processor(request):
    return {"KERNEL_TRACKER_VERSION": settings.VERSION}
