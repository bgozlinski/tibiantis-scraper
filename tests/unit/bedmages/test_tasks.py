"""Tests for apps.bedmages.tasks — periodic notification check (#176).

The bedmage notification was firing up to ~60 min late in prod because the
check ran only as a side-effect of the hourly scrape task. This decouples it:
a new Celery beat task runs every 5 min, iterates active BedmageWatch'es,
and delegates to the existing `apps.bedmages.services.
check_bedmage_watches_for_character` per character.

Pins the task contract:
  - Returns `{"checked": int, "fired": int}` summary
  - Iterates ONLY Characters with at least one active BedmageWatch
    (avoids DoS on the Character table when the watch list is sparse)
  - Idempotent on repeated fires (the service-level `last_notified_login`
    guard prevents double-notify)
  - The seed migration `apps/bedmages/migrations/0002_seed_bedmage_check_periodic_task`
    creates the PeriodicTask with 5-min interval and `enabled=True` so the
    bot works out-of-the-box after `migrate`.

Late imports (inside test functions) are intentional — `apps.bedmages.tasks`
does not exist yet pre-fix; with top-level imports the whole file would
ImportError at collection and none of the tests would run. Late imports let
each test fail individually with a clearer signal until the dev creates the
module.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.bedmages.models import BedmageWatch
from apps.characters.models import Character

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="alice", email="alice@example.com", password="pass-Komplex!1"
    )


@pytest.fixture
def character(db):
    return Character.objects.create(name="Yhral")


@pytest.mark.django_db
def test_check_bedmage_notifications_returns_zero_when_no_active_watches() -> None:
    """Empty DB (no BedmageWatch rows) → task is a no-op, returns 0/0.

    Sanity: the task must NOT iterate the entire Character table. It queries
    Characters joined to active BedmageWatch'es, so an empty watch list means
    zero work. Without this guard, growing Character.objects.count() (each
    scraped death adds a row in M-future) would inflate the task's runtime.
    """
    from apps.bedmages.tasks import check_bedmage_notifications

    result = check_bedmage_notifications()

    assert result == {"checked": 0, "fired": 0}


@pytest.mark.django_db
def test_check_bedmage_notifications_skips_characters_without_active_watches(
    user,
) -> None:
    """Only Characters with at least one active BedmageWatch are iterated.

    Setup:
      - `Watched` — has active=True watch
      - `Inactive` — has watch but active=False
      - `Unwatched` — no BedmageWatch row at all

    All three have `last_login` old enough to fire IF iterated. Only `Watched`
    should be processed (checked=1, fired=1). Verifies the DB-level filter
    (active=True join) — not an in-service skip that would still increment
    the `checked` counter.
    """
    from apps.bedmages.tasks import check_bedmage_notifications

    watched = Character.objects.create(name="Watched")
    inactive = Character.objects.create(name="Inactive")
    Character.objects.create(name="Unwatched")  # no watch at all

    BedmageWatch.objects.create(user=user, character=watched, active=True)
    BedmageWatch.objects.create(user=user, character=inactive, active=False)

    long_ago = timezone.now() - timedelta(minutes=120)
    Character.objects.filter(name__in=["Watched", "Inactive", "Unwatched"]).update(
        last_login=long_ago
    )

    with patch("apps.bedmages.services.get_bedmage_handler", return_value=MagicMock()):
        result = check_bedmage_notifications()

    assert result == {"checked": 1, "fired": 1}


@pytest.mark.django_db
def test_check_bedmage_notifications_fires_when_threshold_passed(
    user, character
) -> None:
    """Active watch + delta >= BEDMAGE_REGEN_MINUTES + not yet notified → fires.

    Returns checked=1 fired=1 + persists `last_notified_login = character.last_login`
    on the watch row. Mirrors `test_check_fires_when_delta_above_threshold_*` from
    test_services.py but exercises the task wrapper instead of the inner service
    directly.
    """
    from apps.bedmages.tasks import check_bedmage_notifications

    BedmageWatch.objects.create(user=user, character=character)
    Character.objects.filter(pk=character.pk).update(
        last_login=timezone.now() - timedelta(minutes=120)
    )
    character.refresh_from_db()

    with patch("apps.bedmages.services.get_bedmage_handler", return_value=MagicMock()):
        result = check_bedmage_notifications()

    assert result == {"checked": 1, "fired": 1}
    watch = BedmageWatch.objects.get(user=user, character=character)
    assert watch.last_notified_login == character.last_login


@pytest.mark.django_db
def test_check_bedmage_notifications_idempotent_on_repeated_call(
    user, character
) -> None:
    """Second call after first fire → no double-notify.

    The Celery beat runs every 5 min; between two fires the same watch is
    eligible to "fire again" (delta still >= threshold) BUT the service's
    `last_notified_login == character.last_login` guard short-circuits.
    Without this guard the user would get a notification every 5 min until
    the character logs in again — spam.

    Verifies the contract end-to-end: first call fires (1/1), second call
    skips (1/0 — still checked because we iterated, but not fired again).
    """
    from apps.bedmages.tasks import check_bedmage_notifications

    BedmageWatch.objects.create(user=user, character=character)
    Character.objects.filter(pk=character.pk).update(
        last_login=timezone.now() - timedelta(minutes=120)
    )
    character.refresh_from_db()

    with patch("apps.bedmages.services.get_bedmage_handler", return_value=MagicMock()):
        first = check_bedmage_notifications()
        second = check_bedmage_notifications()

    assert first == {"checked": 1, "fired": 1}
    assert second == {"checked": 1, "fired": 0}


@pytest.mark.django_db
def test_check_bedmage_notifications_returns_zero_fired_when_below_threshold(
    user, character
) -> None:
    """Active watch but delta < threshold → checked increments, fired=0.

    Verifies the `checked` counter tracks iterated characters regardless of
    whether they fire, useful for confirming the task ran its sweep even when
    nothing was due (operability signal in logs / Mongo handler).
    """
    from apps.bedmages.tasks import check_bedmage_notifications

    BedmageWatch.objects.create(user=user, character=character)
    Character.objects.filter(pk=character.pk).update(
        last_login=timezone.now() - timedelta(minutes=50)  # well below 100
    )
    character.refresh_from_db()

    result = check_bedmage_notifications()

    assert result == {"checked": 1, "fired": 0}


@pytest.mark.django_db
def test_periodic_task_seed_creates_check_bedmage_notifications() -> None:
    """The seed migration 0002 creates the PeriodicTask with the documented
    contract: 5-min interval, enabled=True out-of-the-box.

    Without this test, operators relying on Django admin would see no entry
    until they manually created one — `enabled=True` is the whole point of
    avoiding an undocumented post-deploy step. The test DB runs all
    migrations during setup, so the row should exist after migrate.
    """
    from django_celery_beat.models import PeriodicTask

    task = PeriodicTask.objects.get(name="check_bedmage_notifications")

    assert task.task == "apps.bedmages.tasks.check_bedmage_notifications"
    assert task.enabled is True
    assert task.interval is not None
    assert task.interval.every == 5
    assert task.interval.period == "minutes"
