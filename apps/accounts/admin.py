"""Django admin registration for the accounts app."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from apps.accounts.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin for :class:`User` that adds a Discord fieldset to the default form."""

    fieldsets = (
        *(BaseUserAdmin.fieldsets or ()),
        ("Discord", {"fields": ("discord_id",)}),
    )
    add_fieldsets = (
        *(BaseUserAdmin.add_fieldsets or ()),
        ("Discord", {"fields": ("discord_id",)}),
    )
