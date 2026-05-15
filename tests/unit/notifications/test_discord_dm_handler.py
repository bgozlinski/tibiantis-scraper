"""Tests for DiscordDMHandler — bedmage Discord DM delivery via DiscordRESTClient."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from apps.notifications.handlers import DiscordDMHandler


@pytest.fixture
def watch() -> MagicMock:
    """Minimal BedmageWatch-shaped mock — no DB hit needed for handler unit tests.

    Sets the four attributes the handler actually reads:
    `user.discord_id`, `user.pk`, `user.username`, `character.name`,
    `character.last_login`. Tests override individual fields when exercising
    edge cases (e.g. non-numeric discord_id).
    """
    mock = MagicMock()
    mock.user.discord_id = "12345"
    mock.user.pk = 42
    mock.user.username = "alice"
    mock.character.name = "Yhral"
    mock.character.last_login = timezone.now().replace(
        year=2026, month=5, day=15, hour=10, minute=0, second=0, microsecond=0
    )
    return mock


@pytest.fixture
def mock_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch DiscordRESTClient at its source module.

    Handler does a lazy `from apps.notifications.discord_client import
    DiscordRESTClient` inside `notify()` (defers httpx loading until first
    DM and keeps the mypy pre-commit hook happy without httpx in its venv).
    The lazy import re-resolves the name from `discord_client` on every call,
    so patching the source module's attribute is enough — no need to chase
    the handler's bound name.
    """
    client = MagicMock()
    client.send_dm.return_value = True
    monkeypatch.setattr(
        "apps.notifications.discord_client.DiscordRESTClient", lambda: client
    )
    return client


def test_handler_notify_calls_send_dm_with_int_discord_id_and_rendered_content(
    watch: MagicMock, mock_client: MagicMock
) -> None:
    """Happy path: handler casts discord_id str→int, renders message, calls send_dm.

    Pins three contract points at once:
    1. `int(watch.user.discord_id)` cast — `DiscordRESTClient.send_dm` takes int
    2. Rendered content (not raw watch) passed as second arg
    3. Exactly one DM per notify() call (no duplicates from accidental loops)
    """
    DiscordDMHandler().notify(watch)

    mock_client.send_dm.assert_called_once()
    user_id_arg, content_arg = mock_client.send_dm.call_args.args
    assert user_id_arg == 12345
    assert isinstance(user_id_arg, int)
    assert "Yhral" in content_arg


def test_handler_renders_message_with_character_name_regen_minutes_and_last_login(
    watch: MagicMock, mock_client: MagicMock, settings: pytest.FixtureRequest
) -> None:
    """Message template includes: 🛏️ emoji, character name (bolded), regen minutes
    from settings (NOT hardcoded), and last_login formatted as `YYYY-MM-DD HH:MM UTC`.

    Pułapka C from #129 — using `settings.BEDMAGE_REGEN_MINUTES` (current value,
    not hardcoded "100"). Test overrides the setting and verifies the rendered
    string reflects the override, locking the dynamic-read contract.
    """
    settings.BEDMAGE_REGEN_MINUTES = 90  # type: ignore[attr-defined]

    DiscordDMHandler().notify(watch)

    content = mock_client.send_dm.call_args.args[1]
    assert "🛏️" in content
    assert "**Yhral**" in content
    assert "90" in content  # not 100 — proves the setting is read dynamically
    assert "2026-05-15 10:00 UTC" in content


def test_handler_logs_error_and_skips_send_when_discord_id_is_none(
    watch: MagicMock,
    mock_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Pułapka A: User with `discord_id=None` (Django admin manual create) must
    NOT crash the handler. Implementation coerces None to "" via `or ""` so
    `int("")` raises ValueError, which the handler catches → logs ERROR with
    user pk → returns BEFORE attempting send_dm. No garbage DM, no exception
    leak to M5 `check_bedmage_watches_for_character` (Pułapka G — leaked
    exception would skip the whole batch for the character).
    """
    watch.user.discord_id = None

    with caplog.at_level(logging.ERROR, logger="apps.notifications.handlers"):
        DiscordDMHandler().notify(watch)

    mock_client.send_dm.assert_not_called()
    assert any(
        "Invalid discord_id" in r.getMessage() and "pk=42" in r.getMessage()
        for r in caplog.records
    )


def test_handler_swallows_send_failure_with_warning_log(
    watch: MagicMock,
    mock_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Pułapka G: `send_dm` returning False (403/404/5xx-after-retry) must NOT
    raise. Handler logs WARNING with user + character context and returns
    normally so M5 service can mark `last_notified_login` and avoid a retry
    storm on every subsequent scrape cycle.
    """
    mock_client.send_dm.return_value = False

    with caplog.at_level(logging.WARNING, logger="apps.notifications.handlers"):
        DiscordDMHandler().notify(watch)  # must not raise

    assert any(
        "Bedmage DM failed" in r.getMessage()
        and "user=alice" in r.getMessage()
        and "character=Yhral" in r.getMessage()
        for r in caplog.records
    )
