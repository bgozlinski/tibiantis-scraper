"""E2E integration test for M2 — register → login → JWT → GraphQL mixed query.

Spec M2 §5/D12: jeden e2e łączący wszystkie warstwy (REST register/login,
JWT, GraphQL public + chronione query). Po tym M2 może zostać zamknięty.
"""

from __future__ import annotations

import json

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.characters.models import Character


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_m2_e2e_register_login_graphql_mixed_query() -> None:
    """5-krokowy flow z spec D12 §5.

    Klient REST (`APIClient`, sync) dla /api/auth/* i klient GraphQL
    (`AsyncClient`, async) dla /graphql/ — sync REST view zawinięty przez
    AsyncClient zamaskowałby SynchronousOnlyOperation, na odwrót Strawberry
    AsyncGraphQLView wymaga prawdziwego async clienta. Dwa klienty są
    konieczne (lekcja z mini-retro M2 #30).
    """
    rest = APIClient()
    register_response = await sync_to_async(rest.post)(
        reverse("accounts_api:register"),
        data={
            "username": "yhral",
            "email": "yhral@example.com",
            "password": "KomplexHaslo!23",
        },
        format="json",
    )
    assert (
        register_response.status_code == status.HTTP_201_CREATED
    ), register_response.content

    login_response = await sync_to_async(rest.post)(
        reverse("accounts_api:login"),
        data={"username": "yhral", "password": "KomplexHaslo!23"},
        format="json",
    )
    assert login_response.status_code == status.HTTP_200_OK, login_response.content
    access = login_response.data["access"]
    assert isinstance(access, str) and access

    await sync_to_async(Character.objects.create)(
        name="Yhral",
        level=120,
        vocation="Knight",
        world="Tibiantis",
        sex="male",
        residence="Edron",
        account_status="Free Account",
    )

    graphql = AsyncClient()
    response = await graphql.post(
        "/graphql/",
        data=json.dumps(
            {"query": '{ me { username } character(name: "Yhral") { level } }'}
        ),
        content_type="application/json",
        headers={"Authorization": f"Bearer {access}"},
    )

    assert response.status_code == 200, response.content
    payload = response.json()
    assert "errors" not in payload, payload
    assert payload["data"] == {
        "me": {"username": "yhral"},
        "character": {"level": 120},
    }
