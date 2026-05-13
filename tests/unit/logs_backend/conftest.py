"""Test isolation for logs_backend unit tests.

Module-level singletons in logs_backend (`_client`, `_initialized_collections`)
leak across tests if not reset — and `_initialized_collections` is keyed by
collection name only, so switching MONGO_DB between tests silently skips
index creation in the new DB. Reset both per-test.

Paranoia: force MONGO_DB to a `_test` suffix so a misconfigured env never
drops production `app_logs` (spec §7.4 + plan §Task #1 Pułapka H).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

import pytest

import logs_backend
from logs_backend import get_mongo_client

if TYPE_CHECKING:
    from django.conf import LazySettings


@pytest.fixture(autouse=True)
def mongo_db(settings: LazySettings) -> Iterator[None]:
    if not settings.MONGO_DB.endswith("_test"):
        settings.MONGO_DB = f"{settings.MONGO_DB}_test"

    logs_backend._client = None
    logs_backend._initialized_collections.clear()

    yield

    # Tests that override MONGO_URL to "" (factory NullHandler path) would
    # crash MongoClient on empty URI; skip drop in that case.
    if not settings.MONGO_URL:
        return
    db = get_mongo_client()[settings.MONGO_DB]
    for name in db.list_collection_names():
        db[name].drop()
