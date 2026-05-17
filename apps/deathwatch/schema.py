"""GraphQL schema for DeathWatch (DW-8).

Mirror of apps/bedmages/schema.py pattern: Strawberry-Django types + async
resolvers + JWT auth via `info.context.request.user.is_authenticated`.

Distinct from M4 deaths schema (which exposes `recentDeaths` query). Here:
- `myDeathWatches` — user's own per-character subscriptions (private).
- `watchedDeaths` — events that fired through the deathwatch pipeline
   (auth-gated; not a public feed).
- `addDeathWatch` / `removeDeathWatch` — user mutations.
- `setDeathWatchChannel` — superuser-only (admin GraphQL ops, parallel to
   the Discord `/deathwatch channel` slash command).
"""

from __future__ import annotations

from typing import cast

import strawberry
import strawberry_django
from asgiref.sync import sync_to_async
from strawberry import auto

from apps.accounts.models import User
from apps.characters.schema import CharacterType
from apps.deathwatch.models import (
    DeathWatch,
    DeathWatchChannel,
    WatchedDeathEvent,
)
from apps.deathwatch.services import (
    add_death_watch,
    remove_death_watch,
    set_deathwatch_channel_for_guild,
)


@strawberry_django.type(DeathWatch)
class DeathWatchType:
    id: auto
    created_at: auto
    active: auto
    character: CharacterType

    @strawberry.field
    def added_by_discord_id(self) -> str:
        """Discord ID of the user who added this watch (spec §3.2 / §4.4).

        Returns User.discord_id raw — frontend renders as wants (Discord
        `<@id>` mention in bot output, plain string elsewhere). Empty
        string if user has no linked Discord (manual Django admin user).

        `self.user` is a Django FK that Strawberry-Django doesn't expose in
        the generated type signature (we didn't list `user: auto` because we
        don't want to leak User to GraphQL), so mypy can't see it — runtime
        is fine because Strawberry-Django wraps the underlying DeathWatch
        model. Resolver runs in async context, so we pre-loaded `user` via
        `select_related("user", "character")` in the resolver QuerySet.
        """
        return self.user.discord_id or ""  # type: ignore[attr-defined]


@strawberry_django.type(WatchedDeathEvent)
class WatchedDeathEventType:
    id: auto
    level_at_death: auto
    killed_by: auto
    died_at: auto
    scraped_at: auto
    announced_on_discord: auto
    character: CharacterType


@strawberry.type
class DeathWatchChannelType:
    """Per-guild announcement target.

    `guild_id` and `channel_id` rendered as String because Discord snowflakes
    are 64-bit ints and GraphQL Int is 32-bit (spec §4.3 / plan Task #8
    pułapka B). Client deserializes back to int as needed.
    """

    guild_id: str
    channel_id: str


def _require_auth(info: strawberry.Info) -> User:
    request = info.context.request
    if not request.user.is_authenticated:
        raise PermissionError("Authentication required")
    return cast(User, request.user)


def _require_superuser(info: strawberry.Info) -> User:
    user = _require_auth(info)
    if not user.is_superuser:
        raise PermissionError("Superuser required")
    return user


@strawberry.type
class Query:
    @strawberry.field
    async def deathwatches(self, info: strawberry.Info) -> list[DeathWatchType]:
        """All active deathwatches across all users (M12 follow-up).

        Public list — every authenticated client sees every watch + added_by_discord_id.
        Spec §3.4 — semantic break from M12 `myDeathWatches` (per-user filter).
        Project has no external GraphQL consumers, so breaking rename OK.
        """
        _require_auth(info)
        qs = (
            DeathWatch.objects.filter(active=True)
            .select_related("user", "character")
            .order_by("-created_at")
        )
        return cast("list[DeathWatchType]", [w async for w in qs])

    @strawberry.field
    async def watched_deaths(
        self,
        info: strawberry.Info,
        character_name: str | None = None,
        limit: int = 20,
    ) -> list[WatchedDeathEventType]:
        """Authenticated-only feed of deathwatch-recorded events.

        Optional `character_name` filter narrows to one Character. `limit`
        clamped to [1, 100] — same guard pattern as M4 `recentDeaths`.
        """
        _require_auth(info)
        limit = max(1, min(limit, 100))
        qs = WatchedDeathEvent.objects.select_related("character").order_by("-died_at")
        if character_name:
            qs = qs.filter(character__name=character_name)
        return cast("list[WatchedDeathEventType]", [e async for e in qs[:limit]])


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def add_death_watch(
        self, info: strawberry.Info, character_name: str
    ) -> DeathWatchType:
        user = _require_auth(info)
        watch = await sync_to_async(add_death_watch)(user, character_name)
        return cast("DeathWatchType", watch)

    @strawberry.mutation
    async def remove_death_watch(
        self, info: strawberry.Info, character_name: str
    ) -> bool:
        user = _require_auth(info)
        deleted = await sync_to_async(remove_death_watch)(user, character_name)
        return deleted

    @strawberry.mutation
    async def set_death_watch_channel(
        self, info: strawberry.Info, guild_id: str, channel_id: str
    ) -> DeathWatchChannelType:
        """Superuser-only — parallels admin-only `/deathwatch channel` cog.

        `guild_id` / `channel_id` arrive as String because Discord snowflakes
        exceed GraphQL Int range (see DeathWatchChannelType docstring).
        Resolver parses to int for the service call, then renders back to
        String on the response.
        """
        _require_superuser(info)
        channel: DeathWatchChannel = await sync_to_async(
            set_deathwatch_channel_for_guild
        )(guild_id=int(guild_id), channel_id=int(channel_id))
        return DeathWatchChannelType(
            guild_id=str(channel.guild_id),
            channel_id=str(channel.channel_id),
        )
