"""E2E integration test for M6 — Django logger → MongoLogHandler → app_logs.

Full chain without bypass: invokes the configured Django LOGGING dispatch
(factory_or_null → MongoLogHandler → real Mongo), then reads the document
back via pymongo. Confirms the production wiring works end-to-end.

Scrapy MongoStatsExtension e2e is intentionally skipped (plan §Task #3
Optional AC, recommendation: opcja 3) — D29 unit tests cover the extension
flow, and a real `scrapy crawl` subprocess inside pytest brings up the
Twisted reactor with reactor-reuse hazards. Manual smoke covers it:
`scrapy crawl deaths` locally + `db.scrape_logs.count_documents({})`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Iterator

import pytest

import logs_backend
from logs_backend import get_mongo_client
from logs_backend.handlers import MongoLogHandler

if TYPE_CHECKING:
    from django.conf import LazySettings
    from pymongo.database import Database


@pytest.fixture
def mongo_clean(settings: LazySettings) -> Iterator[Database]:
    """Force _test DB suffix, reset module singletons, drop M6 collections."""
    if not settings.MONGO_DB.endswith("_test"):
        settings.MONGO_DB = f"{settings.MONGO_DB}_test"
    # Paranoia — never let a misconfigured env wipe production app_logs.
    assert "test" in settings.MONGO_DB.lower()

    logs_backend._client = None
    logs_backend._initialized_collections.clear()

    db = get_mongo_client()[settings.MONGO_DB]
    for name in ("app_logs", "scrape_logs"):
        db[name].drop()

    yield db

    for name in ("app_logs", "scrape_logs"):
        db[name].drop()


def _apps_logger_has_mongo_handler() -> bool:
    """LOGGING dict applied at Django startup must have wired MongoLogHandler.

    If MONGO_URL was empty at startup, factory_or_null returned NullHandler
    and these e2e tests cannot assert anything meaningful — fail loudly.
    """
    apps_logger = logging.getLogger("apps")
    return any(isinstance(h, MongoLogHandler) for h in apps_logger.handlers)


def test_e2e_django_logger_persists_to_app_logs(mongo_clean: Database) -> None:
    """logger.info() in apps.* writes 1 doc to app_logs via the configured LOGGING."""
    assert _apps_logger_has_mongo_handler(), (
        "MongoLogHandler not attached to 'apps' logger — MONGO_URL was probably "
        "empty at Django startup. Set MONGO_URL in .env / CI env to run this test."
    )

    logging.getLogger("apps.test").info("hello e2e")

    docs = list(mongo_clean.app_logs.find({"message": "hello e2e"}))
    assert len(docs) == 1
    doc = docs[0]
    assert doc["level"] == "INFO"
    assert doc["logger"] == "apps.test"
    assert doc["message"] == "hello e2e"
    assert doc["timestamp"] is not None


def test_e2e_django_logger_with_exception_persists_traceback(
    mongo_clean: Database,
) -> None:
    """logger.exception() persists formatted exc_info string (§3.6)."""
    assert _apps_logger_has_mongo_handler()

    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("apps.test").exception("operation failed")

    doc = mongo_clean.app_logs.find_one({"message": "operation failed"})
    assert doc is not None
    assert doc["level"] == "ERROR"
    assert "exc_info" in doc
    assert "ValueError" in doc["exc_info"]
    assert "boom" in doc["exc_info"]
    assert "Traceback" in doc["exc_info"]
