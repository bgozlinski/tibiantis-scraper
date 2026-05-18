"""MongoDB access layer for project-wide log storage.

Mongo is used **only** for logs in this project (CLAUDE.md §4). The helpers
here lazily build a singleton :class:`pymongo.MongoClient` and create
collection-specific indexes on first use so the logging and Scrapy pipelines
can stay schema-free.
"""

from __future__ import annotations

from typing import Optional

import pymongo
from django.conf import settings
from pymongo.collection import Collection
from pymongo.database import Database

_client: Optional[pymongo.MongoClient] = None
_initialized_collections: set[str] = set()


def get_mongo_client() -> pymongo.MongoClient:
    """Lazy singleton MongoClient with fail-fast timeouts.

    serverSelectionTimeoutMS=2000 prevents logger.info() from hanging 30s
    when Mongo is down — fall back to stderr quickly instead (§6.4).
    """
    global _client
    if _client is None:
        _client = pymongo.MongoClient(
            settings.MONGO_URL,
            serverSelectionTimeoutMS=2000,
            connectTimeoutMS=2000,
            socketTimeoutMS=2000,
        )
    return _client


def get_database() -> Database:
    """Return the configured :class:`Database` from the lazy client."""
    return get_mongo_client()[settings.MONGO_DB]


def get_collection(name: str) -> Collection:
    """Return collection, creating idempotent indexes on first call.

    Index strategy (§3.5):
    - app_logs: timestamp DESC (most-recent-first debug query).
    - scrape_logs: spider_name + finished_at DESC (recent runs per spider).
    """
    collection = get_database()[name]

    if name not in _initialized_collections:
        if name == "app_logs":
            collection.create_index(
                [("timestamp", pymongo.DESCENDING)],
                name="app_logs_timestamp_desc",
            )
        elif name == "scrape_logs":
            collection.create_index(
                [
                    ("spider_name", pymongo.ASCENDING),
                    ("finished_at", pymongo.DESCENDING),
                ],
                name="scrape_logs_spider_finished_desc",
            )
        _initialized_collections.add(name)

    return collection
