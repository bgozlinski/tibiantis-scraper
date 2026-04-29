import logging
import subprocess
import sys
from datetime import timedelta

from celery import shared_task, Task
from django.conf import settings
from django.utils import timezone

from apps.characters.models import Character

logger = logging.getLogger(__name__)


@shared_task
def ping() -> str:
    return "pong"


@shared_task(bind=True, max_retries=2)
def scrape_watched_characters(self: Task) -> dict[str, int]:
    """Scrape all Character objects via M1 management command (subprocess).

    Subprocess isolates Twisted reactor from Celery worker pool — see M1 retro #8
    (3 event loops can't coexist in one process). Per-character failures are
    absorbed in `failed` count, not propagated to retry — `max_retries=2` covers
    only task-level errors (DB unreachable, etc.).

    Freshness threshold (CELERY_SCRAPE_FRESHNESS_MINUTES, default 30) skips
    Characters scraped recently — mitigates Beat race when task duration
    overlaps with next fire interval.

    Returns: {"scraped": int, "failed": int, "skipped": int}
    """

    threshold_minutes = getattr(settings, "CELERY_SCRAPE_FRESHNESS_MINUTES", 30)
    cutoff = timezone.now() - timedelta(minutes=threshold_minutes)

    scraped = failed = skipped = 0
    for name, last_scraped_at in Character.objects.values_list(
        "name", "last_scraped_at"
    ):
        if last_scraped_at and last_scraped_at > cutoff:
            skipped += 1
            continue
        result = subprocess.run(
            [
                sys.executable,
                "manage.py",
                "scrape_character",
                name,
            ],
            timeout=60,
            check=False,
        )
        if result.returncode == 0:
            scraped += 1
        else:
            failed += 1
            logger.warning(
                "scrape_character %s failed: returncode=%s", name, result.returncode
            )

    summary = {"scraped": scraped, "failed": failed, "skipped": skipped}
    logger.info("scrape_watched_characters: %s", summary)
    return summary
