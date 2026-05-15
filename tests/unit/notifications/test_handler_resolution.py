"""Tests for apps.notifications resolvers + LoggingHandler / DeathLoggingHandler emit."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from apps.notifications import get_bedmage_handler, get_death_handler
from apps.notifications.handlers import (
    DeathLoggingHandler,
    DiscordChannelHandler,
    DiscordDMHandler,
    LoggingHandler,
)


class MockHandler:
    """Test double for handler resolution via settings dotted path.

    Defined at module top-level so import_string can resolve it via
    "tests.unit.notifications.test_handler_resolution.MockHandler".
    """

    def notify(
        self, watch
    ) -> None:  # pragma: no cover — not invoked in resolution test
        pass


def test_get_bedmage_handler_returns_discord_dm_handler_by_default() -> None:
    """Default settings.BEDMAGE_NOTIFICATION_HANDLER points at DiscordDMHandler.

    M5 originally pointed at LoggingHandler (dev/test); M8-D37 flipped the
    default to the production DiscordDMHandler so deployed instances actually
    send DMs without env var override. LoggingHandler is still importable and
    used by tests that need a side-effect-free notify implementation.
    """
    handler = get_bedmage_handler()

    assert isinstance(handler, DiscordDMHandler)


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


def test_get_death_handler_returns_discord_channel_handler_by_default() -> None:
    """Default settings.DEATH_NOTIFICATION_HANDLER points at DiscordChannelHandler.

    M8-D38 introduced this resolver as the parallel of get_bedmage_handler.
    The .env.example documents the same default; this test catches accidental
    env-var/base.py drift between the two declarations.
    """
    handler = get_death_handler()

    assert isinstance(handler, DiscordChannelHandler)


def test_get_death_handler_resolves_custom_class_via_settings(settings) -> None:
    """Per-call resolution mirrors get_bedmage_handler — @override_settings
    swaps the resolved class without an lru_cache trap. Locks the symmetry
    contract: any future caching here would have to be added to both
    resolvers (or neither) to keep the codebase coherent.
    """
    settings.DEATH_NOTIFICATION_HANDLER = (
        "apps.notifications.handlers.DeathLoggingHandler"
    )

    handler = get_death_handler()

    assert isinstance(handler, DeathLoggingHandler)


def test_death_logging_handler_emits_expected_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DeathLoggingHandler.announce emits a single INFO line + returns True.

    Sibling of test_logging_handler_emits — same shape, different domain
    (death announcement instead of bedmage). Locks the test-variant contract:
    structured log fields + `return True` (so the D39 service marks
    `announced_on_discord=True` even when running tests with this handler).
    """
    mock_death = MagicMock()
    mock_death.character_name = "Yhral"
    mock_death.level_at_death = 60
    mock_channel = MagicMock()
    mock_channel.guild_id = 111
    mock_channel.channel_id = 222

    handler = DeathLoggingHandler()

    with caplog.at_level(logging.INFO, logger="apps.notifications"):
        result = handler.announce(mock_death, mock_channel)

    assert result is True
    assert any(
        r.getMessage() == "DEATH ANNOUNCE: Yhral (lvl 60) → guild=111 channel=222"
        for r in caplog.records
    )
