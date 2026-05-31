"""Models owned by the Discord bot.

Currently a single :class:`DiscordChannel` row per guild, configured by
``/deaths threshold`` and consumed by :func:`apps.deaths.services.announce_unannounced_deaths`.
"""

from django.db import models


class DiscordChannel(models.Model):
    """The death-announcement target configured per Discord guild.

    ``death_level_threshold`` is the minimum character level a death must
    have for the announcement task to push it into this channel. The
    ``guild_id`` unique constraint ensures one configuration row per guild.

    ``cleanup_enabled`` + ``last_cleanup_at`` were added 2026-06-01 to
    drive the 3-day auto-purge feature (opt-in per guild, default OFF).
    """

    guild_id = models.BigIntegerField()
    channel_id = models.BigIntegerField()
    death_level_threshold = models.PositiveIntegerField(default=30)
    cleanup_enabled = models.BooleanField(default=False)
    last_cleanup_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["guild_id"], name="discord_channel_one_per_guild"
            ),
        ]

    def __str__(self) -> str:
        return f"Guild {self.guild_id} (threshold={self.death_level_threshold})"
