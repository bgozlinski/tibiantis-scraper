from asgiref.sync import sync_to_async
from scrapers.tibiantis_scrapers.items import CharacterItem, DeathItem


class DjangoPipeline:
    async def process_item(self, item, spider):
        if isinstance(item, CharacterItem):
            from apps.characters.services import upsert_character

            await sync_to_async(upsert_character)(dict(item))
        elif isinstance(item, DeathItem):
            from apps.deaths.services import save_death_event

            await sync_to_async(save_death_event)(dict(item))
        return item
