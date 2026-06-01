"""Migration 0004 seeds the cleanup PeriodicTask with cron 0 0 */3 * * Europe/Warsaw."""

from __future__ import annotations

import pytest
from django_celery_beat.models import CrontabSchedule, PeriodicTask


@pytest.mark.django_db
def test_cleanup_periodic_task_exists() -> None:
    """The seeded periodic task is present after migrations have run."""
    pt = PeriodicTask.objects.get(name="deaths.cleanup_death_channels")
    assert pt.task == "apps.deaths.tasks.cleanup_death_channels"
    assert pt.enabled is True


@pytest.mark.django_db
def test_cleanup_periodic_task_cron_schedule() -> None:
    """Cron is 0 0 */3 * * with Europe/Warsaw timezone."""
    pt = PeriodicTask.objects.get(name="deaths.cleanup_death_channels")
    cron: CrontabSchedule = pt.crontab
    assert cron is not None
    assert cron.minute == "0"
    assert cron.hour == "0"
    assert cron.day_of_month == "*/3"
    assert cron.month_of_year == "*"
    assert cron.day_of_week == "*"
    assert str(cron.timezone) == "Europe/Warsaw"
