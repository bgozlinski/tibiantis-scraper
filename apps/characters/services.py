from apps.characters.models import Character
from apps.characters.types import CharacterPayload


def upsert_character(payload: CharacterPayload) -> Character:
    """Create or update a Character keyed by `name`. Atomic via update_or_create()."""
    name = payload.get("name")
    if not name:
        raise ValueError("CharacterPayload requires non-empty 'name'")
    defaults = {k: v for k, v in payload.items() if k != "name"}
    character, _ = Character.objects.update_or_create(name=name, defaults=defaults)

    return character
