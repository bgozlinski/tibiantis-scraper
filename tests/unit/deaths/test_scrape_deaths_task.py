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

    assert "yielded" in result and "duplicates" in result and "returncode" in result
    assert result["yielded"] == 50
    assert result["duplicates"] == 50
    assert result["returncode"] == 1
    task_warnings = [r for r in caplog.records if r.name == "apps.deaths.tasks"]
    assert any("returncode=1" in r.message for r in task_warnings)


@mock.patch("apps.deaths.tasks.announce_unannounced_deaths")
@mock.patch("apps.deaths.tasks.subprocess.run")
def test_scrape_deaths_calls_announce_after_subprocess_and_merges_summary(
    mock_run: mock.MagicMock,
    mock_announce: mock.MagicMock,
) -> None:
    """M8-D39 wiring: after scrape subprocess completes, the task calls
    `announce_unannounced_deaths()` and merges its summary into the task
    return value via `dict.update()`.

    Pins two contract points: (1) order — announce runs AFTER subprocess parse
    so it only sees events the current scrape persisted, (2) shape — task
    return is the union of scrape keys (yielded/duplicates/returncode) and
    announce keys (events_announced/events_skipped/fail_count), backward
    compatible with M4 task consumers (Pułapka F from #131).
    """
    mock_run.return_value = _completed(
        stdout='{"yielded": 5, "duplicates": 0}', returncode=0
    )
    mock_announce.return_value = {
        "events_announced": 2,
        "events_skipped": 1,
        "fail_count": 0,
    }

    result = scrape_deaths.apply().get()

    assert result == {
        "yielded": 5,
        "duplicates": 0,
        "returncode": 0,
        "events_announced": 2,
        "events_skipped": 1,
        "fail_count": 0,
    }
    mock_announce.assert_called_once_with()


@mock.patch("apps.deaths.tasks.announce_unannounced_deaths")
@mock.patch("apps.deaths.tasks.subprocess.run")
def test_scrape_deaths_swallows_announce_exception_and_returns_scrape_summary(
    mock_run: mock.MagicMock,
    mock_announce: mock.MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Defensive try/except around announce in tasks.py: if the announce phase
    raises (DB connection lost, unexpected handler bug), the task still
    returns the scrape summary so Celery doesn't mark the task as failed and
    Beat keeps firing the next cycle.

    Locks Pułapka F's symmetric concern — announce failure must NOT tank
    the scrape return value, and a logger.exception entry must record it.
    """
    mock_run.return_value = _completed(
        stdout='{"yielded": 3, "duplicates": 1}', returncode=0
    )
    mock_announce.side_effect = RuntimeError("DB down")

    with caplog.at_level(logging.ERROR, logger="apps.deaths.tasks"):
        result = scrape_deaths.apply().get()

    # scrape summary preserved; announce keys absent (update() never ran)
    assert result == {"yielded": 3, "duplicates": 1, "returncode": 0}
    assert any(
        "announce_unannounced_deaths raised" in r.message
        for r in caplog.records
        if r.name == "apps.deaths.tasks"
    )
