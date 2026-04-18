"""Tests for upsert_character() service."""

from __future__ import annotations

import pytest

from apps.characters.models import Character
from apps.characters.services import upsert_character


@pytest.mark.django_db
def test_upsert_creates_new_character_when_not_exists() -> None:
    """First call with a fresh name inserts a new Character row."""
    character = upsert_character({"name": "Yhral", "level": 42, "vocation": "Knight"})

    assert character.pk is not None
    assert character.name == "Yhral"
    assert character.level == 42
    assert character.vocation == "Knight"
    assert Character.objects.count() == 1


@pytest.mark.django_db
def test_upsert_updates_existing_character_in_place() -> None:
    """Second call with the same name updates the existing row, not inserts."""
    Character.objects.create(name="Yhral", level=40, vocation="Knight")

    character = upsert_character({"name": "Yhral", "level": 41, "vocation": "Paladin"})

    assert Character.objects.count() == 1
    character.refresh_from_db()
    assert character.level == 41
    assert character.vocation == "Paladin"


@pytest.mark.django_db
def test_upsert_without_name_raises_valueerror() -> None:
    """Payload missing `name` (or with empty string) must be rejected."""
    with pytest.raises(ValueError):
        upsert_character({})

    with pytest.raises(ValueError):
        upsert_character({"name": "", "level": 50})


@pytest.mark.django_db
def test_upsert_preserves_unspecified_fields() -> None:
    """Fields absent from payload on update must keep their current DB value."""
    Character.objects.create(
        name="Yhral", level=40, vocation="Knight", world="Tibiantis"
    )

    upsert_character({"name": "Yhral", "level": 41})

    character = Character.objects.get(name="Yhral")
    assert character.level == 41
    assert character.vocation == "Knight"
    assert character.world == "Tibiantis"
