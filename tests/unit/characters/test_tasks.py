"""Tests for apps.characters.tasks (Celery smoke tasks)."""

from __future__ import annotations

from pytest_django.fixtures import SettingsWrapper

from apps.characters.tasks import ping


def test_ping_returns_pong_when_called_directly() -> None:
    """Direct sync call — sanity that ping is a plain callable returning 'pong'."""
    assert ping() == "pong"


def test_ping_returns_pong_via_eager_delay(settings: SettingsWrapper) -> None:
    """Eager mode exercises the full Celery task lifecycle (publish → execute → result)
    in-process, without a live broker or worker. CELERY_TASK_EAGER_PROPAGATES=True
    surfaces task exceptions as raw Python exceptions instead of Celery Failure objects.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True

    result = ping.delay()

    assert result.get(timeout=5) == "pong"
