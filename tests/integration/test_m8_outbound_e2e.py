"""E2E sanity for M8 — handler chain delegates to DiscordRESTClient correctly.

Two flows, mocked at the lowest layer (`DiscordRESTClient`):

1. Bedmage flow — `check_bedmage_watches_for_character` → settings-resolved
   `DiscordDMHandler` → mocked `send_dm`. Asserts the handler chain (service
   reads handler from settings, instantiates it, calls .notify) is wired and
   that `discord_id` is cast str→int before reaching the client.
2. Deaths flow — `announce_unannounced_deaths` → settings-resolved
   `DiscordChannelHandler` → mocked `send_channel_message`. Asserts embed
   format flows through and per-guild `channel_id` is passed unchanged.

Lazy import note (Pułapka A, M8-D37/D38 lesson): handlers do
`from apps.notifications.discord_client import DiscordRESTClient` INSIDE
`notify()`/`announce()`. The monkeypatch target is the source module
(`apps.notifications.discord_client.DiscordRESTClient`), not a handlers-module
re-binding — same pattern as the M8 unit tests.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.bedmages.models import BedmageWatch
from apps.bedmages.services import check_bedmage_watches_for_character
from apps.characters.models import Character
from apps.deaths.models import DeathEvent
from apps.deaths.services import announce_unannounced_deaths
from discord_bot.models import DiscordChannel


@pytest.mark.django_db
@override_settings(
    BEDMAGE_REGEN_MINUTES=100,
    BEDMAGE_NOTIFICATION_HANDLER="apps.notifications.handlers.DiscordDMHandler",
)
def test_bedmage_flow_calls_send_dm_via_handler_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bedmage chain (service → settings → DiscordDMHandler → client.send_dm).

    Pins three contract points end-to-end:
    1. `BEDMAGE_NOTIFICATION_HANDLER` setting resolves to `DiscordDMHandler`
       (no env-default coupling — `@override_settings` makes the test robust
       against M8-D37's flip of the project default).
    2. Handler casts `User.discord_id` from str to int before calling
       `send_dm(user_id: int, content: str)`.
    3. Rendered content carries the character name (the bedmage subject).
    """
    mock_client = MagicMock()
    mock_client.send_dm.return_value = True
    monkeypatch.setattr(
        "apps.notifications.discord_client.DiscordRESTClient", lambda: mock_client
    )

    user = User.objects.create_user(
        username="discord_42", email="bedmage@example.com", discord_id="42"
    )
    character = Character.objects.create(
        name="Yhral", last_login=timezone.now() - timedelta(minutes=120)
    )
    BedmageWatch.objects.create(user=user, character=character)

    fired = check_bedmage_watches_for_character(character)

    assert fired == 1
    mock_client.send_dm.assert_called_once()
    user_id_arg, content_arg = mock_client.send_dm.call_args.args
    assert user_id_arg == 42
    assert isinstance(user_id_arg, int)
    assert "Yhral" in content_arg


@pytest.mark.django_db
@override_settings(
    DEATH_NOTIFICATION_HANDLER="apps.notifications.handlers.DiscordChannelHandler",
)
def test_death_flow_calls_send_channel_message_via_handler_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Death chain (service → settings → DiscordChannelHandler → client.send_channel_message).

    Pins:
    1. `DEATH_NOTIFICATION_HANDLER` setting resolves to `DiscordChannelHandler`.
    2. Per-guild `channel_id` from `DiscordChannel` is passed as kwarg unchanged
       (Pułapka A from M8-D38 — BigIntegerField, no str conversion).
    3. Embed payload carries the character name in the title (visible Discord
       card heading from `DiscordChannelHandler._render_embed`).

    `time.sleep` is mocked because `announce_unannounced_deaths` has a defensive
    200ms wait between per-guild fan-out calls (Pułapka B).
    """
    monkeypatch.setattr("time.sleep", lambda _s: None)
    mock_client = MagicMock()
    mock_client.send_channel_message.return_value = True
    monkeypatch.setattr(
        "apps.notifications.discord_client.DiscordRESTClient", lambda: mock_client
    )

    DiscordChannel.objects.create(
        guild_id=111, channel_id=222, death_level_threshold=30
    )
    DeathEvent.objects.create(
        character_name="Yhral",
        level_at_death=60,
        killed_by="a dragon lord",
        died_at=timezone.now(),
    )

    summary = announce_unannounced_deaths()

    assert summary["events_announced"] == 1
    mock_client.send_channel_message.assert_called_once()
    call_kwargs = mock_client.send_channel_message.call_args.kwargs
    assert call_kwargs["channel_id"] == 222
    assert "Yhral" in call_kwargs["embed"]["title"]
