"""Tests for apps.bedmages.models — minimal coverage of __str__ formatting."""

from __future__ import annotations

import pytest

from apps.bedmages.models import BedmageWatch
from apps.characters.models import Character
from apps.accounts.models import User


@pytest.mark.django_db
def test_bedmage_watch_str_includes_username_and_character_name() -> None:
    """`__str__` reads "<username> watching <character_name>".

    Format is consumed by Django admin (list_display falls back to __str__ if a
    field doesn't render) and by tests/services that log the watch instance.
    Pinning the format prevents accidental changes from silently breaking the
    admin row label.
    """
    user = User.objects.create_user(
        username="alice", email="alice@example.com", password="ComplexPass!1"
    )
    character = Character.objects.create(name="Yhral")
    watch = BedmageWatch.objects.create(user=user, character=character)

    assert str(watch) == "alice watching Yhral"
