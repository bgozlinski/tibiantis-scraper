# Death Channel Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-purge messages older than 3 days from death-announcement channels every 3 days at 00:00 Europe/Warsaw, opt-in per guild, controlled via `/deaths cleanup on|off|status|now` slash commands.

**Architecture:** New Celery Beat task `cleanup_death_channels` iterates `DiscordChannel` rows with `cleanup_enabled=True` and calls service `cleanup_death_channel(channel)` per row. Service paginates via Discord snowflake `before=` query, filters pinned messages, deletes in bulk-delete chunks of 100 (single-delete fallback for `N==1` and >14d-old messages). Three new methods on `DiscordRESTClient` (`fetch_channel_messages`, `bulk_delete_messages`, `delete_message`) talk to Discord REST with the existing retry/back-off pattern. Bot process stays slash-command-only (CLAUDE.md §8).

**Tech Stack:** Django 6.0, Celery + django-celery-beat, py-cord, httpx (MockTransport in tests), pytest + pytest-asyncio + pytest-django.

**Data:** 2026-06-01
**Spec:** [`docs/superpowers/specs/2026-06-01-death-channel-cleanup-design.md`](../specs/2026-06-01-death-channel-cleanup-design.md)
**Branch:** `docs/death-channel-cleanup-spec` (spec) → continue implementation on `feat/death-channel-cleanup` (created in pre-flight).
**Status:** READY (spec approved 2026-06-01).

---

## Pre-flight checklist

- [ ] **Spec merged or co-branch.** Spec lives on `docs/death-channel-cleanup-spec`. Implementation branch `feat/death-channel-cleanup` branches off it (or off master if spec PR already merged).
- [ ] **`DiscordChannel`** model exists (`discord_bot/models.py` since M7). New fields stack on top.
- [ ] **`DiscordRESTClient`** exists (`apps/notifications/discord_client.py` since M8). Currently only `_post`-based methods (`send_dm`, `send_channel_message`).
- [ ] **`PeriodicTask` / `CrontabSchedule`** available via `django-celery-beat` (already in `INSTALLED_APPS` since M3).
- [ ] **Test infrastructure** — `pytest-asyncio` ^1.3, `pytest-django` ≥4.12, `httpx.MockTransport` pattern (used in `tests/unit/notifications/test_discord_client.py`).
- [ ] **Branch on master.** `git checkout master && git pull && git checkout -b feat/death-channel-cleanup`.

---

## Task overview

| # | Title | Est. |
|---|---|---|
| 1 | `DiscordChannel`: add `cleanup_enabled` + `last_cleanup_at` (+ schema migration) | 20 min |
| 2 | `snowflake_for_datetime` helper + tests | 15 min |
| 3 | `DiscordRESTClient`: `_request` refactor + `fetch_channel_messages` + tests | 45 min |
| 4 | `DiscordRESTClient`: `bulk_delete_messages` + `BulkDeleteAgeError` + tests | 30 min |
| 5 | `DiscordRESTClient`: `delete_message` + tests | 20 min |
| 6 | `cleanup_death_channel` service + `CleanupError` + tests | 1h |
| 7 | `cleanup_death_channels` Celery task + tests | 30 min |
| 8 | Periodic-task seed migration (`0 0 */3 * *` Europe/Warsaw) + test | 20 min |
| 9 | `discord_bot/services.py`: enable/disable/status helpers + tests | 30 min |
| 10 | `/deaths cleanup on|off|status|now` slash commands + cog tests | 1h |
| 11 | Final pre-commit run + open PR | 15 min |

**Total:** ~5.5h. One PR (`feat/death-channel-cleanup`), all tasks committed on the same branch.

---

## Task 1 — Add `cleanup_enabled` + `last_cleanup_at` fields to `DiscordChannel`

**Files:**
- Modify: `discord_bot/models.py`
- Create: `discord_bot/migrations/0002_discord_channel_cleanup_fields.py` (auto-generated)
- Test: `tests/unit/discord_bot/test_discord_channel_model.py` (create if missing)

### TDD steps

- [ ] **Step 1: Write the failing test**

Create `tests/unit/discord_bot/test_discord_channel_model.py` (or extend if exists):

```python
"""Tests for DiscordChannel model — cleanup fields added 2026-06-01."""

from __future__ import annotations

import pytest

from discord_bot.models import DiscordChannel


@pytest.mark.django_db
def test_discord_channel_cleanup_fields_default_to_disabled() -> None:
    """New cleanup_* fields default to safe values — no surprise mass deletions."""
    ch = DiscordChannel.objects.create(guild_id=1, channel_id=2)

    assert ch.cleanup_enabled is False
    assert ch.last_cleanup_at is None


@pytest.mark.django_db
def test_discord_channel_cleanup_fields_persist() -> None:
    """Both new fields are writable and round-trip through ORM."""
    from django.utils import timezone

    now = timezone.now()
    ch = DiscordChannel.objects.create(
        guild_id=1,
        channel_id=2,
        cleanup_enabled=True,
        last_cleanup_at=now,
    )
    ch.refresh_from_db()

    assert ch.cleanup_enabled is True
    assert ch.last_cleanup_at == now
```

- [ ] **Step 2: Run test — expected FAIL**

```bash
poetry run pytest tests/unit/discord_bot/test_discord_channel_model.py -v
```

Expected: `AttributeError: type object 'DiscordChannel' has no attribute 'cleanup_enabled'` (or migration-related error).

- [ ] **Step 3: Add fields to the model**

In `discord_bot/models.py`, add the two new fields after `death_level_threshold`:

```python
class DiscordChannel(models.Model):
    """The death-announcement target configured per Discord guild.

    ``death_level_threshold`` is the minimum character level a death must
    have for the announcement task to push it into this channel. The
    ``guild_id`` unique constraint ensures one configuration row per guild.

    ``cleanup_enabled`` + ``last_cleanup_at`` were added 2026-06-01 to
    drive the 3-day auto-purge feature (opt-in per guild, default OFF).
    """

    guild_id = models.BigIntegerField()
    channel_id = models.BigIntegerField()
    death_level_threshold = models.PositiveIntegerField(default=30)
    cleanup_enabled = models.BooleanField(default=False)
    last_cleanup_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["guild_id"], name="discord_channel_one_per_guild"
            ),
        ]

    def __str__(self) -> str:
        return f"Guild {self.guild_id} (threshold={self.death_level_threshold})"
```

- [ ] **Step 4: Generate the migration**

```bash
poetry run python manage.py makemigrations discord_bot
```

Expected output: `Migrations for 'discord_bot': discord_bot/migrations/0002_discord_channel_cleanup_fields.py - Add field cleanup_enabled to discordchannel - Add field last_cleanup_at to discordchannel`.

If the auto-generated name differs (e.g. `0002_discordchannel_cleanup_enabled_and_more.py`), rename it to `0002_discord_channel_cleanup_fields.py` (matches spec §3.2) and update the `name` field inside the migration if Django referenced it.

- [ ] **Step 5: Apply migration locally**

```bash
poetry run python manage.py migrate discord_bot
```

Expected: `Applying discord_bot.0002_discord_channel_cleanup_fields... OK`.

- [ ] **Step 6: Run test — expected PASS**

```bash
poetry run pytest tests/unit/discord_bot/test_discord_channel_model.py -v
```

Expected: both tests pass.

- [ ] **Step 7: Commit**

```bash
git add discord_bot/models.py discord_bot/migrations/0002_discord_channel_cleanup_fields.py tests/unit/discord_bot/test_discord_channel_model.py
git commit -m "feat(deaths): add cleanup_enabled + last_cleanup_at to DiscordChannel"
```

---

## Task 2 — `snowflake_for_datetime` helper + tests

**Files:**
- Modify: `apps/deaths/services.py` (add helper + `RETENTION_DAYS` constant at top of module)
- Test: `tests/unit/deaths/test_snowflake_helper.py` (create)

### TDD steps

- [ ] **Step 1: Write the failing test**

Create `tests/unit/deaths/test_snowflake_helper.py`:

