"""Tests for GraphQL `me` query and schema introspection at /graphql/."""

from __future__ import annotations

import json

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient

from apps.accounts.models import User


GRAPHQL_URL = "/graphql/"


async def _post_graphql(client: AsyncClient, query: str) -> dict[str, object]:
    response = await client.post(
        GRAPHQL_URL,
        data=json.dumps({"query": query}),
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


@pytest.mark.asyncio
async def test_schema_introspection_returns_200_with_types() -> None:
    """Introspection canary — wadliwa konfiguracja schema/view wywaliłaby się tutaj."""
    client = AsyncClient()

    payload = await _post_graphql(client, "{ __schema { types { name } } }")

    assert "errors" not in payload
    type_names = {t["name"] for t in payload["data"]["__schema"]["types"]}
    assert "UserType" in type_names
    assert "Query" in type_names


@pytest.mark.asyncio
async def test_me_returns_null_when_unauthenticated() -> None:
    """Niezalogowany użytkownik dostaje `{me: null}` — resolver nie powinien rzucać."""
    client = AsyncClient()

    payload = await _post_graphql(client, "{ me { username } }")

    assert "errors" not in payload
    assert payload["data"] == {"me": None}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_me_returns_user_when_authenticated() -> None:
    """Po `force_login` resolver zwraca dane bieżącego usera."""
    user = await sync_to_async(User.objects.create_user)(
        username="yhral", email="yhral@example.com", password="KomplexHaslo!23"
    )
    client = AsyncClient()
    await sync_to_async(client.force_login)(user)

    payload = await _post_graphql(client, "{ me { username } }")

    assert "errors" not in payload
    assert payload["data"] == {"me": {"username": "yhral"}}
