"""DeathWatch Celery task — per-1-min scrape of Latest Deaths sections.

Subprocess per-Character isolates Twisted reactor from worker pool (M3 retro
#8). Redis lock prevents overlapping Beat fires when iteration > 60s (§3.10).
Freshness gate uses per-source `Character.last_deaths_scraped_at` (§3.12) —
bedmage scraper updates `last_scraped_at` independently, so this gate must
NOT reuse that field (spec §5.1).

Spec: docs/superpowers/specs/2026-05-17-death-blacklist-design.md
"""

from __future__ import annotations

import logging
import subprocess
import sys
from datetime import timedelta

from celery import Task, shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.characters.models import Character
from apps.deathwatch.models import DeathWatch
from apps.deathwatch.services import notify_watched_deaths_for_character

logger = logging.getLogger(__name__)

LOCK_KEY = "deathwatch_scrape_lock"
LOCK_TIMEOUT_SECONDS = 55  # < 60s Beat interval, releases before next fire

SUBPROCESS_TIMEOUT_SECONDS = 30


@shared_task(bind=True, max_retries=2, acks_late=True)
def scrape_for_watched_deaths(self: Task) -> dict[str, int | bool]:
    """Iterate unique characters with active DeathWatch, scrape Latest Deaths,
    fire notifications.

    Lock-first short-circuit (`cache.add` atomic on Redis backend) — if the
    previous fire is still running, the new fire returns immediately rather
    than queueing and potentially double-hammering tibiantis.online.

    Per-character flow:
    1. Freshness skip if `last_deaths_scraped_at > now - DEATHWATCH_FRESHNESS_SECONDS`.
    2. Subprocess `manage.py scrape_character_deaths <name>` (timeout 30s).
    3. On success: update `last_deaths_scraped_at` + fire notify.
    4. On failure: log + continue (next character).

    Returns observability summary `{"checked", "skipped", "scraped", "failed",
    "events_announced", "locked"}` for Flower / log inspection.
    """
    if not cache.add(LOCK_KEY, "1", timeout=LOCK_TIMEOUT_SECONDS):
        logger.info("scrape_for_watched_deaths: lock held, skipping this fire")
        return {
            "checked": 0,
            "skipped": 0,
            "scraped": 0,
            "failed": 0,
            "events_announced": 0,
            "locked": True,
        }

    try:
        return _do_scrape()
    finally:
        cache.delete(LOCK_KEY)


def _do_scrape() -> dict[str, int | bool]:
    cap = settings.DEATHWATCH_MAX_WATCHED_CHARACTERS
    freshness_seconds = settings.DEATHWATCH_FRESHNESS_SECONDS
    cutoff = timezone.now() - timedelta(seconds=freshness_seconds)

    character_names = list(
        DeathWatch.objects.filter(active=True)
        .values_list("character__name", flat=True)
        .distinct()
    )

    if len(character_names) > cap:
        # Defense-in-depth — service-layer cap check in add_death_watch should
        # have prevented this. If it leaks through (manual DB edit, race, etc.)
        # we refuse to bomb tibiantis rather than respecting the broken state.
        logger.error(
            "scrape_for_watched_deaths: cap breached (%s > %s) — refusing iteration",
            len(character_names),
            cap,
        )
        return {
            "checked": 0,
            "skipped": 0,
            "scraped": 0,
            "failed": 0,
            "events_announced": 0,
            "locked": False,
        }

    checked = skipped = scraped = failed = events_announced = 0

    for name in character_names:
        checked += 1
        try:
            character = Character.objects.get(name=name)
        except Character.DoesNotExist:
            logger.warning("character %r vanished mid-iteration", name)
            failed += 1
            continue

        if (
            character.last_deaths_scraped_at
            and character.last_deaths_scraped_at > cutoff
        ):
            skipped += 1
            continue

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "manage.py",
                    "scrape_character_deaths",
                    name,
                ],
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("scrape_character_deaths %r timed out", name)
            failed += 1
            continue

        if result.returncode != 0:
            failed += 1
            logger.warning(
                "scrape_character_deaths %r failed: returncode=%s",
                name,
                result.returncode,
            )
            continue

        scraped += 1
        # §3.12 — update per-source field, NOT generic last_scraped_at. Bedmage
        # scraper writes last_scraped_at via auto_now on every Character.save();
        # reusing it here would let bedmage runs "hide" us from the freshness
        # gate, skipping a 1-min cycle we needed.
        Character.objects.filter(name=name).update(
            last_deaths_scraped_at=timezone.now()
        )

        try:
            character.refresh_from_db(fields=["last_deaths_scraped_at"])
            events_announced += notify_watched_deaths_for_character(character)
        except Exception:
            # Notify is best-effort — a failure here doesn't undo the scrape.
            # DW-6 will plug in real handler; current stub returns 0.
            logger.exception("notify failed for character %r", name)

    summary: dict[str, int | bool] = {
        "checked": checked,
        "skipped": skipped,
        "scraped": scraped,
        "failed": failed,
        "events_announced": events_announced,
        "locked": False,
    }
    logger.info("scrape_for_watched_deaths: %s", summary)
    return summary
