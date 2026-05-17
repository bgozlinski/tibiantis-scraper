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


def test_handler_announce_renders_embed_with_hyperlinked_title_and_info_description(
    death_event: MagicMock,
    discord_channel: MagicMock,
    mock_client: MagicMock,
) -> None:
    """Embed shape contract post-#178 — character name as a clickable embed
    title (via `url` field), info lines in `description`.

    Pinned fields:
    - `title`: raw character name (no emoji prefix, no level suffix)
    - `url`: Tibiantis online character page, URL-encoded via quote_plus
      so Discord renders the title as a clickable hyperlink
    - `description`: three lines — `Died at level N` / `YYYY-MM-DD HH:MM:SS`
      / `Killed by: <killed_by>`
    - `color`: integer `0xDC143C` (crimson) — Pułapka C, NOT hex string
    - `timestamp`: removed (was: ISO 8601 string consumed by Discord as
      a footer). The wall-clock time is in `description` now; the embed
      footer rendered in viewer's local TZ would have shown a different
      value, confusing operators.

    Locks each field separately so a future refactor of one (e.g.
    localizing "level" to "lvl") doesn't silently break the others.
    """
    DiscordChannelHandler().announce(death_event, discord_channel)

    embed = mock_client.send_channel_message.call_args.kwargs["embed"]
    assert embed["title"] == "Yhral"
    assert embed["url"] == "https://www.tibiantis.online/?page=character&name=Yhral"
    # Fixture's died_at is 2026-05-15 14:30 UTC; in CEST (UTC+2, May) that's
    # 16:30 Europe/Warsaw — the post-#180 expected display.
    assert embed["description"] == (
        "Died at level 60\n2026-05-15 16:30:00\nKilled by: a dragon lord"
    )
    assert embed["color"] == 0xDC143C
    assert isinstance(embed["color"], int)  # Pułapka C — int, not "0xDC143C"
    assert (
        "timestamp" not in embed
    )  # removed by #178; wall-clock now lives in description


def test_handler_announce_renders_unknown_when_killed_by_is_empty(
    death_event: MagicMock,
    discord_channel: MagicMock,
    mock_client: MagicMock,
) -> None:
    """Empty `killed_by` (the model default for un-parsed kill messages)
    renders as `Killed by: unknown` in description.

    The model has `killed_by = TextField(blank=True, default="")` so the
    scraper can store "" when it can't parse the kill cause from the
    Tibiantis deaths page. The notification should not say `Killed by: `
    with an empty trailer — that would look like a parser bug to operators.
    `"unknown"` is the post-#178 friendly fallback (shorter than the prior
    `"Cause unknown"` which was a full standalone description).
    """
    death_event.killed_by = ""

    DiscordChannelHandler().announce(death_event, discord_channel)

    embed = mock_client.send_channel_message.call_args.kwargs["embed"]
    assert "Killed by: unknown" in embed["description"]


def test_handler_announce_urlencodes_space_in_character_name(
    death_event: MagicMock,
    discord_channel: MagicMock,
    mock_client: MagicMock,
) -> None:
    """Character names with spaces produce `+`-encoded URLs.

    Tibiantis's character-page URL uses `application/x-www-form-urlencoded`
    style (`+` for space), and `urllib.parse.quote_plus` produces exactly
    that. A name like `Im Bluee` must yield `name=Im+Bluee`, not
    `name=Im%20Bluee` (which the Tibiantis page does also accept but isn't
    the canonical form linked from the site itself) and not `name=Im Bluee`
    (which Discord may render as a broken link).

    Defensive against future names with other special chars — `quote_plus`
    handles `%XX` encoding for those too.
    """
    death_event.character_name = "Im Bluee"

    DiscordChannelHandler().announce(death_event, discord_channel)

    embed = mock_client.send_channel_message.call_args.kwargs["embed"]
    assert embed["url"] == "https://www.tibiantis.online/?page=character&name=Im+Bluee"
    assert (
        embed["title"] == "Im Bluee"
    )  # title text keeps the space; only URL encodes it


def test_handler_announce_renders_died_at_in_europe_warsaw_during_winter(
    death_event: MagicMock,
    discord_channel: MagicMock,
    mock_client: MagicMock,
) -> None:
    """Winter (CET = UTC+1) DST handling — death timestamps render correctly
    outside summer time.

    Guards against someone "fixing" #180 by hardcoding `+ timedelta(hours=2)`
    instead of using `zoneinfo.ZoneInfo("Europe/Warsaw")`. A constant-offset
    fix would be wrong half the year (Oct→Mar = CET, UTC+1) and at the two
    annual DST transition Sundays.

    UTC 14:30 on Dec 10 → Europe/Warsaw 15:30 (CET = UTC+1). Pre-#180 the
    display showed 14:30 (raw UTC). The companion summer test
    (..._hyperlinked_title_and_info_description) covers CEST (UTC+2).
    """
    death_event.died_at = datetime(2026, 12, 10, 14, 30, 0, tzinfo=timezone.utc)

    DiscordChannelHandler().announce(death_event, discord_channel)

    embed = mock_client.send_channel_message.call_args.kwargs["embed"]
    assert "2026-12-10 15:30:00" in embed["description"]
    assert (
        "2026-12-10 14:30:00" not in embed["description"]
    )  # the UTC value must NOT leak


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
