from django.contrib import admin
from django.http import HttpRequest

from apps.deaths.models import DeathEvent


@admin.register(DeathEvent)
class DeathEventAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("character_name", "level_at_death", "died_at", "killed_by")
    list_filter = ("level_at_death",)
    search_fields = ("character_name",)
    ordering = ["-died_at"]
    readonly_fields = ("scraped_at",)

    def has_change_permission(
        self, request: HttpRequest, obj: DeathEvent | None = None
    ) -> bool:
        return False
