"""Tests for apps.characters.tasks (Celery smoke + scrape_watched_characters)."""

from __future__ import annotations

import subprocess
from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone
from pytest_django.fixtures import SettingsWrapper

from apps.characters.models import Character
from apps.characters.tasks import ping, scrape_watched_characters


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


def _make_stale_character(
    name: str, *, level: int = 100, hours_ago: int = 2
) -> Character:
    """Create a Character with `last_scraped_at` forced into the past.

    `Character.last_scraped_at` is `auto_now=True`, which overrides any value
    passed to `create()` at save-time. Workaround per issue #62 Pułapka B:
    `update()` skips model save() and bypasses auto_now.
    """
    char = Character.objects.create(name=name, level=level)
    Character.objects.filter(pk=char.pk).update(
        last_scraped_at=timezone.now() - timedelta(hours=hours_ago)
    )
    char.refresh_from_db()
    return char


@pytest.mark.django_db
@mock.patch("apps.characters.tasks.subprocess.run")
def test_scrape_watched_characters_handles_subprocess_failure(
    mock_run: mock.MagicMock,
) -> None:
    """returncode != 0 → bumps `failed`, never `scraped`. Task swallows
    per-character failures so Beat keeps firing on schedule (see task docstring).
    """
    _make_stale_character("Yhral")
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1)

    result = scrape_watched_characters.apply().get()

    assert result == {"scraped": 0, "failed": 1, "skipped": 0}
    mock_run.assert_called_once()


@pytest.mark.django_db
@mock.patch("apps.characters.tasks.subprocess.run")
def test_scrape_watched_characters_respects_freshness_threshold(
    mock_run: mock.MagicMock,
) -> None:
    """All characters within freshness window → all skipped, subprocess never
    invoked. `assert_not_called` guards against a regression where the freshness
    branch incorrectly falls through to the scrape (see retro #61 critical bug 2:
    counter swap was caught only because smoke surfaced the wrong number).
    """
    Character.objects.create(name="FreshOne", level=50)
    Character.objects.create(name="FreshTwo", level=80)

    result = scrape_watched_characters.apply().get()

    assert result == {"scraped": 0, "failed": 0, "skipped": 2}
    mock_run.assert_not_called()


@pytest.mark.django_db
@mock.patch("apps.characters.tasks.subprocess.run")
def test_scrape_watched_characters_handles_empty_watchlist(
    mock_run: mock.MagicMock,
) -> None:
    """No Characters in DB → no-op summary, subprocess never invoked.
    Edge case for fresh deployment / first Beat fire before any seed.
    """
    assert Character.objects.count() == 0

    result = scrape_watched_characters.apply().get()

    assert result == {"scraped": 0, "failed": 0, "skipped": 0}
    mock_run.assert_not_called()
