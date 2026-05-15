"""Tests for DiscordChannelHandler — death announcement embed delivery."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from apps.notifications.handlers import DiscordChannelHandler


@pytest.fixture
def death_event() -> MagicMock:
    """Minimal DeathEvent-shaped mock — no DB hit needed for embed unit tests.

    Sets the four attributes _render_embed touches:
    `character_name`, `level_at_death`, `killed_by`, `died_at`. Tests override
    individual fields when exercising edge cases (e.g. empty killed_by).
    The `died_at` must be a real `datetime` so `isoformat()` returns a real
    ISO 8601 string (MagicMock auto-generates a Mock object otherwise).
    """
    mock = MagicMock()
    mock.character_name = "Yhral"
    mock.level_at_death = 60
    mock.killed_by = "a dragon lord"
    mock.died_at = datetime(2026, 5, 15, 14, 30, 0, tzinfo=timezone.utc)
    return mock


@pytest.fixture
def discord_channel() -> MagicMock:
    """DiscordChannel-shaped mock. `channel_id` is a real int (BigIntegerField
    semantics, Pułapka A from #130) so the handler passes it through unchanged
    to `send_channel_message(channel_id=...)`."""
    mock = MagicMock()
    mock.channel_id = 987654321012345678  # real Discord snowflake-sized int
    mock.guild_id = 111222333444555666
    return mock


@pytest.fixture
def mock_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch DiscordRESTClient at its source module.

    Handler does a lazy `from apps.notifications.discord_client import
    DiscordRESTClient` inside `announce()` (same pattern as DiscordDMHandler;
    keeps `httpx` out of Django startup and out of the mypy hook's venv).
    The lazy import re-resolves the name from `discord_client` on every call,
    so patching the source module's attribute is enough.
    """
    client = MagicMock()
    client.send_channel_message.return_value = True
    monkeypatch.setattr(
        "apps.notifications.discord_client.DiscordRESTClient", lambda: client
    )
    return client


def test_handler_announce_calls_client_send_channel_message_with_embed(
    death_event: MagicMock,
    discord_channel: MagicMock,
    mock_client: MagicMock,
) -> None:
    """Happy path: handler builds an embed and posts it to the per-guild channel.

    Pins the wiring contract: (1) exactly one outbound call per announce(),
    (2) channel_id from DiscordChannel flows through unchanged (Pułapka A —
    BigIntegerField, no str conversion), (3) embed kwarg, NOT content kwarg
    (caller chose embed format for death notifications per spec §4.4).
    """
    result = DiscordChannelHandler().announce(death_event, discord_channel)

    assert result is True
    mock_client.send_channel_message.assert_called_once()
    call_kwargs = mock_client.send_channel_message.call_args.kwargs
    assert call_kwargs["channel_id"] == 987654321012345678
    assert "embed" in call_kwargs
    assert "content" not in call_kwargs or call_kwargs.get("content") is None


def test_handler_announce_renders_embed_with_character_level_killed_by_color(
    death_event: MagicMock,
    discord_channel: MagicMock,
    mock_client: MagicMock,
) -> None:
    """Embed shape contract — 4 keys with specific semantics:

    - `title`: 💀 + character name + level in parens (visible card heading)
    - `description`: killed_by raw text (Discord renders body)
    - `timestamp`: ISO 8601 with TZ (Discord parses + displays in user's TZ)
    - `color`: integer `0xDC143C` (crimson) — Pułapka C, NOT hex string

    Locks each field separately so a future refactor of one (e.g. localizing
    "level" to "lvl") doesn't silently break the others.
    """
    DiscordChannelHandler().announce(death_event, discord_channel)

    embed = mock_client.send_channel_message.call_args.kwargs["embed"]
    assert embed["title"] == "💀 Yhral (level 60)"
    assert embed["description"] == "a dragon lord"
    assert embed["timestamp"] == "2026-05-15T14:30:00+00:00"
    assert embed["color"] == 0xDC143C
    assert isinstance(embed["color"], int)  # Pułapka C — int, not "0xDC143C"


def test_handler_announce_returns_false_on_send_failure(
    death_event: MagicMock,
    discord_channel: MagicMock,
    mock_client: MagicMock,
) -> None:
    """Send failure (403/404/5xx-after-retry) propagates as `False` return.

    Pins the contract D39 will rely on: `announce()` return value drives
    whether the service marks `DeathEvent.announced_on_discord=True`. False
    means "keep trying on the next scrape cycle"; True means "done, don't
    re-announce". No exception leak — DiscordRESTClient already swallows
    transient failures and returns bool (#128 contract).
    """
    mock_client.send_channel_message.return_value = False

    result = DiscordChannelHandler().announce(death_event, discord_channel)

    assert result is False
    mock_client.send_channel_message.assert_called_once()
