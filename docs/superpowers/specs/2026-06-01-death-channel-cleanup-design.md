# Death Channel Cleanup — Design

**Data:** 2026-06-01
**Robocza nazwa feature:** Death channel cleanup (kanał z ogłoszeniami śmierci jest zalewany wiadomościami — chcemy auto-purge co 3 dni).
**Poprzednie milestone'y istotne dla kontekstu:** M4 (deaths monitor — scrape tibiantis.info), M7 (Discord bot + `/deaths threshold`), M8 (outbound notifications przez `DiscordRESTClient`).

---

## 1. Cel

Dodać auto-cleanup wiadomości w kanale Discord skonfigurowanym jako death-announcement target. Konkretnie:

1. Co 3 dni o **00:00 Europe/Warsaw** Celery Beat odpala task `cleanup_death_channels`.
2. Task iteruje rekordy `DiscordChannel` z włączonym opt-in flagiem (`cleanup_enabled=True`) i dla każdego kanału usuwa wiadomości starsze niż **3 dni** (`RETENTION_DAYS=3`).
3. Usuwanie idzie przez `DiscordRESTClient` (Bot Token, REST, **bez gateway** — bot pozostaje "tylko slash commands" zgodnie z CLAUDE.md §8: "Bot nie wysyła powiadomień sam z siebie — robi to Celery task").
4. Admin serwera Discord steruje featurem przez slash commands `/deaths cleanup on|off|status|now` (subgrupa pod istniejącą `/deaths`).
5. Wiadomości **przypięte** (`pinned=true`) są zawsze pomijane — bezpiecznik na pinned rules/info.

**Świadomie wąski scope:**
- **Stała retencja 3 dni.** Nie konfigurowalna per-guild — user explicit (Q2 w brainstorm) "Keep last 3 days". Jeśli pojawi się potrzeba różnicowania, dorzucamy `retention_days` field w następnym milestone.
- **Opt-in, default OFF.** Istniejące guildy nie zostają zaskoczone masowym usunięciem przy pierwszym deploy.
- **Tylko channel z `DiscordChannel.channel_id`.** Threads, sub-channels, inne kanały — out of scope.

**Świadomie odroczone (Out of scope):**
- Per-guild konfigurowalne `retention_days` (obecnie stała `RETENTION_DAYS=3` w `apps/deaths/services.py`). Trigger: drugi guild prosi o inną wartość.
- Skanowanie threadów wewnątrz kanału (Discord channel-messages endpoint ich nie zwraca; threads zostają nietknięte).
- Backup/archive usuniętych wiadomości do MongoDB (`scrape_logs` to nie jest właściwa kolekcja, a `app_logs` nie jest miejscem na treść biznesową). Trigger: incydent z przypadkowym wyczyszczeniem.
- Soft-delete / preview "co zostanie usunięte" przed wykonaniem. Trigger: pierwszy incident "ojej, miałem tam ważną wiadomość".
- Notification do admina przed/po wyczyszczeniu (DM lub message w kanale). Trigger: feedback od pierwszych użytkowników.
- Auto-disable po N kolejnych failed runs (np. bot kicked z guildy). Manual `/deaths cleanup off` na razie wystarczy.

---

## 2. Scope

**W scope:**

- **Model change** w `discord_bot/models.py` — dwa nowe pola na `DiscordChannel`:
  - `cleanup_enabled = BooleanField(default=False)` — opt-in toggle.
  - `last_cleanup_at = DateTimeField(null=True, blank=True)` — observability dla `/status`.
