from django.conf import settings
from django.db import models


class DeathWatch(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="death_watches",
    )
    character = models.ForeignKey(
        "characters.Character",
        on_delete=models.CASCADE,
        related_name="death_watches",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "character"],
                name="unique_death_watch_per_user_character",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} watching {self.character.name} for deaths"


class WatchedDeathEvent(models.Model):
    character = models.ForeignKey(
        "characters.Character",
        on_delete=models.CASCADE,
        related_name="watched_deaths",
    )
    level_at_death = models.PositiveIntegerField()
    killed_by = models.TextField(blank=True, default="")
    died_at = models.DateTimeField(db_index=True)
    scraped_at = models.DateTimeField(auto_now_add=True)
    announced_on_discord = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-died_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["character", "died_at"],
                name="unique_watched_death_per_character_time",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.character.name} (lvl {self.level_at_death}) "
            f"@ {self.died_at:%Y-%m-%d %H:%M}"
        )


class DeathWatchChannel(models.Model):
    guild_id = models.BigIntegerField()
    channel_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["guild_id"],
                name="deathwatch_channel_one_per_guild",
            ),
        ]

    def __str__(self) -> str:
        return f"DeathWatchChannel guild={self.guild_id} channel={self.channel_id}"
