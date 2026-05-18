"""Django admin registration for the Discord bot models."""

from django.contrib import admin
from discord_bot.models import DiscordChannel


@admin.register(DiscordChannel)
class DiscordChannelAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Admin view for :class:`DiscordChannel`."""

    list_display = ("guild_id", "channel_id", "death_level_threshold", "updated_at")
    search_fields = ("guild_id",)
    readonly_fields = ("created_at", "updated_at")
