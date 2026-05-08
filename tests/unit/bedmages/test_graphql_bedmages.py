"""Tests for myBedmages query + addBedmageWatch / removeBedmageWatch mutations.

Mirror of M4-D22 pattern (`tests/unit/deaths/test_graphql_recent_deaths.py`):
JWT auth via `AccessToken.for_user`, AsyncClient against /graphql/, async
resolvers exercised end-to-end.
"""

from __future__ import annotations

import json

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User
from apps.bedmages.models import BedmageWatch
from apps.characters.models import Character

GRAPHQL_URL = "/graphql/"


async def _post_query(
    client: AsyncClient,
    query: str,
    bearer: str | None = None,
) -> dict[str, object]:
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    response = await client.post(
        GRAPHQL_URL,
        data=json.dumps({"query": query}),
        content_type="application/json",
        headers=headers,
    )
    assert response.status_code == 200, response.content
    return response.json()


async def _make_user_and_token(
    username: str = "alice", email: str | None = None
) -> tuple[User, str]:
    user = await sync_to_async(User.objects.create_user)(
        username=username,
        email=email or f"{username}@example.com",
        password="ComplexPass!123",
    )
    bearer = await sync_to_async(lambda: str(AccessToken.for_user(user)))()
    return user, bearer


# === myBedmages query ===


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_my_bedmages_filters_by_request_user() -> None:
    """`myBedmages` returns ONLY the requesting user's watches.

    Security invariant — must never leak other users' bedmage subscriptions
    (would expose social graph + character names). Seeds 2 users with watches,
    queries as user A, asserts B's watch is not returned.
    """
    user_a, bearer_a = await _make_user_and_token("alice")
    user_b, _ = await _make_user_and_token("bob")

    def _seed() -> None:
        char1 = Character.objects.create(name="Yhral")
        char2 = Character.objects.create(name="Tester")
        char3 = Character.objects.create(name="OtherUserChar")
        BedmageWatch.objects.create(user=user_a, character=char1)
        BedmageWatch.objects.create(user=user_a, character=char2)
        BedmageWatch.objects.create(user=user_b, character=char3)

    await sync_to_async(_seed)()

    payload = await _post_query(
        AsyncClient(),
        "{ myBedmages { id character { name } active } }",
        bearer_a,
    )

    assert "errors" not in payload, payload
    watches = payload["data"]["myBedmages"]
    assert len(watches) == 2
    names = sorted(w["character"]["name"] for w in watches)
    assert names == ["Tester", "Yhral"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_my_bedmages_requires_authentication() -> None:
    """No JWT → resolver raises PermissionError → Strawberry surfaces as errors[]."""
    payload = await _post_query(
        AsyncClient(),
        "{ myBedmages { id } }",
        bearer=None,
    )

    assert "errors" in payload
    error_msg = payload["errors"][0]["message"]
    assert "Authentication" in error_msg or "auth" in error_msg.lower()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_my_bedmages_returns_empty_list_for_user_without_watches() -> None:
    """User with 0 watches → empty list, NOT null and NOT error.

    Distinguishes "no subscriptions" from "auth failed" for the client.
    """
    _, bearer = await _make_user_and_token("nobody")

    payload = await _post_query(
        AsyncClient(),
        "{ myBedmages { id } }",
        bearer,
    )

    assert "errors" not in payload, payload
    assert payload["data"]["myBedmages"] == []


# === addBedmageWatch mutation ===


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_add_bedmage_watch_creates_with_existing_character() -> None:
    """Mutation creates BedmageWatch when Character already exists in DB."""
    user, bearer = await _make_user_and_token("alice")
    await sync_to_async(Character.objects.create)(name="Yhral")

    mutation = """
    mutation {
        addBedmageWatch(characterName: "Yhral") {
            id
            active
            character { name }
        }
    }
    """

    payload = await _post_query(AsyncClient(), mutation, bearer)

    assert "errors" not in payload, payload
    data = payload["data"]["addBedmageWatch"]
    assert data["active"] is True
    assert data["character"]["name"] == "Yhral"

    count = await sync_to_async(BedmageWatch.objects.filter(user=user).count)()
    assert count == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_add_bedmage_watch_creates_character_lazily() -> None:
    """§4.1 lazy fetch via GraphQL: Character is auto-created when missing.

    Verifies the get_or_create path in add_bedmage_watch service surfaces
    correctly through the Strawberry mutation — no separate "create character"
    step required from the client.
    """
    _, bearer = await _make_user_and_token("alice")
    pre_count = await sync_to_async(Character.objects.filter(name="NewChar").count)()
    assert pre_count == 0

    mutation = """
    mutation {
        addBedmageWatch(characterName: "NewChar") {
            character { name }
        }
    }
    """

    payload = await _post_query(AsyncClient(), mutation, bearer)

    assert "errors" not in payload, payload
    assert payload["data"]["addBedmageWatch"]["character"]["name"] == "NewChar"

    post_count = await sync_to_async(Character.objects.filter(name="NewChar").count)()
    assert post_count == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_add_bedmage_watch_raises_on_duplicate_active_watch() -> None:
    """Second add for same (user, character) when already active → errors[]."""
    user, bearer = await _make_user_and_token("alice")
    char = await sync_to_async(Character.objects.create)(name="Yhral")
    await sync_to_async(BedmageWatch.objects.create)(
        user=user, character=char, active=True
    )

    mutation = """
    mutation {
        addBedmageWatch(characterName: "Yhral") { id }
    }
    """

    payload = await _post_query(AsyncClient(), mutation, bearer)

    assert "errors" in payload
    assert "already exists" in payload["errors"][0]["message"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_add_bedmage_watch_requires_authentication() -> None:
    """No JWT → mutation refused via PermissionError."""
    mutation = """
    mutation {
        addBedmageWatch(characterName: "Yhral") { id }
    }
    """

    payload = await _post_query(AsyncClient(), mutation, bearer=None)

    assert "errors" in payload
    error_msg = payload["errors"][0]["message"]
    assert "Authentication" in error_msg or "auth" in error_msg.lower()


# === removeBedmageWatch mutation ===


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_remove_bedmage_watch_returns_true_when_existing() -> None:
    """Existing watch → hard delete, return True, row gone from DB."""
    user, bearer = await _make_user_and_token("alice")
    char = await sync_to_async(Character.objects.create)(name="Yhral")
    await sync_to_async(BedmageWatch.objects.create)(user=user, character=char)

    mutation = """
    mutation {
        removeBedmageWatch(characterName: "Yhral")
    }
    """

    payload = await _post_query(AsyncClient(), mutation, bearer)

    assert "errors" not in payload, payload
    assert payload["data"]["removeBedmageWatch"] is True

    remaining = await sync_to_async(
        BedmageWatch.objects.filter(user=user, character=char).count
    )()
    assert remaining == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_remove_bedmage_watch_returns_false_when_not_found() -> None:
    """§4.6 idempotency: missing watch returns False, NOT errors[].

    Lets the UI safely retry/spam remove without surfacing auth-vs-state
    ambiguity to the user.
    """
    _, bearer = await _make_user_and_token("alice")

    mutation = """
    mutation {
        removeBedmageWatch(characterName: "Nonexistent")
    }
    """

    payload = await _post_query(AsyncClient(), mutation, bearer)

    assert "errors" not in payload, payload
    assert payload["data"]["removeBedmageWatch"] is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_remove_bedmage_watch_requires_authentication() -> None:
    """No JWT → mutation refused via PermissionError."""
    mutation = """
    mutation {
        removeBedmageWatch(characterName: "Yhral")
    }
    """

    payload = await _post_query(AsyncClient(), mutation, bearer=None)

    assert "errors" in payload
    error_msg = payload["errors"][0]["message"]
    assert "Authentication" in error_msg or "auth" in error_msg.lower()
