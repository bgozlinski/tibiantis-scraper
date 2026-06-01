"""Bot-side service layer.

Cogs are kept small and delegate everything to this module so the Django ORM
calls live in one place. Functions here also bridge the Discord-side identity
(``discord_id``) with the Django ``User`` model, auto-creating users on first
contact.
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import TypedDict

from django.db import transaction

from apps.accounts.models import User
from discord_bot.models import DiscordChannel

from apps.bedmages.models import BedmageWatch
from apps.bedmages.services import add_bedmage_watch, remove_bedmage_watch
from apps.characters.models import _canonicalize_name
from apps.deathwatch.models import DeathWatch
from apps.deathwatch.services import (
    add_death_watch,
    list_all_death_watches,
    remove_death_watch,
)

logger = logging.getLogger(__name__)


def get_or_create_user_by_discord_id(
    discord_id: int, discord_username: str
) -> tuple[User, bool]:
    """Lazy auto-create per CLAUDE.md §8.

    Returns (user, created). Username pattern: f"discord_{discord_id}".
    Email empty, password unusable.
    """
    with transaction.atomic():
        user, created = User.objects.get_or_create(
            discord_id=discord_id,
            defaults={
                "username": f"discord_{discord_id}",
                "email": None,
            },
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
            logger.info(
                "Auto-created Django User for Discord user %s (id=%s)",
                discord_username,
                discord_id,
            )
    return user, created


def set_death_threshold_for_guild(
    guild_id: int, channel_id: int, threshold: int
) -> DiscordChannel:
    """Upsert DiscordChannel by guild_id. Updates channel_id + threshold
    (M8 will use channel_id as outbound destination)."""
    channel, created = DiscordChannel.objects.update_or_create(
        guild_id=guild_id,
        defaults={
            "channel_id": channel_id,
            "death_level_threshold": threshold,
        },
    )
    logger.info(
        "%s DiscordChannel for guild=%s threshold=%s",
        "Created" if created else "Updated",
        guild_id,
        threshold,
    )
    return channel


def add_bedmage_for_discord_user(
    discord_id: int, discord_username: str, character_name: str
) -> tuple[BedmageWatch, bool]:
    """Auto-create User + delegate to apps.bedmages.services.add_bedmage_watch.

    Returns (watch, created). created=False when watch already on user's list
    (catches ValueError from apps service, idempotent ack).

    Canonicalizes character_name at entry (same primitive as
    apps.bedmages.services). Without this, the ValueError-recovery .get()
    below would look up the raw user-typed casing (e.g. "akrutki") while the
    Character row is stored under the canonical form ("Akrutki"), producing
    BedmageWatch.DoesNotExist. Caught in prod on M10-D52 after #164 landed.
    """
    user, _ = get_or_create_user_by_discord_id(discord_id, discord_username)
    character_name = _canonicalize_name(character_name)
    try:
        watch = add_bedmage_watch(user, character_name)
        return watch, True
    except ValueError:
        watch = BedmageWatch.objects.get(user=user, character__name=character_name)
        return watch, False


def remove_bedmage_for_discord_user(discord_id: int, character_name: str) -> bool:
    """Auto-create User + delegate to apps.bedmages.services.remove_bedmage_watch.

    Returns True if watch existed and was deleted, False otherwise.
    Idempotent — never raises.
    """
    user, _ = get_or_create_user_by_discord_id(discord_id, discord_username="")
    return remove_bedmage_watch(user, character_name)


def list_bedmages_for_discord_user(discord_id: int) -> list[BedmageWatch]:
    """Active bedmages for user. Empty list if user unknown (no auto-create on read)."""
    try:
        user = User.objects.get(discord_id=discord_id)
    except User.DoesNotExist:
        return []
    return list(
        BedmageWatch.objects.filter(user=user, active=True).select_related("character")
    )


# ─── DeathWatch (DW-7) ──────────────────────────────────────────────────────
# Mirror of the bedmage wrappers above: auto-create User + delegate to the
# domain service in apps.deathwatch.services. Discord-cog-facing entry points
# stay in discord_bot/* per project convention.


def add_deathwatch_for_discord_user(
    discord_id: int, discord_username: str, character_name: str
) -> tuple[DeathWatch, bool]:
    """Auto-create User + delegate to apps.deathwatch.services.add_death_watch.

    Returns (watch, created). `created=False` means the watch was already on
    the user's list — same idempotent-ack pattern as
    `add_bedmage_for_discord_user`. Caller renders different copy for the two
    cases. Canonicalize at entry so the recovery .get() below matches the row
    actually stored (Character.save() canonicalizes on its side too).

    Cap exceeded (`ValueError("cap of N unique characters exceeded")`) is
    re-raised — the cog catches it and surfaces a user-friendly message,
    NOT a stack trace (CLAUDE.md §8).
    """
    user, _ = get_or_create_user_by_discord_id(discord_id, discord_username)
    character_name = _canonicalize_name(character_name)
    try:
        watch = add_death_watch(user, character_name)
        return watch, True
    except ValueError as exc:
        # Two ValueError flavors from add_death_watch:
        # 1. "already active" → idempotent; return existing watch
        # 2. "cap of N unique characters exceeded" → re-raise for cog to surface
        if "already active" in str(exc):
            watch = DeathWatch.objects.get(user=user, character__name=character_name)
            return watch, False
        raise


def remove_deathwatch_for_discord_user(discord_id: int, character_name: str) -> bool:
    """Auto-create User + delegate to apps.deathwatch.services.remove_death_watch.

    Returns True if watch existed and was deleted, False otherwise.
    Idempotent — never raises.
    """
    user, _ = get_or_create_user_by_discord_id(discord_id, discord_username="")
    return remove_death_watch(user, character_name)


def list_all_deathwatches() -> list[DeathWatch]:
    """All active deathwatches across all users (M12 follow-up, public list).

    Wrapper over `apps.deathwatch.services.list_all_death_watches` — returns
    concrete list (cog awaits via `sync_to_async`, py-cord doesn't consume
    QuerySets across the sync/async boundary).
    """
    return list(list_all_death_watches())


# ─── Death-channel cleanup (2026-06-01) ─────────────────────────────────────
# Thin guild-scoped wrappers consumed by the `/deaths cleanup` slash commands.
# Flag lives on DiscordChannel; a guild must register a channel first (via
# `/deaths threshold`) before cleanup can be toggled.


class CleanupStatus(TypedDict):
    """Status payload consumed by ``/deaths cleanup status``."""

    enabled: bool
    last_cleanup_at: datetime | None
    channel_id: int


def enable_cleanup_for_guild(guild_id: int) -> bool:
    """Set ``cleanup_enabled=True`` on the guild's DiscordChannel.

    Returns False (no-op) when no DiscordChannel exists for the guild — cog
    surfaces a "run /deaths threshold first" message in that case.
    """
    updated = DiscordChannel.objects.filter(guild_id=guild_id).update(
        cleanup_enabled=True
    )
    if updated:
        logger.info("Enabled cleanup for guild=%s", guild_id)
        return True
    return False


def disable_cleanup_for_guild(guild_id: int) -> bool:
    """Set ``cleanup_enabled=False`` on the guild's DiscordChannel.

    Returns False (no-op) when no DiscordChannel exists for the guild.
    """
    updated = DiscordChannel.objects.filter(guild_id=guild_id).update(
        cleanup_enabled=False
    )
    if updated:
        logger.info("Disabled cleanup for guild=%s", guild_id)
        return True
    return False


def get_cleanup_status(guild_id: int) -> CleanupStatus | None:
    """Return the cleanup state for the guild, or ``None`` if no channel registered.

    Cog renders the ``None`` case as "no channel registered".
    """
    try:
        channel = DiscordChannel.objects.get(guild_id=guild_id)
    except DiscordChannel.DoesNotExist:
        return None
    return CleanupStatus(
        enabled=channel.cleanup_enabled,
        last_cleanup_at=channel.last_cleanup_at,
        channel_id=channel.channel_id,
    )
