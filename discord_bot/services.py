from __future__ import annotations

import logging

from django.db import transaction

from apps.accounts.models import User
from discord_bot.models import DiscordChannel

logger = logging.getLogger(__name__)


def get_or_create_user_by_discord_id(
    discord_id: int, discord_username: str
) -> tuple[User, bool]:
    """Lazy auto-create per CLAUDE.md §8.

    Returns (user, created). Username pattern: f"discord_{discord_id}".
    Email empty, password unusable.
    """
    with transaction.atomic():
        user, created = User.objects.get_or_create(
            discord_id=discord_id,
            defaults={
                "username": f"discord_{discord_id}",
                "email": "",
            },
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
            logger.info(
                "Auto-created Django User for Discord user %s (id=%s)",
                discord_username,
                discord_id,
            )
    return user, created


def set_death_threshold_for_guild(
    guild_id: int, channel_id: int, threshold: int
) -> DiscordChannel:
    """Upsert DiscordChannel by guild_id. Updates channel_id + threshold
    (M8 will use channel_id as outbound destination)."""
    channel, created = DiscordChannel.objects.update_or_create(
        guild_id=guild_id,
        defaults={
            "channel_id": channel_id,
            "death_level_threshold": threshold,
        },
    )
    logger.info(
        "%s DiscordChannel for guild=%s threshold=%s",
        "Created" if created else "Updated",
        guild_id,
        threshold,
    )
    return channel