```python
"""Tests for snowflake_for_datetime — Discord ID timestamp encoding.

Discord IDs encode a millisecond Unix timestamp offset from the Discord
epoch (2015-01-01 00:00:00 UTC) in the high 42 bits:

    snowflake = (unix_ms - 1420070400000) << 22

Used by cleanup_death_channel to paginate "messages older than X" without
scanning the whole channel.
"""

from __future__ import annotations

from datetime import datetime, timezone

from apps.deaths.services import snowflake_for_datetime


def test_snowflake_for_discord_epoch_is_zero() -> None:
    """The Discord epoch itself maps to snowflake 0."""
    epoch = datetime(2015, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert snowflake_for_datetime(epoch) == 0


def test_snowflake_one_second_after_epoch() -> None:
    """1 second = 1000 ms. The low 22 bits are zero (no worker/seq encoded)."""
    one_sec = datetime(2015, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
    assert snowflake_for_datetime(one_sec) == 1000 << 22


def test_snowflake_known_fixture_2026_06_01() -> None:
    """Round-trip a real cutoff against a precomputed snowflake.

    2026-06-01 00:00:00 UTC → unix_ms = 1780617600000
                          → (1780617600000 - 1420070400000) << 22
                          → 360547200000 << 22
                          → 1512100463837184000
    """
    dt = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert snowflake_for_datetime(dt) == 1512100463837184000
```

- [ ] **Step 2: Run test — expected FAIL**

```bash
poetry run pytest tests/unit/deaths/test_snowflake_helper.py -v
```

Expected: `ImportError: cannot import name 'snowflake_for_datetime' from 'apps.deaths.services'`.

- [ ] **Step 3: Add helper + constants to `apps/deaths/services.py`**

At the top of `apps/deaths/services.py`, after the existing imports, add:

```python
from datetime import datetime, timedelta

from django.utils import timezone as django_timezone

# Death-channel cleanup constants (added 2026-06-01, see spec
# 2026-06-01-death-channel-cleanup-design.md).
RETENTION_DAYS = 3
DISCORD_EPOCH_MS = 1420070400000


def snowflake_for_datetime(dt: datetime) -> int:
    """Encode a UTC datetime as a Discord snowflake (high 42 bits = timestamp).

    Discord message IDs are monotonically time-ordered, so passing this
    value as the ``before=`` query parameter on
    ``GET /channels/{id}/messages`` returns only messages older than ``dt``
    without scanning the whole channel. Lower 22 bits (worker/process/seq)
    are zero — fine for a *boundary* (we want "everything before this
    timestamp", not a specific message).
    """
    unix_ms = int(dt.timestamp() * 1000)
    return (unix_ms - DISCORD_EPOCH_MS) << 22
```

> Note: `datetime` may already be imported; just verify and don't duplicate the import. `django_timezone` is the aliased import — only add if not already present (used by Task 6).

- [ ] **Step 4: Run test — expected PASS**

```bash
poetry run pytest tests/unit/deaths/test_snowflake_helper.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/deaths/services.py tests/unit/deaths/test_snowflake_helper.py
git commit -m "feat(deaths): add snowflake_for_datetime helper for cleanup pagination"
```

---

## Task 3 — `DiscordRESTClient`: `_request` refactor + `fetch_channel_messages`

**Files:**
- Modify: `apps/notifications/discord_client.py`
- Test: `tests/unit/notifications/test_discord_client.py` (extend)

### Background

`DiscordRESTClient` currently only has `_post`. We need GET (`fetch_channel_messages`) and later DELETE (`delete_message`). Refactor `_post` to delegate to a generic `_request(method, url, json_body=None)` so the retry/auth/rate-limit logic is shared.

### TDD steps

- [ ] **Step 1: Write the failing tests for `fetch_channel_messages`**

Append to `tests/unit/notifications/test_discord_client.py`:

```python
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
```

- [ ] **Step 2: Run tests — expected FAIL**

```bash
poetry run pytest tests/unit/notifications/test_discord_client.py -v -k "fetch_channel_messages"
```

Expected: `AttributeError: 'DiscordRESTClient' object has no attribute 'fetch_channel_messages'`.

- [ ] **Step 3: Refactor `_post` to use `_request`, then add `fetch_channel_messages`**

In `apps/notifications/discord_client.py`, replace the existing `_post` with a generic helper. The existing `send_dm` / `send_channel_message` callers still call `self._post(...)`, so keep `_post` as a thin wrapper.

```python
def _request(
    self,
    method: str,
    url: str,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> httpx.Response | None:
    """Shared HTTP helper: auth, single retry on 5xx, respect 429 Retry-After.

    Used by both POST callers (notification senders) and GET/DELETE callers
    (channel-cleanup feature, added 2026-06-01).
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

        # 4xx (permanent) — log and return so caller can decide
        logger.error(
            "Discord 4xx %s for %s: %s",
            response.status_code,
            url,
            response.text[:200],
        )
        return response  # 4xx still returned for callers that need to inspect code

    return None


def _post(self, url: str, json_body: dict[str, Any]) -> httpx.Response | None:
    """Thin wrapper preserving the existing POST-only API for notification senders."""
    response = self._request("POST", url, json_body=json_body)
    if response is None or response.status_code >= 400:
        return None
    return response
```

Then add the new method below `send_channel_message`:

```python
def fetch_channel_messages(
    self,
    channel_id: int,
    before: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """GET /channels/{id}/messages — paginated message list.

    Returns parsed JSON list (empty list on any non-2xx).
    ``before`` is a Discord snowflake; Discord IDs are time-ordered, so
    ``before=<snowflake_of_cutoff>`` yields messages older than the cutoff.
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
        if not isinstance(result, list):
            return []
        return result
    except (ValueError, TypeError):
        return []
```

> Why `_post` semantics changed slightly: the new `_request` returns the 4xx response (so callers like `bulk_delete_messages` can inspect Discord error codes); `_post` re-applies the "treat 4xx as None" behavior so its callers (`send_dm`, `send_channel_message`) keep working unchanged.

- [ ] **Step 4: Run tests — expected PASS**

Run both the new tests and the existing client tests (regression check on the `_post` refactor):

```bash
poetry run pytest tests/unit/notifications/test_discord_client.py -v
```

Expected: all tests pass (existing `send_dm` / `send_channel_message` + new `fetch_channel_messages`).

- [ ] **Step 5: Commit**

```bash
git add apps/notifications/discord_client.py tests/unit/notifications/test_discord_client.py
git commit -m "feat(notifications): add DiscordRESTClient.fetch_channel_messages + generic _request"
```

---

## Task 4 — `DiscordRESTClient.bulk_delete_messages` + `BulkDeleteAgeError`

**Files:**
- Modify: `apps/notifications/discord_client.py` (add `BulkDeleteAgeError`, `bulk_delete_messages`)
- Test: `tests/unit/notifications/test_discord_client.py` (extend)

### TDD steps

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/notifications/test_discord_client.py`:

```python
from apps.notifications.discord_client import BulkDeleteAgeError

# === bulk_delete_messages ===


def test_bulk_delete_messages_happy_path(mock_httpx: MockHttpx) -> None:
    """POST /channels/{id}/messages/bulk-delete with body={'messages': [...]}.

    Discord requires the IDs as strings in the body.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "/channels/12/messages/bulk-delete" in str(request.url)
        body = request.read()
        # Discord wants strings, not ints
        assert b'"100"' in body
        assert b'"200"' in body
        return httpx.Response(204)  # success: no content

    mock_httpx.set_handler(handler)
    client = DiscordRESTClient(bot_token="tok")

    ok = client.bulk_delete_messages(channel_id=12, message_ids=[100, 200])

    assert ok is True


def test_bulk_delete_messages_raises_age_error_on_50034(
    mock_httpx: MockHttpx,
) -> None:
    """Discord returns 400 with code 50034 when any message is >14 days old.

    Service layer catches this to fall back to single-delete (any age).
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"code": 50034, "message": "You can only bulk delete messages..."},
        )

    mock_httpx.set_handler(handler)
    client = DiscordRESTClient(bot_token="tok")

    with pytest.raises(BulkDeleteAgeError):
        client.bulk_delete_messages(channel_id=1, message_ids=[1, 2])


