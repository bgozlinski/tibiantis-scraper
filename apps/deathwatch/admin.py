from django.contrib import admin

from apps.deathwatch.models import DeathWatch, DeathWatchChannel, WatchedDeathEvent


@admin.register(DeathWatch)
class DeathWatchAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("user", "character", "active", "created_at")
    list_filter = ("active",)
    search_fields = ("user__username", "character__name")
    ordering = ("-created_at",)


@admin.register(WatchedDeathEvent)
class WatchedDeathEventAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "character",
        "level_at_death",
        "died_at",
        "announced_on_discord",
    )
    list_filter = ("announced_on_discord",)
    search_fields = ("character__name", "killed_by")
    ordering = ("-died_at",)


@admin.register(DeathWatchChannel)
class DeathWatchChannelAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("guild_id", "channel_id", "updated_at")
    search_fields = ("guild_id", "channel_id")
