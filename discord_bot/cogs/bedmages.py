from __future__ import annotations

from asgiref.sync import sync_to_async
import discord
from discord.ext import commands

from discord_bot.services import (
    add_bedmage_for_discord_user,
    list_bedmages_for_discord_user,
    remove_bedmage_for_discord_user,
)


class BedmageCog(commands.Cog):
    bedmage = discord.SlashCommandGroup("bedmage", "Manage your bedmage tracking list")

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    @bedmage.command(name="add", description="Add a character to your bedmage list")
    async def add(
        self,
        ctx: discord.ApplicationContext,
        character_name: discord.Option(str, "Tibiantis character name", max_length=64),
    ) -> None:
        watch, created = await sync_to_async(add_bedmage_for_discord_user)(
            discord_id=ctx.author.id,
            discord_username=ctx.author.name,
            character_name=character_name,
        )
        msg = (
            f"✅ Added `{character_name}` to your bedmage list."
            if created
            else f"ℹ️ `{character_name}` was already on your list."
        )
        await ctx.respond(msg, ephemeral=True)

    @bedmage.command(
        name="remove", description="Remove a character from your bedmage list"
    )
    async def remove(
        self,
        ctx: discord.ApplicationContext,
        character_name: discord.Option(str, "Tibiantis character name", max_length=64),
    ) -> None:
        removed = await sync_to_async(remove_bedmage_for_discord_user)(
            discord_id=ctx.author.id,
            character_name=character_name,
        )
        msg = (
            f"✅ Removed `{character_name}` from your list."
            if removed
            else f"ℹ️ `{character_name}` wasn't on your list."
        )
        await ctx.respond(msg, ephemeral=True)

    @bedmage.command(name="list", description="Show your bedmage list")
    async def list(self, ctx: discord.ApplicationContext) -> None:
        watches = await sync_to_async(list_bedmages_for_discord_user)(ctx.author.id)
        if not watches:
            await ctx.respond(
                "Your bedmage list is empty. Add with `/bedmage add <name>`.",
                ephemeral=True,
            )
            return
        names = ", ".join(f"`{w.character.name}`" for w in watches)
        await ctx.respond(f"Your bedmages: {names}", ephemeral=True)
