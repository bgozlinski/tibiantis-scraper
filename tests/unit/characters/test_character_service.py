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


# === Issue #164: case-insensitive character name canonicalization ===


@pytest.mark.django_db
def test_upsert_with_different_casing_returns_same_row() -> None:
    """Two upserts of the same game-name in different casings must converge on
    one Character row.

    Pre-fix, `upsert_character({"name": "Akrutki"})` and
    `upsert_character({"name": "akrutki"})` produce two rows because
    `update_or_create(name=...)` does an exact-match lookup. Post-fix, either:
      a) save() canonicalizes both to "Akrutki" → the second upsert's
         update_or_create lookup keys on "akrutki", misses, attempts INSERT,
         hits the case-insensitive unique constraint, retries, and SELECTs
         the canonical row. The retry path in upsert_character() handles this.
      b) services.upsert_character itself canonicalizes the lookup key before
         calling update_or_create.

    Either implementation is acceptable as long as the observable behavior —
    one row, latest payload wins — holds. This test asserts the behavior, not
    the path.
    """
    first = upsert_character({"name": "Akrutki", "level": 12, "vocation": "Sorcerer"})
    second = upsert_character({"name": "akrutki", "level": 13, "vocation": "Sorcerer"})

    assert Character.objects.count() == 1
    assert first.pk == second.pk
    second.refresh_from_db()
    assert second.name == "Akrutki"
    assert second.level == 13


@pytest.mark.django_db
def test_upsert_accepts_none_house_and_guild_membership() -> None:
    """Regression #139 — characters without house AND without guild membership
    (typical for low-level accounts on Tibiantis) reach the pipeline with
    `house=None` and `guild_membership=None`. Pre-fix the model rejected NULL
    on these columns and the whole INSERT rolled back, leaving Character with
    all defaults. Migration 0004 made both fields nullable; this test exercises
    the full path (real ORM, real DB) so the column-level constraint stays
    NULL-tolerant going forward.

    Reproduces the exact failure mode from M8 manual smoke for `Akrutki`
    (level 12 Sorcerer): spider parsed every other field correctly, pipeline
    forwarded the dict to upsert_character, and PostgreSQL raised
    `NOT NULL constraint violation`. With the fix this test must persist a
    row with `house IS NULL`, `guild_membership IS NULL`, and every other
    field populated as supplied.
    """
    from datetime import datetime, timezone

    character = upsert_character(
        {
            "name": "Akrutki",
            "sex": "female",
            "vocation": "Sorcerer",
            "level": 12,
            "world": "Concordia",
            "residence": "Thais",
            "house": None,
            "guild_membership": None,
            "last_login": datetime(2026, 5, 15, 10, 43, 31, tzinfo=timezone.utc),
            "account_status": "Premium Account",
        }
    )

    assert character.pk is not None
    character.refresh_from_db()
    assert character.house is None
    assert character.guild_membership is None
    # rest of the payload must be persisted — pre-fix the entire INSERT rolled back
    assert character.name == "Akrutki"
    assert character.level == 12
    assert character.vocation == "Sorcerer"
    assert character.last_login is not None
    assert character.account_status == "Premium Account"
