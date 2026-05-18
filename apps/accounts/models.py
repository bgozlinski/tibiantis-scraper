"""User model for the project.

Extends Django's ``AbstractUser`` with a Discord identifier so that the same
account can be created either from the REST registration endpoint or
auto-provisioned by the Discord bot on first slash-command interaction.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Project user.

    Adds two project-specific changes on top of Django's ``AbstractUser``:

    * ``email`` is nullable and unique — Discord-only users (created by the bot
      on first command) do not have an email yet, but REST-registered users do.
      The REST ``RegisterSerializer`` enforces a non-empty value at the API
      layer, so the relaxed column never produces empty rows through that path.
    * ``discord_id`` stores the Discord snowflake used to link a Django user
      with a Discord account; nullable for REST-only users.
    """

    # AbstractUser declares `email: EmailField` (non-null, blank=True). We narrow
    # the column to allow NULL so Discord-only users can be auto-created without
    # colliding on the unique constraint (#133). REST register enforces a real
    # value at the serializer layer; the model intentionally diverges from the
    # AbstractUser shape, so silence django-stubs' generic-narrowing complaint.
    email = models.EmailField(  # type: ignore[misc]
        unique=True, null=True, blank=True
    )
    discord_id = models.CharField(max_length=32, null=True, blank=True, unique=True)
