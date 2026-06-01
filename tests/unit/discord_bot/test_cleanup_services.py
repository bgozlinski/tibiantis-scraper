"""Tests for cleanup-related helpers in discord_bot.services."""

from __future__ import annotations

import pytest
from django.utils import timezone

from discord_bot.models import DiscordChannel
from discord_bot.services import (
    disable_cleanup_for_guild,
    enable_cleanup_for_guild,
    get_cleanup_status,
)


@pytest.mark.django_db
def test_enable_cleanup_flips_flag_to_true() -> None:
    ch = DiscordChannel.objects.create(guild_id=1, channel_id=2)
    assert ch.cleanup_enabled is False

    ok = enable_cleanup_for_guild(guild_id=1)

    ch.refresh_from_db()
    assert ok is True
    assert ch.cleanup_enabled is True


@pytest.mark.django_db
def test_enable_cleanup_returns_false_when_no_channel() -> None:
    """No DiscordChannel for this guild → returns False (cog renders 'run /threshold first')."""
    ok = enable_cleanup_for_guild(guild_id=999)
    assert ok is False


@pytest.mark.django_db
def test_disable_cleanup_flips_flag_to_false() -> None:
    ch = DiscordChannel.objects.create(guild_id=1, channel_id=2, cleanup_enabled=True)

    ok = disable_cleanup_for_guild(guild_id=1)

    ch.refresh_from_db()
    assert ok is True
    assert ch.cleanup_enabled is False


@pytest.mark.django_db
def test_disable_cleanup_returns_false_when_no_channel() -> None:
    assert disable_cleanup_for_guild(guild_id=999) is False


@pytest.mark.django_db
def test_get_cleanup_status_returns_full_state() -> None:
    now = timezone.now()
    DiscordChannel.objects.create(
        guild_id=1,
        channel_id=42,
        cleanup_enabled=True,
        last_cleanup_at=now,
    )

    status = get_cleanup_status(guild_id=1)

    assert status is not None
    assert status["enabled"] is True
    assert status["last_cleanup_at"] == now
    assert status["channel_id"] == 42


@pytest.mark.django_db
def test_get_cleanup_status_returns_none_when_no_channel() -> None:
    """Cog uses this None to render 'no channel registered'."""
    assert get_cleanup_status(guild_id=999) is None
