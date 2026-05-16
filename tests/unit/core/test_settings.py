"""Tests for settings shape — #163 fix verification.

#163 surfaced an operator footgun: `.env.example` had `POSTGRES_PASSWORD` and the
same password embedded inside `DATABASE_URL`. When operators generated a strong
random `POSTGRES_PASSWORD` during first prod deploy but forgot to also update
the password inside `DATABASE_URL`, postgres initialized its volume with the
new password while Django connected with the placeholder one — silent until
`migrate` exit 1. Cost ~30 min on M9.5-D47.

The fix removes the duplication by constructing `DATABASES["default"]` from
individual `POSTGRES_*` env vars (USER, PASSWORD, DB, HOST, PORT) in
`config/settings/base.py`, deleting `DATABASE_URL` from `.env.example`, and
mirroring the new shape across CI and Docker build-time placeholders (Option A
per M10 spec §3.4 — unified env shape across dev/CI/prod).

These tests pin the contract that no `DATABASE_URL` reference remains in
settings, `.env.example`, or CI workflow, so future contributors can't
re-introduce the duplication.
"""

from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]


def test_settings_base_has_no_database_url_or_env_db_references() -> None:
    """`config/settings/base.py` constructs DATABASES from individual POSTGRES_*
    env vars — no `env.db()` URL-parser call and no `DATABASE_URL` reference
    remains anywhere in the file.

    Pre-fix: `DATABASES = {"default": env.db()}` parses DATABASE_URL implicitly.
    Post-fix: explicit `DATABASES = {"default": {"ENGINE": ..., "NAME": env(...),
    "USER": env(...), ...}}` keyed off `POSTGRES_*` vars, removing the dual
    source-of-truth that bit the M9.5-D47 deploy.
    """
    base_py = (BASE_DIR / "config" / "settings" / "base.py").read_text()
    assert "DATABASE_URL" not in base_py, (
        "DATABASE_URL reference found in config/settings/base.py — #163 "
        "removes it. Construct DATABASES from POSTGRES_USER / "
        "POSTGRES_PASSWORD / POSTGRES_DB / POSTGRES_HOST / POSTGRES_PORT "
        "instead."
    )
    assert "env.db()" not in base_py, (
        "env.db() call found in config/settings/base.py — #163 replaces the "
        "URL parser with explicit POSTGRES_* construction so the password "
        "lives in exactly one env var."
    )


def test_env_example_has_postgres_individual_vars_not_database_url() -> None:
    """`.env.example` documents POSTGRES_HOST and POSTGRES_PORT as
    operator-settable vars, and the duplicated `DATABASE_URL` line is gone.

    Post-fix, the operator footgun (forgetting to update `DATABASE_URL`'s
    password to match `POSTGRES_PASSWORD`) becomes structurally impossible —
    there's only one place to set the password.
    """
    env_example = (BASE_DIR / ".env.example").read_text()
    assert "DATABASE_URL" not in env_example, (
        ".env.example still references DATABASE_URL — #163 removes it. "
        "Operators set POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB / "
        "POSTGRES_HOST / POSTGRES_PORT and settings build the connection."
    )
    for required in (
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
    ):
        assert required in env_example, (
            f".env.example must document {required} so operators know to "
            f"set it explicitly (single source of truth, no URL embedding)"
        )


def test_ci_workflow_uses_postgres_env_vars_not_database_url() -> None:
    """`.github/workflows/ci.yml` test job env block uses individual POSTGRES_*
    vars — symmetric with the new dev + prod env shape.

    The pre-fix workflow set `DATABASE_URL: postgres://postgres:postgres@...`
    inside the `env:` block. Post-fix, the same five POSTGRES_* vars used in
    dev/prod populate the test job env, keeping the env shape uniform across
    all environments. Avoids env-shape drift that #163 is precisely fixing.
    """
    ci_yml = (BASE_DIR / ".github" / "workflows" / "ci.yml").read_text()
    assert "DATABASE_URL" not in ci_yml, (
        ".github/workflows/ci.yml still references DATABASE_URL — #163 swaps "
        "it for individual POSTGRES_* env vars so test/dev/prod share one "
        "env shape"
    )
    for required in (
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
    ):
        assert (
            required in ci_yml
        ), f".github/workflows/ci.yml must set {required} for the test job"
