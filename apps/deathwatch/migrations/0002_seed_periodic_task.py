"""Seed PeriodicTask for the deathwatch 1-min scrape (DW-5).

Defaults to `enabled=False` — admin opts in via Django admin / Beat UI once
ready to hit tibiantis.online at the 1-min cadence. Bedmage's check (every
5 min, internal-only DB read) ships enabled=True; this one hits an external
site, so we ship disabled to avoid auto-stressing tibiantis.online on every
fresh deploy until the operator explicitly turns it on.

Idempotent: `get_or_create` preserves operator overrides on re-run.
"""

from django.db import migrations


def create_periodic_task(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = IntervalSchedule.objects.get_or_create(
        every=1,
        period="minutes",
    )
    PeriodicTask.objects.get_or_create(
        name="deathwatch.scrape_for_watched_deaths",
        defaults={
            "task": "apps.deathwatch.tasks.scrape_for_watched_deaths",
            "interval": schedule,
            "enabled": False,
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="deathwatch.scrape_for_watched_deaths").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("deathwatch", "0001_initial"),
        ("django_celery_beat", "0001_initial"),
    ]
    operations = [migrations.RunPython(create_periodic_task, remove_periodic_task)]
