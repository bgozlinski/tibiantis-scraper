from datetime import datetime
from typing import TypedDict


class BedmagePayload(TypedDict, total=False):
    """Payload shape for add_bedmage_watch service input.

    Mirror of `apps/characters/types.py::CharacterPayload` pattern (M1 #6) —
    types separated from services for reusability and testability.
    """

    user_id: int
    character_name: str
    created_at: datetime
    last_notified_login: datetime | None
    active: bool
