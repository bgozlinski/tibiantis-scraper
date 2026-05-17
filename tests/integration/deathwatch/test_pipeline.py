"""Integration tests for DjangoPipeline → record_watched_death (DW-4).

E2E: CharacterDeathsSpider parses fixture HTML → emits items → pipeline routes
to apps.deathwatch.services.record_watched_death → real DB rows in
WatchedDeathEvent (or correctly dropped per §3.6 "po dodaniu" filter).

Unit-level dispatch is covered by tests/unit/scrapers/test_pipeline.py. This
file verifies the actual service is wired correctly without mocks.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone
from scrapy.http import HtmlResponse

from apps.accounts.models import User
from apps.characters.models import Character
from apps.deathwatch.models import DeathWatch, WatchedDeathEvent
from apps.deathwatch.services import add_death_watch
from scrapers.tibiantis_scrapers.pipelines import DjangoPipeline
from scrapers.tibiantis_scrapers.spiders.character_deaths_spider import (
    CharacterDeathsSpider,
)

YHRAL_FIXTURE = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "character_yhral.html"
)


def _backdate_watch(watch: DeathWatch, delta: timedelta) -> None:
    """Force watch.created_at backward (auto_now_add workaround)."""
    DeathWatch.objects.filter(pk=watch.pk).update(created_at=timezone.now() - delta)


@pytest.fixture()
def yhral_response() -> HtmlResponse:
    body = YHRAL_FIXTURE.read_bytes()
    return HtmlResponse(
        url="https://tibiantis.online/?page=character&name=Yhral",
        body=body,
        encoding="utf-8",
    )


@pytest.fixture()
def spider_stub():
    """Minimal spider stub — pipeline only reads `crawler.stats.inc_value`."""

    class _Spider:
        class _Crawler:
            class _Stats:
                def __init__(self) -> None:
                    self.calls: list[str] = []

                def inc_value(self, key: str) -> None:
                    self.calls.append(key)

            stats = _Stats()

        crawler = _Crawler()

    return _Spider()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_pipeline_persists_event_for_active_watch_with_past_created_at(
    yhral_response: HtmlResponse, spider_stub
) -> None:
    """Happy path E2E: watch with past created_at → fixture death → DB row."""
    from asgiref.sync import sync_to_async

    user = await sync_to_async(User.objects.create)(username="alice", discord_id="1")
    watch = await sync_to_async(add_death_watch)(user, "Yhral")
    await sync_to_async(_backdate_watch)(watch, timedelta(days=365))

    spider = CharacterDeathsSpider(name="Yhral")
    pipeline = DjangoPipeline()

    items = list(spider.parse(yhral_response))
    assert len(items) >= 1
    for item in items:
        await pipeline.process_item(item, spider_stub)

    persisted = await sync_to_async(
        lambda: WatchedDeathEvent.objects.filter(character__name="Yhral").count()
    )()
    assert persisted >= 1
    # No drops on happy path
    assert "custom/watched_death_dropped" not in spider_stub.crawler.stats.calls


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_pipeline_drops_event_when_no_watch_exists(
    yhral_response: HtmlResponse, spider_stub
) -> None:
    """No watch for character → record_watched_death returns None → counter ticks."""
    from asgiref.sync import sync_to_async

    await sync_to_async(Character.objects.create)(name="Yhral")

    spider = CharacterDeathsSpider(name="Yhral")
    pipeline = DjangoPipeline()

    items = list(spider.parse(yhral_response))
    for item in items:
        await pipeline.process_item(item, spider_stub)

    persisted = await sync_to_async(WatchedDeathEvent.objects.count)()
    assert persisted == 0
    # Counter ticked at least once (per item dropped)
    drops = [
        c
        for c in spider_stub.crawler.stats.calls
        if c == "custom/watched_death_dropped"
    ]
    assert len(drops) == len(items)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_pipeline_drops_event_when_died_before_watch_created(
    yhral_response: HtmlResponse, spider_stub
) -> None:
    """Watch added AFTER death → service drops (§3.6 "po dodaniu")."""
    from asgiref.sync import sync_to_async

    user = await sync_to_async(User.objects.create)(username="alice", discord_id="1")
    # Watch's created_at = now (auto_now_add); fixture death is from 2026-04-12,
    # which (at test runtime in 2026-05+) is in the past → drop.
    await sync_to_async(add_death_watch)(user, "Yhral")

    spider = CharacterDeathsSpider(name="Yhral")
    pipeline = DjangoPipeline()

    for item in spider.parse(yhral_response):
        await pipeline.process_item(item, spider_stub)

    persisted = await sync_to_async(WatchedDeathEvent.objects.count)()
    assert persisted == 0
