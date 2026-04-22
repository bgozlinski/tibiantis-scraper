from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    discord_id = models.CharField(
        max_length=32, null=True, blank=True, unique=True, db_index=True
    )
