"""E2E integration test for M4 — full flow scrape_deaths task → DeathEvent.

Spec M4 §5/D22: Round 1 → DB has 50 fresh deaths. Round 2 → all duplicates
(idempotency). The mocked subprocess invokes the spider on the saved fixture
in-process — no live HTTP, no real subprocess, no Twisted reactor.

Trade-off: this test does NOT exercise the broker→worker serialization path
(eager mode runs in-process), but the goal is task-logic + spider-pipeline
+ service-dedup integration, not Celery transport. Real-broker tests are
post-M4 work.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest
from django.test import override_settings
from scrapy.http import HtmlResponse, Request

from apps.deaths.models import DeathEvent
from apps.deaths.services import save_death_event
from apps.deaths.tasks import scrape_deaths
from scrapers.tibiantis_scrapers.spiders.deaths_spider import DeathsSpider

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "deaths_sample.html"


def _spider_fixture_side_effect(
    *args: object, **kwargs: object
) -> subprocess.CompletedProcess[str]:
    """Replace ``subprocess.run``: invoke spider on saved fixture, save items, return JSON.

    Mirrors what ``manage.py scrape_deaths`` does in real subprocess but in-process:
    spider parses fixture HTML → ``save_death_event`` per item → JSON summary on
    "stdout". Re-invoked across rounds → same items yielded each call (fixture is
    static), so round 2 hits dedup constraint on every row.
    """
    spider = DeathsSpider()
    request = Request(url="https://tibiantis.info/stats/deaths")
    response = HtmlResponse(
        url=request.url,
        body=FIXTURE_PATH.read_bytes(),
        encoding="utf-8",
        request=request,
    )
    yielded = duplicates = 0
    for item in spider.parse(response):
        result = save_death_event(dict(item))
        yielded += 1
        if result is None:
            duplicates += 1
    return subprocess.CompletedProcess(
        args=args[0] if args else [],
        returncode=0,
        stdout=json.dumps({"yielded": yielded, "duplicates": duplicates}),
        stderr="",
    )


@pytest.mark.django_db(transaction=True)
@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
@mock.patch("apps.deaths.tasks.subprocess.run", side_effect=_spider_fixture_side_effect)
def test_e2e_first_scrape_creates_50_deaths_second_scrape_dedups(
    mock_run: mock.MagicMock,
) -> None:
    """Round 1 inserts 50 fresh DeathEvents, round 2 dedups completely.

    Asserts BOTH counters in both rounds (M3 retro #61 lesson — single-counter
    asserts let counter swap bugs slip through) AND DB row count remains stable
    after round 2 (true idempotency, not just "duplicates reported correctly").

    M8-D39 note: scrape_deaths return shape was extended with the announce
    summary (events_announced/events_skipped/fail_count). The M4 contract this
    test guards is the scrape counters — assertions are subset-style so future
    additions to the task return dict don't break this regression guard
    (Pułapka F from #131 — keys added, never removed).
    """
    # Round 1 — fresh DB, all 50 inserted
    result1 = scrape_deaths.apply().get()
    assert result1["yielded"] == 50
    assert result1["duplicates"] == 0
    assert result1["returncode"] == 0
    assert DeathEvent.objects.count() == 50

    # Round 2 — same fixture, full dedup, count stable
    result2 = scrape_deaths.apply().get()
    assert result2["yielded"] == 50
    assert result2["duplicates"] == 50
    assert result2["returncode"] == 0
    assert DeathEvent.objects.count() == 50

    assert mock_run.call_count == 2
