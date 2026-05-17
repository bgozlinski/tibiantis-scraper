"""Shared date parsers for Tibiantis-emitted timestamps.

Single source of truth — extracted from `character_spider._parse_last_login`
(M1) so the new `character_deaths_spider` (DW-3) can reuse without duplication.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def parse_tibiantis_timestamp(raw: str) -> datetime | None:
    """Parse Tibiantis "DD MMM YYYY HH:MM:SS CEST/CET" → tz-aware datetime.

    Tibiantis displays Europe/Berlin time. `ZoneInfo("Europe/Berlin")` handles
    DST transitions (CEST/CET twice yearly) without needing to inspect the
    trailing TZ token. Returns None for:
    - "never" / empty input (profile shows "Last Login: never" for accounts
      that have not yet logged in),
    - any string the strict format parser rejects (defensive — Tibiantis is a
      fan-made site, an unexpected layout change shouldn't crash callers).
    """
    if not raw or "never" in raw.lower():
        return None
    try:
        naive_part, _tz = raw.rsplit(" ", 1)  # drop CEST/CET suffix
        dt = datetime.strptime(naive_part, "%d %b %Y %H:%M:%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=ZoneInfo("Europe/Berlin"))
