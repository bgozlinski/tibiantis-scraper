from django.db import migrations


def create_periodic_task(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    cron, _ = CrontabSchedule.objects.get_or_create(
        minute="0",
        hour="0",
        day_of_month="*/3",
        month_of_year="*",
        day_of_week="*",
        timezone="Europe/Warsaw",
    )
    PeriodicTask.objects.update_or_create(
        name="deaths.cleanup_death_channels",
        defaults={
            "task": "apps.deaths.tasks.cleanup_death_channels",
            "crontab": cron,
            "enabled": True,
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="deaths.cleanup_death_channels").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("deaths", "0003_deathevent_announced_on_discord"),
        ("django_celery_beat", "0016_alter_crontabschedule_timezone"),
    ]
    operations = [migrations.RunPython(create_periodic_task, remove_periodic_task)]
