from typing import cast

from django.conf import settings
from django.utils.module_loading import import_string

from apps.notifications.handlers import (
    BedmageNotificationHandler,
    DeathAnnouncementHandler,
    DeathWatchAnnouncementHandler,
)


def get_bedmage_handler() -> BedmageNotificationHandler:
    """Resolve BedmageNotificationHandler from settings.BEDMAGE_NOTIFICATION_HANDLER.

    Per-call resolution (NOT cached) — @override_settings in tests must work.
    Resolution cost is one import_string call (~microseconds), negligible at
    Beat-fire interval (1h scrape cycle).
    """
    handler_class = import_string(settings.BEDMAGE_NOTIFICATION_HANDLER)
    return cast(BedmageNotificationHandler, handler_class())


def get_death_handler() -> DeathAnnouncementHandler:  # NEW M8
    handler_class = import_string(settings.DEATH_NOTIFICATION_HANDLER)
    return cast(DeathAnnouncementHandler, handler_class())


def get_deathwatch_handler() -> DeathWatchAnnouncementHandler:  # DW-6
    """Resolve DeathWatchAnnouncementHandler from settings.DEATHWATCH_NOTIFICATION_HANDLER.

    Same per-call resolution pattern as get_bedmage_handler / get_death_handler —
    @override_settings in tests must work; cost is negligible at 1-min cadence.
    """
    handler_class = import_string(settings.DEATHWATCH_NOTIFICATION_HANDLER)
    return cast(DeathWatchAnnouncementHandler, handler_class())
