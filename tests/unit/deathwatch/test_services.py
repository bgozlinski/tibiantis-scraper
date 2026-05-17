from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.characters.models import Character
from apps.deathwatch.models import DeathWatch, DeathWatchChannel, WatchedDeathEvent
from apps.deathwatch.services import (
    add_death_watch,
    list_death_watches,
    record_watched_death,
    remove_death_watch,
    set_deathwatch_channel_for_guild,
)


# ──────────────────────────────────────────────────────────────────────────────
# add_death_watch
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_add_death_watch_creates_character_lazy() -> None:
    user = User.objects.create(username="alice", discord_id="1")
    watch = add_death_watch(user, "Yhral")

    assert watch.character.name == "Yhral"
    assert Character.objects.filter(name="Yhral").exists()


@pytest.mark.django_db
def test_add_death_watch_canonicalizes_name() -> None:
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "  yhral  ")

    assert Character.objects.filter(name="Yhral").exists()


@pytest.mark.django_db
def test_add_death_watch_raises_on_active_duplicate() -> None:
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")

    with pytest.raises(ValueError, match="already active"):
        add_death_watch(user, "Yhral")


@pytest.mark.django_db
def test_add_death_watch_reactivates_inactive() -> None:
    user = User.objects.create(username="alice", discord_id="1")
    watch = add_death_watch(user, "Yhral")
    watch.active = False
    watch.save(update_fields=["active"])

    re_watch = add_death_watch(user, "Yhral")

    assert re_watch.pk == watch.pk
    assert re_watch.active is True


@pytest.mark.django_db
@override_settings(DEATHWATCH_MAX_WATCHED_CHARACTERS=2)
def test_add_death_watch_cap_exceeded_raises() -> None:
    u1 = User.objects.create(username="alice", discord_id="1")
    u2 = User.objects.create(username="bob", discord_id="2")
    add_death_watch(u1, "Yhral")
    add_death_watch(u2, "Bubble")

    with pytest.raises(ValueError, match="cap"):
        add_death_watch(u1, "Eternal Oblivion")


@pytest.mark.django_db
@override_settings(DEATHWATCH_MAX_WATCHED_CHARACTERS=2)
def test_add_death_watch_cap_counts_unique_characters_not_watches() -> None:
    """Two users watching the same character = 1 unique, not 2."""
    u1 = User.objects.create(username="alice", discord_id="1")
    u2 = User.objects.create(username="bob", discord_id="2")
    add_death_watch(u1, "Yhral")
    add_death_watch(u2, "Yhral")  # same character — still 1 unique
    add_death_watch(u1, "Bubble")  # 2 unique now

    with pytest.raises(ValueError, match="cap"):
        add_death_watch(u2, "Eternal Oblivion")  # would be 3rd unique


# ──────────────────────────────────────────────────────────────────────────────
# remove_death_watch
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_remove_death_watch_hard_deletes_existing() -> None:
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")

    assert remove_death_watch(user, "Yhral") is True
    assert not DeathWatch.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_remove_death_watch_idempotent_when_not_found() -> None:
    user = User.objects.create(username="alice", discord_id="1")

    assert remove_death_watch(user, "Yhral") is False


@pytest.mark.django_db
def test_remove_death_watch_canonicalizes_name() -> None:
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")

    assert remove_death_watch(user, "  YHRAL  ") is True


# ──────────────────────────────────────────────────────────────────────────────
# list_death_watches
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_list_death_watches_filters_by_user_and_orders_newest_first() -> None:
    alice = User.objects.create(username="alice", discord_id="1")
    bob = User.objects.create(username="bob", discord_id="2")
    add_death_watch(alice, "Yhral")
    add_death_watch(bob, "Bubble")
    add_death_watch(alice, "Eternal Oblivion")

    alice_watches = list(list_death_watches(alice))

    # _canonicalize_name uppercases ONLY the first letter ("Eternal Oblivion"
    # → "Eternal oblivion"). Match canonical form.
    assert len(alice_watches) == 2
    assert {w.character.name for w in alice_watches} == {"Yhral", "Eternal oblivion"}
    assert alice_watches[0].character.name == "Eternal oblivion"


# ──────────────────────────────────────────────────────────────────────────────
# set_deathwatch_channel_for_guild
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_set_deathwatch_channel_creates_when_missing() -> None:
    channel = set_deathwatch_channel_for_guild(guild_id=111, channel_id=222)

    assert channel.guild_id == 111
    assert channel.channel_id == 222
    assert DeathWatchChannel.objects.filter(guild_id=111).count() == 1


