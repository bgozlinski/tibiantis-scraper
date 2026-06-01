"""Service layer for the deaths app.

Owns two concerns:

* dedup-safe insertion of new :class:`DeathEvent` rows from the spider
  (``save_death_event``);
* the fan-out announcement loop that delivers unannounced deaths to every
  Discord channel whose configured threshold is met
  (``announce_unannounced_deaths``).
"""

from datetime import datetime
from typing import TypedDict
import logging
import time

from django.db import IntegrityError, transaction

from apps.deaths.models import DeathEvent
from apps.notifications import get_death_handler
from discord_bot.models import DiscordChannel

logger = logging.getLogger(__name__)

# Death-channel cleanup constants (added 2026-06-01, see spec
# 2026-06-01-death-channel-cleanup-design.md).
RETENTION_DAYS = 3
DISCORD_EPOCH_MS = 1420070400000


def snowflake_for_datetime(dt: datetime) -> int:
    """Encode a UTC datetime as a Discord snowflake (high 42 bits = timestamp).

    Discord message IDs are monotonically time-ordered, so passing this
    value as the ``before=`` query parameter on
    ``GET /channels/{id}/messages`` returns only messages older than ``dt``
    without scanning the whole channel. Lower 22 bits (worker/process/seq)
    are zero — fine for a *boundary* (we want "everything before this
    timestamp", not a specific message).
    """
    unix_ms = int(dt.timestamp() * 1000)
    return (unix_ms - DISCORD_EPOCH_MS) << 22


class DeathPayload(TypedDict):
    """Strongly-typed payload produced by the deaths spider pipeline."""

    character_name: str
    level_at_death: int
    killed_by: str
    died_at: datetime


def save_death_event(payload: DeathPayload) -> DeathEvent | None:
    """Create DeathEvent or skip silently on dedup hit.

    Returns None when (character_name, died_at) already exists in DB.
    Deaths are immutable — no upsert semantics. Caller (pipeline) ignores
    return value, but pipeline's stats counter inc'es on None to track
    duplicates for observability.
    """
    try:
        with transaction.atomic():
            return DeathEvent.objects.create(**payload)
    except IntegrityError:
        return None


def announce_unannounced_deaths() -> dict[str, int]:
    """Iterate unannounced DeathEvents, fan-out do applicable guildów, mark announced.

    Multi-guild fan-out: dla każdej unannounced event'a fetch wszystkie
    DiscordChannel gdzie threshold <= level_at_death. Wyślij do każdej guild
    (rate-limited 200ms sleep). Mark announced_on_discord=True gdy ALL succeed.
    Failed event stays False — retry next scrape cycle.

    "No applicable guilds" semantyka: gdy 0 guildów ma threshold <= level,
    mark announced=True mimo braku message'a (semantyka "evaluated + skipped").
    Unikamy retry storm w queryach każdego scrape cycle.

    Known limitation (§3.3): gdy admin dodaje nowy DiscordChannel z niższym
    threshold PO ogłoszeniu, historyczne śmierci `announced_on_discord=True`
    NIE są retroaktywnie wysłane. Backfill out of scope dla M8 — M-future
    conversion do M2M tracking model.

    Returns: {"events_announced": N, "events_skipped": M, "fail_count": K}
    """
    handler = get_death_handler()
    events_announced = 0
    events_skipped = 0
    fail_count = 0

    unannounced = DeathEvent.objects.filter(announced_on_discord=False).order_by(
        "died_at"
    )
    for event in unannounced:
        applicable_guilds = DiscordChannel.objects.filter(
            death_level_threshold__lte=event.level_at_death
        )

        if not applicable_guilds.exists():
            event.announced_on_discord = True
            event.save(update_fields=["announced_on_discord"])
            events_skipped += 1
            continue

        all_ok = True
        for channel in applicable_guilds:
            try:
                ok = handler.announce(event, channel)
            except Exception:
                logger.exception(
                    "DeathAnnouncementHandler.announce raised for event=%s channel=%s",
                    event.pk,
                    channel.pk,
                )
                ok = False
            all_ok = all_ok and ok
            time.sleep(0.2)  # rate limit defensive

        if all_ok:
            event.announced_on_discord = True
            event.save(update_fields=["announced_on_discord"])
            events_announced += 1
        else:
            fail_count += 1

    summary = {
        "events_announced": events_announced,
        "events_skipped": events_skipped,
        "fail_count": fail_count,
    }
    logger.info("announce_unannounced_deaths: %s", summary)
    return summary
