"""Tests for DiscordRESTClient — httpx.MockTransport-based, no real HTTP."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from apps.notifications.discord_client import DiscordRESTClient


class MockHttpx:
    """Captures outbound requests + lets tests register a response handler.

    Pułapka E from #128: MockTransport handler signature is
    `(httpx.Request) -> httpx.Response`. Multi-step flows (e.g. DM) branch
    on `request.url.path` to return different responses per call.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self._handler: Callable[[httpx.Request], httpx.Response] = (
            lambda _r: httpx.Response(200, json={})
        )

    def set_handler(self, fn: Callable[[httpx.Request], httpx.Response]) -> None:
        self._handler = fn

    def dispatch(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)


@pytest.fixture
def mock_httpx(monkeypatch: pytest.MonkeyPatch) -> MockHttpx:
    """Route every `httpx.Client(...)` in discord_client.py through MockTransport.

    Captures the real `httpx.Client` class BEFORE patching, then replaces the
    module attribute with a factory that injects our MockTransport. Naive
    `lambda **kw: httpx.Client(transport=..., **kw)` would self-recurse — the
    capture avoids that trap.

    Also mocks `time.sleep` (Pułapka F) so tests don't block on real seconds
    when the 429 path triggers.
    """
    mock = MockHttpx()
    transport = httpx.MockTransport(mock.dispatch)
    real_client_cls = httpx.Client

    def fake_client(**kwargs: Any) -> httpx.Client:
        kwargs.pop("transport", None)
        return real_client_cls(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "Client", fake_client)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    return mock