- **Migracja schema** `discord_bot/migrations/0002_discord_channel_cleanup_fields.py` (auto-generated).
- **Migracja data** `apps/deaths/migrations/0004_seed_cleanup_periodic_task.py` — seed `PeriodicTask` z crontab `0 0 */3 * *` timezone `Europe/Warsaw`, `task="apps.deaths.tasks.cleanup_death_channels"`, `enabled=True`.
- **Service** `apps/deaths/services.py::cleanup_death_channel(channel: DiscordChannel) -> dict[str, int]`:
  - Pure-logic per-channel cleanup. Paginates Discord messages używając snowflake-based `before=<id>` query parameter (Discord ID koduje timestamp — `((unix_ms - 1420070400000) << 22)`).
  - Filtruje `pinned=True` client-side.
  - Bulk-delete chunks ≤100 IDs przez `bulk_delete_messages`; fallback single `delete_message` gdy `N == 1` (bulk-delete API wymaga 2 ≤ N ≤ 100).
  - Update `channel.last_cleanup_at = timezone.now()` **tylko** przy sukcesie (`update_fields=["last_cleanup_at"]`).
  - Raises `CleanupError` przy REST failure → caller (task) loguje i kontynuuje z następnym guild.
- **Helper** `apps/deaths/services.py::snowflake_for_datetime(dt: datetime) -> int` — round-trippable z fixturami.
- **Celery task** `apps/deaths/tasks.py::cleanup_death_channels`:
  - `bind=True, max_retries=2` (wzorzec z `scrape_deaths`).
  - Iteruje `DiscordChannel.objects.filter(cleanup_enabled=True)`.
  - Try/except per-guild — pojedynczy fail nie blokuje pozostałych.
  - Returns summary `{"guilds_processed": int, "messages_deleted": int, "fail_count": int}`.
  - Logger INFO summary, WARNING per per-guild failure.
- **Three nowe metody** w `apps/notifications/discord_client.py` (`DiscordRESTClient`):
  - `fetch_channel_messages(channel_id: int, before: int | None = None, limit: int = 100) -> list[dict[str, Any]]` — `GET /channels/{id}/messages?before=&limit=`.
  - `bulk_delete_messages(channel_id: int, message_ids: list[int]) -> bool` — `POST /channels/{id}/messages/bulk-delete` body `{"messages": [...]}`. Wymaga 2 ≤ N ≤ 100 i msgs <14d (zagwarantowane przez 3-day cutoff).
  - `delete_message(channel_id: int, message_id: int) -> bool` — `DELETE /channels/{id}/messages/{mid}`, fallback dla N==1.
  - Wszystkie używają istniejącego `_request` pattern (retry on 5xx/429, single retry, respect `Retry-After`).
- **Discord-bot services** w `discord_bot/services.py`:
  - `enable_cleanup_for_guild(guild_id: int) -> bool` — set `cleanup_enabled=True` na istniejącym `DiscordChannel`. Zwraca `False` gdy brak row.
  - `disable_cleanup_for_guild(guild_id: int) -> bool` — analogicznie.
  - `get_cleanup_status(guild_id: int) -> CleanupStatus | None` — TypedDict `{enabled: bool, last_cleanup_at: datetime | None, channel_id: int}`. None gdy brak `DiscordChannel`.
- **Discord cog** rozszerzenie `discord_bot/cogs/deaths.py`:
  - `cleanup = deaths.create_subgroup("cleanup", "Death-channel auto-cleanup configuration")`.
  - `/deaths cleanup on` — admin-only, public ack: "🧹 Cleanup enabled — messages older than 3 days will be removed every 3 days at 00:00 Europe/Warsaw."
  - `/deaths cleanup off` — admin-only, public ack: "🧹 Cleanup disabled."
  - `/deaths cleanup status` — anyone, ephemeral embed: `enabled`, `last_cleanup_at` (relative format "2d 4h ago" / "never"), `channel_id`.
  - `/deaths cleanup now` — admin-only, defer + followup; synchronous (sync_to_async) call do `services.cleanup_death_channel(channel)`. Followup: "🧹 Deleted N messages." lub user-friendly error.
- **Constant** `RETENTION_DAYS = 3` w `apps/deaths/services.py` (module-level).

**Out of scope (już wymienione w §1):**
- Per-guild `retention_days`, threads, archive/backup, notification before/after, soft-delete.

---

## 3. Dane

### 3.1. Model change: `discord_bot.DiscordChannel`

```python
class DiscordChannel(models.Model):
    guild_id = models.BigIntegerField()
    channel_id = models.BigIntegerField()
    death_level_threshold = models.PositiveIntegerField(default=30)
    # NEW
    cleanup_enabled = models.BooleanField(default=False)
    last_cleanup_at = models.DateTimeField(null=True, blank=True)
    # /NEW
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["guild_id"], name="discord_channel_one_per_guild"
            ),
        ]
```

