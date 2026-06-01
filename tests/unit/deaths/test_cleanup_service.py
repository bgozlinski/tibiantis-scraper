"""Tests for cleanup_death_channel — per-channel message purge."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from apps.deaths.services import (
    CleanupError,
    cleanup_death_channel,
    snowflake_for_datetime,
)
from apps.notifications.discord_client import BulkDeleteAgeError
from discord_bot.models import DiscordChannel


@pytest.fixture
def channel(db) -> DiscordChannel:  # noqa: ARG001
    return DiscordChannel.objects.create(
        guild_id=1, channel_id=42, cleanup_enabled=True
    )


def _msg(id_: int, pinned: bool = False) -> dict[str, object]:
    return {"id": str(id_), "pinned": pinned}


def test_cleanup_paginates_until_empty_batch(
    monkeypatch: pytest.MonkeyPatch, channel: DiscordChannel
) -> None:
    """Service walks `before=` pagination until Discord returns an empty page."""
    pages = iter(
        [
            [_msg(100), _msg(99), _msg(98)],
            [_msg(50), _msg(49)],
            [],
        ]
    )
    client = MagicMock()
    client.fetch_channel_messages.side_effect = lambda **kw: next(pages)
    client.bulk_delete_messages.return_value = True
    monkeypatch.setattr("apps.deaths.services.DiscordRESTClient", lambda: client)

    result = cleanup_death_channel(channel)

    assert result == {"deleted": 5}
    assert client.fetch_channel_messages.call_count == 3
    client.bulk_delete_messages.assert_called_once_with(
        channel_id=42, message_ids=[100, 99, 98, 50, 49]
    )


def test_cleanup_filters_pinned_messages(
    monkeypatch: pytest.MonkeyPatch, channel: DiscordChannel
) -> None:
    """Pinned messages stay (preserves rules/info pins)."""
    pages = iter([[_msg(1), _msg(2, pinned=True), _msg(3)], []])
    client = MagicMock()
    client.fetch_channel_messages.side_effect = lambda **kw: next(pages)
    client.bulk_delete_messages.return_value = True
    monkeypatch.setattr("apps.deaths.services.DiscordRESTClient", lambda: client)

    result = cleanup_death_channel(channel)

    assert result == {"deleted": 2}
    args, kwargs = client.bulk_delete_messages.call_args
    assert kwargs["message_ids"] == [1, 3]


def test_cleanup_chunks_more_than_100(
    monkeypatch: pytest.MonkeyPatch, channel: DiscordChannel
) -> None:
    """>100 messages → multiple bulk-delete calls of <=100 each."""
    ids = list(range(1, 251))  # 250 messages
    pages = iter(
        [
            [_msg(i) for i in ids[:100]],
            [_msg(i) for i in ids[100:200]],
            [_msg(i) for i in ids[200:]],
            [],
        ]
    )
    client = MagicMock()
    client.fetch_channel_messages.side_effect = lambda **kw: next(pages)
    client.bulk_delete_messages.return_value = True
    monkeypatch.setattr("apps.deaths.services.DiscordRESTClient", lambda: client)

    result = cleanup_death_channel(channel)

    assert result == {"deleted": 250}
    assert client.bulk_delete_messages.call_count == 3  # 100 + 100 + 50


def test_cleanup_falls_back_to_single_delete_when_chunk_is_one(
    monkeypatch: pytest.MonkeyPatch, channel: DiscordChannel
) -> None:
    """N==1 chunk → delete_message instead of bulk-delete (API requires N>=2)."""
    pages = iter([[_msg(1)], []])
    client = MagicMock()
    client.fetch_channel_messages.side_effect = lambda **kw: next(pages)
    client.delete_message.return_value = True
    monkeypatch.setattr("apps.deaths.services.DiscordRESTClient", lambda: client)

    result = cleanup_death_channel(channel)

    assert result == {"deleted": 1}
    client.bulk_delete_messages.assert_not_called()
    client.delete_message.assert_called_once_with(channel_id=42, message_id=1)


def test_cleanup_falls_back_to_single_delete_on_age_error(
    monkeypatch: pytest.MonkeyPatch, channel: DiscordChannel
) -> None:
    """BulkDeleteAgeError → retry the chunk message-by-message."""
    pages = iter([[_msg(1), _msg(2), _msg(3)], []])
    client = MagicMock()
    client.fetch_channel_messages.side_effect = lambda **kw: next(pages)
    client.bulk_delete_messages.side_effect = BulkDeleteAgeError("too old")
    client.delete_message.return_value = True
    monkeypatch.setattr("apps.deaths.services.DiscordRESTClient", lambda: client)

    result = cleanup_death_channel(channel)

    assert result == {"deleted": 3}
    assert client.delete_message.call_count == 3


def test_cleanup_empty_channel_updates_last_cleanup_at(
    monkeypatch: pytest.MonkeyPatch, channel: DiscordChannel
) -> None:
    """Empty channel → deleted=0 but `last_cleanup_at` still bumped (run succeeded)."""
    client = MagicMock()
    client.fetch_channel_messages.return_value = []
    monkeypatch.setattr("apps.deaths.services.DiscordRESTClient", lambda: client)
    before = timezone.now() - timedelta(seconds=1)

    result = cleanup_death_channel(channel)

    channel.refresh_from_db()
    assert result == {"deleted": 0}
    assert channel.last_cleanup_at is not None
    assert channel.last_cleanup_at > before


def test_cleanup_raises_and_does_not_update_timestamp_on_rest_failure(
    monkeypatch: pytest.MonkeyPatch, channel: DiscordChannel
) -> None:
    """REST returns False on bulk-delete → CleanupError raised, timestamp unchanged."""
    pages = iter([[_msg(1), _msg(2)], []])
    client = MagicMock()
    client.fetch_channel_messages.side_effect = lambda **kw: next(pages)
    client.bulk_delete_messages.return_value = False
    monkeypatch.setattr("apps.deaths.services.DiscordRESTClient", lambda: client)

    with pytest.raises(CleanupError):
        cleanup_death_channel(channel)

    channel.refresh_from_db()
    assert channel.last_cleanup_at is None


def test_cleanup_passes_snowflake_cutoff_as_before(
    monkeypatch: pytest.MonkeyPatch, channel: DiscordChannel
) -> None:
    """First fetch uses snowflake(now - RETENTION_DAYS) as `before=`."""
    captured: dict[str, object] = {}

    def fake_fetch(**kw: object) -> list[dict[str, object]]:
        if "first" not in captured:
            captured["first"] = kw.get("before")
        return []

    client = MagicMock()
    client.fetch_channel_messages.side_effect = fake_fetch
    monkeypatch.setattr("apps.deaths.services.DiscordRESTClient", lambda: client)

    cleanup_death_channel(channel)

    # Should be ~ snowflake(now - 3 days), tolerate ±1s skew.
    cutoff = timezone.now() - timedelta(days=3)
    expected = snowflake_for_datetime(cutoff)
    delta = abs(int(captured["first"]) - expected)
    # 1 sec ~ 1000 ms ~ 1000 << 22 = 4.19e9 snowflake units
    assert delta < (2 * 1000 << 22), "first-call before snowflake too far from expected"
