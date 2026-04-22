from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from apps.accounts.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin[User]):
    fieldsets = (
        *(BaseUserAdmin.fieldsets or ()),
        ("Discord", {"fields": ("discord_id",)}),
    )
    add_fieldsets = (
        *(BaseUserAdmin.add_fieldsets or ()),
        ("Discord", {"fields": ("discord_id",)}),
    )
