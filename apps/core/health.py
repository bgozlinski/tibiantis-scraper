"""HTTP health endpoint used by Docker ``HEALTHCHECK`` and the load balancer."""

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
    """Liveness + readiness probe for the web container.

    Checks:

    * **DB connectivity** — runs ``SELECT 1`` through the default cursor.
    * **Redis connectivity** — issues a ``PING`` against ``settings.REDIS_URL``.

    Returns ``200`` with ``{"db": "ok", "redis": "ok"}`` when both succeed, or
    ``503`` and a per-component status when one of them fails. Mongo and
    Celery worker checks are intentionally out of scope — Mongo only carries
    logs (graceful-degradation candidate), and each Celery container ships
    its own ``healthcheck`` in compose.
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
