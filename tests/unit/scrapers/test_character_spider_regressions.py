"""Regression tests for bugs fixed in issue #21.

These tests exist to **prevent the two bugs from returning**. Unlike the
xfail markers in `test_character_spider.py` (which document known-broken
behavior until a fix lands), these tests assert the *post-fix contract*
and should stay green forever. If they flip to red, someone has re-
introduced a bug that was already fixed once — investigate before merging.
"""

from __future__ import annotations

import logging

import pytest
from scrapy.http import HtmlResponse

from scrapers.tibiantis_scrapers.spiders.character_spider import CharacterSpider


# ------------------------------------------------------------------ Bug 1 ---
# `self.logger.warning(f"Character not found: {self.name}")` used the Spider
# class attribute (`"character"`) instead of the queried character's name
# held in `self.character_name`. Fix lands in #21.


@pytest.mark.parametrize(
    "character_name",
    ["Yhral", "Ghost", "CharacterWithLongerName", "x"],
    ids=["standard", "short", "long", "single-char"],
)
def test_warning_log_names_queried_character_not_spider_class(
    caplog: pytest.LogCaptureFixture, character_name: str
) -> None:
    """Warning must identify the *queried* character, never the spider's class attr.

    Regression guard for #21 Bug 1: loading `self.name` instead of
    `self.character_name`. Uses both a positive assertion (the queried name
    appears) and a negative one (the spider's class attr does *not* leak
    into the message), so renaming either attribute in the future will not
    silently re-introduce the bug.
    """
    body = b"<html><body><div>Character does not exist.</div></body></html>"
    response = HtmlResponse(
        url=f"https://tibiantis.online/?page=character&name={character_name}",
        body=body,
        encoding="utf-8",
    )
    spider = CharacterSpider(name=character_name)

    with caplog.at_level(logging.WARNING):
        list(spider.parse(response))

    messages = [r.getMessage() for r in caplog.records]

    assert any(character_name in msg for msg in messages), (
        f"Expected warning to contain queried name {character_name!r}, "
        f"got: {messages}"
    )
    leaked = [
        msg for msg in messages if f"Character not found: {CharacterSpider.name}" in msg
    ]
    assert not leaked, (
        f"Warning leaked CharacterSpider.name class attr "
        f"({CharacterSpider.name!r}) — Bug 1 from #21 has regressed: {leaked}"
    )


# ------------------------------------------------------------------ Bug 2 ---
# `_parse_last_login` unconditionally called `rsplit(" ", 1)` +
# `strptime(...)`, crashing with ValueError on any non-timestamp input.
# Observed in the wild for freshly-created characters (`Last Login: Never
# logged in`). Fix lands in #21.


@pytest.mark.parametrize(
    "raw_value",
    [
        "",
        "Never logged in",
        "never logged in",
        "NEVER LOGGED IN",
        "  Never logged in  ",
        pytest.param(
            "Unknown",
            marks=pytest.mark.xfail(
                strict=False,
                reason=(
                    "Edge case outside #21 AC (which only mandates 'Never logged "
                    "in' handling). If the fix is ever upgraded to try/except or "
                    "a broader sentinel list, this will XPASS — a signal to "
                    "tighten the contract. Non-strict so CI stays green either way."
                ),
            ),
        ),
    ],
    ids=[
        "empty-string",
        "canonical-casing",
        "lowercase",
        "uppercase",
        "padded-whitespace",
        "other-sentinel[expected-xfail]",
    ],
)
def test_parse_last_login_returns_none_for_non_timestamp_inputs(
    raw_value: str,
) -> None:
    """Non-timestamp inputs must return None, not raise.

    Regression guard for #21 Bug 2. Any value that cannot be parsed as a
    `"DD MMM YYYY HH:MM:SS TZ"` timestamp must fall back to None so `parse()`
    still yields the item (with `last_login=None`) rather than aborting
    mid-iteration.

    The parameter list is deliberately wider than the single `"Never logged in"`
    case the bug was first reported for — a fix that hardcodes exactly that
    string (and breaks on `"NEVER LOGGED IN"`) would pass in the narrow sense
    but ship a half-solution. The ``Unknown`` case documents a broader class
    of malformed inputs outside the strict #21 AC — see its `xfail` reason.
    """
    spider = CharacterSpider(name="Dummy")

    result = spider._parse_last_login(raw_value)

    assert result is None, (
        f"Expected None for raw={raw_value!r}, got {result!r}. "
        f"Bug 2 from #21 has regressed."
    )


def test_parse_last_login_still_parses_valid_timestamp() -> None:
    """Positive control — the fix must not break the happy path.

    Without this guard, a too-aggressive fix (e.g. `return None` unconditionally)
    would pass both of the negative tests above while silently breaking every
    real scrape.
    """
    spider = CharacterSpider(name="Yhral")

    result = spider._parse_last_login("18 Apr 2026 01:25:30 CEST")

    assert result is not None, "Fix regressed — valid timestamp now returns None"
    assert (result.year, result.month, result.day) == (2026, 4, 18)
    assert (result.hour, result.minute, result.second) == (1, 25, 30)
    assert result.tzinfo is not None, "Result must be timezone-aware"
