"""Tests for Character model behavior."""

from __future__ import annotations

import time

import pytest
from django.db import IntegrityError, transaction

from apps.characters.models import Character


@pytest.mark.django_db
def test_create_character_with_minimum_fields() -> None:
    """Character can be created with only `name` — all other fields are optional."""
    character = Character.objects.create(name="Yhral")

    assert character.pk is not None
    assert character.name == "Yhral"
    assert character.sex == ""
    assert character.vocation == ""
    assert character.level is None
    assert character.world == ""
    assert character.residence == ""
    assert character.house == ""
    assert character.guild_membership == ""
    assert character.last_login is None
    assert character.account_status == ""
    assert character.last_scraped_at is not None


@pytest.mark.django_db
def test_name_uniqueness_enforced() -> None:
    """Second insert with the same `name` raises IntegrityError."""
    Character.objects.create(name="Yhral")

    # Savepoint via transaction.atomic() so the outer test tx isn't broken
    # after IntegrityError — otherwise pytest-django teardown complains.
    with pytest.raises(IntegrityError), transaction.atomic():
        Character.objects.create(name="Yhral")


@pytest.mark.django_db
def test_last_scraped_at_updates_on_save() -> None:
    """`auto_now=True` refreshes last_scraped_at on every save()."""
    character = Character.objects.create(name="Yhral")
    first_timestamp = character.last_scraped_at

    # Small sleep to guarantee measurable timestamp delta — auto_now uses
    # timezone.now() which has microsecond precision, but guard anyway.
    time.sleep(0.01)

    character.vocation = "Knight"
    character.save()
    character.refresh_from_db()

    assert character.last_scraped_at > first_timestamp


# === Issue #164: case-insensitive character name canonicalization ===
#
# Tibia/Tibiantis treats character names case-insensitively at the game layer
# — there is no "Akrutki" distinct from "akrutki" in the game. Our DB must
# agree. The agreed fix (see issue #164 + triage comment) is two-layered:
#
#   1. `Character.save()` canonicalizes `name` to "first-letter-upper,
#      rest-lower" with surrounding whitespace stripped.
#   2. A functional unique constraint on `LOWER(name)` at the DB level
#      catches bypass paths (bulk_create, RunPython, raw SQL).
#
# These tests must FAIL on `master` (no canonicalization in place) and PASS
# once the dev lands the fix on this branch.


@pytest.mark.django_db
def test_name_canonicalized_on_save_lowercase_input() -> None:
    """Lowercase input is canonicalized to first-letter-upper on save()."""
    character = Character.objects.create(name="akrutki")

    character.refresh_from_db()
    assert character.name == "Akrutki"


@pytest.mark.django_db
def test_name_canonicalized_on_save_mixed_case_input() -> None:
    """Mixed-case input (any casing) collapses to first-letter-upper, rest-lower.

    Important: this is `s[0].upper() + s[1:].lower()`, NOT `str.capitalize()`.
    `.capitalize()` happens to produce the same result for ASCII-only strings,
    but the spec is "first-letter-upper", not "title-case with all other
    letters forcibly lowered as a side effect." The distinction matters if
    the canonical form is ever revisited (e.g. non-ASCII names).
    """
    character = Character.objects.create(name="aKrUtKi")

    character.refresh_from_db()
    assert character.name == "Akrutki"


@pytest.mark.django_db
def test_name_canonicalized_strips_surrounding_whitespace() -> None:
    """Leading/trailing whitespace is stripped before canonicalization.

    Operators occasionally paste names with stray whitespace from Discord
    autocomplete or copy-paste. The save() canonical form must be robust to
    this — otherwise '  Akrutki' and 'Akrutki' produce different DB rows.
    """
    character = Character.objects.create(name="  akrutki  ")

    character.refresh_from_db()
    assert character.name == "Akrutki"


@pytest.mark.django_db
def test_name_canonicalized_on_update_via_save() -> None:
    """Re-canonicalization runs on every save(), not just on initial create.

    Guards against the implementation pitfall of canonicalizing only in
    `__init__` or only when `_state.adding` is True. Renames via `save()`
    must canonicalize too — otherwise a direct ORM rename bypasses the rule.
    """
    character = Character.objects.create(name="Akrutki")
    character.name = "yHrAl"
    character.save()
    character.refresh_from_db()

    assert character.name == "Yhral"


@pytest.mark.django_db
def test_name_unique_constraint_case_insensitive_via_save() -> None:
    """Two creates with different casings of the same game-name collide.

    Because save() canonicalizes both to "Akrutki", the existing
    `unique=True` constraint on `name` is what trips here. This test
    exercises the fix from the *save-path* side — `test_…_bulk_create_bypass`
    covers the DB-functional-index side.
    """
    Character.objects.create(name="Akrutki")

    with pytest.raises(IntegrityError), transaction.atomic():
        Character.objects.create(name="akrutki")


@pytest.mark.django_db
def test_name_unique_constraint_holds_against_bulk_create_bypass() -> None:
    """bulk_create() bypasses Model.save() — only a DB-level functional unique
    index on LOWER(name) can catch collisions through this path.

    This is the test that proves the *index* exists, not just save()
    canonicalization. Without the `UniqueConstraint(Lower("name"))` on the
    model, bulk_create silently inserts both rows with different casings.

    Also covers the migration-safety contract: any future RunPython that
    constructs Character rows directly will fail loud at the DB rather than
    silently corrupting the data.
    """
    with pytest.raises(IntegrityError), transaction.atomic():
        Character.objects.bulk_create(
            [
                Character(name="Akrutki"),
                Character(name="akrutki"),
            ]
        )
