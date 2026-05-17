from datetime import datetime

import scrapy

from scrapers.tibiantis_scrapers.items import CharacterItem
from scrapers.tibiantis_scrapers.utils.dates import parse_tibiantis_timestamp


class CharacterSpider(scrapy.Spider):
    name = "character"

    def __init__(self, name=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not name:
            raise ValueError("CharacterSpider requires -a name=<character>")

        self.character_name = name
        self.start_urls = [f"https://tibiantis.online/?page=character&name={name}"]

    def _parse_last_login(self, raw: str) -> datetime | None:
        """Thin wrapper kept for backwards-compatibility — tests call this directly.

        Implementation moved to `utils.dates.parse_tibiantis_timestamp` (DW-3)
        for reuse by `character_deaths_spider`.
        """
        return parse_tibiantis_timestamp(raw)

    def parse(self, response):
        rows = response.css("table.tabi tr.hover")

        if not rows:
            self.logger.warning(f"Character not found: {self.character_name}")
            return

        data = {}
        for row in rows:
            key = row.css("td:first-child::text").get("").strip(": ")
            if key == "Guild Membership":
                value = row.css("td:nth-child(2) a::text").get()
            else:
                value = "".join(row.css("td:nth-child(2) ::text").getall()).strip()
            if key:
                data[key] = value

        item = CharacterItem()
        item["name"] = data.get("Name")
        item["sex"] = data.get("Sex")
        item["vocation"] = data.get("Vocation")

        level_raw = data.get("Level")
        item["level"] = int(level_raw) if level_raw else None

        item["world"] = data.get("World")
        item["residence"] = data.get("Residence")
        item["house"] = data.get("House")
        item["guild_membership"] = data.get("Guild Membership")
        item["last_login"] = self._parse_last_login(data.get("Last Login"))
        item["account_status"] = data.get("Account Status")

        yield item