**Field rationale:**
- `cleanup_enabled` — per-guild opt-in toggle. Default `False` — bezpieczna semantyka deploy.
- `last_cleanup_at` — observability, source of truth dla `/status`. Aktualizowany **tylko** po success (failed run nie aktualizuje → status pokazuje staleness, sygnalizuje problem).

### 3.2. Migracje

- `discord_bot/migrations/0002_discord_channel_cleanup_fields.py` — schema migration (auto-generated `makemigrations`). Backfill nie potrzebny (defaults pokrywają istniejące rows).
- `apps/deaths/migrations/0004_seed_cleanup_periodic_task.py` — data migration:
  ```python
  PeriodicTask.objects.update_or_create(
      name="deaths.cleanup_death_channels",
      defaults={
          "crontab": CrontabSchedule.objects.get_or_create(
              minute="0", hour="0", day_of_month="*/3",
              month_of_year="*", day_of_week="*",
              timezone="Europe/Warsaw",
          )[0],
          "task": "apps.deaths.tasks.cleanup_death_channels",
          "enabled": True,
      },
  )
  ```
  Pattern z istniejącego `apps/deaths/migrations/0002_seed_periodic_task.py`.

**Caveat cron `0 0 */3 * *` (akceptowany):**
Na granicy miesięcy `*/3` resetuje (np. dzień 31 → dzień 1 to tylko 1-dniowy odstęp zamiast 3). User świadomie zaakceptował to w brainstorm Q5. W praktyce: ~10 razy w roku cykl ma 1-2 dni zamiast 3. Nie warto komplikować schedulera.

---

## 4. Algorytm cleanup (per-channel)

```python
RETENTION_DAYS = 3
DISCORD_EPOCH_MS = 1420070400000


def snowflake_for_datetime(dt: datetime) -> int:
    """Discord IDs encode timestamp in their high 42 bits.
    snowflake = (unix_ms - DISCORD_EPOCH_MS) << 22
    """
    unix_ms = int(dt.timestamp() * 1000)
    return (unix_ms - DISCORD_EPOCH_MS) << 22


def cleanup_death_channel(channel: DiscordChannel) -> dict[str, int]:
    """Delete messages older than RETENTION_DAYS in channel.channel_id.

    - Snowflake-based `before=` pagination — nie skanujemy całego kanału.
    - Filtruje pinned messages.
    - Bulk-delete chunks ≤100, fallback single-delete dla N==1.
    - Updates last_cleanup_at tylko on success.
    - Raises CleanupError on REST failure.
    """
    client = DiscordRESTClient()
    cutoff = timezone.now() - timedelta(days=RETENTION_DAYS)
    before_id = snowflake_for_datetime(cutoff)
    to_delete: list[int] = []

    while True:
        batch = client.fetch_channel_messages(channel.channel_id, before=before_id, limit=100)
        if not batch:
            break
        eligible = [int(m["id"]) for m in batch if not m.get("pinned")]
        to_delete.extend(eligible)
        before_id = int(batch[-1]["id"])

    deleted = 0
    for chunk in _chunked(to_delete, 100):
        if len(chunk) == 1:
            ok = client.delete_message(channel.channel_id, chunk[0])
        else:
            ok = client.bulk_delete_messages(channel.channel_id, chunk)
        if not ok:
            raise CleanupError(f"Discord REST failure for guild={channel.guild_id}")
        deleted += len(chunk)

    channel.last_cleanup_at = timezone.now()
    channel.save(update_fields=["last_cleanup_at"])
    return {"deleted": deleted}
```

**Key design points:**
- **Snowflake `before=`.** Discord IDs są monotonicznie rosnące w czasie. `before=<snowflake>` zwraca wiadomości starsze. Eliminuje konieczność pobierania pełnej historii kanału.
- **3-day cutoff vs 14-day bulk-delete limit.** Bulk-delete API wymaga `< 14 days`. Nasz 3-day cutoff to zawsze spełnia. (Edge case: opóźniony task → wiadomości >14d → fallback do per-message DELETE handled w §6 błędach.)
- **`last_cleanup_at` update tylko on success.** Failed cleanup zostawia stare `last_cleanup_at` — `/status` pokazuje "5d ago" → admin widzi że coś nie działa.

