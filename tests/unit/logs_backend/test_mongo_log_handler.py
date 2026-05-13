"""Tests for logs_backend.handlers.MongoLogHandler + factory_or_null + indexes.

Real Mongo per spec §7.1 — mongomock rejected because CI mongo:7 service is
already wired and bypassing the real driver hides bugs. Indexes verified via
`Collection.index_information()` against the names set in `get_collection`.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

import pymongo
import pytest
from pymongo.collection import Collection
from pymongo.errors import ConnectionFailure

import logs_backend
from logs_backend import get_collection, get_mongo_client
from logs_backend.handlers import MongoLogHandler, factory_or_null

if TYPE_CHECKING:
    from django.conf import LazySettings


# === get_mongo_client / get_collection ===


def test_mongo_client_configured_with_fail_fast_timeouts() -> None:
    """§6.4 + Pułapka B — serverSelectionTimeoutMS=2000 prevents 30s hangs."""
    client = get_mongo_client()

    assert client.options.server_selection_timeout == 2.0
    assert client.options.pool_options.connect_timeout == 2.0
    assert client.options.pool_options.socket_timeout == 2.0


def test_get_collection_returns_pymongo_collection() -> None:
    collection = get_collection("app_logs")

    assert isinstance(collection, Collection)


def test_get_collection_creates_index_for_app_logs_on_first_call() -> None:
    """§3.5 — timestamp DESC index created lazily on first call."""
    collection = get_collection("app_logs")

    indexes = collection.index_information()
    assert "app_logs_timestamp_desc" in indexes
    key = indexes["app_logs_timestamp_desc"]["key"]
    assert key == [("timestamp", pymongo.DESCENDING)]


def test_get_collection_creates_compound_index_for_scrape_logs() -> None:
    """§3.5 — spider_name + finished_at DESC compound index."""
    collection = get_collection("scrape_logs")

    indexes = collection.index_information()
    assert "scrape_logs_spider_finished_desc" in indexes
    key = indexes["scrape_logs_spider_finished_desc"]["key"]
    assert key == [
        ("spider_name", pymongo.ASCENDING),
        ("finished_at", pymongo.DESCENDING),
    ]


def test_get_collection_idempotent_on_second_call() -> None:
    """Second call must not raise — Mongo create_index is idempotent (§3.5)."""
    get_collection("app_logs")

    # Force re-entry into the create_index branch by clearing the cache;
    # Mongo itself should still no-op the duplicate index.
    logs_backend._initialized_collections.clear()
    collection = get_collection("app_logs")

    assert "app_logs_timestamp_desc" in collection.index_information()


# === MongoLogHandler.emit ===


def _make_record(
    *,
    name: str = "apps.test",
    level: int = logging.INFO,
    msg: str = "hello",
    lineno: int = 42,
    func: str = "test_func",
    exc_info: tuple | None = None,
) -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=level,
        pathname="/fake/path/services.py",
        lineno=lineno,
        msg=msg,
        args=None,
        exc_info=exc_info,
        func=func,
    )


def test_emit_writes_doc_with_expected_fields(settings: LazySettings) -> None:
    """§4.1 schema — every required field present and correctly typed."""
    handler = MongoLogHandler()
    record = _make_record(msg="bedmage created")

    handler.emit(record)

    doc = get_collection("app_logs").find_one({"message": "bedmage created"})
    assert doc is not None
    assert doc["level"] == "INFO"
    assert doc["logger"] == "apps.test"
    assert doc["message"] == "bedmage created"
    assert doc["module"] == "services"
    assert doc["function"] == "test_func"
    assert doc["line"] == 42
    assert doc["timestamp"] is not None


def test_emit_omits_exc_info_for_records_without_exception() -> None:
    """Pułapka E — exc_info field only present when record.exc_info is set."""
    handler = MongoLogHandler()
    record = _make_record(msg="plain info")

    handler.emit(record)

    doc = get_collection("app_logs").find_one({"message": "plain info"})
    assert doc is not None
    assert "exc_info" not in doc


def test_emit_includes_formatted_exc_info_for_error_records() -> None:
    """§3.6 — formatted traceback string (not structured), via formatter."""
    handler = MongoLogHandler()
    try:
        raise ValueError("boom")
    except ValueError:
        record = _make_record(
            level=logging.ERROR,
            msg="caught it",
            exc_info=sys.exc_info(),
        )

    handler.emit(record)

    doc = get_collection("app_logs").find_one({"message": "caught it"})
    assert doc is not None
    assert "exc_info" in doc
    assert "ValueError" in doc["exc_info"]
    assert "boom" in doc["exc_info"]
    assert "Traceback" in doc["exc_info"]


def test_emit_falls_back_to_stderr_on_mongo_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§3.3 + §6.1 — Mongo down must never raise from emit; stderr fallback."""
    handler = MongoLogHandler()
    record = _make_record(msg="should fall back")

    with patch(
        "logs_backend.handlers.get_collection",
        side_effect=ConnectionFailure("mongo unreachable"),
    ):
        handler.emit(record)  # MUST NOT RAISE

    captured = capsys.readouterr()
    # handleError's default writes the traceback of the failed emit to stderr.
    assert "ConnectionFailure" in captured.err or "mongo unreachable" in captured.err


# === factory_or_null ===


def test_factory_returns_null_handler_when_mongo_url_empty(
    settings: LazySettings,
) -> None:
    """§3.4 — empty MONGO_URL → NullHandler so dev workflow without Mongo works."""
    settings.MONGO_URL = ""

    handler = factory_or_null()

    assert isinstance(handler, logging.NullHandler)
    assert not isinstance(handler, MongoLogHandler)


def test_factory_returns_mongo_handler_when_mongo_url_set(
    settings: LazySettings,
) -> None:
    settings.MONGO_URL = "mongodb://localhost:27017"

    handler = factory_or_null()

    assert isinstance(handler, MongoLogHandler)
