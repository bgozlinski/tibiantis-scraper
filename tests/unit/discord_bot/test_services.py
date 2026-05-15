"""Tests for discord_bot.services — user auto-create + threshold upsert + bedmage wrappers."""

from __future__ import annotations

import pytest

from apps.accounts.models import User
from apps.bedmages.models import BedmageWatch
from discord_bot.models import DiscordChannel
from discord_bot.services import (
    add_bedmage_for_discord_user,
    get_or_create_user_by_discord_id,
    list_bedmages_for_discord_user,
    remove_bedmage_for_discord_user,
    set_death_threshold_for_guild,
)


# === get_or_create_user_by_discord_id ===


@pytest.mark.django_db
def test_get_or_create_user_creates_new_user_with_discord_username_pattern() -> None:
    """First call materializes Django User per CLAUDE.md §8 auto-create default.

    Locks the auto-create contract: username pattern `discord_<id>` (collision-safe
    with web signups), NULL email (Discord doesn't always expose — NULL not ''
    so the unique constraint allows N Discord users; see #133), unusable
    password (account only logs in via Discord, not Django auth).
    """
    assert User.objects.filter(discord_id="12345").count() == 0

    user, created = get_or_create_user_by_discord_id(
        discord_id=12345, discord_username="alice"
    )

    assert created is True
    assert user.username == "discord_12345"
    assert user.email is None
    assert user.has_usable_password() is False

    user.refresh_from_db()
    assert user.discord_id == "12345"


@pytest.mark.django_db
def test_get_or_create_user_does_not_collide_on_email_for_different_discord_ids() -> (
    None
):
    """Regression #133: pre-fix, the second Discord auto-create exploded with
    `IntegrityError: duplicate key value violates unique constraint
    "accounts_user_email_..." Key (email)=() already exists` because `email=''`
    was being inserted twice into a unique column.

    After the fix `email` is NULL on auto-create. PostgreSQL treats multiple
    NULLs in a unique column as distinct, so any number of Discord users can
    be materialized lazily. Without this test the original bug would silently
    return if someone reverts the model nullability or the services.py default
    back to `""`.
    """
    u1, c1 = get_or_create_user_by_discord_id(discord_id=111, discord_username="alice")
    u2, c2 = get_or_create_user_by_discord_id(discord_id=222, discord_username="bob")

    assert c1 is True and c2 is True
    assert u1.pk != u2.pk
    assert u1.email is None and u2.email is None
    assert User.objects.filter(email__isnull=True).count() == 2


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


# === add_bedmage_for_discord_user (D33) ===


@pytest.mark.django_db
def test_add_bedmage_for_discord_user_creates_watch_on_first_call() -> None:
    """First `/bedmage add` for a Discord user materializes User + BedmageWatch.

    Auto-create User via the D31 service, then delegate to M5
    `add_bedmage_watch` — Character is also lazily created (M5 contract).
    """
    watch, created = add_bedmage_for_discord_user(
        discord_id=42, discord_username="alice", character_name="Yhral"
    )

    assert created is True
    assert watch.pk is not None
    assert watch.active is True
    assert watch.character.name == "Yhral"
    assert User.objects.filter(discord_id="42", pk=watch.user_id).exists()


@pytest.mark.django_db
def test_add_bedmage_for_discord_user_returns_existing_on_duplicate() -> None:
    """Idempotent UX (§3.2): second add for same (user, character) → (existing, False).

    Wrapper catches M5's `ValueError` and re-fetches the row instead of
    surfacing the error to Discord — "already on list" is informational, not
    a failure from the user's perspective.
    """
    first, first_created = add_bedmage_for_discord_user(
        discord_id=42, discord_username="alice", character_name="Yhral"
    )
    second, second_created = add_bedmage_for_discord_user(
        discord_id=42, discord_username="alice", character_name="Yhral"
    )

    assert first_created is True
    assert second_created is False
    assert second.pk == first.pk
    assert (
        BedmageWatch.objects.filter(user=first.user, character=first.character).count()
        == 1
    )


# === remove_bedmage_for_discord_user (D33) ===


@pytest.mark.django_db
def test_remove_bedmage_for_discord_user_returns_true_on_match() -> None:
    """Happy path — watch exists and is hard-deleted; service returns True."""
    add_bedmage_for_discord_user(
        discord_id=42, discord_username="alice", character_name="Yhral"
    )

    removed = remove_bedmage_for_discord_user(discord_id=42, character_name="Yhral")

    assert removed is True
    assert (
        BedmageWatch.objects.filter(
            user__discord_id="42", character__name="Yhral"
        ).count()
        == 0
    )


@pytest.mark.django_db
def test_remove_bedmage_for_discord_user_returns_false_when_not_on_list() -> None:
    """No-match case — idempotent (§3.2): never raises, returns False.

    Covers two scenarios in one assertion: unknown user (auto-created) AND
    unknown character. Both paths return False without crashing.
    """
    removed = remove_bedmage_for_discord_user(
        discord_id=42, character_name="NeverAdded"
    )

    assert removed is False


@pytest.mark.django_db
def test_remove_bedmage_for_discord_user_auto_creates_user_when_unknown() -> None:
    """Pułapka G — symmetric with `add`: removing for an unknown Discord user
    auto-creates the User row (idempotent + symmetric behavior with `add`).

    Defensive against UX inconsistency: `/bedmage remove` from a brand-new
    user shouldn't behave differently from `/bedmage add` followed by remove.
    """
    assert User.objects.filter(discord_id="999").count() == 0

    remove_bedmage_for_discord_user(discord_id=999, character_name="Anything")

    assert User.objects.filter(discord_id="999").count() == 1


# === list_bedmages_for_discord_user (D33) ===


@pytest.mark.django_db
def test_list_bedmages_for_discord_user_returns_empty_for_unknown_user() -> None:
    """Pułapka H — read-only: unknown Discord ID returns [], does NOT auto-create.

    Defense against unnecessary DB writes on idle `/bedmage list` calls.
    """
    watches = list_bedmages_for_discord_user(discord_id=99999)

    assert watches == []
    assert User.objects.filter(discord_id="99999").count() == 0


@pytest.mark.django_db
def test_list_bedmages_for_discord_user_returns_active_watches() -> None:
    """Returns all active bedmages for the user, with Character preloaded.

    `select_related("character")` guards against N+1 in the cog handler when
    it formats `w.character.name` for each watch.
    """
    add_bedmage_for_discord_user(
        discord_id=42, discord_username="alice", character_name="Yhral"
    )
    add_bedmage_for_discord_user(
        discord_id=42, discord_username="alice", character_name="Nidrak"
    )

    watches = list_bedmages_for_discord_user(discord_id=42)

    assert len(watches) == 2
    assert {w.character.name for w in watches} == {"Yhral", "Nidrak"}


@pytest.mark.django_db
def test_list_bedmages_for_discord_user_excludes_inactive() -> None:
    """`active=True` filter — soft-deactivated watches are not surfaced.

    M5 `remove_bedmage_watch` is hard-delete so this path is currently dead
    code, but the filter is a contract guarantee for future soft-delete
    refactors (§3.2 wrapper isolation from M5 internals).
    """
    watch, _ = add_bedmage_for_discord_user(
        discord_id=42, discord_username="alice", character_name="Yhral"
    )
    watch.active = False
    watch.save(update_fields=["active"])

    watches = list_bedmages_for_discord_user(discord_id=42)

    assert watches == []
