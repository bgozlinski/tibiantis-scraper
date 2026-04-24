import strawberry
import strawberry_django
from strawberry import auto
from asgiref.sync import sync_to_async
from typing import cast

from apps.accounts.models import User


@strawberry_django.type(User)
class UserType:
    username: auto
    email: auto
    date_joined: auto
    discord_id: auto


@strawberry.type
class Query:
    @strawberry.field
    async def me(self, info: strawberry.Info) -> UserType | None:
        request = info.context.request

        def _resolve_user() -> User | None:
            if not request.user.is_authenticated:
                return None
            return cast(User, request.user)

        result = await sync_to_async(_resolve_user)()
        return cast("UserType | None", result)
