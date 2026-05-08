"""E2E integration test for M3 — `scrape_watched_characters` full flow.

Spec M3 §5/D17: pełny flow `Character.objects.all()` → freshness filter →
subprocess (mock) → counters → return summary, w eager mode (sync,
in-process, bez live brokera ani live spidera).

Trade-off: nie sprawdzamy serializacji broker→worker — to wymaga real-broker
testów (post-M3). Tu chodzi o **logikę tasku**, nie o transport Celery.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from apps.characters.models import Character
from apps.characters.tasks import scrape_watched_characters


def _make_stale_character(name: str = "Yhral") -> Character:
    """Create a Character whose last_scraped_at is stale enough to bypass the
    freshness filter in `scrape_watched_characters`.

    Forces `last_scraped_at = now - 2h` so the task's 30 min freshness threshold
    treats it as eligible for scraping. Uses `.update()` to bypass `auto_now`
    semantics on `last_scraped_at` (M3-D17 retro #5).
    """
    char = Character.objects.create(name=name)
    Character.objects.filter(pk=char.pk).update(
        last_scraped_at=timezone.now() - timedelta(hours=2)
    )
    char.refresh_from_db()
    return char


@pytest.mark.django_db(transaction=True)
@mock.patch("apps.characters.tasks.subprocess.run")
def test_scrape_watched_characters_full_flow_mixed_freshness(
    mock_run: mock.MagicMock,
) -> None:
    """Pełny flow z dwiema postaciami o różnym stanie freshness.

    Seed:
      - "Yhral" (stale, 2h ago) → powinna zostać scrape'owana (subprocess wywołany)
      - "Tester" (fresh, 5 min ago, < 30 min threshold) → skipped (subprocess pominięty)

    Asercje:
      - `result["scraped"] == 1` — tylko Yhral
      - `result["skipped"] == 1` — tylko Tester
      - subprocess wywołany dokładnie raz, z argumentami dla Yhral (sanity:
        gdyby ktoś przeniósł `subprocess.run` do innego modułu, mock-path by
        cicho ucichł i live spider waliłby w tibiantis — `assert_called_once_with`
        wymusza pozytywną walidację, nie tylko negatywną)
      - `Tester.last_scraped_at` niezmienione (skipped → no save → auto_now nie
        odpala)
    """
    yhral = Character.objects.create(name="Yhral", level=120)
    tester = Character.objects.create(name="Tester", level=50)

    stale_ts = timezone.now() - timedelta(hours=2)
    fresh_ts = timezone.now() - timedelta(minutes=5)
    Character.objects.filter(pk=yhral.pk).update(last_scraped_at=stale_ts)
    Character.objects.filter(pk=tester.pk).update(last_scraped_at=fresh_ts)

    tester_last_scraped_before = Character.objects.get(pk=tester.pk).last_scraped_at

    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

    result = scrape_watched_characters.apply().get()

    assert result == {"scraped": 1, "failed": 0, "skipped": 1}
    mock_run.assert_called_once_with(
        [sys.executable, "manage.py", "scrape_character", "Yhral"],
        timeout=60,
        check=False,
    )

    tester_last_scraped_after = Character.objects.get(pk=tester.pk).last_scraped_at
    assert tester_last_scraped_after == tester_last_scraped_before


# === D26 tracker integration tests ===


@pytest.mark.django_db(transaction=True)
@mock.patch("apps.bedmages.services.check_bedmage_watches_for_character")
@mock.patch("apps.characters.tasks.subprocess.run")
def test_scrape_watched_characters_invokes_bedmage_check_on_success(
    mock_run: mock.MagicMock,
    mock_check: mock.MagicMock,
) -> None:
    """Tracker called per scraped character (returncode=0).

    Verifies the post-scrape integration hook from D26: every successful scrape
    fires `check_bedmage_watches_for_character` with the corresponding Character.

    Patch target is `apps.bedmages.services.*` (NOT `apps.characters.tasks.*`)
    because `tasks.py` lazy-imports the function inside the loop — the patch
    intercepts at the source module so the lazy import returns the MagicMock.
    """
    _make_stale_character("Yhral")
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

    result = scrape_watched_characters.apply().get()

    assert result == {"scraped": 1, "failed": 0, "skipped": 0}
    mock_check.assert_called_once()
    called_with = mock_check.call_args[0][0]
    assert called_with.name == "Yhral"


@pytest.mark.django_db(transaction=True)
@mock.patch("apps.bedmages.services.check_bedmage_watches_for_character")
@mock.patch("apps.characters.tasks.subprocess.run")
def test_scrape_watched_characters_does_not_invoke_tracker_on_failure(
    mock_run: mock.MagicMock,
    mock_check: mock.MagicMock,
) -> None:
    """Failed scrape (returncode != 0) skips tracker — §4.5 invariant.

    Tracker decisions must not fire on potentially stale `last_login` from a
    failed scrape. Otherwise a "phantom bed-mage wake" notification could be
    emitted while the character's actual state was never refreshed. Regression
    guard for the design invariant from spec §4.5.
    """
    _make_stale_character("Yhral")
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1)

    scrape_watched_characters.apply().get()

    mock_check.assert_not_called()


@pytest.mark.django_db(transaction=True)
@mock.patch("apps.bedmages.services.check_bedmage_watches_for_character")
@mock.patch("apps.characters.tasks.subprocess.run")
def test_scrape_watched_characters_logs_but_continues_on_tracker_exception(
    mock_run: mock.MagicMock,
    mock_check: mock.MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Tracker exception caught and logged — scrape success metrics intact.

    Defensive isolation: a bug in `apps.bedmages.services` must not bump the
    `failed` counter (the scrape itself succeeded). Failure surfaces via
    `logger.exception` for observability without polluting the Celery task
    return value. Critical for production: tracker bugs would otherwise mask
    real scrape problems in monitoring dashboards.
    """
    _make_stale_character("Yhral")
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
    mock_check.side_effect = RuntimeError("simulated tracker failure")

    with caplog.at_level(logging.ERROR, logger="apps.characters.tasks"):
        result = scrape_watched_characters.apply().get()

    assert result == {"scraped": 1, "failed": 0, "skipped": 0}
    assert any("bedmage check failed" in r.getMessage() for r in caplog.records)
