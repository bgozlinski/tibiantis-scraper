from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    # AbstractUser declares `email: EmailField` (non-null, blank=True). We narrow
    # the column to allow NULL so Discord-only users can be auto-created without
    # colliding on the unique constraint (#133). REST register enforces a real
    # value at the serializer layer; the model intentionally diverges from the
    # AbstractUser shape, so silence django-stubs' generic-narrowing complaint.
    email = models.EmailField(  # type: ignore[misc]
        unique=True, null=True, blank=True
    )
    discord_id = models.CharField(max_length=32, null=True, blank=True, unique=True)
