from django.db import IntegrityError, transaction

from apps.characters.models import Character
from apps.characters.types import CharacterPayload


def upsert_character(payload: CharacterPayload) -> Character:
    """Create or update a Character keyed by `name`.

    update_or_create() is not race-safe: two concurrent scrapes of the
    same character can both see "no row" and both attempt INSERT. The
    unique constraint on `name` rejects the loser with IntegrityError;
    retrying lets its SELECT find the row written by the winner and
    fall through to UPDATE.
    """
    name = payload.get("name")
    if not name:
        raise ValueError("CharacterPayload requires non-empty 'name'")
    defaults = {k: v for k, v in payload.items() if k != "name"}

    try:
        with transaction.atomic():
            character, _ = Character.objects.update_or_create(
                name=name, defaults=defaults
            )
    except IntegrityError:
        with transaction.atomic():
            character, _ = Character.objects.update_or_create(
                name=name, defaults=defaults
            )

    return character
