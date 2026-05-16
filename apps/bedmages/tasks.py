"""Celery tasks for bedmages app.

Notification timing decoupled from scrape cadence per #176. The original M5
design only invoked `check_bedmage_watches_for_character` as a side-effect of
the hourly `scrape_watched_characters` task, which meant Discord notifications
could arrive up to ~60 min late vs the configured `BEDMAGE_REGEN_MINUTES=100`
threshold. This task runs on its own 5-min beat (seeded in migration 0002)
and iterates only Characters with at least one active BedmageWatch — pure
DB read + conditional Discord webhook, no Tibiantis HTTP.
"""

import logging

from celery import shared_task

from apps.bedmages.services import check_bedmage_watches_for_character
from apps.characters.models import Character

logger = logging.getLogger(__name__)


@shared_task
def check_bedmage_notifications() -> dict[str, int]:
    """Iterate active-watched Characters, fire notifications when due.

    Idempotency provided by the inner service via its `last_notified_login`
    guard — repeated fires on the same login session are no-ops, which is
    what enables this task to run every 5 min without spamming users.

    Returns a `{"checked": int, "fired": int}` summary for log/metrics
    visibility. `checked` counts iterated characters; `fired` counts those
    that actually produced a notification on this pass.
    """
    checked = 0
    fired = 0

    characters = Character.objects.filter(bedmage_watches__active=True).distinct()
    for character in characters:
        checked += 1
        fired += check_bedmage_watches_for_character(character)

    summary = {"checked": checked, "fired": fired}
    logger.info("check_bedmage_notifications: %s", summary)
    return summary