def test_bulk_delete_messages_returns_false_on_403(mock_httpx: MockHttpx) -> None:
    """Bot lacks MANAGE_MESSAGES → 403 → False, NOT raise. Service treats as failure."""
    mock_httpx.set_handler(lambda _r: httpx.Response(403, json={"code": 50013}))
    client = DiscordRESTClient(bot_token="tok")

    ok = client.bulk_delete_messages(channel_id=1, message_ids=[1, 2])

    assert ok is False
```

- [ ] **Step 2: Run tests — expected FAIL**

```bash
poetry run pytest tests/unit/notifications/test_discord_client.py -v -k "bulk_delete"
```

Expected: `ImportError: cannot import name 'BulkDeleteAgeError'`.

- [ ] **Step 3: Add `BulkDeleteAgeError` + `bulk_delete_messages`**

In `apps/notifications/discord_client.py`, near the top of the module (after imports, before `DiscordRESTClient`):

```python
class BulkDeleteAgeError(Exception):
    """Raised when Discord rejects bulk-delete because >=1 message is >14d old.

    Service layer (apps/deaths/services.py::cleanup_death_channel) catches
    this and falls back to per-message DELETE for the offending chunk.
    Discord error code: 50034.
    """
```

Then inside `DiscordRESTClient`, add the method below `fetch_channel_messages`:

```python
def bulk_delete_messages(
    self, channel_id: int, message_ids: list[int]
) -> bool:
    """POST /channels/{id}/messages/bulk-delete.

    Discord requirements:
    - 2 ≤ len(message_ids) ≤ 100
    - all messages < 14 days old (else error code 50034)

    Returns True on 204, False on permission/non-age 4xx, raises
    ``BulkDeleteAgeError`` on 400 with code 50034 (caller falls back).
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
```

- [ ] **Step 4: Run tests — expected PASS**

```bash
poetry run pytest tests/unit/notifications/test_discord_client.py -v -k "bulk_delete"
```

Expected: 3 new tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/notifications/discord_client.py tests/unit/notifications/test_discord_client.py
git commit -m "feat(notifications): add bulk_delete_messages + BulkDeleteAgeError"
```

---

## Task 5 — `DiscordRESTClient.delete_message`

**Files:**
- Modify: `apps/notifications/discord_client.py`
- Test: `tests/unit/notifications/test_discord_client.py` (extend)

### TDD steps

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/notifications/test_discord_client.py`:

```python
# === delete_message ===


def test_delete_message_happy_path(mock_httpx: MockHttpx) -> None:
    """DELETE /channels/{cid}/messages/{mid} → 204 → True."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert "/channels/12/messages/100" in str(request.url)
        return httpx.Response(204)

    mock_httpx.set_handler(handler)
    client = DiscordRESTClient(bot_token="tok")

    assert client.delete_message(channel_id=12, message_id=100) is True


def test_delete_message_treats_404_as_success(mock_httpx: MockHttpx) -> None:
    """Already-deleted message → 404 → True (idempotent semantics).

    Cleanup may race with a manual delete by an admin; treating 404 as
    success keeps the task from logging spurious failures.
    """
    mock_httpx.set_handler(lambda _r: httpx.Response(404, json={"code": 10008}))
    client = DiscordRESTClient(bot_token="tok")

    assert client.delete_message(channel_id=1, message_id=1) is True


def test_delete_message_returns_false_on_403(mock_httpx: MockHttpx) -> None:
    """Missing permissions → 403 → False."""
    mock_httpx.set_handler(lambda _r: httpx.Response(403, json={"code": 50013}))
    client = DiscordRESTClient(bot_token="tok")

    assert client.delete_message(channel_id=1, message_id=1) is False
```

- [ ] **Step 2: Run tests — expected FAIL**

```bash
poetry run pytest tests/unit/notifications/test_discord_client.py -v -k "delete_message"
```

Expected: `AttributeError: 'DiscordRESTClient' object has no attribute 'delete_message'`.

- [ ] **Step 3: Implement `delete_message`**

Add to `DiscordRESTClient` (below `bulk_delete_messages`):

```python
def delete_message(self, channel_id: int, message_id: int) -> bool:
    """DELETE /channels/{cid}/messages/{mid} — single-message fallback.

    Used by cleanup_death_channel when:
    1. Chunk is size 1 (bulk-delete requires N ≥ 2).
    2. Bulk-delete raised BulkDeleteAgeError (any-age single deletes OK).

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
```

- [ ] **Step 4: Run tests — expected PASS**

```bash
poetry run pytest tests/unit/notifications/test_discord_client.py -v -k "delete_message"
```

Expected: all 3 new tests pass.

- [ ] **Step 5: Run the whole client test file (regression check)**

```bash
poetry run pytest tests/unit/notifications/test_discord_client.py -v
```

Expected: every test passes (DM, channel message, fetch, bulk-delete, single-delete).

- [ ] **Step 6: Commit**

```bash
git add apps/notifications/discord_client.py tests/unit/notifications/test_discord_client.py
git commit -m "feat(notifications): add DiscordRESTClient.delete_message"
```

---

## Task 6 — `cleanup_death_channel` service + `CleanupError`

**Files:**
- Modify: `apps/deaths/services.py`
- Test: `tests/unit/deaths/test_cleanup_service.py` (create)

### TDD steps

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/deaths/test_cleanup_service.py`:

```python
"""Tests for cleanup_death_channel — per-channel message purge."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from apps.deaths.services import (
    CleanupError,
    cleanup_death_channel,
    snowflake_for_datetime,
)
from apps.notifications.discord_client import BulkDeleteAgeError
from discord_bot.models import DiscordChannel


@pytest.fixture
def channel(db) -> DiscordChannel:  # noqa: ARG001
    return DiscordChannel.objects.create(
        guild_id=1, channel_id=42, cleanup_enabled=True
    )


def _msg(id_: int, pinned: bool = False) -> dict[str, object]:
    return {"id": str(id_), "pinned": pinned}


def test_cleanup_paginates_until_empty_batch(
    monkeypatch: pytest.MonkeyPatch, channel: DiscordChannel
) -> None:
    """Service walks `before=` pagination until Discord returns an empty page."""
    pages = iter(
        [
            [_msg(100), _msg(99), _msg(98)],
            [_msg(50), _msg(49)],
            [],
        ]
    )
    client = MagicMock()
    client.fetch_channel_messages.side_effect = lambda **kw: next(pages)
    client.bulk_delete_messages.return_value = True
    monkeypatch.setattr(
        "apps.deaths.services.DiscordRESTClient", lambda: client
    )

    result = cleanup_death_channel(channel)

    assert result == {"deleted": 5}
    assert client.fetch_channel_messages.call_count == 3
    client.bulk_delete_messages.assert_called_once_with(
        channel_id=42, message_ids=[100, 99, 98, 50, 49]
    )


def test_cleanup_filters_pinned_messages(
    monkeypatch: pytest.MonkeyPatch, channel: DiscordChannel
) -> None:
    """Pinned messages stay (preserves rules/info pins)."""
    pages = iter([[_msg(1), _msg(2, pinned=True), _msg(3)], []])
    client = MagicMock()
    client.fetch_channel_messages.side_effect = lambda **kw: next(pages)
    client.bulk_delete_messages.return_value = True
    monkeypatch.setattr(
        "apps.deaths.services.DiscordRESTClient", lambda: client
    )

    result = cleanup_death_channel(channel)

    assert result == {"deleted": 2}
    args, kwargs = client.bulk_delete_messages.call_args
    assert kwargs["message_ids"] == [1, 3]


