import re
import scrapy
from scrapers.tibiantis_scrapers.items import DeathItem
from datetime import datetime
from zoneinfo import ZoneInfo


class DeathsSpider(scrapy.Spider):
    name = "deaths"

    _LEVEL_RE = re.compile(r"\((\d+)\)")
    _SET_SERVER_URL = "https://tibiantis.info/index/server/tibiantis/2"  # Concordia
    _DEATHS_URL = "https://tibiantis.info/stats/deaths"

    def start_requests(self):
        # najpierw przełącz sesję na Concordia
        yield scrapy.Request(
            self._SET_SERVER_URL,
            callback=self._after_server_switch,
            dont_filter=True,
        )

    def _after_server_switch(self, response):
        yield scrapy.Request(self._DEATHS_URL, callback=self.parse)

    def parse(self, response):
        rows = response.css("table.mytab.long tr")[1:]

        if not rows:
            self.logger.warning(f"No deaths found at {response.url}")
            return

        for row in rows:
            try:
                character_name = row.css("td.ld a::text, td.lu a::text").get("").strip()
                level_text = "".join(row.css("td.ld::text, td.lu::text").getall())
                level_match = self._LEVEL_RE.search(level_text)
                killed_by = "".join(
                    row.css("td.m:last-child ::text, td.md:last-child ::text").getall()
                ).strip()
                died_at_str = row.css("td:nth-child(3)::text").get("").strip()
                died_at = datetime.strptime(died_at_str, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=ZoneInfo("Europe/Berlin")
                )

                yield DeathItem(
                    character_name=character_name,
                    level_at_death=int(level_match.group(1)),
                    killed_by=killed_by,
                    died_at=died_at,
                )

            except (AttributeError, ValueError):
                self.logger.warning(
                    f"Invalid death row, partial=name={character_name!r}"
                )
                continue
