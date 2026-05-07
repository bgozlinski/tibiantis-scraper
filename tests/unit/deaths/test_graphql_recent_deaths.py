"""Tests for recentDeaths GraphQL query — JWT auth + threshold + limit + ordering."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient, override_settings
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User
from apps.deaths.models import DeathEvent

GRAPHQL_URL = "/graphql/"


async def _post_query(
    client: AsyncClient, query: str, bearer: str | None = None
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


async def _make_authed_token() -> str:
    user = await sync_to_async(User.objects.create_user)(
        username="tester",
        email="tester@example.com",
        password="ComplexPass!123",
    )
    return await sync_to_async(lambda: str(AccessToken.for_user(user)))()


def _create_death(
    *, character_name: str, level: int, died_at, killed_by: str = "test"
) -> DeathEvent:
    return DeathEvent.objects.create(
        character_name=character_name,
        level_at_death=level,
        killed_by=killed_by,
        died_at=died_at,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@override_settings(DEATH_LEVEL_THRESHOLD=30)
async def test_recent_deaths_default_uses_settings_threshold() -> None:
    """Without ``minLevel`` argument — falls back to ``settings.DEATH_LEVEL_THRESHOLD``.

    Seed 3 deaths at levels 20/30/40; with threshold=30, only 30 and 40 should
    surface. Verifies the resolver's `effective_min_level` fallback path.
    """
    bearer = await _make_authed_token()
    now = timezone.now()

    await sync_to_async(_create_death)(
        character_name="Low", level=20, died_at=now - timedelta(seconds=2)
    )
    await sync_to_async(_create_death)(
        character_name="At", level=30, died_at=now - timedelta(seconds=1)
    )
    await sync_to_async(_create_death)(character_name="Over", level=40, died_at=now)

    payload = await _post_query(
        AsyncClient(),
        "{ recentDeaths { characterName levelAtDeath } }",
        bearer,
    )

    assert "errors" not in payload
    deaths = payload["data"]["recentDeaths"]
    assert len(deaths) == 2
    levels = sorted(d["levelAtDeath"] for d in deaths)
    assert levels == [30, 40]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@override_settings(DEATH_LEVEL_THRESHOLD=30)
async def test_recent_deaths_explicit_min_level_overrides_default() -> None:
    """``recentDeaths(minLevel: 1)`` overrides settings — returns all 3 rows."""
    bearer = await _make_authed_token()
    now = timezone.now()

    await sync_to_async(_create_death)(
        character_name="A", level=20, died_at=now - timedelta(seconds=2)
    )
    await sync_to_async(_create_death)(
        character_name="B", level=30, died_at=now - timedelta(seconds=1)
    )
    await sync_to_async(_create_death)(character_name="C", level=40, died_at=now)

    payload = await _post_query(
        AsyncClient(),
        "{ recentDeaths(minLevel: 1) { characterName levelAtDeath } }",
        bearer,
    )

    assert "errors" not in payload
    assert len(payload["data"]["recentDeaths"]) == 3


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_recent_deaths_limit_capped_at_200() -> None:
    """``recentDeaths(limit: 1000)`` — runaway query protection clamps to 200."""
    bearer = await _make_authed_token()
    now = timezone.now()

    def _bulk_seed() -> None:
        events = [
            DeathEvent(
                character_name=f"Char{i}",
                level_at_death=100,
                killed_by="x",
                died_at=now - timedelta(seconds=i),
            )
            for i in range(250)
        ]
        DeathEvent.objects.bulk_create(events)

    await sync_to_async(_bulk_seed)()

    payload = await _post_query(
        AsyncClient(),
        "{ recentDeaths(minLevel: 1, limit: 1000) { id } }",
        bearer,
    )

    assert "errors" not in payload
    assert len(payload["data"]["recentDeaths"]) == 200


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_recent_deaths_limit_clamped_at_1_minimum() -> None:
    """``recentDeaths(limit: 0)`` clamped to 1 — empty result is the wrong answer
    for "I asked for some deaths"; surface 1 instead so callers don't think the
    DB is empty.
    """
    bearer = await _make_authed_token()
    now = timezone.now()

    await sync_to_async(_create_death)(character_name="A", level=100, died_at=now)
    await sync_to_async(_create_death)(
        character_name="B", level=100, died_at=now - timedelta(seconds=1)
    )

    payload = await _post_query(
        AsyncClient(),
        "{ recentDeaths(minLevel: 1, limit: 0) { id } }",
        bearer,
    )

    assert "errors" not in payload
    assert len(payload["data"]["recentDeaths"]) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_recent_deaths_ordered_by_died_at_desc() -> None:
    """Result order = ``died_at`` DESC (newest first). Seed inserts deliberately
    out of order to catch a regression where the ``order_by`` clause is dropped.
    """
    bearer = await _make_authed_token()
    now = timezone.now()

    def _seed_out_of_order() -> None:
        for name, hours_ago in [("Oldest", 3), ("Newest", 1), ("Middle", 2)]:
            DeathEvent.objects.create(
                character_name=name,
                level_at_death=100,
                killed_by="x",
                died_at=now - timedelta(hours=hours_ago),
            )

    await sync_to_async(_seed_out_of_order)()

    payload = await _post_query(
        AsyncClient(),
        "{ recentDeaths(minLevel: 1) { characterName } }",
        bearer,
    )

    assert "errors" not in payload
    names = [d["characterName"] for d in payload["data"]["recentDeaths"]]
    assert names == ["Newest", "Middle", "Oldest"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_recent_deaths_requires_authentication() -> None:
    """No JWT → resolver raises ``PermissionError`` → Strawberry serializes as
    ``errors[]`` field. Distinguishes "auth fail" from "empty result" for the
    client (empty list would be ambiguous with "no deaths matching filter").
    """
    payload = await _post_query(
        AsyncClient(),
        "{ recentDeaths(minLevel: 1) { id } }",
        bearer=None,
    )

    assert "errors" in payload
    error_msg = payload["errors"][0]["message"]
    assert "Authentication" in error_msg or "auth" in error_msg.lower()
