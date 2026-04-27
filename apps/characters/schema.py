import strawberry
import strawberry_django
from strawberry import auto
from apps.characters.models import Character
from typing import cast


@strawberry_django.type(Character)
class CharacterType:
    name: auto
    sex: auto
    vocation: auto
    level: auto
    world: auto
    residence: auto
    house: auto
    guild_membership: auto
    last_login: auto
    account_status: auto
    last_scraped_at: auto


@strawberry.type
class Query:
    @strawberry.field
    async def character(self, name: str) -> CharacterType | None:
        result = await Character.objects.filter(name=name).afirst()
        return cast("CharacterType | None", result)
