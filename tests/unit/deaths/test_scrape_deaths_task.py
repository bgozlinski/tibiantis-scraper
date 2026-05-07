"""Tests for apps.deaths.tasks.scrape_deaths — subprocess mocked, no live HTTP."""

from __future__ import annotations

import logging
import subprocess
from unittest import mock

import pytest
from celery.exceptions import Retry
from pytest_django.fixtures import SettingsWrapper

from apps.deaths.tasks import scrape_deaths


def _completed(
    *, stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    """Controllable CompletedProcess for subprocess.run mocks."""
    return subprocess.CompletedProcess(
        args=["python", "manage.py", "scrape_deaths"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


@mock.patch("apps.deaths.tasks.subprocess.run")
def test_returns_parsed_json_summary_with_returncode_added(
    mock_run: mock.MagicMock,
) -> None:
    """Happy path — valid JSON stdout, returncode 0. Task mutates parsed dict
    by injecting returncode key so downstream consumers (Discord notifier in
    M5) get a single typed shape regardless of subprocess outcome.
    """
    mock_run.return_value = _completed(
        stdout='{"yielded": 50, "duplicates": 0}', returncode=0
    )

    result = scrape_deaths.apply().get()

    assert result == {"yielded": 50, "duplicates": 0, "returncode": 0}
    mock_run.assert_called_once()


@mock.patch("apps.deaths.tasks.subprocess.run")
def test_subprocess_timeout_triggers_retry(
    mock_run: mock.MagicMock, settings: SettingsWrapper
) -> None:
    """TimeoutExpired → task calls self.retry, which raises celery.exceptions.Retry.

    Eager mode + propagates surfaces the Retry as a raw exception; in a real
    worker pool this would schedule a delayed re-execution (countdown=60s).
    Mock side_effect = TimeoutExpired only on first call, not on retries —
    we just verify the retry path engages, not the full retry storm.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True

    mock_run.side_effect = subprocess.TimeoutExpired(
        cmd=["python", "manage.py", "scrape_deaths"], timeout=120
    )

    with pytest.raises(Retry):
        scrape_deaths.apply().get()

    mock_run.assert_called_once()


@mock.patch("apps.deaths.tasks.subprocess.run")
def test_json_decode_error_returns_sentinel_dict(
    mock_run: mock.MagicMock,
) -> None:
    """Stdout that isn't valid JSON → sentinel return ``{-1, -1, returncode}``.

    Why a sentinel and not raise: subprocess crashing before printing JSON
    (segfault, scrapy bootstrap failure, etc.) shouldn't tank the Celery
    result backend with an exception. The sentinel keeps the shape stable
    so observability dashboards / D22 GraphQL still parse cleanly.
    """
    mock_run.return_value = _completed(stdout="<scrapy traceback>", returncode=0)

    result = scrape_deaths.apply().get()

    assert result == {"yielded": -1, "duplicates": -1, "returncode": 0}


@mock.patch("apps.deaths.tasks.subprocess.run")
def test_returncode_nonzero_logs_warning_and_returns_summary(
    mock_run: mock.MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Non-zero returncode + valid JSON: log warning, still return parsed summary.

    Task is observability-first — Beat fires next run regardless of one
    bad invocation. Filter to ``apps.deaths.tasks`` logger only; Django's
    db/migration loggers are noise here.
    """
    mock_run.return_value = _completed(
        stdout='{"yielded": 50, "duplicates": 50}',
        returncode=1,
        stderr="connection refused",
    )

    with caplog.at_level(logging.WARNING, logger="apps.deaths.tasks"):
        result = scrape_deaths.apply().get()

    assert result == {"yielded": 50, "duplicates": 50, "returncode": 1}
    task_warnings = [r for r in caplog.records if r.name == "apps.deaths.tasks"]
    assert any("returncode=1" in r.message for r in task_warnings)
