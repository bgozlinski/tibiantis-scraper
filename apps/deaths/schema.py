from typing import cast
import strawberry
import strawberry_django
from django.conf import settings
from strawberry import auto
from apps.deaths.models import DeathEvent


@strawberry_django.type(DeathEvent)
class DeathEventType:
    id: auto
    character_name: auto
    level_at_death: auto
    killed_by: auto
    died_at: auto
    scraped_at: auto


@strawberry.type
class Query:
    @strawberry.field
    async def recent_deaths(
        self,
        info: strawberry.Info,
        min_level: int | None = None,
        limit: int = 50,
    ) -> list[DeathEventType]:
        request = info.context.request
        if not request.user.is_authenticated:
            raise PermissionError("Authentication required")

        effective_min_level = (
            min_level if min_level is not None else settings.DEATH_LEVEL_THRESHOLD
        )
        effective_limit = min(max(limit, 1), 200)

        qs = DeathEvent.objects.filter(
            level_at_death__gte=effective_min_level
        ).order_by("-died_at")[:effective_limit]

        return cast("list[DeathEventType]", [e async for e in qs])
