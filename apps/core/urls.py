from django.urls import path

from apps.core.health import health_check

urlpatterns = [
    path("", health_check, name="health-check"),
]
