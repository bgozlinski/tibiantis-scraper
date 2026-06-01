"""Synchronous Discord REST client used by the notification handlers.

The bot itself runs as a separate process built on top of ``discord.py``; this
module is the path used by Celery tasks that just need to push a message and
do not want to open a gateway connection.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class BulkDeleteAgeError(Exception):
    """Raised when Discord rejects bulk-delete because >=1 message is >14d old.

    Service layer (``apps/deaths/services.py::cleanup_death_channel``) catches
    this and falls back to per-message DELETE for the offending chunk. Discord
    error code: 50034.
    """


class DiscordRESTClient:
    """Thin synchronous wrapper around the Discord REST API.

    The bot token is read from ``settings.DISCORD_BOT_TOKEN`` on construction.
    Every ``send_*`` call opens and closes its own :class:`httpx.Client` via a
    context manager so no connection leaks across requests.
    """

    BASE_URL = "https://discord.com/api/v10"
    DEFAULT_TIMEOUT = 5.0

    def __init__(self, bot_token: str | None = None) -> None:
        self.bot_token = bot_token or settings.DISCORD_BOT_TOKEN

    def send_dm(self, user_discord_id: int, content: str) -> bool:
        """Send a direct message identified by the user's Discord snowflake.

        Two-step flow: ``POST /users/@me/channels {"recipient_id": id}`` to
        get a DM channel, then ``POST /channels/{channel_id}/messages``.
        Returns ``True`` on a successful final message response, ``False`` on
        any 4xx/5xx (after the single retry handled by :meth:`_post`).
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
        """Send a message to ``channel_id``; ``content`` and ``embed`` are both optional."""
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

    def fetch_channel_messages(
        self,
        channel_id: int,
        before: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """GET /channels/{id}/messages — paginated message list.

        Returns the parsed JSON list (empty list on any non-2xx). ``before``
        is a Discord snowflake; Discord IDs are time-ordered, so
        ``before=<snowflake_of_cutoff>`` yields messages older than the
        cutoff. Used by the death-channel cleanup feature (added 2026-06-01).
        """
        params: dict[str, Any] = {"limit": str(limit)}
        if before is not None:
            params["before"] = str(before)

        response = self._request(
            "GET",
            f"{self.BASE_URL}/channels/{channel_id}/messages",
            params=params,
        )
        if response is None or response.status_code >= 400:
            return []
        try:
            result = response.json()
        except (ValueError, TypeError):
            return []
        if not isinstance(result, list):
            return []
        return result

    def bulk_delete_messages(self, channel_id: int, message_ids: list[int]) -> bool:
        """POST /channels/{id}/messages/bulk-delete.

        Discord requirements:
        - ``2 <= len(message_ids) <= 100``
        - all messages < 14 days old (else error code 50034)

        Returns ``True`` on 204, ``False`` on permission/non-age 4xx, raises
        :class:`BulkDeleteAgeError` on 400 with code 50034 (caller falls back
        to per-message delete).
        """
        body = {"messages": [str(mid) for mid in message_ids]}
        response = self._request(
            "POST",
            f"{self.BASE_URL}/channels/{channel_id}/messages/bulk-delete",
            json_body=body,
        )
        if response is None:
            return False

        if 200 <= response.status_code < 300:
            return True

        if response.status_code == 400:
            try:
                code = response.json().get("code")
            except (ValueError, TypeError):
                code = None
            if code == 50034:
                raise BulkDeleteAgeError(
                    f"channel_id={channel_id} has >=1 message older than 14 days"
                )

        return False

    def delete_message(self, channel_id: int, message_id: int) -> bool:
        """DELETE /channels/{cid}/messages/{mid} — single-message fallback.

        Used by ``cleanup_death_channel`` when:
        1. a chunk is size 1 (bulk-delete requires ``N >= 2``);
        2. bulk-delete raised :class:`BulkDeleteAgeError` (any-age single
           deletes are allowed).

        Treats 404 as success (idempotent — message already gone).
        """
        response = self._request(
            "DELETE",
            f"{self.BASE_URL}/channels/{channel_id}/messages/{message_id}",
        )
        if response is None:
            return False
        if 200 <= response.status_code < 300:
            return True
        if response.status_code == 404:
            return True
        return False

    def _post(self, url: str, json_body: dict[str, Any]) -> httpx.Response | None:
        """Thin POST wrapper preserving the existing notification-sender API.

        Delegates to :meth:`_request` and re-applies the "treat 4xx as
        failure" semantics its callers (``send_dm`` / ``send_channel_message``)
        rely on — :meth:`_request` returns 4xx responses so other callers can
        inspect Discord error codes.
        """
        response = self._request("POST", url, json_body=json_body)
        if response is None or response.status_code >= 400:
            return None
        return response

    def _request(
        self,
        method: str,
        url: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response | None:
        """Shared HTTP helper: auth, one retry on 5xx, respect 429 Retry-After.

        Returns the response for any 2xx **or** 4xx (so callers can inspect
        Discord error codes); returns ``None`` on transport error, empty
        token, or an exhausted 5xx/429 retry.
        """
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
                    response = client.request(
                        method,
                        url,
                        json=json_body,
                        params=params,
                        headers=headers,
                    )
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

            # 4xx (permanent) — return so the caller can inspect the code.
            logger.error(
                "Discord 4xx %s for %s: %s",
                response.status_code,
                url,
                response.text[:200],
            )
            return response

        return None
