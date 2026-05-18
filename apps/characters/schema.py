"""GraphQL schema for the characters app.

Exposes a single read endpoint — fetching a character by name — and lets
clients project any subset of the scraped profile fields.
"""

import strawberry
import strawberry_django
from strawberry import auto
from apps.characters.models import Character
from typing import cast


@strawberry_django.type(Character)
class CharacterType:
    """GraphQL projection of :class:`apps.characters.models.Character`."""

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
    """Root query for the characters app."""

    @strawberry.field
    async def character(self, name: str) -> CharacterType | None:
        """Return the character matching ``name`` exactly, or ``None``.

        The lookup is case-sensitive against the canonicalised name stored
        in the DB — pass the name in the form the bot/UI uses, not in raw
        user input casing.
        """
        result = await Character.objects.filter(name=name).afirst()
        return cast("CharacterType | None", result)
