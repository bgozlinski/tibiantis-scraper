"""E2E integration test for M3 — `scrape_watched_characters` full flow.

Spec M3 §5/D17: pełny flow `Character.objects.all()` → freshness filter →
subprocess (mock) → counters → return summary, w eager mode (sync,
in-process, bez live brokera ani live spidera).

Trade-off: nie sprawdzamy serializacji broker→worker — to wymaga real-broker
testów (post-M3). Tu chodzi o **logikę tasku**, nie o transport Celery.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from apps.characters.models import Character
from apps.characters.tasks import scrape_watched_characters


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
