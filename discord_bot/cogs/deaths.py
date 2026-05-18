# NOTE: NO `from __future__ import annotations` here — py-cord introspects
# parameter annotations at slash command invocation time and requires them
# as runtime objects, not PEP 563 strings.
from asgiref.sync import sync_to_async
import discord
from discord.ext import commands

from discord_bot.services import set_death_threshold_for_guild


class DeathsCog(commands.Cog):
    """Admin-side death-monitor configuration commands (``/deaths threshold``)."""

    deaths = discord.SlashCommandGroup("deaths", "Death monitor configuration")

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @deaths.command(
        name="threshold",
        description="Set death notification level threshold (server admin only)",
    )
    async def threshold(
        self,
        ctx: discord.ApplicationContext,
        level: discord.Option(
            int, "Minimum level to notify", min_value=1, max_value=999
        ),
    ) -> None:
        if ctx.guild is None:
            await ctx.respond(
                "❌ This command must be used in a server.", ephemeral=True
            )
            return

        # Narrow types — post DM-check guarantees:
        assert isinstance(ctx.author, discord.Member)
        assert ctx.channel_id is not None

        if not ctx.author.guild_permissions.administrator:
            await ctx.respond(
                "❌ Only server admins can change the death threshold.",
                ephemeral=True,
            )
            return

        await sync_to_async(set_death_threshold_for_guild)(
            guild_id=ctx.guild.id,
            channel_id=ctx.channel_id,
            threshold=level,
        )
        # Public ack — other admins see the change
        await ctx.respond(f"🪦 Death notification threshold set to level **{level}**.")
