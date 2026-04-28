from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    email = models.EmailField(unique=True)
    discord_id = models.CharField(max_length=32, null=True, blank=True, unique=True)
