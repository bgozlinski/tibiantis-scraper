from django.db import models
from django.db.models import PositiveIntegerField, CharField, DateTimeField


class Character(models.Model):
    name = CharField(max_length=64, unique=True)
    sex = CharField(max_length=16, blank=True, default="")
    vocation = CharField(max_length=32, blank=True, default="")
    level = PositiveIntegerField(null=True, blank=True)
    world = CharField(max_length=32, blank=True, default="")
    residence = CharField(max_length=64, blank=True, default="")
    house = CharField(max_length=128, blank=True, default="")
    guild_membership = CharField(max_length=128, blank=True, default="")
    last_login = DateTimeField(null=True, blank=True, db_index=True)
    account_status = CharField(max_length=32, blank=True, default="")
    last_scraped_at = DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-level"]

    def __str__(self) -> str:
        return f"{self.name} (level {self.level})"
