# NOTE: NO `from __future__ import annotations` here — py-cord introspects
# parameter annotations at slash command invocation time and requires them
# as runtime objects, not PEP 563 strings.
from datetime import datetime

from asgiref.sync import sync_to_async
import discord
from discord.ext import commands
from django.utils import timezone

from apps.deaths.services import CleanupError, cleanup_death_channel
from discord_bot.models import DiscordChannel
from discord_bot.services import (
    disable_cleanup_for_guild,
    enable_cleanup_for_guild,
    get_cleanup_status,
    set_death_threshold_for_guild,
)


def _fetch_channel_for_guild(guild_id: int) -> DiscordChannel | None:
    """ORM read isolated in a module function so cog tests can monkeypatch it."""
    try:
        return DiscordChannel.objects.get(guild_id=guild_id)
    except DiscordChannel.DoesNotExist:
        return None


def _humanize_last_cleanup(dt: datetime | None) -> str:
    """Render an absolute timestamp as a short relative string ('2d 4h ago')."""
    if dt is None:
        return "never"

    delta = timezone.now() - dt
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return "just now"
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h ago"
    if hours:
        return f"{hours}h {minutes}m ago"
    return f"{minutes}m ago"


class DeathsCog(commands.Cog):
    """Admin-side death-monitor configuration commands (``/deaths threshold``)."""

    deaths = discord.SlashCommandGroup("deaths", "Death monitor configuration")
    cleanup = deaths.create_subgroup(
        "cleanup", "Death-channel auto-cleanup configuration"
    )

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

    # ─── /deaths cleanup on ───────────────────────────────────────────────

    @cleanup.command(name="on", description="Enable 3-day cleanup (admin only)")
    async def cleanup_on(self, ctx: discord.ApplicationContext) -> None:
        if ctx.guild is None:
            await ctx.respond(
                "❌ This command must be used in a server.", ephemeral=True
            )
            return
        assert isinstance(ctx.author, discord.Member)
        if not ctx.author.guild_permissions.administrator:
            await ctx.respond("❌ Server admins only.", ephemeral=True)
            return

        ok = await sync_to_async(enable_cleanup_for_guild)(guild_id=ctx.guild.id)
        if not ok:
            await ctx.respond(
                "❌ Run `/deaths threshold` first to register this channel.",
                ephemeral=True,
            )
            return

        # Public ack — other admins see cleanup was turned on.
        await ctx.respond(
            "🧹 Cleanup enabled — messages older than 3 days will be removed every "
            "3 days at 00:00 Europe/Warsaw."
        )

    # ─── /deaths cleanup off ──────────────────────────────────────────────

    @cleanup.command(name="off", description="Disable cleanup (admin only)")
    async def cleanup_off(self, ctx: discord.ApplicationContext) -> None:
        if ctx.guild is None:
            await ctx.respond(
                "❌ This command must be used in a server.", ephemeral=True
            )
            return
        assert isinstance(ctx.author, discord.Member)
        if not ctx.author.guild_permissions.administrator:
            await ctx.respond("❌ Server admins only.", ephemeral=True)
            return

        ok = await sync_to_async(disable_cleanup_for_guild)(guild_id=ctx.guild.id)
        if not ok:
            await ctx.respond(
                "❌ Run `/deaths threshold` first to register this channel.",
                ephemeral=True,
            )
            return

        await ctx.respond("🧹 Cleanup disabled.")

    # ─── /deaths cleanup status ───────────────────────────────────────────

    @cleanup.command(name="status", description="Show cleanup state")
    async def cleanup_status(self, ctx: discord.ApplicationContext) -> None:
        if ctx.guild is None:
            await ctx.respond(
                "❌ This command must be used in a server.", ephemeral=True
            )
            return

        status = await sync_to_async(get_cleanup_status)(guild_id=ctx.guild.id)
        if status is None:
            await ctx.respond(
                "❌ Run `/deaths threshold` first to register this channel.",
                ephemeral=True,
            )
            return

        enabled = "✅ enabled" if status["enabled"] else "⏸️ disabled"
        last_run = _humanize_last_cleanup(status["last_cleanup_at"])
        # Ephemeral — status is informational, only the caller needs it.
        await ctx.respond(
            f"🧹 Cleanup: {enabled}\n"
            f"Last run: {last_run}\n"
            f"Channel: <#{status['channel_id']}>",
            ephemeral=True,
        )

    # ─── /deaths cleanup now ──────────────────────────────────────────────

    @cleanup.command(name="now", description="Run cleanup immediately (admin only)")
    async def cleanup_now(self, ctx: discord.ApplicationContext) -> None:
        if ctx.guild is None:
            await ctx.respond(
                "❌ This command must be used in a server.", ephemeral=True
            )
            return
        assert isinstance(ctx.author, discord.Member)
        if not ctx.author.guild_permissions.administrator:
            await ctx.respond("❌ Server admins only.", ephemeral=True)
            return

        channel = await sync_to_async(_fetch_channel_for_guild)(ctx.guild.id)
        if channel is None:
            await ctx.respond(
                "❌ Run `/deaths threshold` first to register this channel.",
                ephemeral=True,
            )
            return

        # Cleanup can take seconds (Discord pagination) — defer to avoid the
        # 3s interaction timeout, then deliver the result via followup.
        await ctx.defer()
        try:
            summary = await sync_to_async(cleanup_death_channel)(channel)
        except CleanupError as exc:
            await ctx.followup.send(f"❌ Cleanup failed: {exc}", ephemeral=True)
            return

        await ctx.followup.send(f"🧹 Deleted {summary['deleted']} messages.")
