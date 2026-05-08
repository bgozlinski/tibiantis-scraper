from typing import cast

import strawberry
import strawberry_django
from strawberry import auto

from apps.bedmages.models import BedmageWatch
from apps.bedmages.services import (
    add_bedmage_watch,
    remove_bedmage_watch,
)
from apps.characters.schema import CharacterType


@strawberry_django.type(BedmageWatch)
class BedmageWatchType:
    id: auto
    created_at: auto
    last_notified_login: auto
    active: auto
    character: CharacterType


@strawberry.type
class Query:
    @strawberry.field
    async def my_bedmages(self, info: strawberry.Info) -> list[BedmageWatchType]:
        request = info.context.request
        if not request.user.is_authenticated:
            raise PermissionError("Authentication required")

        qs = (
            BedmageWatch.objects.filter(user=request.user)
            .select_related("character")
            .order_by("-created_at")
        )
        return cast("list[BedmageWatchType]", [w async for w in qs])


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def add_bedmage_watch(
        self, info: strawberry.Info, character_name: str
    ) -> BedmageWatchType:
        request = info.context.request
        if not request.user.is_authenticated:
            raise PermissionError("Authentication required")

        from asgiref.sync import sync_to_async

        watch = await sync_to_async(add_bedmage_watch)(request.user, character_name)
        return cast("BedmageWatchType", watch)

    @strawberry.mutation
    async def remove_bedmage_watch(
        self, info: strawberry.Info, character_name: str
    ) -> bool:
        request = info.context.request
        if not request.user.is_authenticated:
            raise PermissionError("Authentication required")

        from asgiref.sync import sync_to_async

        deleted = await sync_to_async(remove_bedmage_watch)(
            request.user, character_name
        )
        return deleted
