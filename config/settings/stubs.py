"""Minimal settings used ONLY by mypy django-stubs plugin.

Never loaded at runtime. Hardcoded values — no env vars — so mypy
can analyze models without needing .env or django-environ.
"""

SECRET_KEY = "mypy-stub-not-used-at-runtime"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "apps.characters",
]
USE_TZ = True
