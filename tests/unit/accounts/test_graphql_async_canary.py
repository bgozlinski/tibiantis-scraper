"""Async canary for /graphql/ — wcześnie łapie SynchronousOnlyOperation.

AsyncGraphQLView trzyma resolvery w event-loopie. Każde sync ORM query bez
`sync_to_async` rzuci `django.core.exceptions.SynchronousOnlyOperation` —
jeśli ktoś (świadomie lub przez auto-wrap Strawberry-Django) zepsuje to w
przyszłości, ten test pęknie zanim D12 (JWT + character query) zacznie to
maskować swoją złożonością.
"""

from __future__ import annotations

import json

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient

from apps.accounts.models import User


GRAPHQL_URL = "/graphql/"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_me_resolver_serves_full_user_payload_through_async_view() -> None:
    """Pełny end-to-end flow przez AsyncClient: auth + serializacja wszystkich pól UserType.

    Każde pole UserType (`username`, `email`, `date_joined`, `discord_id`) to
    osobny atrybut modelu — Strawberry-Django w trakcie odpowiedzi czyta je z
    `request.user` (Django LazyObject). Jeśli którykolwiek attribute access
    pociągnie sync ORM call w async kontekście, dostaniemy
    `SynchronousOnlyOperation` zamiast 200 — czyli właśnie to co canary łapie.

    Dodatkowo wykonujemy native async ORM query (`User.objects.acount()`),
    żeby potwierdzić że ścieżka async ORM w ogóle żyje w tym setupie testów.
    """
    await sync_to_async(User.objects.create_user)(
        username="yhral", email="yhral@example.com", password="KomplexHaslo!23"
    )

    user_count = await User.objects.acount()
    assert user_count == 1

    user = await User.objects.aget(username="yhral")
    client = AsyncClient()
    await sync_to_async(client.force_login)(user)

    response = await client.post(
        GRAPHQL_URL,
        data=json.dumps({"query": "{ me { username email dateJoined discordId } }"}),
        content_type="application/json",
    )

    assert response.status_code == 200, response.content
    payload = response.json()
    assert "errors" not in payload, payload
    me = payload["data"]["me"]
    assert me["username"] == "yhral"
    assert me["email"] == "yhral@example.com"
    assert me["dateJoined"] is not None
    assert me["discordId"] is None
