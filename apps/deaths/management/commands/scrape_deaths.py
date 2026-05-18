"""Management command that scrapes the public deaths list.

Always invoked by the Celery ``scrape_deaths`` task in a fresh subprocess so
the Twisted reactor can be reused safely across runs.
"""

import json
from typing import Any

from django.core.management.base import BaseCommand
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from scrapers.tibiantis_scrapers.spiders.deaths_spider import DeathsSpider


class Command(BaseCommand):
    """``manage.py scrape_deaths`` — run the deaths spider once."""

    help = "Scrape latest deaths from tibiantis.info/stats/deaths"

    def handle(self, *args: Any, **options: Any) -> None:
        """Crawl the deaths page and print a JSON summary to stdout.

        The summary (``{"yielded": int, "duplicates": int}``) is parsed by
        the Celery wrapper for observability.
        """
        settings = get_project_settings()
        process = CrawlerProcess(settings=settings, install_root_handler=False)
        crawler = process.create_crawler(DeathsSpider)
        process.crawl(crawler)
        process.start()  # blocks until spider closes

        stats_collector = crawler.stats
        if stats_collector is None:
            self.stdout.write(json.dumps({"yielded": 0, "duplicates": 0}))
            return

        stats = stats_collector.get_stats()
        yielded = stats.get("item_scraped_count", 0)
        duplicates = stats.get("custom/death_duplicates", 0)

        self.stdout.write(json.dumps({"yielded": yielded, "duplicates": duplicates}))
