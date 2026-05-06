"""Offline tests for DeathsSpider — parses fixture HTML via HtmlResponse.

Five tests use the saved 50-row fixture (`deaths_sample.html`); four use
synthetic HTML built per-test to cover edge cases (alternative cell
classes, empty tables, broken rows, HTML-escaped killer text).

No live HTTP, no DB — pipeline is bypassed. The spider's parse() is
exercised in isolation; integration with the pipeline is covered in
`test_pipeline.py`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from scrapy.http import HtmlResponse, Request

from scrapers.tibiantis_scrapers.spiders.deaths_spider import DeathsSpider

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "deaths_sample.html"
)

DEATHS_URL = "https://tibiantis.info/stats/deaths"


def _build_deaths_html(rows: list[dict[str, str]]) -> bytes:
    """Build a minimal deaths-page body containing `table.mytab.long` with given rows.

    Each `row` dict supports:
      - name (required), level (required), died_at (required), killer (required)
      - name_class: "ld" (default, lost-level) or "lu" (no-loss)
      - killer_class: "m" (default, mob/NPC) or "md" (PvP highlight)

    The header row is added automatically (spider skips first tr via [1:]).
    """
    tr_html = ""
    for row in rows:
        name_class = row.get("name_class", "ld")
        killer_class = row.get("killer_class", "m")
        tr_html += (
            f"<tr>"
            f"<td class='{name_class}'>"
            f"<a href='/stats/player/{row['name']}'>{row['name']}</a>"
            f" ({row['level']})"
            f"</td>"
            f"<td class='m'><a href='#'><img/></a></td>"
            f"<td class='m'>{row['died_at']}</td>"
            f"<td class='{killer_class}'>{row['killer']}</td>"
            f"</tr>"
        )
    body = (
        "<html><body>"
        "<table class='mytab long'>"
        "<tr><th></th><th></th><th></th><th></th></tr>"
        f"{tr_html}"
        "</table>"
        "</body></html>"
    )
    return body.encode("utf-8")


def _build_response(body: bytes, url: str = DEATHS_URL) -> HtmlResponse:
    request = Request(url=url)
    return HtmlResponse(url=url, body=body, encoding="utf-8", request=request)


@pytest.fixture
def deaths_response() -> HtmlResponse:
    """Build an HtmlResponse from the saved 50-row fixture."""
    return _build_response(FIXTURE_PATH.read_bytes())


# --------------------------------------------------- Fixture-based tests ---


def test_yields_50_deaths(deaths_response: HtmlResponse) -> None:
    """The saved fixture has exactly 50 data rows after the header skip."""
    spider = DeathsSpider()
    items = list(spider.parse(deaths_response))

    assert len(items) == 50


def test_level_extracted_from_parens(deaths_response: HtmlResponse) -> None:
    """First fixture row (Hakin Ace) has '(10)' in td.ld — extract as int 10."""
    spider = DeathsSpider()
    item = next(iter(spider.parse(deaths_response)))

    assert isinstance(item["level_at_death"], int)
    assert item["level_at_death"] == 10
    assert item["character_name"] == "Hakin Ace"


def test_pvp_killer_parsed(deaths_response: HtmlResponse) -> None:
    """First fixture row killer is `<nick>Beaga</nick> (17)` (PvP, td.md class).

    Whole-cell descendant ::text join must capture both the <nick> contents
    and the level-in-parens that sits outside the tag.
    """
    spider = DeathsSpider()
    item = next(iter(spider.parse(deaths_response)))

    killed_by = item["killed_by"]
    assert "Beaga" in killed_by
    assert "(17)" in killed_by


def test_died_at_is_tz_aware_europe_berlin(deaths_response: HtmlResponse) -> None:
    """Spider yields TZ-aware datetime tagged Europe/Berlin (server TZ).

    UTC conversion happens on Django ORM save (USE_TZ=True), not in the
    spider — the spider's contract is "wall-clock + TZ label", nothing more.
    """
    spider = DeathsSpider()
    item = next(iter(spider.parse(deaths_response)))

    died_at = item["died_at"]
    assert isinstance(died_at, datetime)
    assert died_at.tzinfo == ZoneInfo("Europe/Berlin")
    # Fixture row 1: Hakin Ace died 2026-04-30 05:25:12 (Berlin)
    assert (died_at.year, died_at.month, died_at.day) == (2026, 4, 30)
    assert (died_at.hour, died_at.minute, died_at.second) == (5, 25, 12)


def test_no_warnings_on_clean_fixture(
    deaths_response: HtmlResponse, caplog: pytest.LogCaptureFixture
) -> None:
    """Clean fixture (50 valid rows) must not log any per-row parse warnings.

    Belt-and-suspenders for the AC §Spider try/except block: a regression
    that quietly drops rows (e.g. wrong selector picking up cells from
    sibling tables) would emit warnings the user might miss in a live run.
    Asserting zero warnings on the golden fixture catches that.
    """
    spider = DeathsSpider()

    with caplog.at_level(logging.WARNING, logger=spider.logger.logger.name):
        list(spider.parse(deaths_response))

    parse_warnings = [
        r for r in caplog.records if "Invalid death row" in r.getMessage()
    ]
    assert parse_warnings == [], (
        f"Clean fixture must not emit parse warnings, got: "
        f"{[r.getMessage() for r in parse_warnings]}"
    )


# --------------------------------------------------- Synthetic-HTML tests ---


def test_lu_class_row_parsed_same_as_ld() -> None:
    """`td.lu` (no level loss) rows must parse identically to `td.ld`.

    AC §Spider Pułapka A: the name selector must list both `td.ld a::text`
    and `td.lu a::text`. Forgetting `td.lu` silently drops ~8% of fixture
    rows. Synthetic helper exercises this with a single `lu` row.
    """
    body = _build_deaths_html(
        [
            {
                "name": "Lot",
                "level": "20",
                "died_at": "2026-04-29 22:36:22",
                "killer": "a minotaur guard",
                "name_class": "lu",
            }
        ]
    )
    response = _build_response(body)
    spider = DeathsSpider()

    items = list(spider.parse(response))

    assert len(items) == 1
    assert items[0]["character_name"] == "Lot"
    assert items[0]["level_at_death"] == 20
    assert items[0]["killed_by"] == "a minotaur guard"


def test_monster_killer_parsed() -> None:
    """Plain-text killer (no <nick> tag, no parens) parses verbatim."""
    body = _build_deaths_html(
        [
            {
                "name": "Newbie",
                "level": "5",
                "died_at": "2026-04-30 12:00:00",
                "killer": "a slime",
            }
        ]
    )
    response = _build_response(body)
    spider = DeathsSpider()

    items = list(spider.parse(response))

    assert items[0]["killed_by"] == "a slime"


def test_warning_on_empty_table_uses_url(caplog: pytest.LogCaptureFixture) -> None:
    """Empty deaths table emits a warning that includes the response URL.

    Regression guard analogous to M1 #21 Bug 1: the warning must identify
    *what was scraped* (the URL), not the spider's class attr or hardcoded
    string. If the fix devolves into ``logger.warning("deaths empty")``,
    the test catches it.
    """
    body = b"<html><body><table class='mytab long'><tr><th>header</th></tr></table></body></html>"
    response = _build_response(body)
    spider = DeathsSpider()

    with caplog.at_level(logging.WARNING, logger=spider.logger.logger.name):
        list(spider.parse(response))

    messages = [r.getMessage() for r in caplog.records]
    assert any(
        DEATHS_URL in msg for msg in messages
    ), f"Expected warning to contain URL {DEATHS_URL!r}, got: {messages}"


def test_row_parse_error_does_not_kill_batch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One broken row must not terminate the batch — good rows still yield.

    The middle row has the level cell missing the ``(N)`` parens, which
    makes ``_LEVEL_RE.search(...)`` return None and ``group(1)`` raise
    AttributeError — caught by the spider's ``except (AttributeError, ValueError)``.
    The two flanking rows are valid and must yield.
    """
    # Build manually — _build_deaths_html always wraps level in parens.
    broken_row = (
        "<tr>"
        "<td class='ld'>"
        "<a href='/stats/player/Broken'>Broken</a>"
        " no-parens-here"  # intentionally malformed — no (N) match
        "</td>"
        "<td class='m'><a><img/></a></td>"
        "<td class='m'>2026-04-30 12:00:00</td>"
        "<td class='m'>a rat</td>"
        "</tr>"
    )
    good_rows = _build_deaths_html(
        [
            {
                "name": "Alpha",
                "level": "10",
                "died_at": "2026-04-30 11:00:00",
                "killer": "a slime",
            },
            {
                "name": "Omega",
                "level": "20",
                "died_at": "2026-04-30 13:00:00",
                "killer": "a dragon",
            },
        ]
    ).decode("utf-8")
    body = good_rows.replace("</table>", broken_row + "</table>", 1).encode("utf-8")
    response = _build_response(body)
    spider = DeathsSpider()

    with caplog.at_level(logging.WARNING, logger=spider.logger.logger.name):
        items = list(spider.parse(response))

    names = [it["character_name"] for it in items]
    assert "Alpha" in names
    assert "Omega" in names
    assert "Broken" not in names
    assert len(items) == 2

    invalid_warnings = [
        r for r in caplog.records if "Invalid death row" in r.getMessage()
    ]
    assert len(invalid_warnings) == 1


def test_killer_with_html_entities_decoded() -> None:
    """Killer text with HTML entities is decoded by the parser, not double-escaped.

    Scrapy/parsel decodes ``&amp;`` → ``&`` during selector text extraction.
    The spider's ``"".join(...).strip()`` must not re-encode or double-process
    the text — we asserts the raw post-decode form survives.
    """
    body = _build_deaths_html(
        [
            {
                "name": "Casualty",
                "level": "30",
                "died_at": "2026-04-30 14:00:00",
                # In HTML, this becomes "& monster" once parsed
                "killer": "&amp; monster",
            }
        ]
    )
    response = _build_response(body)
    spider = DeathsSpider()

    items = list(spider.parse(response))

    assert items[0]["killed_by"] == "& monster"
