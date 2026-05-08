"""Tests for apps.bedmages.services."""

from __future__ import annotations

import logging
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.bedmages.models import BedmageWatch
from apps.bedmages.services import (
    add_bedmage_watch,
    check_bedmage_watches_for_character,
    remove_bedmage_watch,
)
from apps.characters.models import Character

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="alice", email="alice@example.com", password="pass-Komplex!1"
    )


@pytest.fixture
def character(db):
    return Character.objects.create(name="Yhral")


# === add_bedmage_watch ===


@pytest.mark.django_db
def test_add_bedmage_watch_creates_character_if_missing(user) -> None:
    """Lazy fetch (§4.1): Character is auto-created via get_or_create."""
    assert Character.objects.filter(name="NewChar").count() == 0

    watch = add_bedmage_watch(user, "NewChar")

    assert watch.pk is not None
    assert watch.active is True
    assert watch.last_notified_login is None
    assert Character.objects.filter(name="NewChar").count() == 1


@pytest.mark.django_db
def test_add_bedmage_watch_uses_existing_character_if_present(user, character) -> None:
    """get_or_create reuses existing Character — no duplicate row."""
    watch = add_bedmage_watch(user, character.name)

    assert watch.character_id == character.pk
    assert Character.objects.filter(name=character.name).count() == 1


@pytest.mark.django_db
def test_add_bedmage_watch_raises_on_duplicate_active(user, character) -> None:
    """Second add for same (user, character) when active=True must raise (§4.6)."""
    add_bedmage_watch(user, character.name)

    with pytest.raises(ValueError, match="already exists"):
        add_bedmage_watch(user, character.name)


@pytest.mark.django_db
def test_add_bedmage_watch_reactivates_inactive(user, character) -> None:
    """Inactive watch → reactivate, reset last_notified_login (Pułapka C).

    The reset is critical: without it, an inactive→active transition with a
    stale last_notified_login could miss the next notification cycle (the
    invariant `last_notified_login != character.last_login` would short-circuit
    to skip on the very first scrape after reactivation).
    """
    stale_login = timezone.now() - timedelta(days=1)
    watch = BedmageWatch.objects.create(
        user=user,
        character=character,
        active=False,
        last_notified_login=stale_login,
    )

    reactivated = add_bedmage_watch(user, character.name)

    assert reactivated.pk == watch.pk
    assert reactivated.active is True
    assert reactivated.last_notified_login is None


# === remove_bedmage_watch ===


@pytest.mark.django_db
def test_remove_bedmage_watch_deletes_existing_returns_true(user, character) -> None:
    """Hard delete (§4.2). Returns True when something was deleted."""
    BedmageWatch.objects.create(user=user, character=character)

    result = remove_bedmage_watch(user, character.name)

    assert result is True
    assert BedmageWatch.objects.filter(user=user, character=character).count() == 0


@pytest.mark.django_db
def test_remove_bedmage_watch_idempotent_returns_false_when_not_found(user) -> None:
    """Idempotent (§4.2): missing watch returns False instead of raising."""
    result = remove_bedmage_watch(user, "NonexistentChar")

    assert result is False


# === check_bedmage_watches_for_character ===


@pytest.mark.django_db
def test_check_returns_zero_when_character_has_no_last_login(character) -> None:
    """Pułapka A: character.last_login=None must early-return safely.

    Without the early-return, `timedelta` comparison against None raises
    TypeError. Fresh Character (lazy-fetched in add_bedmage_watch) starts with
    last_login=None.
    """
    assert character.last_login is None

    fired = check_bedmage_watches_for_character(character)

    assert fired == 0


@pytest.mark.django_db
def test_check_returns_zero_when_delta_below_threshold(user, character) -> None:
    """50 min ago < 100 min threshold → no fire, no DB write."""
    BedmageWatch.objects.create(user=user, character=character)
    Character.objects.filter(pk=character.pk).update(
        last_login=timezone.now() - timedelta(minutes=50)
    )
    character.refresh_from_db()

    fired = check_bedmage_watches_for_character(character)

    assert fired == 0
    watch = BedmageWatch.objects.get(user=user, character=character)
    assert watch.last_notified_login is None


