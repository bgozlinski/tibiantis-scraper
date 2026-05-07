from datetime import datetime
from typing import TypedDict

from django.db import IntegrityError, transaction

from apps.deaths.models import DeathEvent


class DeathPayload(TypedDict):
    character_name: str
    level_at_death: int
    killed_by: str
    died_at: datetime


def save_death_event(payload: DeathPayload) -> DeathEvent | None:
    """Create DeathEvent or skip silently on dedup hit.

    Returns None when (character_name, died_at) already exists in DB.
    Deaths are immutable — no upsert semantics. Caller (pipeline) ignores
    return value, but pipeline's stats counter inc'es on None to track
    duplicates for observability.
    """
    try:
        with transaction.atomic():
            return DeathEvent.objects.create(**payload)
    except IntegrityError:
        return None
