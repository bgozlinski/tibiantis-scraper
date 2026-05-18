"""Models for the deathwatch app.

DeathWatch is a per-user public death subscription: every active row produces
a notification on the configured channel(s) whenever the watched character
dies. Three models cooperate:

* :class:`DeathWatch` — user → character subscription.
* :class:`WatchedDeathEvent` — immutable event recorded by the spider once a
  qualifying death is found.
* :class:`DeathWatchChannel` — per-guild announcement target configured by
  the bot's ``/deathwatch channel`` command.
"""

from django.conf import settings
from django.db import models


class DeathWatch(models.Model):
    """A user's subscription to deaths of a single character.

    Identifying pair is ``(user, character)``; ``created_at`` is also the
    floor used by :func:`apps.deathwatch.services.record_watched_death` to
    drop historical deaths emitted by the spider's "Latest Deaths" table.
    """

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
    """A death recorded by the deathwatch pipeline.

    Distinct from :class:`apps.deaths.models.DeathEvent` — that one is a
    global high-level deaths feed; this one is scoped to characters that at
    least one user has subscribed to. ``announced_on_discord`` mirrors the
    semantics in the deaths app: flipped to ``True`` once every configured
    channel has acknowledged the message.
    """

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
    """The Discord channel that receives deathwatch notifications per guild.

    Both IDs are Discord snowflakes, hence ``BigIntegerField``. One row per
    guild is enforced by the unique constraint; the GraphQL admin mutation
    and the bot's ``/deathwatch channel`` command upsert into the same row.
    """

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
