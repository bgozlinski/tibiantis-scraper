from django.conf import settings
from django.db import models


class BedmageWatch(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bedmage_watches",
    )
    character = models.ForeignKey(
        "characters.Character", on_delete=models.CASCADE, related_name="bedmage_watches"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_notified_login = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "character"],
                name="unique_bedmage_watch_per_user_character",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} watching {self.character.name}"
