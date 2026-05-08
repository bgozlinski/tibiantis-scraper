"""E2E integration test for M5 — full chain: addBedmageWatch → tracker → handler.

Spec M5 §5/D27: addBedmageWatch via service → force Character.last_login past
threshold → invoke check_bedmage_watches_for_character → verify the configured
notification handler was called once with the correct watch. Second invocation
must be a no-op (idempotency invariant from CLAUDE.md §7).

Mocks `LoggingHandler.notify` — the M5 default handler. Doesn't go through
the GraphQL layer (the unit tests cover that boundary); this verifies the
business-logic chain D24+D25 wires up end-to-end.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.bedmages.services import (
    add_bedmage_watch,
    check_bedmage_watches_for_character,
)
from apps.characters.models import Character


@pytest.mark.django_db(transaction=True)
@override_settings(BEDMAGE_REGEN_MINUTES=100)
@mock.patch("apps.notifications.handlers.LoggingHandler.notify")
def test_e2e_add_bedmage_watch_then_check_fires_handler(
    mock_notify: mock.MagicMock,
) -> None:
    """Full M5 chain — first check fires handler, second is idempotent no-op.

    Step 1: addBedmageWatch creates watch + Character (lazy fetch §4.1).
    Step 2: force Character.last_login = now - 120 min (>= REGEN_MINUTES).
    Step 3: check_bedmage_watches_for_character → fired=1, handler.notify called
            once with the watch, last_notified_login persisted on the row.
    Step 4: re-run check immediately — fired=0, handler.notify NOT called again.
            Asserts the idempotency invariant (last_notified_login ==
            character.last_login → skip).
    """
    user = User.objects.create_user(
        username="tester", email="t@example.com", password="ComplexPass!123"
    )

    watch = add_bedmage_watch(user, "Yhral")
    assert watch.character.name == "Yhral"
    assert watch.active is True
    assert watch.last_notified_login is None

    Character.objects.filter(name="Yhral").update(
        last_login=timezone.now() - timedelta(minutes=120)
    )
    character = Character.objects.get(name="Yhral")

    fired = check_bedmage_watches_for_character(character)

    assert fired == 1
    assert mock_notify.call_count == 1
    notified_watch = mock_notify.call_args[0][0]
    assert notified_watch.character.name == "Yhral"
    assert notified_watch.user_id == user.pk

    watch.refresh_from_db()
    assert watch.last_notified_login == character.last_login

    mock_notify.reset_mock()
    fired_again = check_bedmage_watches_for_character(character)

    assert fired_again == 0
    assert mock_notify.call_count == 0