def test_cleanup_chunks_more_than_100(
    monkeypatch: pytest.MonkeyPatch, channel: DiscordChannel
) -> None:
    """>100 messages → multiple bulk-delete calls of ≤100 each."""
    ids = list(range(1, 251))  # 250 messages
    pages = iter([[_msg(i) for i in ids[:100]], [_msg(i) for i in ids[100:200]],
                  [_msg(i) for i in ids[200:]], []])
    client = MagicMock()
    client.fetch_channel_messages.side_effect = lambda **kw: next(pages)
    client.bulk_delete_messages.return_value = True
    monkeypatch.setattr(
        "apps.deaths.services.DiscordRESTClient", lambda: client
    )

    result = cleanup_death_channel(channel)

    assert result == {"deleted": 250}
    assert client.bulk_delete_messages.call_count == 3  # 100 + 100 + 50


def test_cleanup_falls_back_to_single_delete_when_chunk_is_one(
    monkeypatch: pytest.MonkeyPatch, channel: DiscordChannel
) -> None:
    """N==1 chunk → delete_message instead of bulk-delete (API requires N≥2)."""
    pages = iter([[_msg(1)], []])
    client = MagicMock()
    client.fetch_channel_messages.side_effect = lambda **kw: next(pages)
    client.delete_message.return_value = True
    monkeypatch.setattr(
        "apps.deaths.services.DiscordRESTClient", lambda: client
    )

    result = cleanup_death_channel(channel)

    assert result == {"deleted": 1}
    client.bulk_delete_messages.assert_not_called()
    client.delete_message.assert_called_once_with(channel_id=42, message_id=1)


def test_cleanup_falls_back_to_single_delete_on_age_error(
    monkeypatch: pytest.MonkeyPatch, channel: DiscordChannel
) -> None:
    """BulkDeleteAgeError → retry the chunk message-by-message."""
    pages = iter([[_msg(1), _msg(2), _msg(3)], []])
    client = MagicMock()
    client.fetch_channel_messages.side_effect = lambda **kw: next(pages)
    client.bulk_delete_messages.side_effect = BulkDeleteAgeError("too old")
    client.delete_message.return_value = True
    monkeypatch.setattr(
        "apps.deaths.services.DiscordRESTClient", lambda: client
    )

    result = cleanup_death_channel(channel)

    assert result == {"deleted": 3}
    assert client.delete_message.call_count == 3


def test_cleanup_empty_channel_updates_last_cleanup_at(
    monkeypatch: pytest.MonkeyPatch, channel: DiscordChannel
) -> None:
    """Empty channel → deleted=0 but `last_cleanup_at` still bumped (run succeeded)."""
    client = MagicMock()
    client.fetch_channel_messages.return_value = []
    monkeypatch.setattr(
        "apps.deaths.services.DiscordRESTClient", lambda: client
    )
    before = timezone.now() - timedelta(seconds=1)

    result = cleanup_death_channel(channel)

    channel.refresh_from_db()
    assert result == {"deleted": 0}
    assert channel.last_cleanup_at is not None
    assert channel.last_cleanup_at > before


def test_cleanup_raises_and_does_not_update_timestamp_on_rest_failure(
    monkeypatch: pytest.MonkeyPatch, channel: DiscordChannel
) -> None:
    """REST returns False on bulk-delete → CleanupError raised, timestamp unchanged."""
    pages = iter([[_msg(1), _msg(2)], []])
    client = MagicMock()
    client.fetch_channel_messages.side_effect = lambda **kw: next(pages)
    client.bulk_delete_messages.return_value = False
    monkeypatch.setattr(
        "apps.deaths.services.DiscordRESTClient", lambda: client
    )

    with pytest.raises(CleanupError):
        cleanup_death_channel(channel)

    channel.refresh_from_db()
    assert channel.last_cleanup_at is None


def test_cleanup_passes_snowflake_cutoff_as_before(
    monkeypatch: pytest.MonkeyPatch, channel: DiscordChannel
) -> None:
    """First fetch uses snowflake(now - RETENTION_DAYS) as `before=`."""
    captured: dict[str, object] = {}

    def fake_fetch(**kw: object) -> list[dict[str, object]]:
        if "first" not in captured:
            captured["first"] = kw.get("before")
        return []

    client = MagicMock()
    client.fetch_channel_messages.side_effect = fake_fetch
    monkeypatch.setattr(
        "apps.deaths.services.DiscordRESTClient", lambda: client
    )

    cleanup_death_channel(channel)

    # Should be ~ snowflake(now - 3 days), tolerate ±1s skew.
    cutoff = timezone.now() - timedelta(days=3)
    expected = snowflake_for_datetime(cutoff)
    delta = abs(int(captured["first"]) - expected)
    # 1 sec ≈ 1000 ms ≈ 1000 << 22 = 4.19e9 snowflake units
    assert delta < (2 * 1000 << 22), f"first-call before snowflake too far from expected"
```

- [ ] **Step 2: Run tests — expected FAIL**

```bash
poetry run pytest tests/unit/deaths/test_cleanup_service.py -v
```

Expected: `ImportError: cannot import name 'CleanupError'` (or `cleanup_death_channel`).

- [ ] **Step 3: Implement `CleanupError` + `cleanup_death_channel`**

In `apps/deaths/services.py`, add to the top-level imports (so the test's monkeypatch on `apps.deaths.services.DiscordRESTClient` resolves correctly):

```python
from apps.notifications.discord_client import BulkDeleteAgeError, DiscordRESTClient
```

Add the exception near the top (after imports, before the existing `DeathPayload`):

```python
class CleanupError(Exception):
    """Raised by ``cleanup_death_channel`` on Discord REST failure.

    Caller (``cleanup_death_channels`` task) catches this, increments
    ``fail_count``, and moves on to the next guild. ``last_cleanup_at`` is
    NOT updated when this is raised, so ``/deaths cleanup status`` will show
    staleness — a built-in alarm for ops.
    """
```

Append the service function to the same file:

```python
def cleanup_death_channel(channel: "DiscordChannel") -> dict[str, int]:
    """Delete messages older than RETENTION_DAYS in ``channel.channel_id``.

    Algorithm:
      1. cutoff = now - RETENTION_DAYS
      2. paginate Discord messages with ``before=snowflake(cutoff)`` until
         an empty page comes back
      3. filter pinned messages client-side
      4. delete in chunks of 100 via bulk-delete; fall back to per-message
         DELETE for N==1 chunks AND for chunks that trip
         ``BulkDeleteAgeError`` (messages > 14d old)
      5. on success, bump ``last_cleanup_at = now()``

    Raises ``CleanupError`` on the first unrecoverable REST failure — the
    caller decides whether to retry on the next cron tick.
    """
    client = DiscordRESTClient()
    cutoff = django_timezone.now() - timedelta(days=RETENTION_DAYS)
    before_id = snowflake_for_datetime(cutoff)
    to_delete: list[int] = []

    while True:
        batch = client.fetch_channel_messages(
            channel_id=channel.channel_id,
            before=before_id,
            limit=100,
        )
        if not batch:
            break
        eligible = [int(m["id"]) for m in batch if not m.get("pinned")]
        to_delete.extend(eligible)
        before_id = int(batch[-1]["id"])

    deleted = 0
    for chunk in _chunked(to_delete, 100):
        if len(chunk) == 1:
            ok = client.delete_message(channel.channel_id, chunk[0])
            if not ok:
                raise CleanupError(
                    f"delete_message failed guild={channel.guild_id} msg={chunk[0]}"
                )
            deleted += 1
            continue

        try:
            ok = client.bulk_delete_messages(channel.channel_id, chunk)
        except BulkDeleteAgeError:
            logger.info(
                "bulk-delete age fallback for guild=%s chunk_size=%s",
                channel.guild_id,
                len(chunk),
            )
            for mid in chunk:
                if not client.delete_message(channel.channel_id, mid):
                    raise CleanupError(
                        f"delete_message failed guild={channel.guild_id} msg={mid}"
                    ) from None
                deleted += 1
            continue

        if not ok:
            raise CleanupError(
                f"bulk_delete_messages failed guild={channel.guild_id}"
            )
        deleted += len(chunk)

    channel.last_cleanup_at = django_timezone.now()
    channel.save(update_fields=["last_cleanup_at"])
    return {"deleted": deleted}


