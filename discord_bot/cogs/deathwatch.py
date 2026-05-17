# NOTE: NO `from __future__ import annotations` here — py-cord introspects
# parameter annotations at slash command invocation time and requires them
# as runtime objects, not PEP 563 strings.
from asgiref.sync import sync_to_async
import discord
from discord.ext import commands

from apps.deathwatch.services import set_deathwatch_channel_for_guild
from discord_bot.services import (
    add_deathwatch_for_discord_user,
    list_deathwatches_for_discord_user,
    remove_deathwatch_for_discord_user,
)


class DeathWatchCog(commands.Cog):
    """Slash commands for the per-character death blacklist (DW-7).

    `/deathwatch add|remove|list` — user-scoped; ephemeral replies.
    `/deathwatch channel` — guild-admin only; public ack (audit trail).
    """

    deathwatch = discord.SlashCommandGroup(
        "deathwatch",
        "Watch specific characters for new deaths",
    )

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @deathwatch.command(name="add", description="Watch a character for new deaths")
    async def add(
        self,
        ctx: discord.ApplicationContext,
        character_name: discord.Option(str, "Tibiantis character name", max_length=64),
    ) -> None:
        try:
            _, created = await sync_to_async(add_deathwatch_for_discord_user)(
                discord_id=ctx.author.id,
                discord_username=ctx.author.name,
                character_name=character_name,
            )
        except ValueError as exc:
            # Cap exceeded surfaces here. Render the message verbatim — the
            # service-layer string already explains the limit clearly. No
            # stack trace leak (CLAUDE.md §8).
            await ctx.respond(f"❌ {exc}", ephemeral=True)
            return

        msg = (
            f"👀 Now watching `{character_name}` for new deaths."
            if created
            else f"ℹ️ `{character_name}` was already on your deathwatch list."
        )
        await ctx.respond(msg, ephemeral=True)

    @deathwatch.command(name="remove", description="Stop watching a character")
    async def remove(
        self,
        ctx: discord.ApplicationContext,
        character_name: discord.Option(str, "Tibiantis character name", max_length=64),
    ) -> None:
        removed = await sync_to_async(remove_deathwatch_for_discord_user)(
            discord_id=ctx.author.id,
            character_name=character_name,
        )
        msg = (
            f"🗑️ Stopped watching `{character_name}`."
            if removed
            else f"ℹ️ `{character_name}` wasn't on your deathwatch list."
        )
        await ctx.respond(msg, ephemeral=True)

    @deathwatch.command(name="list", description="Show your deathwatch list")
    async def list(self, ctx: discord.ApplicationContext) -> None:
        watches = await sync_to_async(list_deathwatches_for_discord_user)(ctx.author.id)
        if not watches:
            await ctx.respond(
                "Your deathwatch list is empty. " "Add with `/deathwatch add <name>`.",
                ephemeral=True,
            )
            return
        names = ", ".join(f"`{w.character.name}`" for w in watches)
        await ctx.respond(f"Your deathwatches: {names}", ephemeral=True)

    @deathwatch.command(
        name="channel",
        description="Set this channel as the deathwatch announcement target (admin only)",
    )
    async def channel(self, ctx: discord.ApplicationContext) -> None:
        """Two-layer guard (order matters, mirror /deaths threshold):
        DM rejection BEFORE admin check. `guild_permissions` is `Member`-only;
        in a DM `ctx.author` is `discord.User` and accessing it raises
        `AttributeError`. DM branch short-circuits first.
        """
        if ctx.guild is None:
            await ctx.respond(
                "❌ This command must be used in a server.", ephemeral=True
            )
            return

        # Narrow types — post-guild-check guarantees:
        assert isinstance(ctx.author, discord.Member)
        assert ctx.channel_id is not None

        if not ctx.author.guild_permissions.administrator:
            await ctx.respond(
                "❌ Only server admins can set the deathwatch channel.",
                ephemeral=True,
            )
            return

        await sync_to_async(set_deathwatch_channel_for_guild)(
            guild_id=ctx.guild.id,
            channel_id=ctx.channel_id,
        )
        # Public ack — audit trail, other admins see who pointed DW here.
        await ctx.respond(
            "💀👀 DeathWatch announcements will be posted to this channel."
        )
