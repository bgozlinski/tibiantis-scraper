from typing import TypedDict
from datetime import datetime


class CharacterPayload(TypedDict, total=False):
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
