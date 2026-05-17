from __future__ import annotations

import logging
import urllib.parse
from typing import TYPE_CHECKING, Protocol, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from apps.bedmages.models import BedmageWatch
    from apps.deaths.models import DeathEvent
    from apps.deathwatch.models import DeathWatchChannel, WatchedDeathEvent
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
        """Render bedmage notification DM body.

        Per #184: `last_login` converted from UTC (DB storage) to Europe/Warsaw
        before formatting, matching #180/#181's death-notification fix. The
        literal `" UTC"` suffix was dropped — operators saw 1-2h offset vs
        their local clock and the tibiantis.online "Last login" display.
        """
        from django.conf import settings

        # Invariant: services.check_bedmage_watches_for_character early-returns
        # when character.last_login is None, so by the time the handler runs
        # the field is non-None. Assert documents this + narrows the type
        # (DateTimeField(null=True) → datetime | None in stubs).
        assert watch.character.last_login is not None
        last_login_local = watch.character.last_login.astimezone(
            ZoneInfo("Europe/Warsaw")
        )
        return (
            f"🛏️ Your bedmage **{watch.character.name}** has been logged out for "
            f"{settings.BEDMAGE_REGEN_MINUTES} minutes — mana fully regenerated.\n"
            f"Last login: {last_login_local:%Y-%m-%d %H:%M}"
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
        """Build Discord embed with hyperlinked character name + line-by-line info.

        Per #178: `title` is the raw character name; `url` makes it a clickable
        hyperlink to the Tibiantis online character page (quote_plus encoding —
        Tibiantis uses `+` for spaces in URLs). `description` carries the three
        info lines (level / wall-clock time / killer). Empty `killed_by` renders
        as "unknown" (the model default for un-parsed kill messages).

        Per #180: `died_at` is converted from UTC (DB storage) to Europe/Warsaw
        before formatting, so the displayed time matches Polish operator
        expectation and the tibiantis.info deaths-page time (server-local,
        Europe/Berlin = same offset as Europe/Warsaw year-round). `zoneinfo`
        handles DST correctly (CEST/CET transitions at the two annual Sundays).

        Embed `timestamp` field intentionally absent — wall-clock time lives in
        `description` now. Discord's footer timestamp would render in viewer's
        local TZ and disagree with the description, confusing operators.
        """
        died_at_local = death_event.died_at.astimezone(ZoneInfo("Europe/Warsaw"))
        return {
            "title": death_event.character_name,
            "url": (
                "https://www.tibiantis.online/?page=character&name="
                + urllib.parse.quote_plus(death_event.character_name)
            ),
            "description": (
                f"Died at level {death_event.level_at_death}\n"
                f"{died_at_local:%Y-%m-%d %H:%M:%S}\n"
                f"Killed by: {death_event.killed_by or 'unknown'}"
            ),
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


# ─── DeathWatch (DW-6) — per-character death blacklist announcements ────────
#
# Mirrors the DeathEvent stack above (Protocol + REST + Logging impls). Key
# differences:
# - Operates on `WatchedDeathEvent` (FK to Character) instead of `DeathEvent`
#   (denormalized character_name string).
# - Channel model is `DeathWatchChannel` (no per-guild threshold field).
# - Embed color: 0x8B008B (purple) — visually distinct from M4 crimson when
#   both feeds post to the same Discord server.


class DeathWatchAnnouncementHandler(Protocol):
    """Protocol for deathwatch announcements.

    Implementations swap via settings.DEATHWATCH_NOTIFICATION_HANDLER.
    """

    def announce(
        self, event: WatchedDeathEvent, channel: DeathWatchChannel
    ) -> bool: ...


class DeathWatchChannelHandler:
    """Implements DeathWatchAnnouncementHandler. Posts purple embed to per-guild channel."""

    def announce(self, event: WatchedDeathEvent, channel: DeathWatchChannel) -> bool:
        from apps.notifications.discord_client import DiscordRESTClient

        client = DiscordRESTClient()
        embed = self._render_embed(event)
        return client.send_channel_message(
            channel_id=channel.channel_id,
            embed=embed,
        )

    def _render_embed(self, event: WatchedDeathEvent) -> dict[str, Any]:
        """Build Discord embed mirroring M4 DiscordChannelHandler shape.

        Color differs (purple vs crimson) so operators distinguish DW from M4
        deaths in the same channel. `died_at` converted UTC → Europe/Warsaw
        before formatting (matches #180 convention).
        """
        died_at_local = event.died_at.astimezone(ZoneInfo("Europe/Warsaw"))
        return {
            "title": event.character.name,
            "url": (
                "https://www.tibiantis.online/?page=character&name="
                + urllib.parse.quote_plus(event.character.name)
            ),
            "description": (
                f"Died at level {event.level_at_death}\n"
                f"{died_at_local:%Y-%m-%d %H:%M:%S}\n"
                f"Killed by: {event.killed_by or 'unknown'}"
            ),
            "color": 0x8B008B,  # purple — distinct from M4 crimson
        }


class DeathWatchLoggingHandler:
    """Test/dev variant — logs only, returns True (success). No Discord call."""

    def announce(self, event: WatchedDeathEvent, channel: DeathWatchChannel) -> bool:
        logger.info(
            "DEATHWATCH ANNOUNCE: %s (lvl %s) → guild=%s channel=%s",
            event.character.name,
            event.level_at_death,
            channel.guild_id,
            channel.channel_id,
        )
        return True
