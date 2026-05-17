import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.accounts.models import User
from apps.characters.models import Character
from apps.deathwatch.models import (
    DeathWatch,
    DeathWatchChannel,
    WatchedDeathEvent,
)


@pytest.mark.django_db
def test_death_watch_unique_user_character_pair():
    user = User.objects.create(username="alice", discord_id="1")
    character = Character.objects.create(name="Yhral")
    DeathWatch.objects.create(user=user, character=character)
    with pytest.raises(IntegrityError):
        DeathWatch.objects.create(user=user, character=character)


@pytest.mark.django_db
def test_watched_death_event_unique_character_died_at():
    character = Character.objects.create(name="Yhral")
    t = timezone.now()
    WatchedDeathEvent.objects.create(
        character=character,
        level_at_death=100,
        died_at=t,
        killed_by="a dragon",
    )
    with pytest.raises(IntegrityError):
        WatchedDeathEvent.objects.create(
            character=character,
            level_at_death=100,
            died_at=t,
            killed_by="a dragon",
        )


@pytest.mark.django_db
def test_death_watch_channel_unique_per_guild():
    DeathWatchChannel.objects.create(guild_id=123, channel_id=456)
    with pytest.raises(IntegrityError):
        DeathWatchChannel.objects.create(guild_id=123, channel_id=789)


@pytest.mark.django_db
def test_death_watch_str_repr():
    user = User.objects.create(username="alice", discord_id="1")
    character = Character.objects.create(name="Yhral")
    watch = DeathWatch.objects.create(user=user, character=character)
    assert "alice" in str(watch)
    assert "Yhral" in str(watch)


@pytest.mark.django_db
def test_death_watch_defaults():
    user = User.objects.create(username="alice", discord_id="1")
    character = Character.objects.create(name="Yhral")
    watch = DeathWatch.objects.create(user=user, character=character)
    assert watch.active is True
    assert watch.created_at is not None
