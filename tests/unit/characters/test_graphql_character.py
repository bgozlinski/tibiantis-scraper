"""Tests for GraphQL `character(name)` public query.

`character(name)` jest **public** (AC #31) — działa bez auth. Resolver używa
natywnego `afirst()` (Django 4.1+ async ORM), więc null gdy postaci brak,
dane gdy istnieje.
"""

from __future__ import annotations

import json

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient

from apps.characters.models import Character


GRAPHQL_URL = "/graphql/"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_character_returns_data_when_exists_without_auth() -> None:
    """Public query — brak Authorization headera → resolver zwraca dane."""
    await sync_to_async(Character.objects.create)(
        name="Yhral",
        level=124,
        vocation="Royal Paladin",
        world="Concordia",
        sex="male",
        residence="Edron",
        account_status="Free Account",
    )

    response = await AsyncClient().post(
        GRAPHQL_URL,
        data=json.dumps(
            {
                "query": '{ character(name: "Yhral") '
                "{ name level vocation world sex } }"
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 200, response.content
    payload = response.json()
    assert "errors" not in payload
    assert payload["data"]["character"] == {
        "name": "Yhral",
        "level": 124,
        "vocation": "Royal Paladin",
        "world": "Concordia",
        "sex": "male",
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_character_returns_null_when_not_found() -> None:
    """Postaci nie ma w bazie → afirst() zwraca None → resolver `null` (NIE error)."""
    response = await AsyncClient().post(
        GRAPHQL_URL,
        data=json.dumps(
            {"query": '{ character(name: "NotInDatabase") { name level } }'}
        ),
        content_type="application/json",
    )

    assert response.status_code == 200, response.content
    payload = response.json()
    assert "errors" not in payload
    assert payload["data"] == {"character": None}
