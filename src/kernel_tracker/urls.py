"""Root URL configuration for kernel_tracker."""

from django.contrib import admin
from django.urls import include, path, re_path

from kernel_tracker import rpc, views

urlpatterns = [
    re_path(r"^admin/", admin.site.urls),
    path("", include("django_prometheus.urls")),
    re_path(r"^rpc/(?P<cmd>[a-zA-Z0-9_-]+)/$", rpc.handle_rpc),
    path("", views.main_page, name="index"),
    path("tree/<path:tree>/", views.commit_list, name="tree"),
    path("series/<path:series_id>/", views.commit_series, name="series"),
    path("author/<path:email>/", views.commit_list_author, name="author"),
    path("filter/", views.commit_list_filter, name="filter"),
    path("path/<str:tree>/<path:path>/", views.commit_list_path, name="path"),
    path("commit/<path:commit>/", views.commit_view, name="commit"),
    path("health", views.health, name="health"),
]
