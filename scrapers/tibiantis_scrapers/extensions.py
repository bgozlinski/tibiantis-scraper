"""Scrapy extensions that the project plugs into the framework's signal bus."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from django.conf import settings as django_settings
from pymongo.errors import PyMongoError
from scrapy import signals
from scrapy.crawler import Crawler
from scrapy.exceptions import NotConfigured
from scrapy.spiders import Spider

from logs_backend import get_collection

logger = logging.getLogger(__name__)


class MongoStatsExtension:
    """Persist one ``scrape_logs`` document per spider run.

    Wired through Scrapy's ``EXTENSIONS`` setting; raises
    :class:`NotConfigured` when ``MONGO_URL`` is empty so it disables
    cleanly in environments without Mongo (e.g. unit tests).
    """

    def __init__(self) -> None:
        self.started_at: datetime | None = None

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "MongoStatsExtension":
        """Subscribe to spider open/close signals or refuse to load."""
        if not django_settings.MONGO_URL:
            raise NotConfigured(
                "MONGO_URL not configured — MongoStatsExtension disabled"
            )

        instance = cls()
        crawler.signals.connect(instance.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(instance.spider_closed, signal=signals.spider_closed)
        return instance

    def spider_opened(self, spider: Spider) -> None:
        """Record the run start time."""
        self.started_at = datetime.now(tz=timezone.utc)

    def spider_closed(self, spider: Spider, reason: str) -> None:
        """Flush a summary document with run stats to Mongo."""
        finished_at = datetime.now(tz=timezone.utc)
        stats: dict[str, Any] = spider.crawler.stats.get_stats()
        error_count = stats.get("log_count/ERROR", 0)

        doc = {
            "spider_name": spider.name,
            "started_at": self.started_at,
            "finished_at": finished_at,
            "duration_seconds": (
                (finished_at - self.started_at).total_seconds()
                if self.started_at
                else 0.0
            ),
            "items_scraped": stats.get("item_scraped_count", 0),
            "items_dropped": stats.get("item_dropped_count", 0),
            "stats": stats,
            "errors": [f"log_count/ERROR={error_count}"] if error_count > 0 else [],
        }

        try:
            get_collection("scrape_logs").insert_one(doc)
        except (PyMongoError, Exception) as e:
            spider.logger.error("Mongo flush failed: %s", e, exc_info=True)
