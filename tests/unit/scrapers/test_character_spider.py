"""Offline tests for CharacterSpider — parses fixture HTML via HtmlResponse."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pytest
from scrapy.http import HtmlResponse, Request

from scrapers.tibiantis_scrapers.spiders.character_spider import CharacterSpider

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "character_yhral.html"
)


def _build_character_html(rows: dict[str, str]) -> bytes:
    """Build a minimal character-page body containing a `table.tabi` with the given rows.

    Matches the structure the spider actually reads: `table.tabi tr.hover` with
    `td:first-child` label and `td:nth-child(2)` value. Other rows on the real
    page are ignored by the spider, so we omit them.
    """
    tr_html = "".join(
        f"<tr class='hover'><td>{label}:</td><td>{value}</td></tr>"
        for label, value in rows.items()
    )
    body = (
        "<html><body>"
        "<table class='tabi'>"
        "<tr><td colspan='2'><b>Character Information</b></td></tr>"
        f"{tr_html}"
        "</table>"
        "</body></html>"
    )
    return body.encode("utf-8")


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


def test_parse_high_level_character_with_long_guild() -> None:
    """Edge case — level well above 118 and a long guild string parse cleanly."""
    rows = {
        "Name": "Powerlevel",
        "Sex": "male",
        "Vocation": "Elite Knight",
        "Level": "999",
        "World": "Concordia",
        "Residence": "Thais",
        "House": "Magician's Alley 7",
        "Guild Membership": (
            "Grandmaster of the <a href='?page=showguild&id=1'>"
            "Very Long Guild Name Approaching The 128 Char Limit Of The Field</a>"
        ),
        "Last Login": "20 Apr 2026 14:15:16 CEST",
        "Account Status": "Premium Account",
    }
    response = HtmlResponse(
        url="https://tibiantis.online/?page=character&name=Powerlevel",
        body=_build_character_html(rows),
        encoding="utf-8",
    )
    spider = CharacterSpider(name="Powerlevel")

    item = next(iter(spider.parse(response)))

    assert item["level"] == 999
    assert isinstance(item["level"], int)
    assert item[
        "guild_membership"
    ]  # anchor text extracted by the nth-child(2) a::text path
    assert (
        len(item["guild_membership"]) < 128
    )  # stays within Character.guild_membership max_length


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known bug from #7 retro — _parse_last_login calls rsplit/strptime "
        "unconditionally and raises ValueError on 'Never logged in'. "
        "Remove xfail after the bug is fixed."
    ),
)
def test_parse_character_never_logged_handles_gracefully() -> None:
    """Fresh characters have `Last Login: Never logged in` — spider must not crash.

    Expected behavior after fix: yield one item with last_login=None.
    """
    rows = {
        "Name": "Newbie",
        "Sex": "female",
        "Vocation": "None",
        "Level": "1",
        "World": "Concordia",
        "Residence": "Thais",
        "House": "",
        "Guild Membership": "",
        "Last Login": "Never logged in",
        "Account Status": "Free Account",
    }
    response = HtmlResponse(
        url="https://tibiantis.online/?page=character&name=Newbie",
        body=_build_character_html(rows),
        encoding="utf-8",
    )
    spider = CharacterSpider(name="Newbie")

    items = list(spider.parse(response))

    assert len(items) == 1
    assert items[0]["last_login"] is None
    assert items[0]["name"] == "Newbie"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known bug from #7 retro — `self.logger.warning(f'Character not found: "
        "{self.name}')` uses the spider class attr ('character') instead of "
        "self.character_name. Remove xfail after the bug is fixed."
    ),
)
def test_warning_log_contains_queried_character_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`not found` warning must name the queried character, not the spider itself."""
    body = b"<html><body><div>404</div></body></html>"
    response = HtmlResponse(
        url="https://tibiantis.online/?page=character&name=Ghost",
        body=body,
        encoding="utf-8",
    )
    spider = CharacterSpider(name="Ghost")

    with caplog.at_level(logging.WARNING, logger=spider.logger.logger.name):
        list(spider.parse(response))

    assert any("Ghost" in record.getMessage() for record in caplog.records)


def test_spider_settings_respect_contact_and_throttling() -> None:
    """Scrapy settings module enforces the netiquette rules from CLAUDE.md §6."""
    from scrapers.tibiantis_scrapers import settings as scrapy_settings

    assert scrapy_settings.USER_AGENT.startswith("TibiantisMonitor/")
    assert "contact" in scrapy_settings.USER_AGENT.lower()
    assert scrapy_settings.ROBOTSTXT_OBEY is True
    assert scrapy_settings.DOWNLOAD_DELAY >= 2.0
    assert scrapy_settings.CONCURRENT_REQUESTS_PER_DOMAIN == 1


def test_item_fields_match_model_fields() -> None:
    """CharacterItem must expose the same fields the Character model persists.

    Drift between the scraper boundary and the ORM shape is a common bug
    source in Scrapy pipelines — guard against it at the type-system level.
    """
    from apps.characters.models import Character
    from scrapers.tibiantis_scrapers.items import CharacterItem

    item_fields = set(CharacterItem.fields.keys())
    model_fields = {
        f.name
        for f in Character._meta.get_fields()
        if f.name not in {"id", "last_scraped_at"}  # auto-managed, not scraped
    }

    assert item_fields == model_fields, (
        f"Drift between CharacterItem and Character model. "
        f"Only in item: {item_fields - model_fields}. "
        f"Only in model: {model_fields - item_fields}."
    )
