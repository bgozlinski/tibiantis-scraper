"""Typed payload contracts for the characters app.

These dicts are the boundary between Scrapy pipelines and the service layer:
spiders build a :class:`CharacterPayload`, the pipeline forwards it to
``services.upsert_character`` and only there it crosses into the ORM.
"""

from typing import TypedDict
from datetime import datetime


class CharacterPayload(TypedDict, total=False):
    """Subset of :class:`apps.characters.models.Character` fields.

    Marked ``total=False`` so scrapers can omit fields they could not extract;
    only ``name`` is mandatory and validated by ``upsert_character``.
    """

    name: str
    sex: str
    vocation: str
    level: int | None
    world: str
    residence: str
    house: str
    guild_membership: str
    last_login: datetime | None
    account_status: str
