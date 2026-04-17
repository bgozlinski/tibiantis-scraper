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
