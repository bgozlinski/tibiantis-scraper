from __future__ import annotations

import logging
from typing import Any

import redis
from django.conf import settings
from django.db import OperationalError, connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
def health_check(request: HttpRequest) -> JsonResponse:
    """Liveness + readiness check dla Docker HEALTHCHECK i load balancer'a.

    Sprawdza:
    - DB connectivity (cursor.execute("SELECT 1"))
    - Redis connectivity (redis.Redis(...).ping())

    Returns:
        200 + {"db": "ok", "redis": "ok"} gdy oba OK.
        503 + {"db": "fail"|"ok", "redis": "fail"|"ok", "error": "..."} gdy fail.

    Out of scope (M-future): Mongo check (logging może gracefully degradować),
    Celery worker ping (osobny healthcheck per service w compose).
    """
    status: dict[str, Any] = {"db": "ok", "redis": "ok"}
    status_code = 200

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except OperationalError as exc:
        logger.exception("Health check: DB query failed")
        status["db"] = "fail"
        status["error"] = str(exc)
        status_code = 503

    try:
        client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2)
        client.ping()
    except (redis.ConnectionError, redis.TimeoutError) as exc:
        logger.exception("Health check: Redis ping failed")
        status["redis"] = "fail"
        status["error"] = str(exc)
        status_code = 503

    return JsonResponse(status, status=status_code)
