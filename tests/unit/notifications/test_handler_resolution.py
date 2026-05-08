"""Tests for apps.notifications handler resolution + LoggingHandler emit."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from apps.notifications import get_bedmage_handler
from apps.notifications.handlers import LoggingHandler


class MockHandler:
    """Test double for handler resolution via settings dotted path.

    Defined at module top-level so import_string can resolve it via
    "tests.unit.notifications.test_handler_resolution.MockHandler".
    """

    def notify(
        self, watch
    ) -> None:  # pragma: no cover — not invoked in resolution test
        pass


def test_get_bedmage_handler_returns_logging_handler_by_default() -> None:
    """Default settings.BEDMAGE_NOTIFICATION_HANDLER points at LoggingHandler.

    Sanity check that the project default (declared in config/settings/base.py)
    resolves to the M5 reference implementation.
    """
    handler = get_bedmage_handler()

    assert isinstance(handler, LoggingHandler)


def test_get_bedmage_handler_resolves_custom_class_via_settings(settings) -> None:
    """Per-call resolution honors @override_settings — no lru_cache trap.

    Pułapka B: caching get_bedmage_handler() with functools.lru_cache would
    freeze the first-resolved handler and ignore later @override_settings
    overrides. M5 design is per-call resolution; this test enforces it.
    """
    settings.BEDMAGE_NOTIFICATION_HANDLER = (
        "tests.unit.notifications.test_handler_resolution.MockHandler"
    )

    handler = get_bedmage_handler()

    assert isinstance(handler, MockHandler)


def test_logging_handler_emits_expected_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """LoggingHandler.notify emits a single INFO line with watch fields.

    Format: "BEDMAGE: user=<username> character=<name> last_login=<datetime>".
    Filters to apps.notifications logger to ignore unrelated framework noise.
    """
    mock_watch = MagicMock()
    mock_watch.user.username = "alice"
    mock_watch.character.name = "Yhral"
    mock_watch.character.last_login = "2026-05-08T10:00:00+00:00"

    handler = LoggingHandler()

    with caplog.at_level(logging.INFO, logger="apps.notifications"):
        handler.notify(mock_watch)

    assert any(
        r.getMessage()
        == "BEDMAGE: user=alice character=Yhral last_login=2026-05-08T10:00:00+00:00"
        for r in caplog.records
    )
