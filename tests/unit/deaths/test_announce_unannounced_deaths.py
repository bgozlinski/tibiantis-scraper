"""Tests for announce_unannounced_deaths service — multi-guild fan-out + mark-on-success."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from apps.deaths.models import DeathEvent
from apps.deaths.services import announce_unannounced_deaths
from discord_bot.models import DiscordChannel


@pytest.fixture
def mock_handler(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace `get_death_handler` resolver with a controllable mock.

    Tests configure `mock.announce.return_value` or `.side_effect` to exercise
    success/failure/raise paths without hitting real Discord. Patched at the
    service's import binding (`apps.deaths.services.get_death_handler`) so
    the lookup inside `announce_unannounced_deaths` resolves to the mock.
    """
    handler = MagicMock()
    handler.announce.return_value = True
    monkeypatch.setattr("apps.deaths.services.get_death_handler", lambda: handler)
    return handler


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pułapka G — autouse mock of `time.sleep` so the defensive 200ms wait
    between guild fan-out calls doesn't slow the suite. Service uses the
    stdlib `time` module imported at the top of `services.py`.
    """
    monkeypatch.setattr("time.sleep", lambda _s: None)


def _make_event(*, level: int, announced: bool = False) -> DeathEvent:
    """Minimal DeathEvent factory — only the fields the service touches."""
    return DeathEvent.objects.create(
        character_name="Yhral",
        level_at_death=level,
        killed_by="a dragon lord",
        died_at=timezone.now(),
        announced_on_discord=announced,
    )


def _make_channel(*, threshold: int, guild_id: int = 111) -> DiscordChannel:
    """Minimal DiscordChannel factory — unique guild_id required by the model."""
    return DiscordChannel.objects.create(
        guild_id=guild_id,
        channel_id=guild_id * 10,
        death_level_threshold=threshold,
    )


@pytest.mark.django_db
def test_announce_processes_only_unannounced_events(mock_handler: MagicMock) -> None:
    """`filter(announced_on_discord=False)` is the only queryset — already-announced
    rows are never re-sent.

    Catches accidental re-announcement bugs (e.g. someone changing the filter
    to `True`, or dropping the filter entirely) that would spam users with
    duplicate notifications on every scrape cycle.
    """
    _make_channel(threshold=30)
    already_announced = _make_event(level=60, announced=True)
    new_event = _make_event(level=70)

    announce_unannounced_deaths()

    # mock called exactly once — for the unannounced event, NOT for the announced
    assert mock_handler.announce.call_count == 1
    event_arg = mock_handler.announce.call_args.args[0]
    assert event_arg.pk == new_event.pk
    already_announced.refresh_from_db()
    assert already_announced.announced_on_discord is True  # untouched


@pytest.mark.django_db
def test_announce_marks_event_as_announced_on_success(
    mock_handler: MagicMock,
) -> None:
    """Happy path: handler returns True → `announced_on_discord` flips to True
    via `save(update_fields=[...])` (Pułapka B — single-column atomic write).

    Locks the success contract that D40 e2e + prod observability will rely on:
    after a successful scrape+announce cycle, no unannounced rows remain for
    events whose level cleared the threshold.
    """
    _make_channel(threshold=30)
    event = _make_event(level=60)

    announce_unannounced_deaths()

    event.refresh_from_db()
    assert event.announced_on_discord is True
    mock_handler.announce.assert_called_once()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "failure_mode",
    ["returns_false", "raises_exception"],
)
def test_announce_keeps_unannounced_on_handler_failure(
    mock_handler: MagicMock, failure_mode: str
) -> None:
    """Failure (False return OR raised exception — Pułapka E) leaves the event
    `announced_on_discord=False` so the next scrape cycle retries it.

    Parametrized to cover both paths in one test method: returns False (graceful
    handler decline) and raises Exception (e.g. httpx.ConnectError leaking past
    DiscordRESTClient's own try/except). Service's defensive `try/except
    Exception` around `handler.announce` must catch the raise and count it as
    failure without aborting the whole batch.
    """
    if failure_mode == "returns_false":
        mock_handler.announce.return_value = False
    else:
        mock_handler.announce.side_effect = RuntimeError("simulated handler crash")

    _make_channel(threshold=30)
    event = _make_event(level=60)

    summary = announce_unannounced_deaths()

    event.refresh_from_db()
    assert event.announced_on_discord is False
    assert summary["fail_count"] == 1
    assert summary["events_announced"] == 0


@pytest.mark.django_db
def test_announce_iterates_all_applicable_guilds_per_event(
    mock_handler: MagicMock,
) -> None:
    """Multi-guild fan-out: a single event with N applicable channels triggers
    N `announce()` calls — each with the same event + a different channel.

    Pins the per-event multi-target wiring. Channels with threshold > event
    level must NOT receive the announcement (the service's filter is
    `death_level_threshold__lte=event.level_at_death`).
    """
    _make_channel(threshold=30, guild_id=111)  # applicable
    _make_channel(threshold=50, guild_id=222)  # applicable
    _make_channel(threshold=99, guild_id=333)  # NOT applicable
    event = _make_event(level=60)

    announce_unannounced_deaths()

    assert mock_handler.announce.call_count == 2
    channel_args = [call.args[1] for call in mock_handler.announce.call_args_list]
    guild_ids = {c.guild_id for c in channel_args}
    assert guild_ids == {111, 222}  # threshold 99 channel skipped
    # all calls receive the same event
    event_args = {call.args[0].pk for call in mock_handler.announce.call_args_list}
    assert event_args == {event.pk}


@pytest.mark.django_db
def test_announce_marks_event_announced_when_no_applicable_guilds(
    mock_handler: MagicMock,
) -> None:
    """ "Evaluated + skipped" semantics: when ZERO channels have
    `threshold <= level`, the event is still marked `announced_on_discord=True`.

    Without this branch, low-level events would be re-evaluated on every scrape
    cycle forever (retry storm against the DB even though nothing changes).
    The mark says "we've decided this event has no targets — don't re-check."
    """
    _make_channel(threshold=99)  # threshold above any event we make
    event = _make_event(level=10)

    summary = announce_unannounced_deaths()

    event.refresh_from_db()
    assert event.announced_on_discord is True
    mock_handler.announce.assert_not_called()
    assert summary["events_skipped"] == 1
    assert summary["events_announced"] == 0


@pytest.mark.django_db
def test_announce_stays_unannounced_when_any_guild_fails(
    mock_handler: MagicMock,
) -> None:
    """Partial failure = full failure: if ANY guild in the fan-out fails, the
    event stays `False` so the next scrape cycle retries the WHOLE set.

    Trade-off documented in spec §3.3: simpler than per-(event, channel) state,
    but means a single guild outage causes duplicate sends to healthy guilds
    next cycle. M-future could split into an M2M tracking table; out of scope
    for M8.
    """
    mock_handler.announce.side_effect = [True, False]  # guild 1 ok, guild 2 fails
    _make_channel(threshold=30, guild_id=111)
    _make_channel(threshold=40, guild_id=222)
    event = _make_event(level=60)

    summary = announce_unannounced_deaths()

    event.refresh_from_db()
    assert event.announced_on_discord is False
    assert mock_handler.announce.call_count == 2  # both attempted
    assert summary["fail_count"] == 1
    assert summary["events_announced"] == 0


@pytest.mark.django_db
def test_announce_summary_dict_reports_counts(mock_handler: MagicMock) -> None:
    """Summary dict shape contract: three integer counters that D40 e2e and the
    scrape_deaths task return value depend on.

    Constructs a mixed batch (success + skipped + fail) in one call to lock
    all three counters in a single assertion. Order matters because the
    service iterates `order_by("died_at")`; uses controlled `died_at`s to make
    the side_effect list deterministic.
    """
    _make_channel(threshold=30)

    # 1 success: high-level event, handler returns True
    success_event = _make_event(level=80)
    success_event.died_at = timezone.now()
    success_event.save(update_fields=["died_at"])

    # 1 skipped: low-level event, no applicable guild
    skipped_event = _make_event(level=5)
    skipped_event.died_at = timezone.now() + timezone.timedelta(seconds=1)
    skipped_event.save(update_fields=["died_at"])

    # 1 fail: high-level event, but handler returns False for it
    fail_event = _make_event(level=90)
    fail_event.died_at = timezone.now() + timezone.timedelta(seconds=2)
    fail_event.save(update_fields=["died_at"])

    # order_by("died_at") = success, skipped, fail
    # service iterates: success (calls announce, True) → mark True
    #                   skipped (no applicable, threshold=30 IS <= 5? no, 30>5, so skipped) → mark True
    #                   fail (calls announce, False) → keep False
    mock_handler.announce.side_effect = [True, False]  # success→True, fail→False

    summary = announce_unannounced_deaths()

    assert summary == {
        "events_announced": 1,
        "events_skipped": 1,
        "fail_count": 1,
    }
