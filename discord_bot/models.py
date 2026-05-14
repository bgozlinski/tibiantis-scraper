from django.db import models


class DiscordChannel(models.Model):
    guild_id = models.BigIntegerField()
    channel_id = models.BigIntegerField()
    death_level_threshold = models.PositiveIntegerField(default=30)
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
