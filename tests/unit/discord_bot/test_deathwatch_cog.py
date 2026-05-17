"""Tests for discord_bot.cogs.deathwatch — 4 slash commands (DW-7).

Mirror of tests/unit/discord_bot/test_deaths_cog.py for the admin-only
`/deathwatch channel` command + bedmage-style add/remove/list coverage.

`monkeypatch.setattr` on the cog's import-site bindings, NOT on the source
modules — cog imports the helpers at module load, so patching the source
module after cog import is a no-op.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from discord_bot.cogs.deathwatch import DeathWatchCog


# ══════════════════════════════════════════════════════════════════════════════
# /deathwatch add
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_add_command_creates_watch_and_responds_ephemerally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.author.id = 12345
    mock_ctx.author.name = "alice"
    mock_ctx.respond = AsyncMock()

    spy = MagicMock(return_value=(MagicMock(), True))
    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.add_deathwatch_for_discord_user", spy
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.add.callback(cog, mock_ctx, "Yhral")

    spy.assert_called_once_with(
        discord_id=12345, discord_username="alice", character_name="Yhral"
    )
    args, kwargs = mock_ctx.respond.call_args
    assert "👀" in args[0]
    assert "Yhral" in args[0]
    assert kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_add_command_idempotent_ack_when_already_on_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """created=False from service → friendly 'already on list' message,
    NOT an error. Same pattern as bedmage `add` (M7)."""
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.author.id = 12345
    mock_ctx.author.name = "alice"
    mock_ctx.respond = AsyncMock()

    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.add_deathwatch_for_discord_user",
        MagicMock(return_value=(MagicMock(), False)),
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.add.callback(cog, mock_ctx, "Yhral")

    args, _ = mock_ctx.respond.call_args
    assert "ℹ️" in args[0]
    assert "already" in args[0].lower()


@pytest.mark.asyncio
async def test_add_command_surfaces_cap_exceeded_without_stack_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ValueError from cap check → ephemeral error, NO traceback (CLAUDE.md §8)."""
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.author.id = 12345
    mock_ctx.author.name = "alice"
    mock_ctx.respond = AsyncMock()

    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.add_deathwatch_for_discord_user",
        MagicMock(
            side_effect=ValueError(
                "DeathWatch cap of 20 unique characters exceeded (would be 21)"
            )
        ),
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.add.callback(cog, mock_ctx, "Yhral")

    args, kwargs = mock_ctx.respond.call_args
    assert "❌" in args[0]
    assert "cap" in args[0].lower()
    assert "Traceback" not in args[0]
    assert kwargs["ephemeral"] is True


# ══════════════════════════════════════════════════════════════════════════════
# /deathwatch remove
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_remove_command_acknowledges_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.author.id = 12345
    mock_ctx.respond = AsyncMock()

    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.remove_deathwatch_for_discord_user",
        MagicMock(return_value=True),
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.remove.callback(cog, mock_ctx, "Yhral")

    args, kwargs = mock_ctx.respond.call_args
    assert "🗑️" in args[0]
    assert kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_remove_command_idempotent_when_not_on_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.author.id = 12345
    mock_ctx.respond = AsyncMock()

    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.remove_deathwatch_for_discord_user",
        MagicMock(return_value=False),
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.remove.callback(cog, mock_ctx, "Yhral")

    args, _ = mock_ctx.respond.call_args
    assert "ℹ️" in args[0]


