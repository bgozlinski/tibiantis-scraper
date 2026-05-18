"""Scrapy item definitions for the Tibiantis spiders.

Items are deliberately schema-less ``Item`` subclasses — typing happens at the
service boundary via the ``TypedDict`` payloads in ``apps/*/types.py``.
"""

from scrapy import Item, Field


class CharacterItem(Item):
    """Profile fields emitted by :class:`CharacterSpider`."""

    name = Field()
    sex = Field()
    vocation = Field()
    level = Field()
    world = Field()
    residence = Field()
    house = Field()
    guild_membership = Field()
    last_login = Field()
    account_status = Field()


class DeathItem(Item):
    """A row from the global ``tibiantis.info`` deaths feed."""

    character_name = Field()
    level_at_death = Field()
    killed_by = Field()
    died_at = Field()


class CharacterDeathItem(Item):
    """Death emitted by `character_deaths_spider` (DW-3) parsing the "Latest
    Deaths" section on `tibiantis.online` character profile pages.

    Shape mirrors `DeathItem` (M4) but is a distinct type so the pipeline can
    route it to `apps.deathwatch.services.record_watched_death` rather than
    `apps.deaths.services.save_death_event`. Spec §3.4 — full separation from
    M4 deaths feature.
    """

    character_name = Field()
    level_at_death = Field()
    killed_by = Field()
    died_at = Field()
