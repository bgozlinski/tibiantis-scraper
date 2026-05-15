from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class DiscordRESTClient:
    """Sync httpx client dla Discord REST API.

    Bot token z settings.DISCORD_BOT_TOKEN (lazy, per-instance). Każdy
    send_* call otwiera/zamyka httpx.Client przez context manager —
    connection pooling lokalne dla jednego callu, no leak risk.
    """

    BASE_URL = "https://discord.com/api/v10"
    DEFAULT_TIMEOUT = 5.0

    def __init__(self, bot_token: str | None = None) -> None:
        self.bot_token = bot_token or settings.DISCORD_BOT_TOKEN

    def send_dm(self, user_discord_id: int, content: str) -> bool:
        """Wyślij DM do user'a po Discord snowflake.

        2-step flow: POST /users/@me/channels {"recipient_id": id} →
        channel_id, potem POST /channels/{channel_id}/messages.
        Returns True przy 2xx (final message), False przy 4xx/5xx (po retry).
        """
        channel_response = self._post(
            f"{self.BASE_URL}/users/@me/channels",
            {"recipient_id": user_discord_id},
        )
        if channel_response is None:
            return False
        try:
            channel_id = channel_response.json()["id"]
        except (KeyError, TypeError, ValueError):
            logger.error(
                "DM channel response malformed: %s", channel_response.text[:200]
            )
            return False

        message_response = self._post(
            f"{self.BASE_URL}/channels/{channel_id}/messages",
            {"content": content},
        )
        return message_response is not None

    def send_channel_message(
        self,
        channel_id: int,
        content: str | None = None,
        embed: dict[str, Any] | None = None,
    ) -> bool:
        """Wyślij wiadomość do kanału. Content LUB embed (oba dozwolone)."""
        body: dict[str, Any] = {}
        if content is not None:
            body["content"] = content
        if embed is not None:
            body["embeds"] = [embed]

        response = self._post(
            f"{self.BASE_URL}/channels/{channel_id}/messages",
            body,
        )
        return response is not None

    def _post(self, url: str, json_body: dict[str, Any]) -> httpx.Response | None:
        """POST helper z 1-retry na 5xx/429. Returns Response (2xx) or None."""
        if not self.bot_token:
            logger.error("DISCORD_BOT_TOKEN empty — outbound disabled")
            return None

        headers = {
            "Authorization": f"Bot {self.bot_token}",
            "Accept": "application/json",
        }

        for attempt in range(2):  # initial + 1 retry
            try:
                with httpx.Client(timeout=self.DEFAULT_TIMEOUT) as client:
                    response = client.post(url, json=json_body, headers=headers)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                logger.warning("Discord REST request failed: %s", exc)
                return None

            if 200 <= response.status_code < 300:
                return response

            if response.status_code == 429:
                retry_after = min(float(response.headers.get("Retry-After", "1")), 5.0)
                logger.info("Discord rate limit, retrying after %ss", retry_after)
                time.sleep(retry_after)
                continue

            if 500 <= response.status_code < 600:
                if attempt == 0:
                    logger.warning(
                        "Discord 5xx %s — retrying once",
                        response.status_code,
                    )
                    continue
                logger.warning(
                    "Discord 5xx %s after retry — giving up",
                    response.status_code,
                )
                return None

            # 4xx (permanent)
            logger.error(
                "Discord 4xx %s for %s: %s",
                response.status_code,
                url,
                response.text[:200],
            )
            return None

        return None
