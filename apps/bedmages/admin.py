from django.contrib import admin

from apps.bedmages.models import BedmageWatch


@admin.register(BedmageWatch)
class BedmageWatchAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("user", "character", "active", "last_notified_login", "created_at")
    list_filter = ("active",)
    search_fields = ("user__username", "character__name")
    ordering = ("-created_at",)
