"""Celery application factory.

Imported as ``config.celery:app`` by the worker, beat and any module that
needs to enqueue tasks. ``autodiscover_tasks`` walks every installed Django
app for a ``tasks`` module so new feature apps do not have to be wired in
here.
"""

import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("tibiantis")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