@pytest.mark.django_db
def test_check_fires_when_delta_above_threshold_and_not_yet_notified(
    user, character
) -> None:
    """120 min >= 100 min threshold → fire once, set last_notified_login.

    Verifies the core invariant fire path AND the timezone arithmetic
    (would catch `from datetime import timezone` instead of django.utils).

    Mocks the handler to avoid coupling to LoggingHandler's log format —
    this test asserts behaviour (fired count + last_notified_login persisted),
    not log strings. test_check_invokes_handler_when_delta_exceeds_threshold
    explicitly verifies the handler is called.
    """
    BedmageWatch.objects.create(user=user, character=character)
    Character.objects.filter(pk=character.pk).update(
        last_login=timezone.now() - timedelta(minutes=120)
    )
    character.refresh_from_db()

    with patch("apps.bedmages.services.get_bedmage_handler", return_value=MagicMock()):
        fired = check_bedmage_watches_for_character(character)

    assert fired == 1
    watch = BedmageWatch.objects.get(user=user, character=character)
    assert watch.last_notified_login == character.last_login


@pytest.mark.django_db
def test_check_skips_when_already_notified_for_this_login(user, character) -> None:
    """Idempotency: last_notified_login == character.last_login → skip.

    Prevents duplicate notifications when scrape_watched_characters fires
    repeatedly while the character is still in the same bed-mage session.
    Core M5 invariant — see CLAUDE.md §7.
    """
    login_time = timezone.now() - timedelta(minutes=120)
    Character.objects.filter(pk=character.pk).update(last_login=login_time)
    character.refresh_from_db()

    BedmageWatch.objects.create(
        user=user,
        character=character,
        last_notified_login=character.last_login,
    )

    fired = check_bedmage_watches_for_character(character)

    assert fired == 0


@pytest.mark.django_db
def test_check_filters_only_active_watches(user, character) -> None:
    """active=False watches are excluded from notification dispatch."""
    user2 = User.objects.create_user(
        username="bob", email="bob@example.com", password="pass-Komplex!2"
    )
    BedmageWatch.objects.create(user=user, character=character, active=True)
    BedmageWatch.objects.create(user=user2, character=character, active=False)
    Character.objects.filter(pk=character.pk).update(
        last_login=timezone.now() - timedelta(minutes=120)
    )
    character.refresh_from_db()

    with patch("apps.bedmages.services.get_bedmage_handler", return_value=MagicMock()):
        fired = check_bedmage_watches_for_character(character)

    assert fired == 1
    inactive_watch = BedmageWatch.objects.get(user=user2, character=character)
    assert inactive_watch.last_notified_login is None


# === D25 handler dispatch tests ===


@pytest.mark.django_db
def test_check_invokes_handler_when_delta_exceeds_threshold(user, character) -> None:
    """Handler.notify is invoked exactly once per fired watch with the watch arg.

    Verifies the dispatch contract — services.py routes through the resolved
    handler, passing the BedmageWatch instance. The handler is mocked to keep
    this test independent of LoggingHandler's log format.
    """
    BedmageWatch.objects.create(user=user, character=character)
    Character.objects.filter(pk=character.pk).update(
        last_login=timezone.now() - timedelta(minutes=120)
    )
    character.refresh_from_db()

    mock_handler = MagicMock()
    with patch("apps.bedmages.services.get_bedmage_handler", return_value=mock_handler):
        fired = check_bedmage_watches_for_character(character)

    assert fired == 1
    assert mock_handler.notify.call_count == 1
    called_watch = mock_handler.notify.call_args[0][0]
    assert called_watch.user_id == user.pk
    assert called_watch.character_id == character.pk


@pytest.mark.django_db
def test_check_does_not_set_last_notified_login_when_handler_raises(
    user, character, caplog: pytest.LogCaptureFixture
) -> None:
    """If handler.notify raises, last_notified_login stays None — retry next scrape.

    Critical invariant: a failing notification must NOT mark the watch as notified,
    otherwise the user permanently misses that login's notification. Service wraps
    handler.notify in try/except and `continue`s without setting last_notified_login.
    Failure surface to logger.exception for observability.
    """
    BedmageWatch.objects.create(user=user, character=character)
    Character.objects.filter(pk=character.pk).update(
        last_login=timezone.now() - timedelta(minutes=120)
    )
    character.refresh_from_db()

    mock_handler = MagicMock()
    mock_handler.notify.side_effect = RuntimeError("simulated handler failure")

    with patch("apps.bedmages.services.get_bedmage_handler", return_value=mock_handler):
        with caplog.at_level(logging.ERROR, logger="apps.bedmages"):
            fired = check_bedmage_watches_for_character(character)

    assert fired == 0
    watch = BedmageWatch.objects.get(user=user, character=character)
    assert watch.last_notified_login is None
    assert any("Notification handler failed" in r.getMessage() for r in caplog.records)
