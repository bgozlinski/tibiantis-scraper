"""Discord bot entry point.

The bot exposes a single module-level :class:`discord.Bot` singleton so cog
registration in tests and in the live process happen against the same
instance. The actual loop is started by the ``run_discord_bot`` management
command.
"""

from __future__ import annotations

import logging

import discord
from django.conf import settings

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
bot = discord.Bot(intents=intents)  # type: ignore[no-untyped-call]


@bot.event
async def on_ready() -> None:
    """Sync slash commands once the gateway connection is established.

    When ``DISCORD_DEV_GUILD_ID`` is set the sync is scoped to that one
    guild (instant), otherwise it goes global (Discord-side propagation
    can take up to an hour).
    """
    assert bot.user is not None  # on_ready fires only after login
    logger.info("Bot logged in as %s (id=%s)", bot.user, bot.user.id)
    if settings.DISCORD_DEV_GUILD_ID:
        await bot.sync_commands(guild_ids=[settings.DISCORD_DEV_GUILD_ID])
        logger.info("Synced commands to dev guild %s", settings.DISCORD_DEV_GUILD_ID)
    else:
        await bot.sync_commands()
        logger.info("Synced commands globally")


@bot.event
async def on_application_command_error(
    ctx: discord.ApplicationContext, error: discord.DiscordException
) -> None:
    """Global slash-command error handler — never leaks a stack trace to chat."""
    logger.exception("Slash command error in /%s: %s", ctx.command, error)
    msg = "❌ Something went wrong. The admins have been notified."
    if ctx.response.is_done():
        await ctx.followup.send(msg, ephemeral=True)
    else:
        await ctx.respond(msg, ephemeral=True)


def setup_bot() -> discord.Bot:
    """Register cogs and return configured bot. Idempotent — safe to call
    multiple times (tests share the module-level bot singleton)."""
    from discord_bot.cogs.bedmages import BedmageCog
    from discord_bot.cogs.deaths import DeathsCog
    from discord_bot.cogs.deathwatch import DeathWatchCog

    if "BedmageCog" not in bot.cogs:
        bot.add_cog(BedmageCog(bot))
    if "DeathsCog" not in bot.cogs:
        bot.add_cog(DeathsCog(bot))
    if "DeathWatchCog" not in bot.cogs:
        bot.add_cog(DeathWatchCog(bot))

    return bot