def _chunked(items: list[int], size: int) -> list[list[int]]:
    """Split a list into consecutive chunks of at most ``size``."""
    return [items[i : i + size] for i in range(0, len(items), size)]
```

> The `from apps.notifications.discord_client import ...` lives inside the function to avoid an import cycle at module load (notifications imports from discord_bot which imports from deaths in some test paths).

- [ ] **Step 4: Run tests — expected PASS**

```bash
poetry run pytest tests/unit/deaths/test_cleanup_service.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/deaths/services.py tests/unit/deaths/test_cleanup_service.py
git commit -m "feat(deaths): add cleanup_death_channel service with pagination + chunking"
```

---

## Task 7 — `cleanup_death_channels` Celery task

**Files:**
- Modify: `apps/deaths/tasks.py`
- Test: `tests/integration/test_cleanup_task.py` (create)

### TDD steps

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_cleanup_task.py`:

```python
"""Integration test for cleanup_death_channels Celery task — eager execution."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apps.deaths.tasks import cleanup_death_channels
from discord_bot.models import DiscordChannel


@pytest.mark.django_db
def test_cleanup_task_skips_disabled_guilds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only DiscordChannel rows with cleanup_enabled=True are processed."""
    DiscordChannel.objects.create(guild_id=1, channel_id=11, cleanup_enabled=True)
    DiscordChannel.objects.create(guild_id=2, channel_id=22, cleanup_enabled=True)
    DiscordChannel.objects.create(guild_id=3, channel_id=33, cleanup_enabled=False)

    fake_service = MagicMock(return_value={"deleted": 5})
    monkeypatch.setattr(
        "apps.deaths.tasks.cleanup_death_channel", fake_service
    )

    result = cleanup_death_channels.apply().get()

    assert result == {
        "guilds_processed": 2,
        "messages_deleted": 10,
        "fail_count": 0,
    }
    assert fake_service.call_count == 2


@pytest.mark.django_db
def test_cleanup_task_continues_after_per_guild_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One guild raises → fail_count increments, loop continues with others."""
    DiscordChannel.objects.create(guild_id=1, channel_id=11, cleanup_enabled=True)
    DiscordChannel.objects.create(guild_id=2, channel_id=22, cleanup_enabled=True)
    DiscordChannel.objects.create(guild_id=3, channel_id=33, cleanup_enabled=True)

    def fake(channel: DiscordChannel) -> dict[str, int]:
        if channel.guild_id == 2:
            raise RuntimeError("simulated REST failure")
        return {"deleted": 3}

    monkeypatch.setattr("apps.deaths.tasks.cleanup_death_channel", fake)

    result = cleanup_death_channels.apply().get()

    assert result == {
        "guilds_processed": 2,
        "messages_deleted": 6,
        "fail_count": 1,
    }


@pytest.mark.django_db
def test_cleanup_task_returns_zeros_when_no_guilds_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty enabled set → zeros, no crash, no service calls."""
    DiscordChannel.objects.create(guild_id=1, channel_id=11, cleanup_enabled=False)

    spy = MagicMock()
    monkeypatch.setattr("apps.deaths.tasks.cleanup_death_channel", spy)

    result = cleanup_death_channels.apply().get()

    assert result == {
        "guilds_processed": 0,
        "messages_deleted": 0,
        "fail_count": 0,
    }
    spy.assert_not_called()
```

- [ ] **Step 2: Run tests — expected FAIL**

```bash
poetry run pytest tests/integration/test_cleanup_task.py -v
```

Expected: `ImportError: cannot import name 'cleanup_death_channels' from 'apps.deaths.tasks'`.

- [ ] **Step 3: Implement the task**

Append to `apps/deaths/tasks.py`:

```python
from apps.deaths.services import cleanup_death_channel
from discord_bot.models import DiscordChannel


@shared_task(bind=True, max_retries=2)
def cleanup_death_channels(self: Task) -> dict[str, int]:
    """Iterate cleanup-enabled DiscordChannels, purge messages >RETENTION_DAYS old.

    Per-guild errors are logged and skipped — one failure does not block
    the others. Beat schedule lives in
    ``apps/deaths/migrations/0004_seed_cleanup_periodic_task.py`` (cron
    ``0 0 */3 * *`` Europe/Warsaw).
    """
    totals = {"guilds_processed": 0, "messages_deleted": 0, "fail_count": 0}

    for ch in DiscordChannel.objects.filter(cleanup_enabled=True):
        try:
            summary = cleanup_death_channel(ch)
            totals["messages_deleted"] += summary["deleted"]
            totals["guilds_processed"] += 1
        except Exception:
            logger.exception(
                "cleanup failed for guild=%s channel=%s",
                ch.guild_id,
                ch.channel_id,
            )
            totals["fail_count"] += 1

    logger.info("cleanup_death_channels: %s", totals)
    return totals
```

> Imports go at top of the file alongside existing ones; the `from apps.deaths.services import cleanup_death_channel` will already be near `announce_unannounced_deaths`.

- [ ] **Step 4: Run tests — expected PASS**

```bash
poetry run pytest tests/integration/test_cleanup_task.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/deaths/tasks.py tests/integration/test_cleanup_task.py
git commit -m "feat(deaths): add cleanup_death_channels Celery task"
```

---

## Task 8 — Periodic-task seed migration

**Files:**
- Create: `apps/deaths/migrations/0004_seed_cleanup_periodic_task.py`
- Test: `tests/integration/test_cleanup_periodic_task_seeded.py` (create)

### Background

Reuse the pattern from `apps/deaths/migrations/0002_seed_periodic_task.py`, but use `CrontabSchedule` instead of `IntervalSchedule` (we need timezone-aware cron, not a simple "every N minutes").

### TDD steps

- [ ] **Step 1: Verify next migration number**

```bash
ls apps/deaths/migrations/
```

Expected: existing `0001_initial.py`, `0002_seed_periodic_task.py`, `0003_deathevent_announced_on_discord.py`. New migration is `0004_seed_cleanup_periodic_task.py`. If a higher number exists (later milestone landed), bump accordingly.

- [ ] **Step 2: Write the failing test**

Create `tests/integration/test_cleanup_periodic_task_seeded.py`:

```python
"""Migration 0004 seeds the cleanup PeriodicTask with cron 0 0 */3 * * Europe/Warsaw."""

from __future__ import annotations

import pytest
from django_celery_beat.models import CrontabSchedule, PeriodicTask


@pytest.mark.django_db
def test_cleanup_periodic_task_exists() -> None:
    """The seeded periodic task is present after migrations have run."""
    pt = PeriodicTask.objects.get(name="deaths.cleanup_death_channels")
    assert pt.task == "apps.deaths.tasks.cleanup_death_channels"
    assert pt.enabled is True


@pytest.mark.django_db
def test_cleanup_periodic_task_cron_schedule() -> None:
    """Cron is 0 0 */3 * * with Europe/Warsaw timezone."""
    pt = PeriodicTask.objects.get(name="deaths.cleanup_death_channels")
    cron: CrontabSchedule = pt.crontab
    assert cron is not None
    assert cron.minute == "0"
    assert cron.hour == "0"
    assert cron.day_of_month == "*/3"
    assert cron.month_of_year == "*"
    assert cron.day_of_week == "*"
    assert str(cron.timezone) == "Europe/Warsaw"
```

- [ ] **Step 3: Run test — expected FAIL**

```bash
poetry run pytest tests/integration/test_cleanup_periodic_task_seeded.py -v
```

Expected: `PeriodicTask.DoesNotExist: PeriodicTask matching query does not exist.`

- [ ] **Step 4: Create the migration**

Create `apps/deaths/migrations/0004_seed_cleanup_periodic_task.py`:

