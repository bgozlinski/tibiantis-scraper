"""Tests for discord_bot.bot — setup_bot factory + on_ready sync routing.

`on_ready` is registered as a `@bot.event` decorator on the module-level bot
instance. Module functions look up free names via __globals__ at call time,
so monkeypatching `discord_bot.bot.bot` to a MagicMock rebinds what
`on_ready` sees — no need to patch the property descriptor on `discord.Bot`
to inject a mock `bot.user`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from django.test import override_settings

from discord_bot.bot import on_ready, setup_bot


def test_setup_bot_returns_a_discord_bot_instance() -> None:
    """D32 contract: factory hands back a `discord.Bot` ready for `.run(token)`.

    D33+D34 will extend `setup_bot()` to `bot.add_cog(...)` before return —
    test guards the return type, not the cog list.
    """
    assert isinstance(setup_bot(), discord.Bot)


@pytest.mark.asyncio
async def test_on_ready_syncs_per_guild_when_dev_guild_id_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dev workflow (§3.6) — `DISCORD_DEV_GUILD_ID>0` triggers per-guild sync.

    Per-guild sync propagates instantly (Discord cache scope = guild); global
    sync can take up to 1h. The env var toggle keeps dev iteration fast
    without a separate `sync_discord_commands` management command.
    """
    fake_bot = MagicMock()
    fake_bot.user = MagicMock(id=999)
    fake_bot.sync_commands = AsyncMock()
    monkeypatch.setattr("discord_bot.bot.bot", fake_bot)

    with override_settings(DISCORD_DEV_GUILD_ID=12345):
        await on_ready()

    fake_bot.sync_commands.assert_awaited_once_with(guild_ids=[12345])


@pytest.mark.asyncio
async def test_on_ready_syncs_globally_when_dev_guild_id_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prod path — `DISCORD_DEV_GUILD_ID=0` (default) → global sync, no kwargs.

    `env.int("DISCORD_DEV_GUILD_ID", default=0)` returns `0` for empty/unset
    env var, which is falsy → `else` branch in `on_ready` calls
    `sync_commands()` without `guild_ids` kwarg.
    """
    fake_bot = MagicMock()
    fake_bot.user = MagicMock(id=999)
    fake_bot.sync_commands = AsyncMock()
    monkeypatch.setattr("discord_bot.bot.bot", fake_bot)

    with override_settings(DISCORD_DEV_GUILD_ID=0):
        await on_ready()

    fake_bot.sync_commands.assert_awaited_once_with()
