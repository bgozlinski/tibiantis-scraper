"""Tests for scrape_deaths management command.

The command spawns a CrawlerProcess and blocks until the spider closes.
Tests must NEVER call the real CrawlerProcess — Twisted's reactor is
single-shot per Python process, so a real run would either hit the live
site or break subsequent tests in the same session. Always mock the class.
"""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command


@pytest.fixture()
def crawler_with_stats() -> MagicMock:
    """A fake crawler whose .stats.get_stats() returns a controllable dict."""
    crawler = MagicMock()
    crawler.stats.get_stats.return_value = {
        "item_scraped_count": 50,
        "custom/death_duplicates": 7,
    }
    return crawler


def test_command_outputs_json_summary_to_stdout(
    crawler_with_stats: MagicMock,
) -> None:
    """Command writes a single JSON line: {"yielded": N, "duplicates": M}.

    D21's Celery task will parse this stdout, so any extra text (Scrapy log
    leaking through, print debug, traceback) breaks downstream consumers.
    """
    out = StringIO()

    with patch(
        "apps.deaths.management.commands.scrape_deaths.CrawlerProcess"
    ) as mock_process_cls:
        mock_process = MagicMock()
        mock_process.create_crawler.return_value = crawler_with_stats
        mock_process_cls.return_value = mock_process

        call_command("scrape_deaths", stdout=out)

    payload = json.loads(out.getvalue().strip())
    assert payload == {"yielded": 50, "duplicates": 7}


def test_command_dispatches_deaths_spider() -> None:
    """Verify the command actually crawls DeathsSpider, not some other class.

    Easy regression: someone refactors and the import at the top of the
    command shifts — the test pinpoints the issue without a live HTTP run.
    """
    out = StringIO()

    with patch(
        "apps.deaths.management.commands.scrape_deaths.CrawlerProcess"
    ) as mock_process_cls:
        from apps.deaths.management.commands.scrape_deaths import (
            DeathsSpider,
        )

        mock_process = MagicMock()
        mock_process.create_crawler.return_value = MagicMock(
            stats=MagicMock(get_stats=MagicMock(return_value={}))
        )
        mock_process_cls.return_value = mock_process

        call_command("scrape_deaths", stdout=out)

        mock_process.create_crawler.assert_called_once_with(DeathsSpider)


def test_command_disables_scrapy_root_log_handler() -> None:
    """Pułapka D from Issue #80 — install_root_handler=False must be set.

    Without it Scrapy installs a global logging handler that overrides
    Django's logging config and writes Scrapy chatter to stdout, which
    corrupts the JSON line that D21 will parse. Pin this contract in a test
    so a refactor that drops the kwarg fails CI immediately.
    """
    out = StringIO()

    with patch(
        "apps.deaths.management.commands.scrape_deaths.CrawlerProcess"
    ) as mock_process_cls:
        mock_process = MagicMock()
        mock_process.create_crawler.return_value = MagicMock(
            stats=MagicMock(get_stats=MagicMock(return_value={}))
        )
        mock_process_cls.return_value = mock_process

        call_command("scrape_deaths", stdout=out)

        _args, kwargs = mock_process_cls.call_args
        assert kwargs.get("install_root_handler") is False


def test_command_defaults_to_zero_when_stats_missing_keys() -> None:
    """Stats dict can lack keys when the spider closes before yielding (HTTP
    error, network timeout). The summary must still be valid JSON with zeros,
    not blow up with KeyError.
    """
    out = StringIO()

    with patch(
        "apps.deaths.management.commands.scrape_deaths.CrawlerProcess"
    ) as mock_process_cls:
        mock_process = MagicMock()
        mock_process.create_crawler.return_value = MagicMock(
            stats=MagicMock(get_stats=MagicMock(return_value={}))
        )
        mock_process_cls.return_value = mock_process

        call_command("scrape_deaths", stdout=out)

    payload = json.loads(out.getvalue().strip())
    assert payload == {"yielded": 0, "duplicates": 0}


def test_command_handles_none_stats_collector_gracefully() -> None:
    """Scrapy types ``crawler.stats`` as ``StatsCollector | None`` — None
    when the stats handler is unregistered or process closed early. Command
    must still emit valid JSON (with zeros), not raise — D21's Celery task
    parses stdout and a traceback there would mask the real failure.
    """
    out = StringIO()

    with patch(
        "apps.deaths.management.commands.scrape_deaths.CrawlerProcess"
    ) as mock_process_cls:
        mock_process = MagicMock()
        crawler = MagicMock()
        crawler.stats = None
        mock_process.create_crawler.return_value = crawler
        mock_process_cls.return_value = mock_process

        call_command("scrape_deaths", stdout=out)

    payload = json.loads(out.getvalue().strip())
    assert payload == {"yielded": 0, "duplicates": 0}