```python
from django.db import migrations


def create_periodic_task(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    cron, _ = CrontabSchedule.objects.get_or_create(
        minute="0",
        hour="0",
        day_of_month="*/3",
        month_of_year="*",
        day_of_week="*",
        timezone="Europe/Warsaw",
    )
    PeriodicTask.objects.update_or_create(
        name="deaths.cleanup_death_channels",
        defaults={
            "task": "apps.deaths.tasks.cleanup_death_channels",
            "crontab": cron,
            "enabled": True,
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="deaths.cleanup_death_channels").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("deaths", "0003_deathevent_announced_on_discord"),
        ("django_celery_beat", "0001_initial"),
    ]
    operations = [migrations.RunPython(create_periodic_task, remove_periodic_task)]
```

- [ ] **Step 5: Apply migration locally**

```bash
poetry run python manage.py migrate deaths
```

Expected: `Applying deaths.0004_seed_cleanup_periodic_task... OK`.

- [ ] **Step 6: Run test — expected PASS**

```bash
poetry run pytest tests/integration/test_cleanup_periodic_task_seeded.py -v
```

Expected: both tests pass.

- [ ] **Step 7: Commit**

```bash
git add apps/deaths/migrations/0004_seed_cleanup_periodic_task.py tests/integration/test_cleanup_periodic_task_seeded.py
git commit -m "feat(deaths): seed cleanup_death_channels periodic task (cron 0 0 */3 * * Europe/Warsaw)"
```

---

## Task 9 — `discord_bot/services.py`: enable/disable/status helpers

**Files:**
- Modify: `discord_bot/services.py`
- Test: `tests/unit/discord_bot/test_cleanup_services.py` (create)

### TDD steps

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/discord_bot/test_cleanup_services.py`:

```python
"""Tests for cleanup-related helpers in discord_bot.services."""

from __future__ import annotations

import pytest
from django.utils import timezone

from discord_bot.models import DiscordChannel
from discord_bot.services import (
    disable_cleanup_for_guild,
    enable_cleanup_for_guild,
    get_cleanup_status,
)


@pytest.mark.django_db
def test_enable_cleanup_flips_flag_to_true() -> None:
    ch = DiscordChannel.objects.create(guild_id=1, channel_id=2)
    assert ch.cleanup_enabled is False

    ok = enable_cleanup_for_guild(guild_id=1)

    ch.refresh_from_db()
    assert ok is True
    assert ch.cleanup_enabled is True


@pytest.mark.django_db
def test_enable_cleanup_returns_false_when_no_channel() -> None:
    """No DiscordChannel for this guild → returns False (cog renders 'run /threshold first')."""
    ok = enable_cleanup_for_guild(guild_id=999)
    assert ok is False


@pytest.mark.django_db
def test_disable_cleanup_flips_flag_to_false() -> None:
    ch = DiscordChannel.objects.create(
        guild_id=1, channel_id=2, cleanup_enabled=True
    )

    ok = disable_cleanup_for_guild(guild_id=1)

    ch.refresh_from_db()
    assert ok is True
    assert ch.cleanup_enabled is False


@pytest.mark.django_db
def test_disable_cleanup_returns_false_when_no_channel() -> None:
    assert disable_cleanup_for_guild(guild_id=999) is False


@pytest.mark.django_db
def test_get_cleanup_status_returns_full_state() -> None:
    now = timezone.now()
    DiscordChannel.objects.create(
        guild_id=1,
        channel_id=42,
        cleanup_enabled=True,
        last_cleanup_at=now,
    )

    status = get_cleanup_status(guild_id=1)

    assert status is not None
    assert status["enabled"] is True
    assert status["last_cleanup_at"] == now
    assert status["channel_id"] == 42


@pytest.mark.django_db
def test_get_cleanup_status_returns_none_when_no_channel() -> None:
    """Cog uses this None to render 'no channel registered'."""
    assert get_cleanup_status(guild_id=999) is None
```

- [ ] **Step 2: Run tests — expected FAIL**

```bash
poetry run pytest tests/unit/discord_bot/test_cleanup_services.py -v
```

Expected: `ImportError: cannot import name 'enable_cleanup_for_guild'`.

- [ ] **Step 3: Implement the helpers**

Append to `discord_bot/services.py` (below the existing functions):

```python
from datetime import datetime
from typing import TypedDict


class CleanupStatus(TypedDict):
    """Status payload consumed by ``/deaths cleanup status``."""

    enabled: bool
    last_cleanup_at: datetime | None
    channel_id: int


def enable_cleanup_for_guild(guild_id: int) -> bool:
    """Set ``cleanup_enabled=True`` on the guild's DiscordChannel.

    Returns False (no-op) when no DiscordChannel exists for the guild —
    cog surfaces a "run /deaths threshold first" message in that case.
    """
    updated = DiscordChannel.objects.filter(guild_id=guild_id).update(
        cleanup_enabled=True
    )
    if updated:
        logger.info("Enabled cleanup for guild=%s", guild_id)
        return True
    return False


def disable_cleanup_for_guild(guild_id: int) -> bool:
    """Mirror of ``enable_cleanup_for_guild`` flipping the flag off."""
    updated = DiscordChannel.objects.filter(guild_id=guild_id).update(
        cleanup_enabled=False
    )
    if updated:
        logger.info("Disabled cleanup for guild=%s", guild_id)
        return True
    return False


def get_cleanup_status(guild_id: int) -> CleanupStatus | None:
    """Return ``CleanupStatus`` for the guild, or ``None`` if no channel registered."""
    try:
        ch = DiscordChannel.objects.get(guild_id=guild_id)
    except DiscordChannel.DoesNotExist:
        return None
    return CleanupStatus(
        enabled=ch.cleanup_enabled,
        last_cleanup_at=ch.last_cleanup_at,
        channel_id=ch.channel_id,
    )
```

- [ ] **Step 4: Run tests — expected PASS**

```bash
poetry run pytest tests/unit/discord_bot/test_cleanup_services.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add discord_bot/services.py tests/unit/discord_bot/test_cleanup_services.py
git commit -m "feat(discord-bot): add enable/disable/status helpers for channel cleanup"
```

---

## Task 10 — `/deaths cleanup on|off|status|now` slash commands

**Files:**
- Modify: `discord_bot/cogs/deaths.py`
- Test: `tests/unit/discord_bot/test_deaths_cog.py` (extend)

### Notes

- Sub-group `cleanup` lives under the existing `deaths = SlashCommandGroup("deaths", ...)`.
- DM-context guard and admin guard mirror the existing `/deaths threshold` (see file header doc for the two-layer order).
- `cleanup now` calls `cleanup_death_channel` synchronously via `sync_to_async` — immediate feedback matters for `now`.
- `cleanup status` responds **ephemerally** (visible only to the caller); the other three are public.

### TDD steps

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/discord_bot/test_deaths_cog.py`:

