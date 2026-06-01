"""Tests for snowflake_for_datetime — Discord ID timestamp encoding.

Discord IDs encode a millisecond Unix timestamp offset from the Discord
epoch (2015-01-01 00:00:00 UTC) in the high 42 bits:

    snowflake = (unix_ms - 1420070400000) << 22

Used by cleanup_death_channel to paginate "messages older than X" without
scanning the whole channel.
"""

from __future__ import annotations

from datetime import datetime, timezone

from apps.deaths.services import snowflake_for_datetime


def test_snowflake_for_discord_epoch_is_zero() -> None:
    """The Discord epoch itself maps to snowflake 0."""
    epoch = datetime(2015, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert snowflake_for_datetime(epoch) == 0


def test_snowflake_one_second_after_epoch() -> None:
    """1 second = 1000 ms. The low 22 bits are zero (no worker/seq encoded)."""
    one_sec = datetime(2015, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
    assert snowflake_for_datetime(one_sec) == 1000 << 22


def test_snowflake_known_fixture_2026_06_01() -> None:
    """Round-trip a real cutoff against a precomputed snowflake.

    2026-06-01 00:00:00 UTC → unix_ms = 1780272000000
                          → (1780272000000 - 1420070400000) << 22
                          → 360201600000 << 22
                          → 1510795011686400000
    """
    dt = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert snowflake_for_datetime(dt) == 1510795011686400000
