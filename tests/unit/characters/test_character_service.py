"""Tests for upsert_character() service."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.db import IntegrityError

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


@pytest.mark.django_db
def test_upsert_retries_after_race_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulates the race: a concurrent scrape inserts the row between our
    SELECT and INSERT, so update_or_create raises IntegrityError. The retry
    must find the row and UPDATE it in place — not re-raise, not duplicate."""
    Character.objects.create(name="Yhral", level=40, vocation="Knight")

    real_update_or_create = Character.objects.update_or_create
    calls: list[int] = []

    def flaky_update_or_create(*args: object, **kwargs: object) -> object:
        calls.append(1)
        if len(calls) == 1:
            raise IntegrityError("duplicate key value violates unique constraint")
        return real_update_or_create(*args, **kwargs)

    monkeypatch.setattr(Character.objects, "update_or_create", flaky_update_or_create)

    character = upsert_character({"name": "Yhral", "level": 41, "vocation": "Paladin"})

    assert len(calls) == 2
    assert Character.objects.count() == 1
    character.refresh_from_db()
    assert character.level == 41
    assert character.vocation == "Paladin"


@pytest.mark.django_db
def test_upsert_propagates_integrity_error_after_single_retry() -> None:
    """If IntegrityError persists on the retry (unlikely in practice — would
    require someone deleting the row between attempts), propagate instead of
    looping forever."""
    with patch.object(Character.objects, "update_or_create") as mock_uoc:
        mock_uoc.side_effect = IntegrityError("persistent")

        with pytest.raises(IntegrityError):
            upsert_character({"name": "Yhral", "level": 41})

        assert mock_uoc.call_count == 2
