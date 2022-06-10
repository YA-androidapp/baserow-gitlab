from django.http import HttpResponse, JsonResponse
from django.urls import path, include, re_path
from django.views.decorators.csrf import csrf_exempt

from rest_framework import status
from drf_spectacular.views import SpectacularJSONAPIView, SpectacularRedocView

from baserow.core.registries import plugin_registry, application_type_registry

from .settings import urls as settings_urls
from .user import urls as user_urls
from .user_files import urls as user_files_urls
from .groups import urls as group_urls
from .templates import urls as templates_urls
from .applications import urls as application_urls
from .trash import urls as trash_urls


app_name = "baserow.api"


def public_health_check(request):
    return HttpResponse("OK")


@csrf_exempt
def missing_trailing_slash_error(request):
    return JsonResponse(
        {
            "detail": "URL must end with a trailing slash.",
            "error": "URL_TRAILING_SLASH_MISSING",
        },
        status=status.HTTP_404_NOT_FOUND,
    )


urlpatterns = (
    [
        path("schema.json", SpectacularJSONAPIView.as_view(), name="json_schema"),
        path(
            "redoc/",
            SpectacularRedocView.as_view(url_name="api:json_schema"),
            name="redoc",
        ),
        path("settings/", include(settings_urls, namespace="settings")),
        path("user/", include(user_urls, namespace="user")),
        path("user-files/", include(user_files_urls, namespace="user_files")),
        path("groups/", include(group_urls, namespace="groups")),
        path("templates/", include(templates_urls, namespace="templates")),
        path("applications/", include(application_urls, namespace="applications")),
        path("trash/", include(trash_urls, namespace="trash")),
        path("_health/", public_health_check, name="public_health_check"),
    ]
    + application_type_registry.api_urls
    + plugin_registry.api_urls
    + [
        re_path(
            r".*(?!/)$",
            missing_trailing_slash_error,
            name="missing_trailing_slash_error",
        ),
    ]
)
