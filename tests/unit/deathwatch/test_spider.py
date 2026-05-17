"""Offline tests for CharacterDeathsSpider — fixture HTML via HtmlResponse.

Reuses `tests/fixtures/character_yhral.html` (M1 fixture) — it already has a
"Latest Deaths" section with one death. Tests requiring >=2 deaths build a
synthetic in-test fixture via `_build_character_with_deaths_html` (mirror of
`_build_character_html` in test_character_spider.py).

CLAUDE.md §15.6: never hit live Tibiantis in CI.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from scrapy.http import HtmlResponse, Request

from scrapers.tibiantis_scrapers.spiders.character_deaths_spider import (
    CharacterDeathsSpider,
)

YHRAL_FIXTURE = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "character_yhral.html"
)


def _build_character_with_deaths_html(deaths: list[tuple[str, str]]) -> bytes:
    """Build minimal page body containing a 'Latest Deaths' table with given rows.

    Each tuple is (timestamp_raw, death_text). Mirrors the real markup layout:
    `<table class="tabi">` with first row containing `<b>Latest Deaths</b>`,
    subsequent rows `<tr class='hover'><td>{timestamp}</td><td>{text}</td></tr>`.
    """
    death_rows = "".join(
        f"<tr class='hover'><td>{ts}</td><td>{text}</td></tr>" for ts, text in deaths
    )
    return (
        "<html><body>"
        # Profile table (spider doesn't read it but real markup has it)
        "<table class='tabi'>"
        "<tr><td colspan='2'><b>Character Information</b></td></tr>"
        "<tr class='hover'><td>Name:</td><td>Yhral</td></tr>"
        "</table>"
        "<br /><br />"
        # Latest Deaths table — what the spider targets
        "<table class='tabi'>"
        "<tr><td colspan='2'><b>Latest Deaths</b></td></tr>"
        f"{death_rows}"
        "</table>"
        "</body></html>"
    ).encode("utf-8")


@pytest.fixture
def yhral_response() -> HtmlResponse:
    """Real-world snapshot from M1: one death entry in Latest Deaths."""
    body = YHRAL_FIXTURE.read_bytes()
    request = Request(url="https://tibiantis.online/?page=character&name=Yhral")
    return HtmlResponse(
        url=request.url,
        body=body,
        encoding="utf-8",
        request=request,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Sanity / argument handling
# ──────────────────────────────────────────────────────────────────────────────


def test_spider_requires_name_arg() -> None:
    """Spider raises if -a name= is missing (matches CharacterSpider behaviour)."""
    with pytest.raises(ValueError, match="name"):
        CharacterDeathsSpider()


def test_spider_start_url_is_tibiantis_online() -> None:
    spider = CharacterDeathsSpider(name="Yhral")
    assert spider.start_urls == ["https://tibiantis.online/?page=character&name=Yhral"]


# ──────────────────────────────────────────────────────────────────────────────
# Single-death fixture (M1 character_yhral.html snapshot)
# ──────────────────────────────────────────────────────────────────────────────


def test_parse_yields_one_item_from_yhral_fixture(
    yhral_response: HtmlResponse,
) -> None:
    """character_yhral.html has exactly one Latest Deaths row."""
    spider = CharacterDeathsSpider(name="Yhral")
    items = list(spider.parse(yhral_response))

    assert len(items) == 1
    item = items[0]
    assert item["character_name"] == "Yhral"
    assert item["level_at_death"] == 115
    assert item["killed_by"] == "a deathslicer"


def test_parsed_died_at_is_europe_berlin_tz(yhral_response: HtmlResponse) -> None:
    """died_at parses to tz-aware datetime in Europe/Berlin (matches CEST suffix)."""
    spider = CharacterDeathsSpider(name="Yhral")
    item = next(iter(spider.parse(yhral_response)))

    assert isinstance(item["died_at"], datetime)
    assert item["died_at"].tzinfo == ZoneInfo("Europe/Berlin")
    # Fixture timestamp: "12 Apr 2026 23:25:53 CEST"
    assert item["died_at"] == datetime(
        2026,
        4,
        12,
        23,
        25,
        53,
        tzinfo=ZoneInfo("Europe/Berlin"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Multi-death synthetic fixture
# ──────────────────────────────────────────────────────────────────────────────


def test_parse_yields_item_per_death_row() -> None:
    """Multi-death page → one item per row, preserving order."""
    body = _build_character_with_deaths_html(
        [
            ("07 May 2026 16:15:46 CEST", "Killed at Level 128 by a giant crayfish."),
            ("05 May 2026 00:11:11 CEST", "Killed at Level 127 by a dragon."),
        ]
    )
    response = HtmlResponse(url="https://x/", body=body, encoding="utf-8")
    spider = CharacterDeathsSpider(name="Yhral")
    items = list(spider.parse(response))

    assert len(items) == 2
    assert items[0]["level_at_death"] == 128
    assert items[0]["killed_by"] == "a giant crayfish"
    assert items[1]["level_at_death"] == 127
    assert items[1]["killed_by"] == "a dragon"


def test_parse_handles_winter_cet_timezone() -> None:
    """CET (winter) deaths parse correctly — DST transition not hardcoded."""
    body = _build_character_with_deaths_html(
        [("10 Dec 2025 22:00:00 CET", "Killed at Level 50 by an orc.")]
    )
    response = HtmlResponse(url="https://x/", body=body, encoding="utf-8")
    spider = CharacterDeathsSpider(name="Yhral")
    item = next(iter(spider.parse(response)))

    assert item["died_at"] == datetime(
        2025,
        12,
        10,
        22,
        0,
        0,
        tzinfo=ZoneInfo("Europe/Berlin"),
    )


def test_parse_handles_no_deaths_section() -> None:
    """Page without Latest Deaths section → no items, no crash."""
    body = (
        b"<html><body>"
        b"<table class='tabi'>"
        b"<tr><td colspan='2'><b>Character Information</b></td></tr>"
        b"</table>"
        b"</body></html>"
    )
    response = HtmlResponse(url="https://x/", body=body, encoding="utf-8")
    spider = CharacterDeathsSpider(name="Yhral")
    items = list(spider.parse(response))

    assert items == []


def test_parse_skips_row_with_unparseable_timestamp() -> None:
    """Defensive: malformed timestamp row dropped, valid rows kept."""
    body = _build_character_with_deaths_html(
        [
            ("WHATEVER", "Killed at Level 100 by a noob."),
            ("07 May 2026 16:15:46 CEST", "Killed at Level 128 by a dragon."),
        ]
    )
    response = HtmlResponse(url="https://x/", body=body, encoding="utf-8")
    spider = CharacterDeathsSpider(name="Yhral")
    items = list(spider.parse(response))

    # First row dropped (bad timestamp), second kept
    assert len(items) == 1
    assert items[0]["level_at_death"] == 128
