"""Tests for myDeathWatches / watchedDeaths queries + DW mutations (DW-8).

Mirror of `tests/unit/bedmages/test_graphql_bedmages.py`: JWT auth via
`AccessToken.for_user`, AsyncClient against /graphql/, async resolvers
exercised end-to-end. Memory: async + DB tests need
`@pytest.mark.django_db(transaction=True)`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User
from apps.characters.models import Character
from apps.deathwatch.models import (
    DeathWatch,
    DeathWatchChannel,
    WatchedDeathEvent,
)

GRAPHQL_URL = "/graphql/"


async def _post(
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
    username: str = "alice",
    is_superuser: bool = False,
) -> tuple[User, str]:
    user = await sync_to_async(User.objects.create_user)(
        username=username,
        email=f"{username}@example.com",
        password="ComplexPass!123",
        is_superuser=is_superuser,
    )
    bearer = await sync_to_async(lambda: str(AccessToken.for_user(user)))()
    return user, bearer


# ═══════════════════════════════════════════════════════════════════════════
# myDeathWatches query
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_my_death_watches_filters_by_request_user() -> None:
    """Security invariant — never leak other users' deathwatch subscriptions."""
    user_a, bearer_a = await _make_user_and_token("alice")
    user_b, _ = await _make_user_and_token("bob")

    def _seed() -> None:
        c1 = Character.objects.create(name="Yhral")
        c2 = Character.objects.create(name="Bubble")
        c3 = Character.objects.create(name="Otherusers")
        DeathWatch.objects.create(user=user_a, character=c1)
        DeathWatch.objects.create(user=user_a, character=c2)
        DeathWatch.objects.create(user=user_b, character=c3)

    await sync_to_async(_seed)()

    payload = await _post(
        AsyncClient(),
        "{ myDeathWatches { id character { name } active } }",
        bearer_a,
    )

    assert "errors" not in payload, payload
    watches = payload["data"]["myDeathWatches"]
    assert len(watches) == 2
    names = sorted(w["character"]["name"] for w in watches)
    assert names == ["Bubble", "Yhral"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_my_death_watches_requires_authentication() -> None:
    payload = await _post(AsyncClient(), "{ myDeathWatches { id } }", bearer=None)
    assert "errors" in payload
    msg = payload["errors"][0]["message"]
    assert "auth" in msg.lower()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_my_death_watches_returns_empty_list_for_user_without_watches() -> None:
    _, bearer = await _make_user_and_token("nobody")
    payload = await _post(AsyncClient(), "{ myDeathWatches { id } }", bearer)
    assert "errors" not in payload, payload
    assert payload["data"]["myDeathWatches"] == []


# ═══════════════════════════════════════════════════════════════════════════
# watchedDeaths query
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_watched_deaths_returns_events_newest_first() -> None:
    _, bearer = await _make_user_and_token("alice")

    def _seed() -> None:
        char = Character.objects.create(name="Yhral")
        base = datetime(2026, 5, 7, 14, 0, 0, tzinfo=ZoneInfo("UTC"))
        for i in range(3):
            WatchedDeathEvent.objects.create(
                character=char,
                level_at_death=100 + i,
                killed_by=f"k{i}",
                died_at=base + timedelta(hours=i),
            )

    await sync_to_async(_seed)()

    payload = await _post(
        AsyncClient(),
        "{ watchedDeaths { levelAtDeath diedAt } }",
        bearer,
    )

    assert "errors" not in payload, payload
    events = payload["data"]["watchedDeaths"]
    assert len(events) == 3
    # Newest first → level 102 → 101 → 100
    assert [e["levelAtDeath"] for e in events] == [102, 101, 100]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_watched_deaths_filters_by_character_name() -> None:
    _, bearer = await _make_user_and_token("alice")

    def _seed() -> None:
        c1 = Character.objects.create(name="Yhral")
        c2 = Character.objects.create(name="Bubble")
        t = timezone.now()
        WatchedDeathEvent.objects.create(
            character=c1, level_at_death=100, killed_by="x", died_at=t
        )
        WatchedDeathEvent.objects.create(
            character=c2,
            level_at_death=50,
            killed_by="y",
            died_at=t - timedelta(minutes=1),
        )

    await sync_to_async(_seed)()

    payload = await _post(
        AsyncClient(),
        '{ watchedDeaths(characterName: "Yhral") { character { name } } }',
        bearer,
    )

    assert "errors" not in payload, payload
    events = payload["data"]["watchedDeaths"]
    assert len(events) == 1
    assert events[0]["character"]["name"] == "Yhral"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_watched_deaths_clamps_limit_to_max_100() -> None:
    """limit > 100 is clamped to 100 (mirror M4 recentDeaths guard)."""
    _, bearer = await _make_user_and_token("alice")

    def _seed() -> None:
        char = Character.objects.create(name="Yhral")
        base = timezone.now()
        for i in range(120):
            WatchedDeathEvent.objects.create(
                character=char,
                level_at_death=50,
                killed_by="x",
                died_at=base - timedelta(seconds=i),
            )

    await sync_to_async(_seed)()

    payload = await _post(
        AsyncClient(),
        "{ watchedDeaths(limit: 500) { id } }",
        bearer,
    )

    assert "errors" not in payload, payload
    assert len(payload["data"]["watchedDeaths"]) == 100


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_watched_deaths_requires_authentication() -> None:
    payload = await _post(AsyncClient(), "{ watchedDeaths { id } }", bearer=None)
    assert "errors" in payload


# ═══════════════════════════════════════════════════════════════════════════
# addDeathWatch mutation
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_add_death_watch_creates_lazy_character() -> None:
    _, bearer = await _make_user_and_token("alice")
    pre = await sync_to_async(Character.objects.filter(name="Newchar").count)()
    assert pre == 0

    mutation = """
    mutation {
        addDeathWatch(characterName: "Newchar") {
            character { name }
            active
        }
    }
    """
    payload = await _post(AsyncClient(), mutation, bearer)

    assert "errors" not in payload, payload
    data = payload["data"]["addDeathWatch"]
    assert data["character"]["name"] == "Newchar"
    assert data["active"] is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_add_death_watch_raises_on_duplicate_active_watch() -> None:
    user, bearer = await _make_user_and_token("alice")
    char = await sync_to_async(Character.objects.create)(name="Yhral")
    await sync_to_async(DeathWatch.objects.create)(
        user=user, character=char, active=True
    )

    mutation = """
    mutation { addDeathWatch(characterName: "Yhral") { id } }
    """
    payload = await _post(AsyncClient(), mutation, bearer)

    assert "errors" in payload
    assert "already active" in payload["errors"][0]["message"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_add_death_watch_requires_authentication() -> None:
    mutation = """
    mutation { addDeathWatch(characterName: "Yhral") { id } }
    """
    payload = await _post(AsyncClient(), mutation, bearer=None)
    assert "errors" in payload


# ═══════════════════════════════════════════════════════════════════════════
# removeDeathWatch mutation
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_remove_death_watch_returns_true_when_existing() -> None:
    user, bearer = await _make_user_and_token("alice")
    char = await sync_to_async(Character.objects.create)(name="Yhral")
    await sync_to_async(DeathWatch.objects.create)(user=user, character=char)

    mutation = 'mutation { removeDeathWatch(characterName: "Yhral") }'
    payload = await _post(AsyncClient(), mutation, bearer)

    assert "errors" not in payload, payload
    assert payload["data"]["removeDeathWatch"] is True

    remaining = await sync_to_async(
        DeathWatch.objects.filter(user=user, character=char).count
    )()
    assert remaining == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_remove_death_watch_returns_false_when_not_found() -> None:
    _, bearer = await _make_user_and_token("alice")
    mutation = 'mutation { removeDeathWatch(characterName: "Nonexistent") }'
    payload = await _post(AsyncClient(), mutation, bearer)

    assert "errors" not in payload, payload
    assert payload["data"]["removeDeathWatch"] is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_remove_death_watch_requires_authentication() -> None:
    mutation = 'mutation { removeDeathWatch(characterName: "Yhral") }'
    payload = await _post(AsyncClient(), mutation, bearer=None)
    assert "errors" in payload


# ═══════════════════════════════════════════════════════════════════════════
# setDeathWatchChannel mutation (superuser only)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_set_death_watch_channel_persists_for_superuser() -> None:
    _, bearer = await _make_user_and_token("admin", is_superuser=True)

    mutation = """
    mutation {
        setDeathWatchChannel(guildId: "555", channelId: "666") {
            guildId
            channelId
        }
    }
    """
    payload = await _post(AsyncClient(), mutation, bearer)

    assert "errors" not in payload, payload
    data = payload["data"]["setDeathWatchChannel"]
    assert data["guildId"] == "555"
    assert data["channelId"] == "666"

    persisted = await sync_to_async(
        DeathWatchChannel.objects.filter(guild_id=555).get
    )()
    assert persisted.channel_id == 666


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_set_death_watch_channel_rejects_non_superuser() -> None:
    """Plain auth user → PermissionError → errors[] (NOT silent persistence)."""
    _, bearer = await _make_user_and_token("normal", is_superuser=False)

    mutation = """
    mutation {
        setDeathWatchChannel(guildId: "555", channelId: "666") { guildId }
    }
    """
    payload = await _post(AsyncClient(), mutation, bearer)

    assert "errors" in payload
    assert "superuser" in payload["errors"][0]["message"].lower()

    nothing = await sync_to_async(DeathWatchChannel.objects.count)()
    assert nothing == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_set_death_watch_channel_handles_64bit_discord_snowflakes() -> None:
    """Guild/channel IDs as String avoid GraphQL Int 32-bit overflow.

    Real Discord snowflakes (e.g. 1234567890123456789) exceed 2^31, so the
    schema accepts them as String. Resolver parses to int for the service call.
    """
    _, bearer = await _make_user_and_token("admin", is_superuser=True)
    # Both values well above 32-bit int max (2^31 - 1 = 2_147_483_647) but
    # below Postgres bigint max (2^63 - 1 = 9.22e18). Real Discord snowflakes
    # live in this range; GraphQL Int would overflow either side.
    big_guild = "1234567890123456789"
    big_channel = "1098765432109876543"

    mutation = f"""
    mutation {{
        setDeathWatchChannel(guildId: "{big_guild}", channelId: "{big_channel}") {{
            guildId
            channelId
        }}
    }}
    """
    payload = await _post(AsyncClient(), mutation, bearer)

    assert "errors" not in payload, payload
    data = payload["data"]["setDeathWatchChannel"]
    assert data["guildId"] == big_guild
    assert data["channelId"] == big_channel