```python
# ─── /deaths cleanup on ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_on_rejects_dm_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.guild = None
    mock_ctx.respond = AsyncMock()

    spy = MagicMock()
    monkeypatch.setattr("discord_bot.cogs.deaths.enable_cleanup_for_guild", spy)

    cog = DeathsCog(bot=MagicMock())
    await cog.cleanup_on.callback(cog, mock_ctx)

    args, kwargs = mock_ctx.respond.call_args
    assert "must be used in a server" in args[0]
    assert kwargs["ephemeral"] is True
    spy.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_on_rejects_non_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.guild = MagicMock()
    mock_ctx.guild.id = 1
    mock_ctx.author = MagicMock(spec=discord.Member)
    mock_ctx.author.guild_permissions.administrator = False
    mock_ctx.respond = AsyncMock()

    spy = MagicMock()
    monkeypatch.setattr("discord_bot.cogs.deaths.enable_cleanup_for_guild", spy)

    cog = DeathsCog(bot=MagicMock())
    await cog.cleanup_on.callback(cog, mock_ctx)

    args, kwargs = mock_ctx.respond.call_args
    assert "Server admins only" in args[0]
    assert kwargs["ephemeral"] is True
    spy.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_on_warns_when_channel_not_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service returns False (no row) → cog tells admin to run /threshold first."""
    mock_ctx = _admin_ctx()
    monkeypatch.setattr(
        "discord_bot.cogs.deaths.enable_cleanup_for_guild",
        MagicMock(return_value=False),
    )

    cog = DeathsCog(bot=MagicMock())
    await cog.cleanup_on.callback(cog, mock_ctx)

    args, kwargs = mock_ctx.respond.call_args
    assert "Run `/deaths threshold` first" in args[0]
    assert kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_cleanup_on_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_ctx = _admin_ctx()
    monkeypatch.setattr(
        "discord_bot.cogs.deaths.enable_cleanup_for_guild",
        MagicMock(return_value=True),
    )

    cog = DeathsCog(bot=MagicMock())
    await cog.cleanup_on.callback(cog, mock_ctx)

    args, kwargs = mock_ctx.respond.call_args
    assert "Cleanup enabled" in args[0]
    # Public ack (no ephemeral kwarg)
    assert "ephemeral" not in kwargs or kwargs["ephemeral"] is False


# ─── /deaths cleanup off ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_off_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_ctx = _admin_ctx()
    monkeypatch.setattr(
        "discord_bot.cogs.deaths.disable_cleanup_for_guild",
        MagicMock(return_value=True),
    )

    cog = DeathsCog(bot=MagicMock())
    await cog.cleanup_off.callback(cog, mock_ctx)

    args, _ = mock_ctx.respond.call_args
    assert "Cleanup disabled" in args[0]


# ─── /deaths cleanup status ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_status_renders_never_when_no_runs_yet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_ctx = _admin_ctx()
    monkeypatch.setattr(
        "discord_bot.cogs.deaths.get_cleanup_status",
        MagicMock(
            return_value={"enabled": True, "last_cleanup_at": None, "channel_id": 42}
        ),
    )

    cog = DeathsCog(bot=MagicMock())
    await cog.cleanup_status.callback(cog, mock_ctx)

    args, kwargs = mock_ctx.respond.call_args
    text = args[0] if args else kwargs.get("content", "")
    assert "never" in text.lower()
    assert kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_cleanup_status_warns_when_channel_not_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_ctx = _admin_ctx()
    monkeypatch.setattr(
        "discord_bot.cogs.deaths.get_cleanup_status", MagicMock(return_value=None)
    )

    cog = DeathsCog(bot=MagicMock())
    await cog.cleanup_status.callback(cog, mock_ctx)

    args, kwargs = mock_ctx.respond.call_args
    assert "Run `/deaths threshold` first" in args[0]
    assert kwargs["ephemeral"] is True


# ─── /deaths cleanup now ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_now_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_ctx = _admin_ctx()
    mock_ctx.defer = AsyncMock()
    mock_ctx.followup = MagicMock()
    mock_ctx.followup.send = AsyncMock()

    from discord_bot.models import DiscordChannel

    fake_channel = DiscordChannel(guild_id=1, channel_id=42)
    monkeypatch.setattr(
        "discord_bot.cogs.deaths._fetch_channel_for_guild",
        MagicMock(return_value=fake_channel),
    )
    monkeypatch.setattr(
        "discord_bot.cogs.deaths.cleanup_death_channel",
        MagicMock(return_value={"deleted": 17}),
    )

    cog = DeathsCog(bot=MagicMock())
    await cog.cleanup_now.callback(cog, mock_ctx)

    mock_ctx.defer.assert_called_once()
    args, _ = mock_ctx.followup.send.call_args
    assert "Deleted 17" in args[0]


@pytest.mark.asyncio
async def test_cleanup_now_handles_cleanup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.deaths.services import CleanupError
    from discord_bot.models import DiscordChannel

    mock_ctx = _admin_ctx()
    mock_ctx.defer = AsyncMock()
    mock_ctx.followup = MagicMock()
    mock_ctx.followup.send = AsyncMock()

    monkeypatch.setattr(
        "discord_bot.cogs.deaths._fetch_channel_for_guild",
        MagicMock(return_value=DiscordChannel(guild_id=1, channel_id=42)),
    )
    monkeypatch.setattr(
        "discord_bot.cogs.deaths.cleanup_death_channel",
        MagicMock(side_effect=CleanupError("simulated")),
    )

    cog = DeathsCog(bot=MagicMock())
    await cog.cleanup_now.callback(cog, mock_ctx)

    args, kwargs = mock_ctx.followup.send.call_args
    assert "Cleanup failed" in args[0]
    assert kwargs.get("ephemeral") is True


# === helper ===


def _admin_ctx() -> MagicMock:
    """Build a MagicMock ctx that looks like an admin in a guild."""
    ctx = MagicMock(spec=discord.ApplicationContext)
    ctx.guild = MagicMock()
    ctx.guild.id = 1
    ctx.channel_id = 42
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.guild_permissions.administrator = True
    ctx.respond = AsyncMock()
    return ctx
```

- [ ] **Step 2: Run tests — expected FAIL**

```bash
poetry run pytest tests/unit/discord_bot/test_deaths_cog.py -v -k "cleanup"
```

Expected: `AttributeError: 'DeathsCog' object has no attribute 'cleanup_on'`.

- [ ] **Step 3: Implement the cog**

Replace `discord_bot/cogs/deaths.py` with the extended version:

