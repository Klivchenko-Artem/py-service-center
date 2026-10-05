"""Корневые маршруты."""

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthz(_request):
    """Живость процесса. База тут намеренно не трогается."""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz),
    path("", include("service.urls")),
]
