"""Unit tests for DW-6 handlers — embed shape + dispatch wiring."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from apps.characters.models import Character
from apps.deathwatch.models import DeathWatchChannel, WatchedDeathEvent
from apps.notifications import get_deathwatch_handler
from apps.notifications.handlers import (
    DeathWatchChannelHandler,
    DeathWatchLoggingHandler,
)


@pytest.fixture
def character(db) -> Character:
    return Character.objects.create(name="Yhral")


@pytest.fixture
def event(character: Character) -> WatchedDeathEvent:
    return WatchedDeathEvent.objects.create(
        character=character,
        level_at_death=128,
        killed_by="a giant crayfish",
        died_at=datetime(2026, 5, 7, 14, 15, 46, tzinfo=ZoneInfo("UTC")),
    )


@pytest.fixture
def channel(db) -> DeathWatchChannel:
    return DeathWatchChannel.objects.create(guild_id=1, channel_id=42)


# ──────────────────────────────────────────────────────────────────────────────
# DeathWatchChannelHandler._render_embed
# ──────────────────────────────────────────────────────────────────────────────


def test_render_embed_uses_purple_color(event: WatchedDeathEvent) -> None:
    """Spec §3.11 — purple (0x8B008B) distinguishes DW from M4 crimson."""
    embed = DeathWatchChannelHandler()._render_embed(event)
    assert embed["color"] == 0x8B008B


def test_render_embed_title_is_character_name(event: WatchedDeathEvent) -> None:
    embed = DeathWatchChannelHandler()._render_embed(event)
    assert embed["title"] == "Yhral"


def test_render_embed_url_is_clickable_tibiantis_profile(
    event: WatchedDeathEvent,
) -> None:
    embed = DeathWatchChannelHandler()._render_embed(event)
    assert embed["url"].startswith("https://www.tibiantis.online/?page=character&name=")
    assert "Yhral" in embed["url"]


def test_render_embed_url_quote_plus_encodes_spaces(db) -> None:
    """Character names with spaces use `+` separator (Tibiantis URL convention)."""
    character = Character.objects.create(name="Eternal oblivion")
    event = WatchedDeathEvent.objects.create(
        character=character,
        level_at_death=200,
        killed_by="x",
        died_at=datetime(2026, 5, 7, 14, 15, 46, tzinfo=ZoneInfo("UTC")),
    )
    embed = DeathWatchChannelHandler()._render_embed(event)
    assert "name=Eternal+oblivion" in embed["url"]


def test_render_embed_description_includes_level_time_killer(
    event: WatchedDeathEvent,
) -> None:
    embed = DeathWatchChannelHandler()._render_embed(event)
    desc = embed["description"]
    assert "Died at level 128" in desc
    assert "Killed by: a giant crayfish" in desc


def test_render_embed_died_at_converted_to_europe_warsaw(
    event: WatchedDeathEvent,
) -> None:
    """May 2026 → CEST (UTC+2). 14:15:46 UTC = 16:15:46 Warsaw."""
    embed = DeathWatchChannelHandler()._render_embed(event)
    assert "16:15:46" in embed["description"]


def test_render_embed_renders_unknown_killer_when_empty(
    character: Character,
) -> None:
    event = WatchedDeathEvent.objects.create(
        character=character,
        level_at_death=50,
        killed_by="",
        died_at=datetime(2026, 5, 7, 12, 0, 0, tzinfo=ZoneInfo("UTC")),
    )
    embed = DeathWatchChannelHandler()._render_embed(event)
    assert "Killed by: unknown" in embed["description"]


# ──────────────────────────────────────────────────────────────────────────────
# Dispatch wiring
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_channel_handler_announce_calls_discord_rest_client(
    event: WatchedDeathEvent, channel: DeathWatchChannel
) -> None:
    """announce() routes through DiscordRESTClient.send_channel_message
    with channel.channel_id + rendered embed payload.
    """
    with patch(
        "apps.notifications.discord_client.DiscordRESTClient.send_channel_message",
        return_value=True,
    ) as mock_send:
        result = DeathWatchChannelHandler().announce(event, channel)

    assert result is True
    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["channel_id"] == 42
    assert call_kwargs["embed"]["title"] == "Yhral"


@pytest.mark.django_db
def test_channel_handler_propagates_false_on_send_failure(
    event: WatchedDeathEvent, channel: DeathWatchChannel
) -> None:
    """When DiscordRESTClient signals failure (None or False return), handler
    returns False — caller treats as failed-on-this-channel.
    """
    with patch(
        "apps.notifications.discord_client.DiscordRESTClient.send_channel_message",
        return_value=False,
    ):
        result = DeathWatchChannelHandler().announce(event, channel)
    assert result is False


# ──────────────────────────────────────────────────────────────────────────────
# Logging handler (test/dev variant)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_logging_handler_always_returns_true_no_discord_call(
    event: WatchedDeathEvent, channel: DeathWatchChannel
) -> None:
    with patch(
        "apps.notifications.discord_client.DiscordRESTClient.send_channel_message"
    ) as mock_send:
        result = DeathWatchLoggingHandler().announce(event, channel)

    assert result is True
    mock_send.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# Factory resolution
# ──────────────────────────────────────────────────────────────────────────────


def test_get_deathwatch_handler_default_is_channel_handler() -> None:
    handler = get_deathwatch_handler()
    assert isinstance(handler, DeathWatchChannelHandler)


def test_get_deathwatch_handler_swappable_via_settings(settings) -> None:
    """@override_settings (via pytest's settings fixture) must affect resolution."""
    settings.DEATHWATCH_NOTIFICATION_HANDLER = (
        "apps.notifications.handlers.DeathWatchLoggingHandler"
    )
    handler = get_deathwatch_handler()
    assert isinstance(handler, DeathWatchLoggingHandler)
