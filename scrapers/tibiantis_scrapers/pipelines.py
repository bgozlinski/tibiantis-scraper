"""Scrapy item pipeline that hands every item to the Django service layer.

CLAUDE.md §6 forbids spiders from touching the Django ORM directly — the
pipeline is the only place that bridges Scrapy items into ``apps.*.services``.
"""

from asgiref.sync import sync_to_async
from scrapers.tibiantis_scrapers.items import (
    CharacterDeathItem,
    CharacterItem,
    DeathItem,
)


class DjangoPipeline:
    """Route each item type to the right Django service function.

    Service calls are sync, but the Scrapy 2.11+ pipeline interface is async,
    hence the ``sync_to_async`` wrapper around every dispatch.
    """

    async def process_item(self, item, spider):
        """Dispatch ``item`` to the matching service and return it unchanged."""
        if isinstance(item, CharacterItem):
            from apps.characters.services import upsert_character

            await sync_to_async(upsert_character)(dict(item))

        elif isinstance(item, DeathItem):
            from apps.deaths.services import save_death_event

            result = await sync_to_async(save_death_event)(dict(item))
            if result is None:
                spider.crawler.stats.inc_value("custom/death_duplicates")

        elif isinstance(item, CharacterDeathItem):
            # DW-4: route to deathwatch services. record_watched_death applies
            # the §3.6 "po dodaniu" filter — returns None for items that
            # don't qualify (no active watch, died before watch.created_at,
            # missing Character, or unique-constraint dedup). Spider already
            # emits ALL deaths from the Latest Deaths table; service decides
            # which to persist.
            from apps.deathwatch.services import record_watched_death

            result = await sync_to_async(record_watched_death)(dict(item))
            if result is None:
                spider.crawler.stats.inc_value("custom/watched_death_dropped")

        return item
