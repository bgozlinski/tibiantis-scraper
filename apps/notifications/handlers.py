from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from apps.bedmages.models import BedmageWatch

logger = logging.getLogger(__name__)


class BedmageNotificationHandler(Protocol):
    """Protocol for handling bedmage notifications.

    M5 default: LoggingHandler (this module). M6 will add DiscordHandler.
    Implementations swap via settings.BEDMAGE_NOTIFICATION_HANDLER (dotted path).
    """

    def notify(self, watch: BedmageWatch) -> None: ...


class LoggingHandler:
    """Default M5 handler — emits log entry per notification.

    M6 DiscordHandler will replace this for prod via settings switch.
    """

    def notify(self, watch: BedmageWatch) -> None:
        logger.info(
            "BEDMAGE: user=%s character=%s last_login=%s",
            watch.user.username,
            watch.character.name,
            watch.character.last_login,
        )
