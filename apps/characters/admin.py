from django.contrib import admin
from apps.characters.models import Character


@admin.register(Character)
class CharacterAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("name", "level", "vocation", "world", "last_login")
    list_filter = ("vocation", "world")
    search_fields = ("name",)
    readonly_fields = ("last_scraped_at",)
