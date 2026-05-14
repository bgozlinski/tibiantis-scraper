"""Tests for discord_bot.models — DiscordChannel persistence + unique constraint."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from discord_bot.models import DiscordChannel


@pytest.mark.django_db
def test_discord_channel_save_persists_all_fields() -> None:
    """Round-trip every field through Postgres to lock the schema contract.

    Pins BigIntegerField storage for Discord snowflakes (64-bit IDs > 2^31)
    and the default threshold inherited from CLAUDE.md §10 DEATH_LEVEL_THRESHOLD.
    """
    channel = DiscordChannel.objects.create(
        guild_id=1_357_924_680_135_792_468,
        channel_id=2_468_135_792_468_135_792,
    )

    channel.refresh_from_db()
    assert channel.guild_id == 1_357_924_680_135_792_468
    assert channel.channel_id == 2_468_135_792_468_135_792
    assert channel.death_level_threshold == 30
    assert channel.created_at is not None
    assert channel.updated_at is not None


@pytest.mark.django_db
def test_discord_channel_unique_constraint_on_guild_id() -> None:
    """`discord_channel_one_per_guild` enforces per-server config (§3.4).

    Inserting a second row with the same guild_id must raise IntegrityError —
    UI command `/deaths threshold` must upsert (services.set_death_threshold_for_guild),
    never create duplicates.
    """
    DiscordChannel.objects.create(guild_id=111, channel_id=222)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DiscordChannel.objects.create(guild_id=111, channel_id=333)


@pytest.mark.django_db
def test_discord_channel_str_includes_guild_id_and_threshold() -> None:
    """__str__ format consumed by Django admin list rows + log messages."""
    channel = DiscordChannel.objects.create(
        guild_id=42, channel_id=43, death_level_threshold=80
    )

    assert str(channel) == "Guild 42 (threshold=80)"
