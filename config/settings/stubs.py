"""Minimal settings used ONLY by mypy django-stubs plugin.

Imports from base.py to keep custom env-based settings in sync automatically
(no more "stubs.py forgot DEATH_LEVEL_THRESHOLD" carry-over from M3-M4).

INSTALLED_APPS is overridden to a minimal set — Django auth/contenttypes +
``LOCAL_APPS`` (our domain apps) — to keep mypy's isolated env lean. Without
this override, ``import *`` would pull in the full INSTALLED_APPS list
(rest_framework, strawberry_django, django_celery_beat, …) and mypy's plugin
would try to populate Django's Apps registry by importing each one, requiring
every third-party package in ``additional_dependencies`` of
``.pre-commit-config.yaml``. That doesn't scale (every M5+ app would extend
the list). The minimal override sidesteps the cost while preserving the
LOCAL_APPS single-source-of-truth from base.py.

Never loaded at runtime — referenced only by [tool.django-stubs]
django_settings_module in pyproject.toml for type checking.
"""

import os

# Stub defaults for env-based settings — non-empty values so base.py's
# environ.Env bootstrap doesn't blow up at import time. os.environ.setdefault
# is a no-op when key is already set, so .env (dev) and CI workflow env: block
# values take precedence — these only kick in for isolated mypy runs that
# have neither (e.g. pre-commit's isolated env on a fresh machine).
os.environ.setdefault("DJANGO_SECRET_KEY", "stub-not-runtime")
os.environ.setdefault("POSTGRES_DB", "stub")
os.environ.setdefault("POSTGRES_USER", "stub")
os.environ.setdefault("POSTGRES_PASSWORD", "stub")
os.environ.setdefault("POSTGRES_HOST", "stub")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DJANGO_DEBUG", "False")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "")

from config.settings.base import *  # noqa: F401, F403, E402
from config.settings.base import LOCAL_APPS  # noqa: E402  (explicit re-import for type checker)

# Override INSTALLED_APPS to a minimal set — see module docstring.
# LOCAL_APPS comes from base.py (single source of truth).
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    *LOCAL_APPS,
]
