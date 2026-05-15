import logging
import subprocess
import sys
import json

from celery import shared_task, Task
from apps.deaths.services import announce_unannounced_deaths


logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2)
def scrape_deaths(self: Task) -> dict[str, int]:
    """Scrape deaths from tibiantis.info via subprocess `manage.py scrape_deaths`.
    Subprocess isolates Twisted reactor from Celery worker pool (M1 retro #8).
    Parses JSON summary from stdout for observability — sentinel return on
    parse error so result backend gets a typed dict, never None.

    Returns: {"yielded": int, "duplicates": int, "returncode": int}
    """
    try:
        result = subprocess.run(
            [sys.executable, "manage.py", "scrape_deaths"],
            timeout=120,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        logger.warning("scrape_deaths subprocess timed out: %s", exc)
        raise self.retry(exc=exc, countdown=60) from exc

    if result.returncode != 0:
        logger.warning(
            "scrape_deaths subprocess returncode=%s stderr=%s",
            result.returncode,
            result.stderr[:500],
        )

    try:
        summary: dict[str, int] = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.error("scrape_deaths stdout not JSON: %s", result.stdout[:500])
        return {"yielded": -1, "duplicates": -1, "returncode": result.returncode}

    summary["returncode"] = result.returncode
    logger.info("scrape_deaths: %s", summary)

    try:
        announce_summary = announce_unannounced_deaths()
        summary.update(announce_summary)
    except Exception:
        logger.exception(
            "announce_unannounced_deaths raised — events stay unannounced for next cycle"
        )

    return summary
