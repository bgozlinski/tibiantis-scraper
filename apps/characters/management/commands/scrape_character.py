import asyncio
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from twisted.internet import asyncioreactor

asyncioreactor.install()  # type: ignore[no-untyped-call]

from crochet import setup, wait_for  # noqa: E402
from django.core.management.base import BaseCommand  # noqa: E402
from scrapy.crawler import CrawlerRunner  # noqa: E402
from scrapy.utils.project import get_project_settings  # noqa: E402

from argparse import ArgumentParser  # noqa: E402
from typing import Any  # noqa: E402

os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "scrapers.tibiantis_scrapers.settings")
setup()


class Command(BaseCommand):
    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("name", type=str)

    @wait_for(timeout=60.0)
    def _run_crawl(self, name: str) -> Any:
        settings = get_project_settings()
        runner = CrawlerRunner(settings)
        from scrapers.tibiantis_scrapers.spiders.character_spider import CharacterSpider

        return runner.crawl(CharacterSpider, name=name)

    def handle(self, *args: Any, **options: Any) -> None:
        self._run_crawl(options["name"])
        self.stdout.write(self.style.SUCCESS(f"Scraped {options['name']}"))
