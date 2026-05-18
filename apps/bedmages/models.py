"""Models for the bedmages app.

A :class:`BedmageWatch` is the link between a Django user and a Tibiantis
character they want a "regen-finished" reminder for. The pair must be
unique — re-adding an already-watched character either raises (active row)
or reactivates the existing inactive row.
"""

from django.conf import settings
from django.db import models


class BedmageWatch(models.Model):
    """A single user → character bedmage subscription.

    ``last_notified_login`` stores the character's ``last_login`` value at
    the time of the last sent notification. It is the idempotency key that
    prevents the 5-min Celery task from re-notifying about the same in-bed
    session — see :func:`apps.bedmages.services.check_bedmage_watches_for_character`.
    """

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
