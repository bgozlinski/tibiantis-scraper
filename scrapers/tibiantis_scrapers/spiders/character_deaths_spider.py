"""Spider parsing the "Latest Deaths" section of tibiantis.online character profiles.

DW-3 — emits one `CharacterDeathItem` per row in the Latest Deaths table.
Pipeline route (DW-4) calls `apps.deathwatch.services.record_watched_death`
which applies the "po dodaniu" filter (§3.6).
"""

from __future__ import annotations

import re

import scrapy

from scrapers.tibiantis_scrapers.items import CharacterDeathItem
from scrapers.tibiantis_scrapers.utils.dates import parse_tibiantis_timestamp

_DEATH_TEXT_RE = re.compile(r"Killed at Level (\d+)(?: by (.+?))?\.?$")


class CharacterDeathsSpider(scrapy.Spider):
    name = "character_deaths"

    def __init__(self, name=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not name:
            raise ValueError("CharacterDeathsSpider requires -a name=<character>")
        self.character_name = name
        self.start_urls = [f"https://tibiantis.online/?page=character&name={name}"]

    def parse(self, response):
        """Locate the Latest Deaths table and yield one item per data row.

        Selector strategy: find the `<table class="tabi">` whose first row
        contains the bold "Latest Deaths" heading, then iterate `tr.hover`
        siblings. Avoids brittle dependence on the table's position in the
        page — the profile has multiple `.tabi` tables in non-fixed order.
        """
        deaths_table = response.xpath(
            '//table[contains(@class,"tabi")][.//b[normalize-space(text())="Latest Deaths"]]'
        )
        if not deaths_table:
            self.logger.info("No Latest Deaths section for %s", self.character_name)
            return

        rows = deaths_table.css("tr.hover")
        for row in rows:
            timestamp_raw = row.css("td:nth-child(1)::text").get("").strip()
            died_at = parse_tibiantis_timestamp(timestamp_raw)
            if died_at is None:
                self.logger.warning(
                    "Unparseable death timestamp for %s: %r",
                    self.character_name,
                    timestamp_raw,
                )
                continue

            death_text = " ".join(row.css("td:nth-child(2) ::text").getall()).strip()
            level, killer = self._parse_death_text(death_text)

            item = CharacterDeathItem()
            item["character_name"] = self.character_name
            item["died_at"] = died_at
            item["level_at_death"] = level
            item["killed_by"] = killer
            yield item

    @staticmethod
    def _parse_death_text(text: str) -> tuple[int, str]:
        """Parse "Killed at Level 128 by a giant crayfish." → (128, "a giant crayfish").

        Returns (0, "") on no-match — defensive, logged upstream. The trailing
        period is optional in the regex because some rare entries omit it.
        """
        match = _DEATH_TEXT_RE.match(text.strip())
        if not match:
            return 0, ""
        level = int(match.group(1))
        killer = (match.group(2) or "").strip()
        return level, killer
