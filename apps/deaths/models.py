from django.db import models


class DeathEvent(models.Model):
    character_name = models.CharField(max_length=64, db_index=True)
    level_at_death = models.PositiveIntegerField()
    killed_by = models.TextField(blank=True, default="")
    died_at = models.DateTimeField(db_index=True)
    scraped_at = models.DateTimeField(auto_now_add=True)

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
