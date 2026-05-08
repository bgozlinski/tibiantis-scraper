import logging
from datetime import timedelta
from django.utils import timezone

from django.db import transaction

from apps.bedmages.models import BedmageWatch
from apps.characters.models import Character
from apps.accounts.models import User
from apps.notifications import get_bedmage_handler

logger = logging.getLogger(__name__)


def add_bedmage_watch(user: User, character_name: str) -> BedmageWatch:
    """Create BedmageWatch for user+character. Auto-create Character if missing.

    Raises ValueError if active watch already exists for this user+character pair.
    Reactivates inactive watch if found instead of creating duplicate.

    lazy fetch — first scrape will populate Character.last_login
    via the next Beat fire of scrape_watched_characters.
    """
    character, _ = Character.objects.get_or_create(name=character_name)

    with transaction.atomic():
        watch, created = BedmageWatch.objects.get_or_create(
            user=user,
            character=character,
            defaults={"active": True},
        )

    if not created and watch.active:
        raise ValueError(
            f"BedmageWatch for {character_name!r} already exists for user "
            f"{user.username!r}"
        )
    if not created and not watch.active:
        watch.active = True
        watch.last_notified_login = None
        watch.save()

    return watch


def remove_bedmage_watch(user: User, character_name: str) -> bool:
    """Hard-delete BedmageWatch for user+character. Idempotent (returns False
    when no match found, doesn't raise).

    §4.2 design decision: hard delete (not soft via active=False) — M5 doesn't
    need watch history; unique_together resets cycle cleanly on re-add.
    """
    deleted_count, _ = BedmageWatch.objects.filter(
        user=user,
        character__name=character_name,
    ).delete()
    return deleted_count > 0


def check_bedmage_watches_for_character(character: Character) -> int:
    """Iterate active BedmageWatch'es for character; fire handler when delta >= threshold
    AND notification not yet sent for this login.

    §4.4 design decision: invoked post-success in scrape_watched_characters task (D26).
    §4.5 design decision: scope = all watches for character (no further filtering).

    Returns count of watches that triggered notification (for logging/metrics).
    """
    from django.conf import settings

    if character.last_login is None:
        return 0

    threshold = settings.BEDMAGE_REGEN_MINUTES
    cutoff = timezone.now() - timedelta(minutes=threshold)

    if character.last_login > cutoff:
        return 0

    handler = get_bedmage_handler()
    fired = 0
    watches = BedmageWatch.objects.filter(
        character=character, active=True
    ).select_related("user", "character")

    for watch in watches:
        if watch.last_notified_login == character.last_login:
            continue

        try:
            handler.notify(watch)
        except Exception:
            logger.exception(
                "Notification handler failed for watch user=%s character=%s",
                watch.user.username,
                character.name,
            )
            continue

        watch.last_notified_login = character.last_login
        watch.save(update_fields=["last_notified_login"])
        fired += 1

    return fired
