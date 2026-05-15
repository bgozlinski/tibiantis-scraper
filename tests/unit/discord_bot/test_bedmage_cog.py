"""Tests for discord_bot.cogs.bedmages — slash command handlers.

py-cord wraps `@bedmage.command(...)` decorators into `SlashCommand` objects
with a `.callback` attribute holding the underlying coroutine. Tests invoke
`cog.<name>.callback(cog, ctx, **kwargs)` to bypass Discord's slash option
parsing — the parameter values are passed directly.

Service functions are monkey-patched in the cog module's namespace so we
test the cog wiring (response shape, ephemeral flag, message formatting)
in isolation from M5 ORM and the auto-create logic exercised by
test_services.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from discord_bot.cogs.bedmages import BedmageCog


# === /bedmage add ===


@pytest.mark.asyncio
async def test_bedmage_add_command_responds_with_added_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path — created=True → ✅ confirmation + ephemeral.

    Locks the response shape: emoji prefix, character name in backticks,
    ephemeral=True (user-private data per §3.7).
    """
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.author.id = 12345
    mock_ctx.author.name = "alice"
    mock_ctx.respond = AsyncMock()

    fake_watch = MagicMock()
    monkeypatch.setattr(
        "discord_bot.cogs.bedmages.add_bedmage_for_discord_user",
        lambda **kw: (fake_watch, True),
    )

    cog = BedmageCog(bot=MagicMock())
    await cog.add.callback(cog, mock_ctx, character_name="Yhral")

    mock_ctx.respond.assert_awaited_once()
    args, kwargs = mock_ctx.respond.call_args
    assert "✅" in args[0]
    assert "`Yhral`" in args[0]
    assert "Added" in args[0]
    assert kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_bedmage_add_command_responds_with_already_on_list_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Duplicate add — created=False → ℹ️ info, NOT an error.

    §3.2 idempotent UX: wrapper translates M5 `ValueError` into `(existing, False)`
    so the user sees a friendly "already on list" message instead of a traceback.
    """
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.author.id = 12345
    mock_ctx.author.name = "alice"
    mock_ctx.respond = AsyncMock()

    fake_watch = MagicMock()
    monkeypatch.setattr(
        "discord_bot.cogs.bedmages.add_bedmage_for_discord_user",
        lambda **kw: (fake_watch, False),
    )

    cog = BedmageCog(bot=MagicMock())
    await cog.add.callback(cog, mock_ctx, character_name="Yhral")

    args, kwargs = mock_ctx.respond.call_args
    assert "ℹ️" in args[0]
    assert "already on your list" in args[0]
    assert kwargs["ephemeral"] is True


# === /bedmage remove ===


@pytest.mark.asyncio
async def test_bedmage_remove_command_responds_with_removed_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service returned True → ✅ removal confirmation."""
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.author.id = 12345
    mock_ctx.respond = AsyncMock()

    monkeypatch.setattr(
        "discord_bot.cogs.bedmages.remove_bedmage_for_discord_user",
        lambda **kw: True,
    )

    cog = BedmageCog(bot=MagicMock())
    await cog.remove.callback(cog, mock_ctx, character_name="Yhral")

    args, kwargs = mock_ctx.respond.call_args
    assert "✅" in args[0]
    assert "Removed" in args[0]
    assert "`Yhral`" in args[0]
    assert kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_bedmage_remove_command_responds_with_not_on_list_when_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service returned False → ℹ️ info, idempotent ack."""
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.author.id = 12345
    mock_ctx.respond = AsyncMock()

    monkeypatch.setattr(
        "discord_bot.cogs.bedmages.remove_bedmage_for_discord_user",
        lambda **kw: False,
    )

    cog = BedmageCog(bot=MagicMock())
    await cog.remove.callback(cog, mock_ctx, character_name="Unknown")

    args, kwargs = mock_ctx.respond.call_args
    assert "ℹ️" in args[0]
    assert "wasn't on your list" in args[0]
    assert kwargs["ephemeral"] is True


# === /bedmage list ===


@pytest.mark.asyncio
async def test_bedmage_list_command_responds_with_empty_hint_when_no_bedmages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty list — hint pointing user to the `/bedmage add` command.

    Provides discoverability: a new user running `/bedmage list` first sees
    how to populate it, not just a silent empty response.
    """
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.author.id = 12345
    mock_ctx.respond = AsyncMock()

    monkeypatch.setattr(
        "discord_bot.cogs.bedmages.list_bedmages_for_discord_user",
        lambda *args, **kw: [],
    )

    cog = BedmageCog(bot=MagicMock())
    await cog.list.callback(cog, mock_ctx)

    args, kwargs = mock_ctx.respond.call_args
    assert "empty" in args[0].lower()
    assert "/bedmage add" in args[0]
    assert kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_bedmage_list_command_responds_with_populated_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Populated list — character names joined with commas, each in backticks.

    Backtick formatting is significant: Discord renders backticks as inline
    monospace, visually separating character names from prose. Locks the
    contract against accidental string-join refactors.
    """
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.author.id = 12345
    mock_ctx.respond = AsyncMock()

    watch1 = MagicMock()
    watch1.character.name = "Yhral"
    watch2 = MagicMock()
    watch2.character.name = "Nidrak"
    monkeypatch.setattr(
        "discord_bot.cogs.bedmages.list_bedmages_for_discord_user",
        lambda *args, **kw: [watch1, watch2],
    )

    cog = BedmageCog(bot=MagicMock())
    await cog.list.callback(cog, mock_ctx)

    args, kwargs = mock_ctx.respond.call_args
    assert "Your bedmages:" in args[0]
    assert "`Yhral`" in args[0]
    assert "`Nidrak`" in args[0]
    assert kwargs["ephemeral"] is True


# === Cog registration ===


def test_bedmage_cog_has_slash_command_group_at_class_level() -> None:
    """Pułapka A — `SlashCommandGroup` MUST live on the class, not in __init__.

    py-cord introspects class body when `bot.add_cog(...)` runs; groups
    defined inside `__init__` are invisible to the registration walk.
    """
    assert isinstance(BedmageCog.bedmage, discord.SlashCommandGroup)
    assert BedmageCog.bedmage.name == "bedmage"
