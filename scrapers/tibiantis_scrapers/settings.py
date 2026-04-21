import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

BOT_NAME = "tibiantis_scrapers"

SPIDER_MODULES = ["scrapers.tibiantis_scrapers.spiders"]
NEWSPIDER_MODULE = "scrapers.tibiantis_scrapers.spiders"

USER_AGENT = "TibiantisMonitor/1.0 (contact: bartlomiej.gozlinski@gmail.com)"
ROBOTSTXT_OBEY = True
DOWNLOAD_DELAY = 2.5
CONCURRENT_REQUESTS_PER_DOMAIN = 1

ITEM_PIPELINES = {
    "scrapers.tibiantis_scrapers.pipelines.DjangoPipeline": 300,
}

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
