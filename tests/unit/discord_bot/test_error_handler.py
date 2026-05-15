"""Tests for global `on_application_command_error` listener.

CLAUDE.md §8: "Nigdy nie pokazuj stack trace na Discordzie." The handler
swallows exceptions from any cog, logs via `logger.exception` (routed to
Mongo by M6 LOGGING dispatcher + §3.8 `"discord_bot"` named logger), and
responds with a generic ephemeral message — using `followup.send` when the
interaction already responded (§6.1, py-cord `InteractionResponded` defense).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from discord_bot.bot import on_application_command_error


GENERIC_MSG = "❌ Something went wrong. The admins have been notified."


@pytest.mark.asyncio
async def test_error_handler_responds_with_ephemeral_generic_when_response_not_done() -> (
    None
):
    """Default path — interaction not yet responded → `ctx.respond(...)`.

    Calling `ctx.respond` a second time on an already-responded interaction
    raises `discord.errors.InteractionResponded`; the `is_done()` check
    routes around it.
    """
    mock_ctx = MagicMock()
    mock_ctx.command = "bedmage_add"
    mock_ctx.response.is_done.return_value = False
    mock_ctx.respond = AsyncMock()
    error = RuntimeError("boom")

    await on_application_command_error(mock_ctx, error)

    mock_ctx.respond.assert_awaited_once_with(GENERIC_MSG, ephemeral=True)
    mock_ctx.followup.send.assert_not_called()


@pytest.mark.asyncio
async def test_error_handler_uses_followup_when_response_already_done() -> None:
    """Late-error path — cog deferred or already responded → `followup.send`.

    Common scenario: cog called `ctx.defer()` then service call raised. Discord
    interaction lifecycle requires `followup.send` for any further messages.
    """
    mock_ctx = MagicMock()
    mock_ctx.command = "deaths_threshold"
    mock_ctx.response.is_done.return_value = True
    mock_ctx.followup.send = AsyncMock()
    error = RuntimeError("boom")

    await on_application_command_error(mock_ctx, error)

    mock_ctx.followup.send.assert_awaited_once_with(GENERIC_MSG, ephemeral=True)
    mock_ctx.respond.assert_not_called()


@pytest.mark.asyncio
async def test_error_handler_logs_exception_with_command_and_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`logger.exception(...)` routes to Mongo via M6 dispatcher + §3.8 logger.

    `propagate: True` on the `"discord_bot"` logger preserves pytest caplog
    capture (M6 retro lekcja #2). Without this, caplog stays silent and
    Mongo observability for bot errors regresses.
    """
    import logging

    mock_ctx = MagicMock()
    mock_ctx.command = "bedmage_add"
    mock_ctx.response.is_done.return_value = False
    mock_ctx.respond = AsyncMock()
    error = RuntimeError("boom")

    with caplog.at_level(logging.ERROR, logger="discord_bot.bot"):
        await on_application_command_error(mock_ctx, error)

    assert any(
        "bedmage_add" in record.getMessage() and record.levelname == "ERROR"
        for record in caplog.records
    )
