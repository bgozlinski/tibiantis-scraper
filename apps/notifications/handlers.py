from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, Any

if TYPE_CHECKING:
    from apps.bedmages.models import BedmageWatch
    from apps.deaths.models import DeathEvent
    from discord_bot.models import DiscordChannel

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


class DiscordDMHandler:
    """Implements BedmageNotificationHandler. Sends DM via DiscordRESTClient.

    Failures (403 user blocked DMs, 5xx Discord down, invalid discord_id)
    logged but NOT re-raised — M5 service marks last_notified_login anyway
    to avoid retry storm on every scrape cycle.
    """

    def notify(self, watch: BedmageWatch) -> None:
        from apps.notifications.discord_client import DiscordRESTClient

        try:
            user_discord_id = int(watch.user.discord_id or "")
        except ValueError:
            logger.error(
                "Invalid discord_id for user pk=%s — bedmage DM skipped",
                watch.user.pk,
            )
            return

        content = self._render(watch)
        client = DiscordRESTClient()
        ok = client.send_dm(user_discord_id, content)
        if not ok:
            logger.warning(
                "Bedmage DM failed for user=%s character=%s",
                watch.user.username,
                watch.character.name,
            )

    def _render(self, watch: BedmageWatch) -> str:
        from django.conf import settings

        return (
            f"🛏️ Your bedmage **{watch.character.name}** has been logged out for "
            f"{settings.BEDMAGE_REGEN_MINUTES} minutes — mana fully regenerated.\n"
            f"Last login: {watch.character.last_login:%Y-%m-%d %H:%M UTC}"
        )


class DeathAnnouncementHandler(Protocol):
    """Protocol for death announcement handlers.

    Implementations swap via settings.DEATH_NOTIFICATION_HANDLER (dotted path).
    """

    def announce(
        self, death_event: DeathEvent, discord_channel: DiscordChannel
    ) -> bool: ...


class DiscordChannelHandler:
    """Implements DeathAnnouncementHandler. Posts embed to per-guild channel."""

    def announce(
        self, death_event: DeathEvent, discord_channel: DiscordChannel
    ) -> bool:
        from apps.notifications.discord_client import DiscordRESTClient

        client = DiscordRESTClient()
        embed = self._render_embed(death_event)
        return client.send_channel_message(
            channel_id=discord_channel.channel_id,
            embed=embed,
        )

    def _render_embed(self, death_event: DeathEvent) -> dict[str, Any]:
        return {
            "title": f"💀 {death_event.character_name} (level {death_event.level_at_death})",
            "description": death_event.killed_by or "Cause unknown",
            "timestamp": death_event.died_at.isoformat(),
            "color": 0xDC143C,  # crimson
        }


class DeathLoggingHandler:
    """Test/dev variant — logs only, no Discord call."""

    def announce(
        self, death_event: DeathEvent, discord_channel: DiscordChannel
    ) -> bool:
        logger.info(
            "DEATH ANNOUNCE: %s (lvl %s) → guild=%s channel=%s",
            death_event.character_name,
            death_event.level_at_death,
            discord_channel.guild_id,
            discord_channel.channel_id,
        )
        return True
