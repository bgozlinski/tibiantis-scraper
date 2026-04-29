from django.db import migrations


def create_periodic_task(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = IntervalSchedule.objects.get_or_create(
        every=1,
        period="hours",
    )
    PeriodicTask.objects.get_or_create(
        name="scrape_watched_characters",
        defaults={
            "task": "apps.characters.tasks.scrape_watched_characters",
            "interval": schedule,
            "enabled": False,
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="scrape_watched_characters").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("characters", "0002_remove_character_characters__name_6d8b81_idx"),
        ("django_celery_beat", "0001_initial"),
    ]
    operations = [migrations.RunPython(create_periodic_task, remove_periodic_task)]
