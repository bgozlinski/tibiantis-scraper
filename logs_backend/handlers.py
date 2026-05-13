from __future__ import annotations

import logging
from datetime import datetime, timezone

from django.conf import settings
from pymongo.errors import PyMongoError

from logs_backend import get_collection


class MongoLogHandler(logging.Handler):
    """Persist log records to Mongo `app_logs`. Silent stderr fallback on failure.

    Synchronous emit (§3.1): blocks the calling thread for one insert_one
    roundtrip (~5-50ms on local Mongo, fail-fast 2s on unreachable). Acceptable
    for low-traffic backend.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(logging.Formatter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            doc: dict[str, object] = {
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno,
            }
            if record.exc_info:
                formatter = self.formatter or logging.Formatter()
                doc["exc_info"] = formatter.formatException(record.exc_info)

            get_collection("app_logs").insert_one(doc)
        except (PyMongoError, Exception):
            # Standard logging.Handler.handleError: writes formatted record
            # to sys.stderr. Never break the app from a log call.
            self.handleError(record)


def factory_or_null() -> logging.Handler:
    """Return MongoLogHandler if MONGO_URL configured, NullHandler otherwise.

    Wired into Django LOGGING via the `()` factory pattern. Empty MONGO_URL
    means dev mode without Mongo — app starts cleanly, logs go to console
    via Django default handlers.
    """
    if not settings.MONGO_URL:
        return logging.NullHandler()
    return MongoLogHandler()
