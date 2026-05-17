from typing import Any

from django.db import models
from django.db.models import (
    CharField,
    DateTimeField,
    PositiveIntegerField,
    UniqueConstraint,
)
from django.db.models.functions import Lower


def _canonicalize_name(name: str) -> str:
    """Return canonical form of a Tibia character name: first-letter-upper,
    rest-lower, with surrounding whitespace stripped.

    Per M10 spec §3.4 — explicit primitive, NOT str.capitalize(). Tibia names
    today are ASCII so the two produce the same result, but the spec locks
    the explicit form because the intent ('uppercase the first letter only')
    is clearer and the behaviour is independent of Python's locale-aware
    capitalize().
    """
    s = name.strip()
    if not s:
        return s
    return s[0].upper() + s[1:].lower()


class Character(models.Model):
    name = CharField(max_length=64, unique=True)
    sex = CharField(max_length=16, blank=True, default="")
    vocation = CharField(max_length=32, blank=True, default="")
    level = PositiveIntegerField(null=True, blank=True)
    world = CharField(max_length=32, blank=True, default="")
    residence = CharField(max_length=64, blank=True, default="")
    house = CharField(max_length=128, null=True, blank=True, default="")
    guild_membership = CharField(max_length=128, null=True, blank=True, default="")
    last_login = DateTimeField(null=True, blank=True, db_index=True)
    account_status = CharField(max_length=32, blank=True, default="")
    last_scraped_at = DateTimeField(auto_now=True)
    last_deaths_scraped_at = DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-level"]
        constraints = [
            UniqueConstraint(
                Lower("name"),
                name="character_name_lower_unique",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.name:
            self.name = _canonicalize_name(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} (level {self.level})"
