"""Tests for save_death_event() service."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.deaths.models import DeathEvent
from apps.deaths.services import save_death_event


def _payload(
    *,
    character_name: str = "Yhral",
    level_at_death: int = 42,
    killed_by: str = "a slime",
    died_at: datetime | None = None,
) -> dict[str, object]:
    """Helper — defaults map to a single canonical death."""
    return {
        "character_name": character_name,
        "level_at_death": level_at_death,
        "killed_by": killed_by,
        "died_at": died_at or datetime(2026, 4, 30, 5, 25, 12, tzinfo=ZoneInfo("UTC")),
    }


@pytest.mark.django_db
def test_create_returns_persisted_event() -> None:
    """Happy path — fresh payload inserts a new DeathEvent and returns it."""
    event = save_death_event(_payload())  # type: ignore[arg-type]

    assert event is not None
    assert event.pk is not None
    assert event.character_name == "Yhral"
    assert event.level_at_death == 42
    assert event.killed_by == "a slime"
    assert DeathEvent.objects.count() == 1


@pytest.mark.django_db
def test_duplicate_returns_none_and_does_not_insert() -> None:
    """Second save with identical (character_name, died_at) is silently skipped.

    Deaths are immutable — no upsert semantics. The unique_together constraint
    on (character_name, died_at) raises IntegrityError, which the service
    catches and converts to a None return so the pipeline can count it.
    """
    payload = _payload()

    first = save_death_event(payload)  # type: ignore[arg-type]
    second = save_death_event(payload)  # type: ignore[arg-type]

    assert first is not None
    assert second is None
    assert DeathEvent.objects.count() == 1


@pytest.mark.django_db
def test_same_character_different_died_at_creates_two_events() -> None:
    """Dedup key is (character_name, died_at) — same name + different timestamps
    must yield two rows. Verifies the unique constraint covers exactly the
    expected fields, no broader.
    """
    base = datetime(2026, 4, 30, 5, 25, 12, tzinfo=ZoneInfo("UTC"))
    later = datetime(2026, 4, 30, 6, 0, 0, tzinfo=ZoneInfo("UTC"))

    first = save_death_event(_payload(died_at=base))  # type: ignore[arg-type]
    second = save_death_event(_payload(died_at=later))  # type: ignore[arg-type]

    assert first is not None
    assert second is not None
    assert first.pk != second.pk
    assert DeathEvent.objects.count() == 2


@pytest.mark.django_db
def test_dedup_emits_no_log_records(caplog: pytest.LogCaptureFixture) -> None:
    """Service must not log on dedup hit.

    Why this matters: prod runs every 5 min over ~50 deaths/page; if 49/50 are
    duplicates per scrape (steady state), a logger.warning at WARN+ would
    produce ~600 log entries per hour of pure noise. Observability lives in
    the pipeline's stats counter, not in service-level logs.

    Filter to apps.deaths.* loggers — Django's ORM/db loggers are noise here.
    """
    payload = _payload()
    save_death_event(payload)  # type: ignore[arg-type]

    with caplog.at_level(logging.DEBUG, logger="apps.deaths"):
        result = save_death_event(payload)  # type: ignore[arg-type]

    deaths_records = [r for r in caplog.records if r.name.startswith("apps.deaths")]
    assert result is None
    assert deaths_records == []


@pytest.mark.django_db
def test_unknown_field_in_payload_raises_typeerror() -> None:
    """Service catches IntegrityError but not TypeError.

    Django ORM raises TypeError when constructing a model with an unknown
    field name — that's a programmer bug, not a data integrity issue, and
    must surface loudly instead of being swallowed by the dedup branch.
    """
    bad_payload = {**_payload(), "nonexistent_field": "boom"}

    with pytest.raises(TypeError):
        save_death_event(bad_payload)  # type: ignore[arg-type]
