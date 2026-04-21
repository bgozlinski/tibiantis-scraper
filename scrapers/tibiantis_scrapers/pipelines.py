from asgiref.sync import sync_to_async


class DjangoPipeline:
    async def process_item(self, item, spider):
        from apps.characters.services import upsert_character

        await sync_to_async(upsert_character)(dict(item))
        return item
