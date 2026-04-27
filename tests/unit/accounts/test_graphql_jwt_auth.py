"""Tests for JWT-based authentication on /graphql/ via JWTAsyncGraphQLView.

D11 testowało `me` przez `force_login` (session). D12 dopina JWT — te testy
sprawdzają że `me` zwraca usera dla validnego Bearera, null dla invalid,
null dla expired.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User


GRAPHQL_URL = "/graphql/"


async def _post_me(client: AsyncClient, bearer: str | None) -> dict[str, object]:
    headers = {"Authorization": f"Bearer {bearer}"} if bearer is not None else {}
    response = await client.post(
        GRAPHQL_URL,
        data=json.dumps({"query": "{ me { username } }"}),
        content_type="application/json",
        headers=headers,
    )
    assert response.status_code == 200, response.content
    return response.json()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_me_with_valid_bearer_returns_user() -> None:
    """`me` z poprawnym JWT zwraca dane usera — JWT-first path."""
    user = await sync_to_async(User.objects.create_user)(
        username="yhral", email="yhral@example.com", password="KomplexHaslo!23"
    )
    access = await sync_to_async(lambda: str(AccessToken.for_user(user)))()

    payload = await _post_me(AsyncClient(), access)

    assert "errors" not in payload
    assert payload["data"] == {"me": {"username": "yhral"}}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_me_with_invalid_bearer_returns_null() -> None:
    """Zły token (np. random string) → AuthenticationFailed → AnonymousUser → null."""
    payload = await _post_me(AsyncClient(), "this.is.not.a.valid.jwt")

    assert "errors" not in payload
    assert payload["data"] == {"me": None}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_me_with_expired_bearer_returns_null() -> None:
    """Token wygasły → AuthenticationFailed (TokenError) → AnonymousUser → null.

    `set_exp(lifetime=timedelta(seconds=-1))` cofa exp w przeszłość zachowując
    walidny podpis — trafia w gałąź TokenExpired w simplejwt, nie w InvalidToken.
    """
    user = await sync_to_async(User.objects.create_user)(
        username="yhral", email="yhral@example.com", password="KomplexHaslo!23"
    )

    def _expired_token() -> str:
        token = AccessToken.for_user(user)
        token.set_exp(lifetime=timedelta(seconds=-1))
        return str(token)

    expired = await sync_to_async(_expired_token)()

    payload = await _post_me(AsyncClient(), expired)

    assert "errors" not in payload
    assert payload["data"] == {"me": None}
