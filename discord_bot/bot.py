from __future__ import annotations

import logging

import discord
from django.conf import settings

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
bot = discord.Bot(intents=intents)  # type: ignore[no-untyped-call]


@bot.event
async def on_ready() -> None:
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
    logger.exception("Slash command error in /%s: %s", ctx.command, error)
    msg = "❌ Something went wrong. The admins have been notified."
    if ctx.response.is_done():
        await ctx.followup.send(msg, ephemeral=True)
    else:
        await ctx.respond(msg, ephemeral=True)


def setup_bot() -> discord.Bot:
    """Add cogs and return configured bot. D32: no cogs yet (D33+D34 add them)."""
    from discord_bot.cogs.bedmages import BedmageCog

    bot.add_cog(BedmageCog(bot))
    return bot
