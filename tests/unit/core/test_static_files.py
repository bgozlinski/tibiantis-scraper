"""Tests for static-file serving config — #162 fix verification.

Pre-#162, Django admin in prod (`DEBUG=False`, gunicorn, no nginx) renders
unstyled because nothing serves `/static/`: `STATIC_URL` is set but `STATIC_ROOT`
is missing, no `collectstatic` runs during image build, and `MIDDLEWARE` has no
whitenoise to serve the collected tree at runtime.

These tests assert the three-part contract that fixes the bug:
  1. `STATIC_ROOT` points at a writable directory so `collectstatic --noinput`
     has somewhere to write.
  2. `STORAGES["staticfiles"]["BACKEND"]` uses whitenoise's compressed manifest
     storage (Django 6 settings shape — NOT legacy `STATICFILES_STORAGE`).
  3. `WhiteNoiseMiddleware` sits in `MIDDLEWARE` immediately after
     `SecurityMiddleware` (per whitenoise docs — earlier or later breaks the
     content-encoding / security-header interleaving).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings


def test_static_root_is_configured() -> None:
    """STATIC_ROOT must be set so `collectstatic --noinput` has a target dir.

    Pre-fix the setting is missing entirely; Django falls back to `None` which
    makes `collectstatic` a no-op and gunicorn has nothing to serve.
    """
    assert settings.STATIC_ROOT, (
        "STATIC_ROOT must be set (typically BASE_DIR / 'staticfiles') so "
        "collectstatic has a destination"
    )
    assert Path(settings.STATIC_ROOT).name == "staticfiles", (
        f"STATIC_ROOT should be named 'staticfiles' per project convention; "
        f"got {settings.STATIC_ROOT}"
    )


def test_storages_staticfiles_uses_whitenoise_compressed_manifest() -> None:
    """STORAGES['staticfiles']['BACKEND'] must point at whitenoise's
    CompressedManifestStaticFilesStorage.

    Django 6 deprecated the legacy `STATICFILES_STORAGE` flat setting in favour
    of the `STORAGES` dict. This test pins the modern shape so a future
    contributor doesn't accidentally use the legacy key (which Django 6 ignores).

    Whitenoise's CompressedManifestStaticFilesStorage gives us:
      - gzip/brotli pre-compression at collectstatic time → smaller wire
      - manifest-based cache busting (hash in filename) → far-future Cache-Control
    """
    storages = getattr(settings, "STORAGES", None)
    assert storages is not None, (
        "settings.STORAGES dict must be defined (Django 6 shape, not legacy "
        "STATICFILES_STORAGE)"
    )
    assert "staticfiles" in storages, "STORAGES must declare a 'staticfiles' key"
    assert (
        storages["staticfiles"]["BACKEND"]
        == "whitenoise.storage.CompressedManifestStaticFilesStorage"
    ), (
        f"STORAGES['staticfiles']['BACKEND'] must be whitenoise's "
        f"CompressedManifestStaticFilesStorage; got "
        f"{storages['staticfiles']['BACKEND']!r}"
    )


def test_whitenoise_middleware_directly_after_security() -> None:
    """WhiteNoiseMiddleware must sit at index N+1 where N is SecurityMiddleware.

    Per whitenoise docs (http://whitenoise.evans.io/en/stable/django.html#enable-whitenoise):
    placement is strict — Security MUST come first (so security headers attach to
    every response, including static files), and WhiteNoise MUST come second (so
    it short-circuits `/static/*` before any heavier middleware runs).

    Any other middleware between them is a misconfiguration.
    """
    middleware = list(settings.MIDDLEWARE)
    security = "django.middleware.security.SecurityMiddleware"
    whitenoise = "whitenoise.middleware.WhiteNoiseMiddleware"

    assert security in middleware, "SecurityMiddleware missing — base config broken"
    assert whitenoise in middleware, (
        "WhiteNoiseMiddleware missing from MIDDLEWARE — /static/ won't be served "
        "in prod (DEBUG=False)"
    )

    security_idx = middleware.index(security)
    whitenoise_idx = middleware.index(whitenoise)
    assert whitenoise_idx == security_idx + 1, (
        f"WhiteNoiseMiddleware must be immediately after SecurityMiddleware "
        f"(security at index {security_idx}, whitenoise at index {whitenoise_idx})"
    )
