"""Offline tests for CharacterSpider — parses fixture HTML via HtmlResponse."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from scrapy.http import HtmlResponse, Request

from scrapers.tibiantis_scrapers.spiders.character_spider import CharacterSpider

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "character_yhral.html"
)


@pytest.fixture
def yhral_response() -> HtmlResponse:
    """Build an HtmlResponse from the saved Yhral character page."""
    body = FIXTURE_PATH.read_bytes()
    request = Request(url="https://tibiantis.online/?page=character&name=Yhral")
    return HtmlResponse(
        url=request.url,
        body=body,
        encoding="utf-8",
        request=request,
    )


def test_parse_yields_character_item(yhral_response: HtmlResponse) -> None:
    """parse() yields exactly one item for a valid character page."""
    spider = CharacterSpider(name="Yhral")
    items = list(spider.parse(yhral_response))

    assert len(items) == 1


def test_parsed_name_matches_yhral(yhral_response: HtmlResponse) -> None:
    """name field is extracted verbatim from the Name: row."""
    spider = CharacterSpider(name="Yhral")
    item = next(iter(spider.parse(yhral_response)))

    assert item["name"] == "Yhral"


def test_parsed_level_is_integer(yhral_response: HtmlResponse) -> None:
    """level is parsed to int (not str) and matches the fixture value."""
    spider = CharacterSpider(name="Yhral")
    item = next(iter(spider.parse(yhral_response)))

    assert isinstance(item["level"], int)
    assert item["level"] == 118


def test_parsed_last_login_is_datetime(yhral_response: HtmlResponse) -> None:
    """last_login is parsed to timezone-aware datetime in Europe/Berlin."""
    spider = CharacterSpider(name="Yhral")
    item = next(iter(spider.parse(yhral_response)))

    last_login = item["last_login"]
    assert isinstance(last_login, datetime)
    assert last_login.tzinfo is not None
    # Fixture says "18 Apr 2026 01:25:30 CEST" → UTC+2 in April
    assert (last_login.year, last_login.month, last_login.day) == (2026, 4, 18)
    assert (last_login.hour, last_login.minute, last_login.second) == (1, 25, 30)


def test_parse_missing_section_yields_nothing() -> None:
    """If Character Information table is absent, parse() yields no items."""
    body = b"<html><body><div>Character does not exist.</div></body></html>"
    response = HtmlResponse(
        url="https://tibiantis.online/?page=character&name=CharacterThatDoesNotExist",
        body=body,
        encoding="utf-8",
    )
    spider = CharacterSpider(name="CharacterThatDoesNotExist")

    items = list(spider.parse(response))

    assert items == []
