"""Spider that scrapes a single character profile from ``tibiantis.online``."""

from datetime import datetime

import scrapy

from scrapers.tibiantis_scrapers.items import CharacterItem
from scrapers.tibiantis_scrapers.utils.dates import parse_tibiantis_timestamp


class CharacterSpider(scrapy.Spider):
    """Crawl one character's profile and emit a :class:`CharacterItem`.

    The character name is passed as a Scrapy argument: ``-a name=Yhral``.
    """

    name = "character"

    def __init__(self, name=None, *args, **kwargs):
        """Validate the ``name`` argument and build the start URL."""
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
        """Parse the profile table into a :class:`CharacterItem`.

        Walks the ``<tr class="hover">`` rows of the first ``table.tabi``,
        treating the first cell as the field name and the second cell as the
        value. Returns silently when the page does not contain the expected
        table (e.g. the character does not exist).
        """
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