@pytest.mark.django_db
def test_set_deathwatch_channel_updates_when_exists() -> None:
    set_deathwatch_channel_for_guild(guild_id=111, channel_id=222)
    updated = set_deathwatch_channel_for_guild(guild_id=111, channel_id=999)

    assert updated.channel_id == 999
    assert DeathWatchChannel.objects.filter(guild_id=111).count() == 1


# ──────────────────────────────────────────────────────────────────────────────
# record_watched_death
# ──────────────────────────────────────────────────────────────────────────────


def _backdate_watch(watch: DeathWatch, delta: timedelta) -> None:
    """Force watch.created_at backward, bypassing auto_now_add.

    Workaround for `auto_now_add=True` — `.save()` with passed `created_at`
    is ignored. Must use `.filter().update()` (M3-D17 retro #5 pattern).
    """
    DeathWatch.objects.filter(pk=watch.pk).update(created_at=timezone.now() - delta)


@pytest.mark.django_db
def test_record_watched_death_creates_event_when_died_after_watch_created() -> None:
    user = User.objects.create(username="alice", discord_id="1")
    watch = add_death_watch(user, "Yhral")
    _backdate_watch(watch, timedelta(hours=1))

    item = {
        "character_name": "Yhral",
        "level_at_death": 128,
        "killed_by": "a giant crayfish",
        "died_at": timezone.now(),
    }
    event = record_watched_death(item)

    assert event is not None
    assert event.character.name == "Yhral"
    assert event.level_at_death == 128
    assert event.killed_by == "a giant crayfish"


@pytest.mark.django_db
def test_record_watched_death_drops_when_died_before_watch_created() -> None:
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")

    item = {
        "character_name": "Yhral",
        "level_at_death": 128,
        "killed_by": "a dragon",
        "died_at": timezone.now() - timedelta(hours=1),  # before watch.created_at
    }

    assert record_watched_death(item) is None
    assert not WatchedDeathEvent.objects.exists()


@pytest.mark.django_db
def test_record_watched_death_drops_when_no_active_watch() -> None:
    Character.objects.create(name="Yhral")  # exists but unwatched

    item = {
        "character_name": "Yhral",
        "level_at_death": 128,
        "killed_by": "a dragon",
        "died_at": timezone.now(),
    }

    assert record_watched_death(item) is None
    assert not WatchedDeathEvent.objects.exists()


@pytest.mark.django_db
def test_record_watched_death_drops_when_watch_inactive() -> None:
    user = User.objects.create(username="alice", discord_id="1")
    watch = add_death_watch(user, "Yhral")
    watch.active = False
    watch.save(update_fields=["active"])
    _backdate_watch(watch, timedelta(hours=1))

    item = {
        "character_name": "Yhral",
        "level_at_death": 128,
        "killed_by": "x",
        "died_at": timezone.now(),
    }

    assert record_watched_death(item) is None


@pytest.mark.django_db
def test_record_watched_death_deduplicates_via_unique_constraint() -> None:
    user = User.objects.create(username="alice", discord_id="1")
    watch = add_death_watch(user, "Yhral")
    _backdate_watch(watch, timedelta(hours=1))

    t = timezone.now()
    item = {
        "character_name": "Yhral",
        "level_at_death": 128,
        "killed_by": "x",
        "died_at": t,
    }

    e1 = record_watched_death(item)
    e2 = record_watched_death(item)

    assert e1 is not None
    assert e2 is None  # already exists — dedup
    assert WatchedDeathEvent.objects.count() == 1


@pytest.mark.django_db
def test_record_watched_death_drops_when_character_missing() -> None:
    item = {
        "character_name": "Ghost",
        "level_at_death": 1,
        "killed_by": "x",
        "died_at": timezone.now(),
    }

    assert record_watched_death(item) is None


@pytest.mark.django_db
def test_record_watched_death_canonicalizes_character_name() -> None:
    user = User.objects.create(username="alice", discord_id="1")
    watch = add_death_watch(user, "Yhral")
    _backdate_watch(watch, timedelta(hours=1))

    item = {
        "character_name": "  yhral  ",  # un-canonical input
        "level_at_death": 128,
        "killed_by": "x",
        "died_at": timezone.now(),
    }
    event = record_watched_death(item)

    assert event is not None
    assert event.character.name == "Yhral"
