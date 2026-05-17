"""Integration tests for scrape_for_watched_deaths Celery task (DW-5).

Subprocess + notify mocked — verify Redis lock, freshness gate, cap defense,
and Character.last_deaths_scraped_at update semantics (§3.12). Real DB,
mocked external boundary (subprocess + notify).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.characters.models import Character
from apps.deathwatch.models import DeathWatch
from apps.deathwatch.services import add_death_watch
from apps.deathwatch.tasks import LOCK_KEY, scrape_for_watched_deaths


@pytest.fixture(autouse=True)
def _clear_lock():
    """Ensure each test starts with the lock released."""
    cache.delete(LOCK_KEY)
    yield
    cache.delete(LOCK_KEY)


# ──────────────────────────────────────────────────────────────────────────────
# Redis lock
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_task_locked_returns_locked_summary_without_iterating() -> None:
    """Existing lock → early return, no DB query, no subprocess."""
    cache.set(LOCK_KEY, "1", timeout=55)
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")  # would be iterated if lock weren't held

    with patch("apps.deathwatch.tasks.subprocess.run") as mock_subprocess:
        result = scrape_for_watched_deaths()

    assert result["locked"] is True
    assert result["scraped"] == 0
    mock_subprocess.assert_not_called()


@pytest.mark.django_db
def test_task_releases_lock_after_completion() -> None:
    """Lock released even when no characters to scrape (empty DB)."""
    with patch("apps.deathwatch.tasks.subprocess.run"):
        scrape_for_watched_deaths()

    assert cache.get(LOCK_KEY) is None


@pytest.mark.django_db
def test_task_releases_lock_even_when_subprocess_raises() -> None:
    """Lock cleanup in `finally` — exception must not leave it stuck."""
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")

    with patch(
        "apps.deathwatch.tasks.subprocess.run",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            scrape_for_watched_deaths()

    assert cache.get(LOCK_KEY) is None


# ──────────────────────────────────────────────────────────────────────────────
# Freshness gate (§3.12 — uses last_deaths_scraped_at, not last_scraped_at)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_freshness_gate_uses_last_deaths_scraped_at_not_last_scraped_at() -> None:
    """Critical: gate must read per-source field, not generic last_scraped_at.

    Spec §5.1 — reusing last_scraped_at would let bedmage scraper "hide" us
    from the freshness check by writing it via auto_now on every Character.save().
    """
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")

    # Last bedmage scrape (last_scraped_at) is fresh — but deathwatch hasn't
    # touched this character. Gate should NOT skip; subprocess should run.
    Character.objects.filter(name="Yhral").update(
        last_deaths_scraped_at=None,  # never scraped by deathwatch
    )

    with patch("apps.deathwatch.tasks.subprocess.run") as mock_subprocess:
        mock_subprocess.return_value = MagicMock(returncode=0)
        result = scrape_for_watched_deaths()

    assert result["scraped"] == 1
    assert result["skipped"] == 0
    mock_subprocess.assert_called_once()


@pytest.mark.django_db
def test_task_skips_freshly_scraped_character() -> None:
    """Character with recent last_deaths_scraped_at → skipped, no subprocess."""
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")
    Character.objects.filter(name="Yhral").update(last_deaths_scraped_at=timezone.now())

    with patch("apps.deathwatch.tasks.subprocess.run") as mock_subprocess:
        result = scrape_for_watched_deaths()

    assert result["skipped"] == 1
    assert result["scraped"] == 0
    mock_subprocess.assert_not_called()


@pytest.mark.django_db
def test_task_scrapes_character_with_stale_last_deaths_scraped_at() -> None:
    """Character last scraped > DEATHWATCH_FRESHNESS_SECONDS ago → scrape."""
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")
    Character.objects.filter(name="Yhral").update(
        last_deaths_scraped_at=timezone.now() - timedelta(minutes=5),
    )

    with patch("apps.deathwatch.tasks.subprocess.run") as mock_subprocess:
        mock_subprocess.return_value = MagicMock(returncode=0)
        result = scrape_for_watched_deaths()

    assert result["scraped"] == 1


# ──────────────────────────────────────────────────────────────────────────────
# Subprocess + post-success bookkeeping (§3.12 — task updates the field, not pipeline)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_task_updates_last_deaths_scraped_at_on_success() -> None:
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")

    before = timezone.now()
    with patch("apps.deathwatch.tasks.subprocess.run") as mock_subprocess:
        mock_subprocess.return_value = MagicMock(returncode=0)
        scrape_for_watched_deaths()
    after = timezone.now()

    character = Character.objects.get(name="Yhral")
    assert character.last_deaths_scraped_at is not None
    assert before <= character.last_deaths_scraped_at <= after


@pytest.mark.django_db
def test_task_does_not_update_last_deaths_on_subprocess_failure() -> None:
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")

    with patch("apps.deathwatch.tasks.subprocess.run") as mock_subprocess:
        mock_subprocess.return_value = MagicMock(returncode=1)
        result = scrape_for_watched_deaths()

    assert result["failed"] == 1
    assert result["scraped"] == 0
    character = Character.objects.get(name="Yhral")
    assert character.last_deaths_scraped_at is None


@pytest.mark.django_db
def test_task_handles_subprocess_timeout() -> None:
    """TimeoutExpired exception → counted as failed, lock released, no crash."""
    import subprocess as _subprocess

    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")

    with patch(
        "apps.deathwatch.tasks.subprocess.run",
        side_effect=_subprocess.TimeoutExpired(cmd="x", timeout=30),
    ):
        result = scrape_for_watched_deaths()

    assert result["failed"] == 1
    assert cache.get(LOCK_KEY) is None  # lock released despite the exception


@pytest.mark.django_db
def test_task_calls_notify_after_successful_scrape() -> None:
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")

    with (
        patch("apps.deathwatch.tasks.subprocess.run") as mock_subprocess,
        patch(
            "apps.deathwatch.tasks.notify_watched_deaths_for_character",
            return_value=3,
        ) as mock_notify,
    ):
        mock_subprocess.return_value = MagicMock(returncode=0)
        result = scrape_for_watched_deaths()

    mock_notify.assert_called_once()
    assert result["events_announced"] == 3


# ──────────────────────────────────────────────────────────────────────────────
# Cap defense
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
@override_settings(DEATHWATCH_MAX_WATCHED_CHARACTERS=1)
def test_task_refuses_iteration_when_cap_breached() -> None:
    """Defense-in-depth: if cap check in services leaked, task must NOT scrape.

    Force two watches past cap by bypassing add_death_watch (service-layer
    cap blocks it). Direct ORM insert simulates state drift / manual edit.
    """
    u1 = User.objects.create(username="alice", discord_id="1")
    u2 = User.objects.create(username="bob", discord_id="2")
    c1 = Character.objects.create(name="Yhral")
    c2 = Character.objects.create(name="Bubble")
    DeathWatch.objects.create(user=u1, character=c1)
    DeathWatch.objects.create(user=u2, character=c2)

    with patch("apps.deathwatch.tasks.subprocess.run") as mock_subprocess:
        result = scrape_for_watched_deaths()

    assert result["scraped"] == 0
    assert result["failed"] == 0
    mock_subprocess.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# Empty / inactive watches
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_task_returns_zero_summary_when_no_active_watches() -> None:
    """Inactive watches are not iterated (matches DW-5 DeathWatch.filter active=True)."""
    user = User.objects.create(username="alice", discord_id="1")
    watch = add_death_watch(user, "Yhral")
    watch.active = False
    watch.save(update_fields=["active"])

    with patch("apps.deathwatch.tasks.subprocess.run") as mock_subprocess:
        result = scrape_for_watched_deaths()

    assert result == {
        "checked": 0,
        "skipped": 0,
        "scraped": 0,
        "failed": 0,
        "events_announced": 0,
        "locked": False,
    }
    mock_subprocess.assert_not_called()
