"""GraphQL schema for the ``accounts`` app.

Exposes the currently authenticated user through the ``me`` query. Login,
registration and token refresh stay in REST (DRF + SimpleJWT) — GraphQL only
reads identity, never issues credentials.
"""

import strawberry
import strawberry_django
from strawberry import auto
from asgiref.sync import sync_to_async
from typing import cast

from apps.accounts.models import User


@strawberry_django.type(User)
class UserType:
    """GraphQL representation of :class:`apps.accounts.models.User`.

    Only the fields safe to expose publicly are listed — password hashes,
    permission flags and ``is_staff`` are intentionally omitted.
    """

    username: auto
    email: auto
    date_joined: auto
    discord_id: auto


@strawberry.type
class Query:
    """Root query for the accounts app."""

    @strawberry.field
    async def me(self, info: strawberry.Info) -> UserType | None:
        """Return the authenticated user, or ``None`` for anonymous requests.

        The resolver is async because Strawberry runs the schema under ASGI;
        the actual user lookup uses ``sync_to_async`` to read the ORM-managed
        request user.
        """
        request = info.context.request

        def _resolve_user() -> User | None:
            if not request.user.is_authenticated:
                return None
            return cast(User, request.user)

        result = await sync_to_async(_resolve_user)()
        return cast("UserType | None", result)
