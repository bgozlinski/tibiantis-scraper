from datetime import datetime
from typing import TypedDict


class DeathWatchPayload(TypedDict, total=False):
    """Payload shape for DeathWatch service input/output.

    Mirror of `apps/bedmages/types.py::BedmagePayload` pattern — types
    separated from services for reusability and testability.
    """

    id: int
    user_id: int
    character_name: str
    created_at: datetime
    active: bool


class WatchedDeathPayload(TypedDict, total=False):
    """Pipeline-side payload — `CharacterDeathItem` shape from spider (DW-3).

    `record_watched_death(item: dict)` accepts dict-like input matching this
    shape. Plain dict (not TypedDict subclass) because Scrapy `Item` exposes
    dict-access but isn't a TypedDict.
    """

    id: int
    character_name: str
    level_at_death: int
    killed_by: str
    died_at: datetime
    announced_on_discord: bool
