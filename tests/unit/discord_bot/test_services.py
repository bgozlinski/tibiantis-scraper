"""Tests for discord_bot.services — user auto-create + threshold upsert."""

from __future__ import annotations

import pytest

from apps.accounts.models import User
from discord_bot.models import DiscordChannel
from discord_bot.services import (
    get_or_create_user_by_discord_id,
    set_death_threshold_for_guild,
)


# === get_or_create_user_by_discord_id ===


@pytest.mark.django_db
def test_get_or_create_user_creates_new_user_with_discord_username_pattern() -> None:
    """First call materializes Django User per CLAUDE.md §8 auto-create default.

    Locks the auto-create contract: username pattern `discord_<id>` (collision-safe
    with web signups), empty email (Discord doesn't always expose), unusable
    password (account only logs in via Discord, not Django auth).
    """
    assert User.objects.filter(discord_id="12345").count() == 0

    user, created = get_or_create_user_by_discord_id(
        discord_id=12345, discord_username="alice"
    )

    assert created is True
    assert user.username == "discord_12345"
    assert user.email == ""
    assert user.has_usable_password() is False

    user.refresh_from_db()
    assert user.discord_id == "12345"


@pytest.mark.django_db
def test_get_or_create_user_returns_existing_user_on_second_call() -> None:
    """Idempotent — second call for the same discord_id reuses the row.

    `created=False` and the returned PK matches. Guards against accidental
    duplicate User rows when a single Discord user fires multiple slash commands
    in quick succession.
    """
    first, first_created = get_or_create_user_by_discord_id(
        discord_id=99, discord_username="bob"
    )
    second, second_created = get_or_create_user_by_discord_id(
        discord_id=99, discord_username="bob_renamed"
    )

    assert first_created is True
    assert second_created is False
    assert second.pk == first.pk
    assert User.objects.filter(discord_id="99").count() == 1


@pytest.mark.django_db
def test_get_or_create_user_does_not_overwrite_username_on_repeat_call() -> None:
    """Username is set only at create time — repeat calls don't touch it.

    Even if Discord user renames themselves, the Django username stays
    `discord_<id>` (stable identifier). Prevents collision with web-signup
    usernames and matches §3.3 rationale.
    """
    get_or_create_user_by_discord_id(discord_id=42, discord_username="original")

    user, _ = get_or_create_user_by_discord_id(
        discord_id=42, discord_username="rebranded"
    )

    assert user.username == "discord_42"


# === set_death_threshold_for_guild ===


@pytest.mark.django_db
def test_set_death_threshold_creates_new_discord_channel_on_first_call() -> None:
    """First `/deaths threshold` for a server materializes DiscordChannel row."""
    assert DiscordChannel.objects.filter(guild_id=555).count() == 0

    channel = set_death_threshold_for_guild(guild_id=555, channel_id=666, threshold=50)

    assert channel.pk is not None
    assert channel.guild_id == 555
    assert channel.channel_id == 666
    assert channel.death_level_threshold == 50
    assert DiscordChannel.objects.filter(guild_id=555).count() == 1


@pytest.mark.django_db
def test_set_death_threshold_updates_existing_channel_threshold() -> None:
    """Second call for the same guild updates threshold in place — no new row.

    Locks the upsert contract (§4.2): unique=guild_id never creates duplicates,
    admin can adjust threshold repeatedly.
    """
    original = set_death_threshold_for_guild(guild_id=777, channel_id=888, threshold=40)

    updated = set_death_threshold_for_guild(guild_id=777, channel_id=888, threshold=120)

    assert updated.pk == original.pk
    assert updated.death_level_threshold == 120
    assert DiscordChannel.objects.filter(guild_id=777).count() == 1


@pytest.mark.django_db
def test_set_death_threshold_updates_channel_id_when_changed() -> None:
    """Re-running `/deaths threshold` from a different channel rotates channel_id.

    M8 will use the latest channel_id as the outbound destination — admin can
    move announcements by re-running the command in a new channel.
    """
    set_death_threshold_for_guild(guild_id=42, channel_id=100, threshold=30)

    updated = set_death_threshold_for_guild(guild_id=42, channel_id=200, threshold=30)

    assert updated.channel_id == 200
    assert DiscordChannel.objects.filter(guild_id=42).count() == 1
