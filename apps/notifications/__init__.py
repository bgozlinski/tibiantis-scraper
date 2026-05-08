from typing import cast

from django.conf import settings
from django.utils.module_loading import import_string

from apps.notifications.handlers import BedmageNotificationHandler


def get_bedmage_handler() -> BedmageNotificationHandler:
    """Resolve BedmageNotificationHandler from settings.BEDMAGE_NOTIFICATION_HANDLER.

    Per-call resolution (NOT cached) — @override_settings in tests must work.
    Resolution cost is one import_string call (~microseconds), negligible at
    Beat-fire interval (1h scrape cycle).
    """
    handler_class = import_string(settings.BEDMAGE_NOTIFICATION_HANDLER)
    return cast(BedmageNotificationHandler, handler_class())
