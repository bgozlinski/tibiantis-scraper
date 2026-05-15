"""Tests for `manage.py run_discord_bot` management command.

`bot.run(token)` is sync and blocks forever — tests MUST mock it or pytest
hangs the whole CI run. Monkeypatch the module-level bot global; the command
imports `setup_bot` which returns that global, so the mock propagates.
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock

import pytest
from django.core.management import call_command
from django.test import override_settings


def test_run_discord_bot_writes_stderr_and_exits_when_token_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty TOKEN must NOT raise — clean stderr message + no `bot.run` call.

    Pułapka G: management command exits 0 (Django default) with stderr hint
    so a missing-token misconfig doesn't dump a Python traceback at the user.
    """
    fake_bot = MagicMock()
    monkeypatch.setattr("discord_bot.bot.bot", fake_bot)
    stderr = StringIO()

    with override_settings(DISCORD_BOT_TOKEN=""):
        call_command("run_discord_bot", stderr=stderr)

    assert "DISCORD_BOT_TOKEN not set" in stderr.getvalue()
    fake_bot.run.assert_not_called()


def test_run_discord_bot_calls_bot_run_when_token_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid TOKEN → command delegates to `bot.run(token)` (the blocking call).

    Mock `bot.run` so the test doesn't hang on a real gateway connection.
    """
    fake_bot = MagicMock()
    monkeypatch.setattr("discord_bot.bot.bot", fake_bot)

    with override_settings(DISCORD_BOT_TOKEN="fake-token"):
        call_command("run_discord_bot")

    fake_bot.run.assert_called_once_with("fake-token")
