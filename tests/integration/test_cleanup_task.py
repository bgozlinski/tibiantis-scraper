"""Integration test for cleanup_death_channels Celery task — eager execution."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apps.deaths.tasks import cleanup_death_channels
from discord_bot.models import DiscordChannel


@pytest.mark.django_db
def test_cleanup_task_skips_disabled_guilds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only DiscordChannel rows with cleanup_enabled=True are processed."""
    DiscordChannel.objects.create(guild_id=1, channel_id=11, cleanup_enabled=True)
    DiscordChannel.objects.create(guild_id=2, channel_id=22, cleanup_enabled=True)
    DiscordChannel.objects.create(guild_id=3, channel_id=33, cleanup_enabled=False)

    fake_service = MagicMock(return_value={"deleted": 5})
    monkeypatch.setattr("apps.deaths.tasks.cleanup_death_channel", fake_service)

    result = cleanup_death_channels.apply().get()

    assert result == {
        "guilds_processed": 2,
        "messages_deleted": 10,
        "fail_count": 0,
    }
    assert fake_service.call_count == 2


@pytest.mark.django_db
def test_cleanup_task_continues_after_per_guild_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One guild raises → fail_count increments, loop continues with others."""
    DiscordChannel.objects.create(guild_id=1, channel_id=11, cleanup_enabled=True)
    DiscordChannel.objects.create(guild_id=2, channel_id=22, cleanup_enabled=True)
    DiscordChannel.objects.create(guild_id=3, channel_id=33, cleanup_enabled=True)

    def fake(channel: DiscordChannel) -> dict[str, int]:
        if channel.guild_id == 2:
            raise RuntimeError("simulated REST failure")
        return {"deleted": 3}

    monkeypatch.setattr("apps.deaths.tasks.cleanup_death_channel", fake)

    result = cleanup_death_channels.apply().get()

    assert result == {
        "guilds_processed": 2,
        "messages_deleted": 6,
        "fail_count": 1,
    }


@pytest.mark.django_db
def test_cleanup_task_returns_zeros_when_no_guilds_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty enabled set → zeros, no crash, no service calls."""
    DiscordChannel.objects.create(guild_id=1, channel_id=11, cleanup_enabled=False)

    spy = MagicMock()
    monkeypatch.setattr("apps.deaths.tasks.cleanup_death_channel", spy)

    result = cleanup_death_channels.apply().get()

    assert result == {
        "guilds_processed": 0,
        "messages_deleted": 0,
        "fail_count": 0,
    }
    spy.assert_not_called()