```python
# NOTE: NO `from __future__ import annotations` here — py-cord introspects
# parameter annotations at slash command invocation time and requires them
# as runtime objects, not PEP 563 strings.
from asgiref.sync import sync_to_async
import discord
from discord.ext import commands

from apps.deaths.services import CleanupError, cleanup_death_channel
from discord_bot.models import DiscordChannel
from discord_bot.services import (
    disable_cleanup_for_guild,
    enable_cleanup_for_guild,
    get_cleanup_status,
    set_death_threshold_for_guild,
)


def _fetch_channel_for_guild(guild_id: int) -> DiscordChannel | None:
    """ORM read isolated for monkeypatching in cog tests."""
    try:
        return DiscordChannel.objects.get(guild_id=guild_id)
    except DiscordChannel.DoesNotExist:
        return None


def _humanize_last_cleanup(dt) -> str:
    """Render an absolute timestamp as a short relative string ('2d 4h ago')."""
    if dt is None:
        return "never"
    from django.utils import timezone

    delta = timezone.now() - dt
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return "just now"
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h ago"
    if hours:
        return f"{hours}h {minutes}m ago"
    return f"{minutes}m ago"


class DeathsCog(commands.Cog):
    """Admin-side death-monitor configuration commands."""

    deaths = discord.SlashCommandGroup("deaths", "Death monitor configuration")
    cleanup = deaths.create_subgroup(
        "cleanup", "Death-channel auto-cleanup configuration"
    )

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    # ─── /deaths threshold (unchanged) ────────────────────────────────────

    @deaths.command(
        name="threshold",
        description="Set death notification level threshold (server admin only)",
    )
    async def threshold(
        self,
        ctx: discord.ApplicationContext,
        level: discord.Option(
            int, "Minimum level to notify", min_value=1, max_value=999
        ),
    ) -> None:
        if ctx.guild is None:
            await ctx.respond(
                "❌ This command must be used in a server.", ephemeral=True
            )
            return

        assert isinstance(ctx.author, discord.Member)
        assert ctx.channel_id is not None

        if not ctx.author.guild_permissions.administrator:
            await ctx.respond(
                "❌ Only server admins can change the death threshold.",
                ephemeral=True,
            )
            return

        await sync_to_async(set_death_threshold_for_guild)(
            guild_id=ctx.guild.id,
            channel_id=ctx.channel_id,
            threshold=level,
        )
        await ctx.respond(f"🪦 Death notification threshold set to level **{level}**.")

    # ─── /deaths cleanup on ───────────────────────────────────────────────

    @cleanup.command(name="on", description="Enable 3-day cleanup (admin only)")
    async def cleanup_on(self, ctx: discord.ApplicationContext) -> None:
        if ctx.guild is None:
            await ctx.respond(
                "❌ This command must be used in a server.", ephemeral=True
            )
            return
        assert isinstance(ctx.author, discord.Member)
        if not ctx.author.guild_permissions.administrator:
            await ctx.respond("❌ Server admins only.", ephemeral=True)
            return

        ok = await sync_to_async(enable_cleanup_for_guild)(guild_id=ctx.guild.id)
        if not ok:
            await ctx.respond(
                "❌ Run `/deaths threshold` first to register this channel.",
                ephemeral=True,
            )
            return

        await ctx.respond(
            "🧹 Cleanup enabled — messages older than 3 days will be removed every "
            "3 days at 00:00 Europe/Warsaw."
        )

    # ─── /deaths cleanup off ──────────────────────────────────────────────

    @cleanup.command(name="off", description="Disable cleanup (admin only)")
    async def cleanup_off(self, ctx: discord.ApplicationContext) -> None:
        if ctx.guild is None:
            await ctx.respond(
                "❌ This command must be used in a server.", ephemeral=True
            )
            return
        assert isinstance(ctx.author, discord.Member)
        if not ctx.author.guild_permissions.administrator:
            await ctx.respond("❌ Server admins only.", ephemeral=True)
            return

        ok = await sync_to_async(disable_cleanup_for_guild)(guild_id=ctx.guild.id)
        if not ok:
            await ctx.respond(
                "❌ Run `/deaths threshold` first to register this channel.",
                ephemeral=True,
            )
            return

        await ctx.respond("🧹 Cleanup disabled.")

    # ─── /deaths cleanup status ───────────────────────────────────────────

    @cleanup.command(name="status", description="Show cleanup state")
    async def cleanup_status(self, ctx: discord.ApplicationContext) -> None:
        if ctx.guild is None:
            await ctx.respond(
                "❌ This command must be used in a server.", ephemeral=True
            )
            return

        status = await sync_to_async(get_cleanup_status)(guild_id=ctx.guild.id)
        if status is None:
            await ctx.respond(
                "❌ Run `/deaths threshold` first to register this channel.",
                ephemeral=True,
            )
            return

        enabled = "✅ enabled" if status["enabled"] else "⏸️ disabled"
        last_run = _humanize_last_cleanup(status["last_cleanup_at"])
        await ctx.respond(
            f"🧹 Cleanup: {enabled}\n"
            f"Last run: {last_run}\n"
            f"Channel: <#{status['channel_id']}>",
            ephemeral=True,
        )

    # ─── /deaths cleanup now ──────────────────────────────────────────────

    @cleanup.command(
        name="now", description="Run cleanup immediately (admin only)"
    )
    async def cleanup_now(self, ctx: discord.ApplicationContext) -> None:
        if ctx.guild is None:
            await ctx.respond(
                "❌ This command must be used in a server.", ephemeral=True
            )
            return
        assert isinstance(ctx.author, discord.Member)
        if not ctx.author.guild_permissions.administrator:
            await ctx.respond("❌ Server admins only.", ephemeral=True)
            return

        channel = await sync_to_async(_fetch_channel_for_guild)(ctx.guild.id)
        if channel is None:
            await ctx.respond(
                "❌ Run `/deaths threshold` first to register this channel.",
                ephemeral=True,
            )
            return

        await ctx.defer()
        try:
            summary = await sync_to_async(cleanup_death_channel)(channel)
        except CleanupError as exc:
            await ctx.followup.send(
                f"❌ Cleanup failed: {exc}", ephemeral=True
            )
            return

        await ctx.followup.send(f"🧹 Deleted {summary['deleted']} messages.")
```

- [ ] **Step 4: Run cog tests — expected PASS**

```bash
poetry run pytest tests/unit/discord_bot/test_deaths_cog.py -v
```

Expected: all tests pass — pre-existing `/deaths threshold` tests plus the new cleanup-subcommand tests.

- [ ] **Step 5: Full test sweep — regression check**

```bash
poetry run pytest -v
```

Expected: every test passes. Pay attention to anything in `tests/unit/notifications/`, `tests/unit/deaths/`, `tests/integration/`, `tests/unit/discord_bot/`.

- [ ] **Step 6: Run pre-commit on the full diff**

```bash
poetry run pre-commit run --all-files
```

Expected: all hooks pass. If `ruff` reformats or `mypy` flags anything, fix and re-run.

- [ ] **Step 7: Commit**

```bash
git add discord_bot/cogs/deaths.py tests/unit/discord_bot/test_deaths_cog.py
git commit -m "feat(discord-bot): add /deaths cleanup on|off|status|now slash commands"
```

---

## Task 11 — Final verification + PR

**Files:**
- None to change. This task verifies the full diff and opens a PR.

### Steps

- [ ] **Step 1: Full test suite + coverage**

```bash
poetry run pytest --cov=apps --cov=discord_bot --cov-report=term-missing
```

Expected: all pass, coverage ≥70% (CI threshold). Inspect the report — cleanup-related modules should be 85%+.

- [ ] **Step 2: Pre-commit on all files**

```bash
poetry run pre-commit run --all-files
```

Expected: green.

- [ ] **Step 3: Smoke-run the Celery task locally (dev DB)**

```bash
poetry run python manage.py shell -c "from apps.deaths.tasks import cleanup_death_channels; print(cleanup_death_channels.apply().get())"
```

Expected (in clean dev DB with no enabled channels): `{'guilds_processed': 0, 'messages_deleted': 0, 'fail_count': 0}`.

- [ ] **Step 4: Push branch**

```bash
git push -u origin feat/death-channel-cleanup
```

- [ ] **Step 5: Open PR via `gh`**

```bash
gh pr create --title "feat(deaths): 3-day auto-cleanup of death-announcement channels" --body "$(cat <<'EOF'
## Summary
- Adds `cleanup_enabled` + `last_cleanup_at` to `DiscordChannel` (opt-in default OFF).
- New Celery Beat task `cleanup_death_channels` running cron `0 0 */3 * *` Europe/Warsaw.
- Service `apps.deaths.services.cleanup_death_channel` paginates Discord by snowflake, filters pinned messages, deletes in bulk-delete chunks of 100 (single-delete fallback for N==1 and >14d messages).
- Three new `DiscordRESTClient` methods: `fetch_channel_messages`, `bulk_delete_messages` (raises `BulkDeleteAgeError` on 50034), `delete_message`.
- Slash commands `/deaths cleanup on|off|status|now` (admin gated except `status`).

Spec: `docs/superpowers/specs/2026-06-01-death-channel-cleanup-design.md`
Plan: `docs/superpowers/plans/2026-06-01-death-channel-cleanup-implementation-plan.md`

## Test plan
- [x] Unit: snowflake helper, cleanup service (8 scenarios), Discord client (fetch/bulk-delete/delete), discord_bot service helpers
- [x] Integration: Celery task with eager execution (skip-disabled, per-guild-failure, empty set), migration seeds PeriodicTask
- [x] Cog: admin/DM gates, "channel not registered" error path, happy path for each of the 4 commands
- [x] `pre-commit run --all-files` green
- [x] Smoke: `cleanup_death_channels.apply().get()` returns zeros on clean DB
- [ ] Manual: enable on a test guild via `/deaths cleanup on`, post >3d-old message manually, `cleanup now`, verify it disappears
EOF
)"
```

- [ ] **Step 6: Mark plan tasks complete in PR description**

After PR is open, ensure the checklist reflects everything that's done.

---

## Self-review notes (for the implementer)

- **Order independence:** Tasks 2–9 reference each other only by name. If you reorder, only Task 1 (model) must come before Task 6 (service uses model), and Task 6 before Task 7 (task uses service), and Task 8 (migration) after Task 7 (migration references the task). Tasks 3, 4, 5 can be reordered freely.
- **Tests live alongside production code commits.** Each task commits both the test file AND the implementation in one commit (TDD red→green inside the task, but one commit per task per spec convention §15.15).
- **No mocks for the actual Discord REST.** Tests use `httpx.MockTransport` (see fixture in `tests/unit/notifications/test_discord_client.py`) — never hit real `discord.com`.
- **CLAUDE.md §15.9 reminder:** the Discord bot is a separate process. Don't run `cleanup_death_channel` from a Django view — only from Celery (Tasks 7-8) or via `sync_to_async` inside a slash-command handler (Task 10).
