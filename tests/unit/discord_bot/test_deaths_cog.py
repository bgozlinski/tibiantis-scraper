"""Tests for discord_bot.cogs.deaths — /deaths threshold guarded by perms.

Two-layer guard (order matters): DM rejection BEFORE admin check.
`ctx.author.guild_permissions` is a `Member`-only attribute — in a DM
`ctx.author` is `discord.User` and accessing `guild_permissions` raises
`AttributeError`. The DM check short-circuits before the admin path runs.

Mixed-visibility responses (§3.5 design):
- Rejection (DM, non-admin) → `ephemeral=True` (private feedback to caller)
- Success ack → public (audit trail; other admins see who changed threshold)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from discord_bot.cogs.deaths import DeathsCog


# === Guard layer ===


@pytest.mark.asyncio
async def test_deaths_threshold_rejects_dm_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pułapka A — DM check MUST come before admin check.

    In a DM `ctx.guild is None` and `ctx.author.guild_permissions` would
    `AttributeError`. The DM branch short-circuits with a clear message
    instead of leaking the generic error-handler response from D32.
    """
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.guild = None
    mock_ctx.respond = AsyncMock()

    spy_service = MagicMock()
    monkeypatch.setattr(
        "discord_bot.cogs.deaths.set_death_threshold_for_guild", spy_service
    )

    cog = DeathsCog(bot=MagicMock())
    await cog.threshold.callback(cog, mock_ctx, level=50)

    args, kwargs = mock_ctx.respond.call_args
    assert "❌" in args[0]
    assert "must be used in a server" in args[0]
    assert kwargs["ephemeral"] is True
    spy_service.assert_not_called()


@pytest.mark.asyncio
async def test_deaths_threshold_rejects_non_admin_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§3.5 — only Discord Server Admins can change threshold.

    Permission decided server-side (Discord `Member.guild_permissions`), not
    via Django `User.is_superuser` — avoids pre-linking friction and matches
    standard Discord bot conventions.
    """
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.guild = MagicMock()
    mock_ctx.channel_id = 666
    mock_ctx.author = MagicMock(spec=discord.Member)
    mock_ctx.author.guild_permissions.administrator = False
    mock_ctx.respond = AsyncMock()

    spy_service = MagicMock()
    monkeypatch.setattr(
        "discord_bot.cogs.deaths.set_death_threshold_for_guild", spy_service
    )

    cog = DeathsCog(bot=MagicMock())
    await cog.threshold.callback(cog, mock_ctx, level=50)

    args, kwargs = mock_ctx.respond.call_args
    assert "❌" in args[0]
    assert "Only server admins" in args[0]
    assert kwargs["ephemeral"] is True
    spy_service.assert_not_called()


# === Success path ===


@pytest.mark.asyncio
async def test_deaths_threshold_persists_value_on_admin_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admin path delegates to the D31 service with (guild_id, channel_id, level).

    `channel_id` from `ctx.channel_id` is captured so M8 can use it as the
    default outbound destination for death announcements — admin moves
    threshold-setting to a new channel → that channel becomes the target.
    """
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.guild = MagicMock()
    mock_ctx.guild.id = 555
    mock_ctx.channel_id = 666
    mock_ctx.author = MagicMock(spec=discord.Member)
    mock_ctx.author.guild_permissions.administrator = True
    mock_ctx.respond = AsyncMock()

    spy_service = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(
        "discord_bot.cogs.deaths.set_death_threshold_for_guild", spy_service
    )

    cog = DeathsCog(bot=MagicMock())
    await cog.threshold.callback(cog, mock_ctx, level=50)

    spy_service.assert_called_once_with(guild_id=555, channel_id=666, threshold=50)


@pytest.mark.asyncio
async def test_deaths_threshold_responds_with_public_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§3.5 design — success ack is PUBLIC, not ephemeral.

    Other admins on the server see who changed the threshold (audit trail).
    Locks the contract against accidental `ephemeral=True` addition during
    refactor — would silently break the visibility intent.
    """
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.guild = MagicMock()
    mock_ctx.guild.id = 555
    mock_ctx.channel_id = 666
    mock_ctx.author = MagicMock(spec=discord.Member)
    mock_ctx.author.guild_permissions.administrator = True
    mock_ctx.respond = AsyncMock()

    monkeypatch.setattr(
        "discord_bot.cogs.deaths.set_death_threshold_for_guild",
        lambda **kw: MagicMock(),
    )

    cog = DeathsCog(bot=MagicMock())
    await cog.threshold.callback(cog, mock_ctx, level=50)

    _, kwargs = mock_ctx.respond.call_args
    assert kwargs.get("ephemeral", False) is False


@pytest.mark.asyncio
async def test_deaths_threshold_message_format_includes_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Success message embeds the level value with bold markdown.

    Locks the response shape: 🪦 emoji + "level **N**" formatting. Discord
    renders `**X**` as bold; pinning this guards against accidental
    formatting drift during message-string refactors.
    """
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.guild = MagicMock()
    mock_ctx.guild.id = 555
    mock_ctx.channel_id = 666
    mock_ctx.author = MagicMock(spec=discord.Member)
    mock_ctx.author.guild_permissions.administrator = True
    mock_ctx.respond = AsyncMock()

    monkeypatch.setattr(
        "discord_bot.cogs.deaths.set_death_threshold_for_guild",
        lambda **kw: MagicMock(),
    )

    cog = DeathsCog(bot=MagicMock())
    await cog.threshold.callback(cog, mock_ctx, level=42)

    args, _ = mock_ctx.respond.call_args
    assert "🪦" in args[0]
    assert "level **42**" in args[0]


# === Cog registration ===


def test_deaths_cog_has_slash_command_group_at_class_level() -> None:
    """Pułapka A (M7 cog idiom) — `SlashCommandGroup` MUST live on the class.

    py-cord introspects class body at `bot.add_cog(...)` time; groups
    declared inside `__init__` are invisible to the registration walk.
    """
    assert isinstance(DeathsCog.deaths, discord.SlashCommandGroup)
    assert DeathsCog.deaths.name == "deaths"
