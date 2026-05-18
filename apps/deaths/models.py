"""Models for the deaths app.

A :class:`DeathEvent` is an immutable record of a single character death
pulled from the public Tibiantis deaths list. Deduplication is enforced at
the DB level via the ``(character_name, died_at)`` unique constraint.
"""

from django.db import models


class DeathEvent(models.Model):
    """One scraped death event.

    The ``announced_on_discord`` flag is the state used by the announcement
    task to find rows that still need to be pushed to Discord channels.
    Once flipped to ``True`` a row is never sent again — back-fills for
    channels that lower their threshold after the fact are explicitly out
    of scope (see services docstring).
    """

    character_name = models.CharField(max_length=64, db_index=True)
    level_at_death = models.PositiveIntegerField()
    killed_by = models.TextField(blank=True, default="")
    died_at = models.DateTimeField(db_index=True)
    scraped_at = models.DateTimeField(auto_now_add=True)
    announced_on_discord = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-died_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["character_name", "died_at"],
                name="unique_death_event_per_character_time",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.character_name} (lvl {self.level_at_death}) @ {self.died_at:%Y-%m-%d %H:%M}"