---

## 5. Celery task

```python
# apps/deaths/tasks.py

@shared_task(bind=True, max_retries=2)
def cleanup_death_channels(self: Task) -> dict[str, int]:
    """Iterate cleanup-enabled DiscordChannels, delete messages >RETENTION_DAYS old.

    Per-guild errors are logged and skipped — single failure nie blokuje pozostałych.
    Returns aggregated summary for observability.
    """
    channels = DiscordChannel.objects.filter(cleanup_enabled=True)
    totals = {"guilds_processed": 0, "messages_deleted": 0, "fail_count": 0}

    for ch in channels:
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

**Decyzje:**
- **Brak `self.retry()` na poziomie task.** Cleanup jest idempotentne (bulk-delete na już-usuniętych ID zwraca 4xx, swalliwane), więc retry storm nie bolą, ale partial progress jest OK — następny cron run pickup leftovers.
- **`max_retries=2`** wewnątrz Celery pattern (jak `scrape_deaths`) — chronie przed transient infrastructure errors (Redis down podczas start).
- **Brak singleton lock** (jak `deathwatch_scrape_lock` w M11). Cron `0 0 */3 * *` = raz na 3 dni — szansa overlap ~zero.

---

## 6. Error handling

| Failure | Where caught | Behaviour |
|---|---|---|
| Discord 4xx (channel deleted, bot kicked) | `DiscordRESTClient._request` zwraca `None`/`False` | `cleanup_death_channel` raises `CleanupError`. Task loop loguje `guild_id, channel_id`, increments `fail_count`, kontynuuje. `last_cleanup_at` NIE update'owany. |
| Discord 429 | `_request` retry once respecting `Retry-After` (existing) | Transparent. Persistent 429 → treated as failure. |
| Discord 5xx | `_request` retry once (existing) | Persistent 5xx → failure. |
| Bot lacks `MANAGE_MESSAGES` | 403 na bulk-delete | Logged once per run. `cleanup_enabled` zostaje True — admin manual fix permissions albo `/deaths cleanup off`. |
| Message >14d (edge case: opóźniony task) | 400 na bulk-delete | Fallback: chunk iterated per-message przez `delete_message` (slower, ale działa na messages dowolnego wieku). Implementacja: catch `BulkDeleteAgeError` z `bulk_delete_messages`, retry chunk single-by-single. |
| `DiscordChannel` row deleted mid-run | Iteration snapshot — already in memory | No effect. Next run skip. |
| Beat overlap (poprzedni run jeszcze leci) | Acceptable (idempotent semantics) | Bulk-delete na już-usuniętych ID → 4xx, swalliwane. |
| `cleanup now` while Beat run leci | Same — idempotent | OK. |
| Empty channel / nic do usunięcia | Pagination loop exits z `to_delete=[]` | `deleted=0`, `last_cleanup_at` updated (run zakończył się sukcesem). |
| Pinned message w >3d window | Filtered client-side (`m["pinned"]`) | Stays. |
| Threads w kanale | Discord channel-messages endpoint ich nie zwraca | Threads untouched. |
| Bot token missing | Istniejący guard w `_request` | Task fails fast wszystkim guildom, logs once. |

**Custom exception** `apps/deaths/services.py::CleanupError(Exception)` — sygnalizuje task loop'owi że per-guild operation failed.

---

## 7. Discord cog — slash commands

Rozszerzenie istniejącego `discord_bot/cogs/deaths.py::DeathsCog`. Subgrupa `cleanup` pod istniejącą `/deaths`.

```python
class DeathsCog(commands.Cog):
    deaths = discord.SlashCommandGroup("deaths", "Death monitor configuration")
    cleanup = deaths.create_subgroup("cleanup", "Death-channel auto-cleanup configuration")

    # ... istniejący /deaths threshold ...

    @cleanup.command(name="on", description="Enable 3-day cleanup (admin only)")
    async def cleanup_on(self, ctx): ...

    @cleanup.command(name="off", description="Disable cleanup (admin only)")
    async def cleanup_off(self, ctx): ...

    @cleanup.command(name="status", description="Show cleanup state")
    async def cleanup_status(self, ctx): ...

    @cleanup.command(name="now", description="Run cleanup immediately (admin only)")
    async def cleanup_now(self, ctx): ...
