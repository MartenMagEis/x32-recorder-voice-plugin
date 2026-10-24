"""Mounted by x32-recorder under /plugins/<name>/ (see its plugins/PLUGIN_DEVELOPMENT.md)."""
from django.urls import path

from . import views

urlpatterns = [
    path("samples/", views.review_page),
    path("samples/api/list/", views.sample_list),
    path("samples/api/label/", views.sample_label),
    path("samples/api/delete/", views.sample_delete),
    path("samples/audio/<path:rel>", views.sample_audio),
]
