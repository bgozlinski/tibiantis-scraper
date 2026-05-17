"""DeathWatch services — business logic for per-character death blacklist.

CLAUDE.md §7: logic lives here, not in views/resolvers/spiders. Pipeline route
in `scrapers/.../pipelines.py` calls `record_watched_death(dict(item))` rather
than touching ORM directly (CLAUDE.md §6).

Spec: docs/superpowers/specs/2026-05-17-death-blacklist-design.md
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet

from apps.accounts.models import User
from apps.characters.models import Character, _canonicalize_name
from apps.deathwatch.models import DeathWatch, DeathWatchChannel, WatchedDeathEvent

logger = logging.getLogger(__name__)


def add_death_watch(user: User, character_name: str) -> DeathWatch:
    """Create or reactivate a DeathWatch for user+character, with global cap check.

    §3.2 / §3.8 — lazy Character fetch (auto-create), cap enforced atomically
    via post-create count + rollback. Naive pre-check is TOCTOU between
    concurrent /add calls.

    Cap counts UNIQUE characters across all users (§3.2): 10 users watching
    Yhral + Bubble = 2 unique chars, not 20 watches.

    Raises ValueError when active duplicate exists for user, or when adding
    this watch would push unique-character count past
    `settings.DEATHWATCH_MAX_WATCHED_CHARACTERS`.
    """
    character_name = _canonicalize_name(character_name)

    with transaction.atomic():
        character, _ = Character.objects.get_or_create(name=character_name)
        watch, created = DeathWatch.objects.get_or_create(
            user=user, character=character, defaults={"active": True}
        )

        if not created and watch.active:
            raise ValueError(
                f"DeathWatch for {character_name!r} already active for user "
                f"{user.username!r}"
            )
        if not created and not watch.active:
            watch.active = True
            watch.save(update_fields=["active"])

        cap = settings.DEATHWATCH_MAX_WATCHED_CHARACTERS
        unique_count = (
            DeathWatch.objects.filter(active=True)
            .values("character_id")
            .distinct()
            .count()
        )
        if unique_count > cap:
            raise ValueError(
                f"DeathWatch cap of {cap} unique characters exceeded "
                f"(would be {unique_count})"
            )

    return watch


def remove_death_watch(user: User, character_name: str) -> bool:
    """Hard-delete DeathWatch for user+character. Idempotent.

    §3.7 — hard delete consistent with bedmages `remove_bedmage_watch`.
    Re-add resets the `created_at` floor used by `record_watched_death`,
    so historical deaths between remove/add are correctly ignored.
    """
    character_name = _canonicalize_name(character_name)
    deleted, _ = DeathWatch.objects.filter(
        user=user, character__name=character_name
    ).delete()
    return deleted > 0


def list_death_watches(user: User) -> QuerySet[DeathWatch]:
    """List user's watches, newest first, with Character preloaded.

    `select_related` to avoid N+1 when Discord cog / GraphQL renders names.
    """
    return (
        DeathWatch.objects.filter(user=user)
        .select_related("character")
        .order_by("-created_at")
    )


def set_deathwatch_channel_for_guild(
    guild_id: int, channel_id: int
) -> DeathWatchChannel:
    """Upsert announcement channel for a guild. Called by /deathwatch channel.

    Per spec §2 / §3.1: one channel per guild (UniqueConstraint on guild_id).
    Multiple guilds = multiple rows = announcements fan out to all (§3.9).
    """
    channel, _ = DeathWatchChannel.objects.update_or_create(
        guild_id=guild_id, defaults={"channel_id": channel_id}
    )
    return channel


def record_watched_death(item: dict[str, Any]) -> WatchedDeathEvent | None:
    """Pipeline-side: persist event if it qualifies for any active watch.

    §3.6 — filter "po dodaniu": event qualifies only when at least one
    active DeathWatch for this character has `created_at < died_at`.
    Tabela "Latest Deaths" on tibiantis.online shows ~10 historical entries
    so the spider WILL emit deaths from before /add — service drops them.

    Drops (returns None) when:
    - Character missing (abnormal — spider shouldn't emit for unknown chars
      in normal flow; defensive against state drift).
    - No qualifying watch (no active watcher OR all watches added after died_at).
    - Event already exists (unique constraint hit on character+died_at).
    """
    character_name = _canonicalize_name(item["character_name"])
    try:
        character = Character.objects.get(name=character_name)
    except Character.DoesNotExist:
        logger.warning(
            "record_watched_death: Character %r missing, dropping item",
            character_name,
        )
        return None

    died_at = item["died_at"]
    qualifies = DeathWatch.objects.filter(
        character=character, active=True, created_at__lt=died_at
    ).exists()
    if not qualifies:
        return None

    event, created = WatchedDeathEvent.objects.get_or_create(
        character=character,
        died_at=died_at,
        defaults={
            "level_at_death": item["level_at_death"],
            "killed_by": item.get("killed_by", ""),
        },
    )
    return event if created else None


def notify_watched_deaths_for_character(character: Character) -> int:
    """Dispatch pending WatchedDeathEvents for character via configured handler.

    Multi-channel iteration (§3.9): an event fans out to every configured
    `DeathWatchChannel` row. The `announced_on_discord` flag is set ONLY when
    every channel returns True (§3.13 — partial failure leaves the flag false
    so the next task fire retries on all channels). This trades duplicate
    posts on healthy channels for at-least-once delivery on unhealthy ones —
    acceptable for MVP, follow-up §9.5 plans per-channel tracking.

    Returns count of events fully announced this call (for task summary).
    """
    from apps.deathwatch.models import DeathWatchChannel
    from apps.notifications import get_deathwatch_handler

    channels = list(DeathWatchChannel.objects.all())
    if not channels:
        # No channel configured (admin hasn't run /deathwatch channel yet).
        # Pending events stay with announced_on_discord=False and will fire
        # next time a channel exists — acceptable backlog per spec §5 edge.
        return 0

    handler = get_deathwatch_handler()
    fired = 0

    events = WatchedDeathEvent.objects.filter(
        character=character, announced_on_discord=False
    ).select_related("character")

    for event in events:
        all_channels_ok = True
        for channel in channels:
            try:
                if not handler.announce(event, channel):
                    all_channels_ok = False
            except Exception:
                # Isolate per-channel failure — one channel's 5xx must not
                # short-circuit dispatch to the others (spec §3.9).
                logger.exception(
                    "deathwatch announce raised for event=%s channel=%s",
                    event.pk,
                    channel.pk,
                )
                all_channels_ok = False

        if all_channels_ok:
            event.announced_on_discord = True
            event.save(update_fields=["announced_on_discord"])
            fired += 1

    return fired
