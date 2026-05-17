"""Integration tests for notify_watched_deaths_for_character (DW-6 real impl).

Verifies multi-channel iteration + atomic flag-set-on-full-success (§3.13).
Handler swapped to DeathWatchLoggingHandler for default success cases; mocked
explicitly when partial failure semantics are under test.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.characters.models import Character
from apps.deathwatch.models import DeathWatch, WatchedDeathEvent
from apps.deathwatch.services import (
    add_death_watch,
    notify_watched_deaths_for_character,
    set_deathwatch_channel_for_guild,
)


def _backdate_watch(watch: DeathWatch, delta: timedelta) -> None:
    DeathWatch.objects.filter(pk=watch.pk).update(created_at=timezone.now() - delta)


@pytest.fixture
def alice_watching_yhral(db) -> tuple[User, Character, DeathWatch]:
    user = User.objects.create(username="alice", discord_id="1")
    watch = add_death_watch(user, "Yhral")
    _backdate_watch(watch, timedelta(hours=1))
    character = Character.objects.get(name="Yhral")
    return user, character, watch


@pytest.fixture
def pending_event(alice_watching_yhral) -> WatchedDeathEvent:
    _, character, _ = alice_watching_yhral
    return WatchedDeathEvent.objects.create(
        character=character,
        level_at_death=128,
        killed_by="a giant crayfish",
        died_at=datetime(2026, 5, 7, 14, 15, 46, tzinfo=ZoneInfo("UTC")),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Multi-channel iteration + atomic flag-set
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
@override_settings(
    DEATHWATCH_NOTIFICATION_HANDLER="apps.notifications.handlers.DeathWatchLoggingHandler"
)
def test_notify_marks_event_announced_when_all_channels_succeed(
    alice_watching_yhral, pending_event: WatchedDeathEvent
) -> None:
    _, character, _ = alice_watching_yhral
    set_deathwatch_channel_for_guild(guild_id=1, channel_id=10)
    set_deathwatch_channel_for_guild(guild_id=2, channel_id=20)

    fired = notify_watched_deaths_for_character(character)

    assert fired == 1
    pending_event.refresh_from_db()
    assert pending_event.announced_on_discord is True


@pytest.mark.django_db
def test_notify_does_not_mark_when_one_channel_fails(
    alice_watching_yhral, pending_event: WatchedDeathEvent
) -> None:
    """§3.13 — partial channel failure leaves flag False so next fire retries."""
    _, character, _ = alice_watching_yhral
    set_deathwatch_channel_for_guild(guild_id=1, channel_id=10)
    set_deathwatch_channel_for_guild(guild_id=2, channel_id=20)

    with patch(
        "apps.notifications.handlers.DeathWatchChannelHandler.announce",
        side_effect=[True, False],
    ):
        fired = notify_watched_deaths_for_character(character)

    assert fired == 0
    pending_event.refresh_from_db()
    assert pending_event.announced_on_discord is False


@pytest.mark.django_db
def test_notify_isolates_per_channel_exceptions(
    alice_watching_yhral, pending_event: WatchedDeathEvent
) -> None:
    """One channel's exception must not short-circuit dispatch to the others.

    Handler raises on channel A → handler succeeds on channel B → event stays
    unannounced (partial failure rule from §3.13) but the second channel's
    announce was still called.
    """
    _, character, _ = alice_watching_yhral
    set_deathwatch_channel_for_guild(guild_id=1, channel_id=10)
    set_deathwatch_channel_for_guild(guild_id=2, channel_id=20)

    with patch(
        "apps.notifications.handlers.DeathWatchChannelHandler.announce",
        side_effect=[RuntimeError("boom"), True],
    ) as mock_announce:
        fired = notify_watched_deaths_for_character(character)

    assert mock_announce.call_count == 2  # second channel still attempted
    assert fired == 0
    pending_event.refresh_from_db()
    assert pending_event.announced_on_discord is False


# ──────────────────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_notify_returns_zero_when_no_channels_configured(
    alice_watching_yhral, pending_event: WatchedDeathEvent
) -> None:
    """Admin hasn't run /deathwatch channel yet → backlog stays pending."""
    _, character, _ = alice_watching_yhral

    fired = notify_watched_deaths_for_character(character)

    assert fired == 0
    pending_event.refresh_from_db()
    assert pending_event.announced_on_discord is False


@pytest.mark.django_db
@override_settings(
    DEATHWATCH_NOTIFICATION_HANDLER="apps.notifications.handlers.DeathWatchLoggingHandler"
)
def test_notify_skips_already_announced_events(
    alice_watching_yhral, pending_event: WatchedDeathEvent
) -> None:
    _, character, _ = alice_watching_yhral
    set_deathwatch_channel_for_guild(guild_id=1, channel_id=10)
    pending_event.announced_on_discord = True
    pending_event.save(update_fields=["announced_on_discord"])

    with patch(
        "apps.notifications.handlers.DeathWatchLoggingHandler.announce"
    ) as mock_announce:
        fired = notify_watched_deaths_for_character(character)

    assert fired == 0
    mock_announce.assert_not_called()


@pytest.mark.django_db
@override_settings(
    DEATHWATCH_NOTIFICATION_HANDLER="apps.notifications.handlers.DeathWatchLoggingHandler"
)
def test_notify_processes_multiple_pending_events_in_one_call(
    alice_watching_yhral,
) -> None:
    """Several pending events for the same character → each gets fanned out."""
    _, character, _ = alice_watching_yhral
    set_deathwatch_channel_for_guild(guild_id=1, channel_id=10)
    base_t = datetime(2026, 5, 7, 14, 0, 0, tzinfo=ZoneInfo("UTC"))
    for i in range(3):
        WatchedDeathEvent.objects.create(
            character=character,
            level_at_death=100 + i,
            killed_by=f"k{i}",
            died_at=base_t + timedelta(minutes=i),
        )

    fired = notify_watched_deaths_for_character(character)

    assert fired == 3
    assert WatchedDeathEvent.objects.filter(announced_on_discord=False).count() == 0
