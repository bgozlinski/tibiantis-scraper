"""Seed PeriodicTask for the bedmage notification check (#176).

Runs the new `apps.bedmages.tasks.check_bedmage_notifications` task every
5 minutes, `enabled=True` out-of-the-box. Mirrors the pattern in
`apps/characters/migrations/0003_seed_default_periodic_task.py` but defaults
to enabled because the check has no external HTTP side-effects (pure DB
read + conditional Discord webhook, no Tibiantis scrape) — works as a no-op
on empty databases.

Idempotent: `get_or_create` on both the IntervalSchedule (5 min) and the
PeriodicTask. Re-running the migration is safe; pre-existing rows are
preserved untouched (no overwrite of operator-tuned interval).
"""

from django.db import migrations


def create_periodic_task(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = IntervalSchedule.objects.get_or_create(
        every=5,
        period="minutes",
    )
    PeriodicTask.objects.get_or_create(
        name="check_bedmage_notifications",
        defaults={
            "task": "apps.bedmages.tasks.check_bedmage_notifications",
            "interval": schedule,
            "enabled": True,
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="check_bedmage_notifications").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("bedmages", "0001_initial"),
        ("django_celery_beat", "0001_initial"),
    ]
    operations = [migrations.RunPython(create_periodic_task, remove_periodic_task)]