```

**Command contracts:**

| Command | Gate | Service call | Reply |
|---|---|---|---|
| `/deaths cleanup on` | server admin | `enable_cleanup_for_guild(guild_id)` | Public: "🧹 Cleanup enabled — messages older than 3 days will be removed every 3 days at 00:00 Europe/Warsaw." |
| `/deaths cleanup off` | server admin | `disable_cleanup_for_guild(guild_id)` | Public: "🧹 Cleanup disabled." |
| `/deaths cleanup status` | anyone (ephemeral) | `get_cleanup_status(guild_id)` | Ephemeral embed: enabled?, last_cleanup_at (relative: "2d 4h ago" / "never"), channel_id |
| `/deaths cleanup now` | server admin | `cleanup_death_channel(channel)` przez `sync_to_async`, defer + followup | Followup public: "🧹 Deleted N messages." / "❌ Cleanup failed: <error>" |

**`cleanup now` — synchronous, nie Celery.**
Rationale: immediate feedback to whole point of `now`. Per-channel cleanup ~<2s w typowym wypadku. Gdyby pojawiły się problemy timeout, można później przerzucić na Celery `.delay()` + `task.get(timeout=10)` lub follow-up polling. MVP: bezpośrednie wywołanie `sync_to_async(cleanup_death_channel)(channel)`.

**Pre-conditions per command** (wczesne returns z ephemeral error):
- `ctx.guild is None` → "❌ Use this in a server."
- `on/off/now`: not admin → "❌ Server admins only." (`ctx.author.guild_permissions.administrator`)
- `on/off/now/status`: brak `DiscordChannel` row → "❌ Run `/deaths threshold` first to register this channel."

Global `on_application_command_error` w `bot.py` (już istniejący) jest safety net dla unhandled exceptions.

---

## 8. `DiscordRESTClient` — nowe metody

Wszystkie używają istniejącego `_post` pattern (retry on 5xx/429, single retry, respect `Retry-After`). Trzeba rozszerzyć client o `_get` i `_delete` analogiczne do `_post`, albo wprowadzić generic `_request(method, url, body=None)`.

**Recommendation:** wprowadzić generic `_request` + zachować `_post` jako thin wrapper (backwards compat z istniejącymi callerami). Mniej duplikacji.

```python
def fetch_channel_messages(
    self,
    channel_id: int,
    before: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """GET /channels/{id}/messages?before=&limit=
    Returns parsed JSON list (empty list on failure)."""

def bulk_delete_messages(self, channel_id: int, message_ids: list[int]) -> bool:
    """POST /channels/{id}/messages/bulk-delete body={"messages": [str(id), ...]}
    Requires 2 ≤ N ≤ 100. Discord requires str IDs in body.
    Raises BulkDeleteAgeError on 400 z `code=50034` (message too old)."""

def delete_message(self, channel_id: int, message_id: int) -> bool:
    """DELETE /channels/{id}/messages/{mid}
    Single-message fallback (any age, slower)."""
```

**Custom exception** `apps/notifications/discord_client.py::BulkDeleteAgeError` — sygnał dla service layer że trzeba fallback.

---

## 9. Testing

**Unit (`tests/unit/`):**
- `test_discord_rest_client_cleanup.py` (new) — `respx`-mocked HTTP:
  - `fetch_channel_messages` happy path, 429-then-200, 5xx-then-fail, empty list on 4xx.
  - `bulk_delete_messages` happy path, 400-with-code-50034 → raises `BulkDeleteAgeError`, 403 → False.
  - `delete_message` happy path, 404 (already deleted) → True (idempotent semantics), 403 → False.
- `test_cleanup_service.py` (new):
  - Mocks `DiscordRESTClient`, asserts paginacja do empty batch.
  - Filtruje pinned messages.
  - Chunks >100 → multiple bulk-delete calls.
  - `N==1` chunk → fallback `delete_message`.
  - Empty channel → `deleted=0`, `last_cleanup_at` jeszcze updated.
  - REST error → raises `CleanupError`, `last_cleanup_at` NOT updated.
  - `BulkDeleteAgeError` → fallback per-message delete dla chunk'a.
- `test_snowflake_helper.py` (new) — round-trip `snowflake_for_datetime(dt)`:
  - Discord epoch (2015-01-01 00:00:00 UTC) → snowflake `0`.
  - Known datetime → known snowflake (fixture-based).
- `test_discord_bot_services_cleanup.py` (new) — `enable_cleanup_for_guild`, `disable_cleanup_for_guild`, `get_cleanup_status` happy + missing-row paths.

**Integration (`tests/integration/`):**
- `test_cleanup_task.py` (new) — Celery eager execution, real DB:
  - 3 `DiscordChannel` rows (2 enabled, 1 disabled). Mocked REST client.
  - Asserts: 2 guildów processed, totals dict, `last_cleanup_at` set on right rows.
  - One guild raises → continues, `fail_count=1`, others succeed.
- `test_periodic_task_seeded.py` (new) — assert migration created `PeriodicTask` z right crontab + timezone.

**Cog tests** (`tests/unit/test_deaths_cog.py`, extend):
- Per command: admin gate, DM context guard, missing `DiscordChannel` row → friendly error.
- `cleanup now` returns summary w followup.
- `status` renderuje "never" gdy `last_cleanup_at is None`.

**Out of scope dla testów:**
- Hit real Discord API (project rule §15.6).
- Verify Beat actually fires cron (third-party concern; testujemy że migration tworzy right row).

**Coverage target:** ≥70% per CI threshold, target ~85% dla nowego kodu.

---

## 10. Konfiguracja

Bez zmian w `.env`. `RETENTION_DAYS=3` jako module-level constant w `apps/deaths/services.py` (nie env var — feature MVP, hardcoded).

Beat schedule seedowany przez migrację (§3.2). Admin może go disable przez Django admin lub `PeriodicTask.objects.filter(name="deaths.cleanup_death_channels").update(enabled=False)` gdy potrzebny manual stop.

---

## 11. Otwarte kwestie (do decyzji w implementacji, nie blocker)

- **`DiscordRESTClient` generic `_request` vs separate `_post/_get/_delete`** — design recommenduje generic refactor. Jeśli refactor wychodzi za duży, można zostawić oddzielne metody (kosztem duplikacji retry/auth code).
- **`BulkDeleteAgeError` vs return value sentinel** — exception cleaner ale rozszerza public API. Alternatywa: `bulk_delete_messages` returns `Literal["ok", "age_error", "fail"]`. Implementator wybiera.
- **Status embed format** — `last_cleanup_at` jako "2d 4h ago" (humanize) vs "2026-05-29 14:00 Europe/Warsaw" (absolute). Implementator wybiera; preferowane humanize (mniej kognitywny overhead dla admina).

---

## 12. Migration & deployment notes

- **Order of operations** w deploy:
  1. Run `migrate` — adds `cleanup_enabled` + `last_cleanup_at` (default values, no backfill needed).
  2. Restart Celery Beat — pickup nowego `PeriodicTask`.
  3. Restart Discord bot — load nowych slash commands (sync to dev guild instant; global up to 1h).
- **Rollback:** disable `PeriodicTask` przez admin, drop `cleanup_enabled`/`last_cleanup_at` fields w follow-up migration. Bot pozostaje funkcjonalny (cleanup commands zwracają "Cleanup not configured" gracefully gdy fields removed → wymagałyby dedykowanego rollback PR-a).
- **First-run safety:** wszystkie istniejące rows mają `cleanup_enabled=False` → pierwszy fire'owy task będzie no-op. Admin musi explicit `/deaths cleanup on` żeby cokolwiek się usunęło.
