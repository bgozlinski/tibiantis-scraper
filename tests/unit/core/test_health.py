"""Tests for /health/ endpoint — DB + Redis ping sanity for Docker HEALTHCHECK."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import redis
from django.db import OperationalError
from django.test import Client
from django.urls import reverse


@pytest.fixture(autouse=True)
def mock_redis_ok(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Default: Redis ping returns True. Tests override side_effect for failure."""
    mock_client = MagicMock()
    mock_client.ping.return_value = True
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda *a, **kw: mock_client,
    )
    return mock_client


@pytest.mark.django_db
def test_health_returns_200_when_db_and_redis_ok(client: Client) -> None:
    """Happy path: oba checki przechodzą, JSON shape pinned, 200 OK."""
    response = client.get(reverse("health-check"))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    body = response.json()
    assert body == {"db": "ok", "redis": "ok"}


@pytest.mark.django_db
def test_health_returns_503_when_db_fails(client: Client) -> None:
    """DB cursor raises OperationalError → 503 + db: fail + error message."""
    with patch(
        "apps.core.health.connection.cursor",
        side_effect=OperationalError("connection refused"),
    ):
        response = client.get(reverse("health-check"))

    assert response.status_code == 503
    body = response.json()
    assert body["db"] == "fail"
    assert body["redis"] == "ok"
    assert "connection refused" in body["error"]


@pytest.mark.django_db
def test_health_returns_503_when_redis_fails(
    client: Client,
    mock_redis_ok: MagicMock,
) -> None:
    """Redis ping raises ConnectionError → 503 + redis: fail."""
    mock_redis_ok.ping.side_effect = redis.ConnectionError("Connection refused")

    response = client.get(reverse("health-check"))

    assert response.status_code == 503
    body = response.json()
    assert body["db"] == "ok"
    assert body["redis"] == "fail"
    assert "Connection refused" in body["error"]


@pytest.mark.django_db
def test_health_response_shape_keys_locked(client: Client) -> None:
    """JSON keys subset of {db, redis, error}.

    Forward-compat lock dla M-future Mongo/Celery checks — gdy ktoś doda
    "mongo" lub "celery" do response bez aktualizacji testu, ten test pada
    i wymusza świadomą decyzję o rozszerzeniu shape.
    """
    response = client.get(reverse("health-check"))
    body = response.json()

    assert set(body.keys()).issubset({"db", "redis", "error"})
