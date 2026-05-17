"""Tests for scrapers/utils/dates.py — shared Tibiantis timestamp parser."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scrapers.tibiantis_scrapers.utils.dates import parse_tibiantis_timestamp


def test_parse_tibiantis_timestamp_cest() -> None:
    """CEST suffix (summer time, UTC+2) parses to Europe/Berlin tz-aware datetime."""
    raw = "07 May 2026 16:15:46 CEST"
    result = parse_tibiantis_timestamp(raw)
    expected = datetime(2026, 5, 7, 16, 15, 46, tzinfo=ZoneInfo("Europe/Berlin"))
    assert result == expected


def test_parse_tibiantis_timestamp_cet() -> None:
    """CET suffix (winter time, UTC+1) parses to Europe/Berlin tz-aware datetime."""
    raw = "10 Dec 2025 22:00:00 CET"
    result = parse_tibiantis_timestamp(raw)
    expected = datetime(2025, 12, 10, 22, 0, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    assert result == expected


def test_parse_tibiantis_timestamp_never_returns_none() -> None:
    """'never' / empty string returns None (Tibiantis profile 'Last Login: never')."""
    assert parse_tibiantis_timestamp("never") is None
    assert parse_tibiantis_timestamp("") is None


def test_parse_tibiantis_timestamp_case_insensitive_never() -> None:
    """Case-insensitive 'never' (defensive against future site changes)."""
    assert parse_tibiantis_timestamp("Never") is None
    assert parse_tibiantis_timestamp("NEVER") is None


def test_parse_tibiantis_timestamp_garbage_returns_none() -> None:
    """Unparseable input returns None rather than raising (defensive)."""
    assert parse_tibiantis_timestamp("WHATEVER") is None
    assert parse_tibiantis_timestamp("not a date") is None
    assert parse_tibiantis_timestamp("32 May 2026 99:99:99 CEST") is None
