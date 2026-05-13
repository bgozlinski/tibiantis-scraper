"""Tests for scrapers.tibiantis_scrapers.extensions.MongoStatsExtension.

Real Mongo per spec §7.1 (CI mongo:7 service). Spider/Crawler are mocked
because instantiating a real Scrapy crawl inside pytest brings up the
Twisted reactor and is too heavy for unit scope (plan §Pułapka G).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator
from unittest.mock import MagicMock, patch

import pytest
from pymongo.errors import ConnectionFailure
from scrapy import signals
from scrapy.exceptions import NotConfigured

import logs_backend
from logs_backend import get_collection, get_mongo_client
from scrapers.tibiantis_scrapers.extensions import MongoStatsExtension

if TYPE_CHECKING:
    from django.conf import LazySettings


# === Mongo isolation (mirrors tests/unit/logs_backend/conftest.py) ===


@pytest.fixture(autouse=True)
def mongo_isolation(settings: LazySettings) -> Iterator[None]:
    """Force _test DB suffix, reset module singletons, drop collections."""
    if not settings.MONGO_DB.endswith("_test"):
        settings.MONGO_DB = f"{settings.MONGO_DB}_test"

    logs_backend._client = None
    logs_backend._initialized_collections.clear()

    yield

    if not settings.MONGO_URL:
        return
    db = get_mongo_client()[settings.MONGO_DB]
    for name in db.list_collection_names():
        db[name].drop()


# === Spider / Crawler test doubles ===


def _make_spider(
    *,
    name: str = "deaths",
    stats: dict | None = None,
) -> MagicMock:
    spider = MagicMock()
    spider.name = name
    spider.crawler.stats.get_stats.return_value = stats or {
        "item_scraped_count": 50,
        "item_dropped_count": 0,
        "log_count/INFO": 5,
        "log_count/ERROR": 0,
    }
    return spider


# === from_crawler ===


def test_from_crawler_raises_not_configured_when_mongo_url_empty(
    settings: LazySettings,
) -> None:
    """§3.4 — empty MONGO_URL must NotConfigured-disable cleanly, not break Scrapy."""
    settings.MONGO_URL = ""
    crawler = MagicMock()

    with pytest.raises(NotConfigured):
        MongoStatsExtension.from_crawler(crawler)


def test_from_crawler_returns_instance_when_mongo_url_set(
    settings: LazySettings,
) -> None:
    settings.MONGO_URL = "mongodb://localhost:27017"
    crawler = MagicMock()

    instance = MongoStatsExtension.from_crawler(crawler)

    assert isinstance(instance, MongoStatsExtension)


def test_from_crawler_subscribes_to_spider_opened_and_closed(
    settings: LazySettings,
) -> None:
    """Extension must connect both lifecycle signals — otherwise no doc flushed."""
    settings.MONGO_URL = "mongodb://localhost:27017"
    crawler = MagicMock()

    instance = MongoStatsExtension.from_crawler(crawler)

    connected_signals = {
        call.kwargs["signal"] for call in crawler.signals.connect.call_args_list
    }
    assert signals.spider_opened in connected_signals
    assert signals.spider_closed in connected_signals
    # And the handlers are the instance's bound methods
    handlers = {call.args[0] for call in crawler.signals.connect.call_args_list}
    assert instance.spider_opened in handlers
    assert instance.spider_closed in handlers


# === spider_opened ===


def test_spider_opened_records_started_at_utc() -> None:
    """started_at must be timezone-aware UTC — BSON requires tz-aware datetimes."""
    extension = MongoStatsExtension()
    spider = _make_spider()

    extension.spider_opened(spider)

    assert extension.started_at is not None
    assert extension.started_at.tzinfo is not None
    assert extension.started_at.utcoffset().total_seconds() == 0  # UTC


# === spider_closed — happy path doc shape ===


def test_spider_closed_flushes_doc_with_expected_fields() -> None:
    """§4.2 schema — full lifecycle produces one doc with all required fields."""
    extension = MongoStatsExtension()
    spider = _make_spider(
        name="deaths",
        stats={
            "item_scraped_count": 50,
            "item_dropped_count": 2,
            "log_count/INFO": 5,
            "log_count/ERROR": 0,
            "downloader/request_count": 1,
        },
    )

    extension.spider_opened(spider)
    extension.spider_closed(spider, reason="finished")

    doc = get_collection("scrape_logs").find_one({"spider_name": "deaths"})
    assert doc is not None
    assert doc["spider_name"] == "deaths"
    assert doc["started_at"] is not None
    assert doc["finished_at"] is not None
    assert doc["duration_seconds"] >= 0.0
    assert doc["items_scraped"] == 50
    assert doc["items_dropped"] == 2
    assert isinstance(doc["stats"], dict)
    assert doc["stats"]["downloader/request_count"] == 1
    assert doc["errors"] == []


def test_spider_closed_uses_zero_duration_when_opened_skipped() -> None:
    """Defensive — if spider_opened never fired, duration must not crash on None subtraction."""
    extension = MongoStatsExtension()
    spider = _make_spider(name="orphan")

    # Skip spider_opened — started_at stays None
    extension.spider_closed(spider, reason="cancelled")

    doc = get_collection("scrape_logs").find_one({"spider_name": "orphan"})
    assert doc is not None
    assert doc["duration_seconds"] == 0.0
    assert doc["started_at"] is None


# === errors field ===


def test_spider_closed_populates_errors_when_log_count_error_nonzero() -> None:
    """Plan §Pułapka G — errors marker when stats show ERROR-level logs."""
    extension = MongoStatsExtension()
    spider = _make_spider(
        name="failing",
        stats={
            "item_scraped_count": 10,
            "item_dropped_count": 0,
            "log_count/ERROR": 3,
        },
    )

    extension.spider_opened(spider)
    extension.spider_closed(spider, reason="finished")

    doc = get_collection("scrape_logs").find_one({"spider_name": "failing"})
    assert doc is not None
    assert doc["errors"] != []
    assert any("log_count/ERROR=3" in entry for entry in doc["errors"])


def test_spider_closed_leaves_errors_empty_when_no_error_logs() -> None:
    """Sanity inverse of populates_errors — clean runs get empty errors list."""
    extension = MongoStatsExtension()
    spider = _make_spider(name="clean", stats={"log_count/ERROR": 0})

    extension.spider_opened(spider)
    extension.spider_closed(spider, reason="finished")

    doc = get_collection("scrape_logs").find_one({"spider_name": "clean"})
    assert doc is not None
    assert doc["errors"] == []


# === Mongo failure path ===


def test_spider_closed_logs_error_on_mongo_failure_and_does_not_raise() -> None:
    """§6.2 — Mongo down during spider_closed must NOT block the crawl shutdown."""
    extension = MongoStatsExtension()
    spider = _make_spider(name="unreachable_mongo")

    extension.spider_opened(spider)
    with patch(
        "scrapers.tibiantis_scrapers.extensions.get_collection",
        side_effect=ConnectionFailure("mongo unreachable"),
    ):
        # MUST NOT RAISE — spider close is on the crawl-shutdown hot path.
        extension.spider_closed(spider, reason="finished")

    spider.logger.error.assert_called_once()
    args, kwargs = spider.logger.error.call_args
    assert "Mongo flush failed" in args[0]
    assert kwargs.get("exc_info") is True