def test_send_dm_creates_channel_then_posts_message(mock_httpx: MockHttpx) -> None:
    """Happy path 2-step DM flow: POST /users/@me/channels yields channel_id,
    then POST /channels/<id>/messages actually sends.

    Locks the 2-step contract — both POSTs happen in order, channel_id from
    step 1 appears in the URL of step 2, and Authorization header carries
    the literal `Bot <token>` prefix on both requests (Pułapka A).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/users/@me/channels"):
            return httpx.Response(200, json={"id": "999"})
        return httpx.Response(200, json={"id": "msg_42"})

    mock_httpx.set_handler(handler)
    client = DiscordRESTClient(bot_token="fake-token")

    ok = client.send_dm(user_discord_id=12345, content="hello")

    assert ok is True
    assert len(mock_httpx.requests) == 2
    assert mock_httpx.requests[0].url.path == "/api/v10/users/@me/channels"
    assert mock_httpx.requests[1].url.path == "/api/v10/channels/999/messages"
    for r in mock_httpx.requests:
        assert r.headers["Authorization"] == "Bot fake-token"


def test_send_dm_returns_false_on_403_user_dms_disabled(
    mock_httpx: MockHttpx,
) -> None:
    """4xx on step 1 short-circuits without sending the second POST.

    Real-world trigger: target user has "DMs from server members" disabled
    → Discord returns 403 "Cannot send messages to this user" on the channel
    creation step. 4xx is permanent (no retry per #128 spec), so we expect
    exactly one outbound request and `False` return.
    """
    mock_httpx.set_handler(
        lambda _r: httpx.Response(
            403, json={"message": "Cannot send messages to this user"}
        )
    )

    client = DiscordRESTClient(bot_token="fake-token")
    ok = client.send_dm(user_discord_id=12345, content="hello")

    assert ok is False
    assert len(mock_httpx.requests) == 1


def test_send_channel_message_posts_and_returns_true_on_success(
    mock_httpx: MockHttpx,
) -> None:
    """Happy path channel post — content in JSON body, returns True.

    Also pins the JSON body shape: httpx auto-sets `Content-Type:
    application/json` when called with `json=` (Pułapka J), and the body
    must contain `content` (not form-encoded — Pułapka B).
    """
    mock_httpx.set_handler(lambda _r: httpx.Response(200, json={"id": "msg_1"}))

    client = DiscordRESTClient(bot_token="fake-token")
    ok = client.send_channel_message(channel_id=42, content="hello")

    assert ok is True
    assert len(mock_httpx.requests) == 1
    request = mock_httpx.requests[0]
    assert request.url.path == "/api/v10/channels/42/messages"
    assert request.headers["content-type"].startswith("application/json")
    assert b'"content":"hello"' in request.content


def test_send_channel_message_returns_false_on_404_channel_not_found(
    mock_httpx: MockHttpx,
) -> None:
    """4xx (channel deleted or wrong ID) returns False, no retry.

    Pins the "4xx is permanent" contract so downstream handlers (D38
    `DeathAnnouncementHandler`) can rely on `False` meaning "give up,
    mark as failed" rather than "transient — try again later".
    """
    mock_httpx.set_handler(
        lambda _r: httpx.Response(404, json={"message": "Unknown Channel"})
    )

    client = DiscordRESTClient(bot_token="fake-token")
    ok = client.send_channel_message(channel_id=99, content="hi")

    assert ok is False
    assert len(mock_httpx.requests) == 1


def test_client_retries_once_on_5xx(mock_httpx: MockHttpx) -> None:
    """5xx on attempt 1 → retry → 2xx on attempt 2 returns True.

    Pins the "1-retry on 5xx" contract: total request count is exactly 2,
    final outcome is success. A third 5xx (which we don't simulate here)
    would cause `_post` to give up and return None.
    """
    attempt = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempt["n"] += 1
        if attempt["n"] == 1:
            return httpx.Response(503, json={})
        return httpx.Response(200, json={"id": "msg_1"})

    mock_httpx.set_handler(handler)
    client = DiscordRESTClient(bot_token="fake-token")

    ok = client.send_channel_message(channel_id=42, content="hi")

    assert ok is True
    assert len(mock_httpx.requests) == 2


def test_send_channel_message_wraps_embed_in_embeds_list(
    mock_httpx: MockHttpx,
) -> None:
    """Embed payload is wrapped in `embeds: [...]` (list of dicts, not bare dict).

    Pins the Discord REST contract — the API expects `embeds` (plural, array)
    even for a single embed. Without the wrap, Discord rejects the request as
    "embed must be an object" and DiscordChannelHandler silently fails. Test
    locks the wire-format shape that D38 `DiscordChannelHandler` depends on.
    """
    mock_httpx.set_handler(lambda _r: httpx.Response(200, json={"id": "msg_1"}))

    client = DiscordRESTClient(bot_token="fake-token")
    embed = {"title": "💀 Yhral", "color": 0xDC143C}
    ok = client.send_channel_message(channel_id=42, embed=embed)

    assert ok is True
    request = mock_httpx.requests[0]
    assert b'"embeds":[{"title"' in request.content
    assert b'"content"' not in request.content  # bare embed call, no content


def test_post_returns_none_when_bot_token_empty(
    mock_httpx: MockHttpx, caplog: pytest.LogCaptureFixture
) -> None:
    """Empty bot_token short-circuits BEFORE any HTTP request — defensive guard.

    Catches the misconfigured-env case (DISCORD_BOT_TOKEN missing from .env
    in prod): we log an ERROR and return None instead of attempting an
    unauthenticated request that would surface as a 401 deeper in the stack.
    `mock_httpx` fixture asserts the contract by remaining empty — zero
    outbound requests confirms the early return path.
    """
    import logging

    # `__init__` does `bot_token or settings.DISCORD_BOT_TOKEN`, so we set the
    # attribute directly after construction to bypass the settings fallback.
    client = DiscordRESTClient(bot_token="placeholder")
    client.bot_token = ""

    with caplog.at_level(logging.ERROR, logger="apps.notifications.discord_client"):
        ok = client.send_channel_message(channel_id=42, content="hi")

    assert ok is False
    assert len(mock_httpx.requests) == 0
    assert any("DISCORD_BOT_TOKEN empty" in r.getMessage() for r in caplog.records)


def test_client_gives_up_after_second_5xx(mock_httpx: MockHttpx) -> None:
    """5xx on BOTH attempts → returns False (None from `_post`).

    Locks the "exactly 1 retry on 5xx" contract — after the retry also fails
    we don't loop forever. Counterpart to `test_client_retries_once_on_5xx`
    which proves we DO retry once; this proves we DON'T retry twice.
    Downstream (D38 `DiscordChannelHandler`, D37 `DiscordDMHandler`) relies
    on the False return to log a WARNING and skip marking-as-announced.
    """
    mock_httpx.set_handler(lambda _r: httpx.Response(503, json={}))

    client = DiscordRESTClient(bot_token="fake-token")
    ok = client.send_channel_message(channel_id=42, content="hi")

    assert ok is False
    assert len(mock_httpx.requests) == 2  # initial + 1 retry, no more


def test_client_respects_retry_after_on_429(
    mock_httpx: MockHttpx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """429 → sleep `Retry-After` seconds → retry → 2xx returns True.

    Verifies three things at once: (1) we actually retry after 429 instead
    of giving up, (2) we read the `Retry-After` header (here `0.5`) rather
    than a hardcoded default, (3) the sleep happens between attempts. The
    fixture's `time.sleep` no-op is overridden here to a recorder so we
    can assert the exact sleep duration.
    """
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    attempt = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempt["n"] += 1
        if attempt["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0.5"}, json={})
        return httpx.Response(200, json={"id": "msg_1"})

    mock_httpx.set_handler(handler)
    client = DiscordRESTClient(bot_token="fake-token")

    ok = client.send_channel_message(channel_id=42, content="hi")

    assert ok is True
    assert len(mock_httpx.requests) == 2
    assert sleeps == [0.5]


# === fetch_channel_messages ===


def test_fetch_channel_messages_returns_parsed_list(mock_httpx: MockHttpx) -> None:
    """Happy path: GET returns 200 with a JSON array of message objects."""
    payload = [
        {"id": "100", "content": "hi", "pinned": False},
        {"id": "99", "content": "older", "pinned": True},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "/channels/12345/messages" in str(request.url)
        return httpx.Response(200, json=payload)

    mock_httpx.set_handler(handler)
    client = DiscordRESTClient(bot_token="tok")

    result = client.fetch_channel_messages(channel_id=12345, limit=100)

    assert result == payload


def test_fetch_channel_messages_sends_before_and_limit(
    mock_httpx: MockHttpx,
) -> None:
    """`before` and `limit` are passed as query parameters."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["before"] == "999"
        assert request.url.params["limit"] == "50"
        return httpx.Response(200, json=[])

    mock_httpx.set_handler(handler)
    client = DiscordRESTClient(bot_token="tok")

    client.fetch_channel_messages(channel_id=1, before=999, limit=50)


def test_fetch_channel_messages_empty_on_4xx(mock_httpx: MockHttpx) -> None:
    """4xx returns empty list — caller decides how to react (loop exit)."""
    mock_httpx.set_handler(lambda _r: httpx.Response(403, json={}))
    client = DiscordRESTClient(bot_token="tok")

    result = client.fetch_channel_messages(channel_id=1)

    assert result == []


def test_fetch_channel_messages_retries_on_5xx(mock_httpx: MockHttpx) -> None:
    """Existing retry policy (single retry on 5xx) carried into GET path."""
    responses = iter([httpx.Response(503), httpx.Response(200, json=[{"id": "1"}])])
    mock_httpx.set_handler(lambda _r: next(responses))
    client = DiscordRESTClient(bot_token="tok")

    result = client.fetch_channel_messages(channel_id=1)

    assert result == [{"id": "1"}]
    assert len(mock_httpx.requests) == 2
