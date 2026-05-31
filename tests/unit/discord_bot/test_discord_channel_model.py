"""Tests for DiscordChannel model — cleanup fields added 2026-06-01."""

from __future__ import annotations

import pytest

from discord_bot.models import DiscordChannel


@pytest.mark.django_db
def test_discord_channel_cleanup_fields_default_to_disabled() -> None:
    """New cleanup_* fields default to safe values — no surprise mass deletions."""
    ch = DiscordChannel.objects.create(guild_id=1, channel_id=2)

    assert ch.cleanup_enabled is False
    assert ch.last_cleanup_at is None


@pytest.mark.django_db
def test_discord_channel_cleanup_fields_persist() -> None:
    """Both new fields are writable and round-trip through ORM."""
    from django.utils import timezone

    now = timezone.now()
    ch = DiscordChannel.objects.create(
        guild_id=1,
        channel_id=2,
        cleanup_enabled=True,
        last_cleanup_at=now,
    )
    ch.refresh_from_db()

    assert ch.cleanup_enabled is True
    assert ch.last_cleanup_at == now