# ══════════════════════════════════════════════════════════════════════════════
# /deathwatch list
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_list_command_empty_state_when_no_watches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No watches anywhere in the system → hint to add (M12 follow-up)."""
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.respond = AsyncMock()

    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.list_all_deathwatches",
        MagicMock(return_value=[]),
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.list.callback(cog, mock_ctx)

    args, kwargs = mock_ctx.respond.call_args
    assert "No active deathwatches" in args[0]
    assert "/deathwatch add" in args[0]
    assert kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_list_command_renders_all_users_watches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public list visibility — every user's watches included (spec §3.4)."""
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.respond = AsyncMock()

    w1 = MagicMock()
    w1.character.name = "Yhral"
    w1.user.discord_id = "111"
    w2 = MagicMock()
    w2.character.name = "Bubble"
    w2.user.discord_id = "222"
    w3 = MagicMock()
    w3.character.name = "Eternal oblivion"
    w3.user.discord_id = "111"  # alice again

    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.list_all_deathwatches",
        MagicMock(return_value=[w1, w2, w3]),
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.list.callback(cog, mock_ctx)

    args, kwargs = mock_ctx.respond.call_args
    text = args[0]
    assert "Yhral" in text
    assert "Bubble" in text
    assert "Eternal oblivion" in text
    assert kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_list_command_shows_added_by_discord_mention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each entry includes `<@discord_id>` mention syntax (spec §3.2)."""
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.respond = AsyncMock()

    w = MagicMock()
    w.character.name = "Yhral"
    w.user.discord_id = "99999"

    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.list_all_deathwatches",
        MagicMock(return_value=[w]),
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.list.callback(cog, mock_ctx)

    args, _ = mock_ctx.respond.call_args
    assert "<@99999>" in args[0]


@pytest.mark.asyncio
async def test_list_command_uses_allowed_mentions_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """20 mentions w outputie nie mogą pingować users (spec §3.3)."""
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.respond = AsyncMock()

    w = MagicMock()
    w.character.name = "Yhral"
    w.user.discord_id = "1"
    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.list_all_deathwatches",
        MagicMock(return_value=[w]),
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.list.callback(cog, mock_ctx)

    _, kwargs = mock_ctx.respond.call_args
    am = kwargs["allowed_mentions"]
    # AllowedMentions.none() = no everyone/users/roles pings
    assert am.everyone is False
    assert am.users is False
    assert am.roles is False


@pytest.mark.asyncio
async def test_list_command_shows_count_over_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cap indicator `(N/20)` w outputie (spec §3.5)."""
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.respond = AsyncMock()

    watches = []
    for i in range(3):
        w = MagicMock()
        w.character.name = f"Char{i}"
        w.user.discord_id = str(i)
        watches.append(w)

    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.list_all_deathwatches",
        MagicMock(return_value=watches),
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.list.callback(cog, mock_ctx)

    args, _ = mock_ctx.respond.call_args
    assert "3/20" in args[0]


# ══════════════════════════════════════════════════════════════════════════════
# /deathwatch channel — guard layer (mirror /deaths threshold)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_channel_command_rejects_dm_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DM check MUST come before admin check — guild_permissions is Member-only
    and accessing it on a discord.User (DM) raises AttributeError."""
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.guild = None
    mock_ctx.respond = AsyncMock()

    spy = MagicMock()
    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.set_deathwatch_channel_for_guild", spy
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.channel.callback(cog, mock_ctx)

    args, kwargs = mock_ctx.respond.call_args
    assert "❌" in args[0]
    assert "must be used in a server" in args[0]
    assert kwargs["ephemeral"] is True
    spy.assert_not_called()


@pytest.mark.asyncio
async def test_channel_command_rejects_non_admin_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.guild = MagicMock()
    mock_ctx.channel_id = 666
    mock_ctx.author = MagicMock(spec=discord.Member)
    mock_ctx.author.guild_permissions.administrator = False
    mock_ctx.respond = AsyncMock()

    spy = MagicMock()
    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.set_deathwatch_channel_for_guild", spy
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.channel.callback(cog, mock_ctx)

    args, kwargs = mock_ctx.respond.call_args
    assert "❌" in args[0]
    assert "Only server admins" in args[0]
    assert kwargs["ephemeral"] is True
    spy.assert_not_called()


@pytest.mark.asyncio
async def test_channel_command_persists_on_admin_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.guild = MagicMock()
    mock_ctx.guild.id = 555
    mock_ctx.channel_id = 666
    mock_ctx.author = MagicMock(spec=discord.Member)
    mock_ctx.author.guild_permissions.administrator = True
    mock_ctx.respond = AsyncMock()

    spy = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.set_deathwatch_channel_for_guild", spy
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.channel.callback(cog, mock_ctx)

    spy.assert_called_once_with(guild_id=555, channel_id=666)


@pytest.mark.asyncio
async def test_channel_command_responds_with_public_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirror /deaths threshold — public ack so other admins see the change."""
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.guild = MagicMock()
    mock_ctx.guild.id = 555
    mock_ctx.channel_id = 666
    mock_ctx.author = MagicMock(spec=discord.Member)
    mock_ctx.author.guild_permissions.administrator = True
    mock_ctx.respond = AsyncMock()

    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.set_deathwatch_channel_for_guild",
        lambda **kw: MagicMock(),
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.channel.callback(cog, mock_ctx)

    _, kwargs = mock_ctx.respond.call_args
    assert kwargs.get("ephemeral", False) is False


# ══════════════════════════════════════════════════════════════════════════════
# Cog structural sanity (M7 idiom)
# ══════════════════════════════════════════════════════════════════════════════


def test_deathwatch_cog_has_slash_command_group_at_class_level() -> None:
    """py-cord introspects class body at bot.add_cog time — group MUST be
    a class attribute, not declared inside __init__."""
    assert isinstance(DeathWatchCog.deathwatch, discord.SlashCommandGroup)
    assert DeathWatchCog.deathwatch.name == "deathwatch"
