# M8 — Discord outbound notifications — Design spec

**Data:** 2026-05-15
**Status:** ACCEPTED (decyzje §3.1-3.5 zaakceptowane przez developera 2026-05-15 w sesji M8 brainstorm)
**Plan:** [`docs/superpowers/plans/2026-05-15-m8-implementation-plan.md`](../plans/2026-05-15-m8-implementation-plan.md) (ten sam PR)
**Milestone:** M8 — Discord outbound notifications

---

## §1 Cel + scope

M5 zaprojektował `BedmageNotificationHandler` Protocol z testowym `LoggingHandler` jako default — outbound bedmage alerts logowały do `apps.notifications` loggera, NIE wysyłały do Discord. M7 dorzucił bot (inbound slash commands) + `DiscordChannel` model z `channel_id` + `death_level_threshold` — outbound NIE wpięty. CLAUDE.md §5 spec'd `DeathEvent.announced_on_discord` field — NIE zaimplementowane.

M8 zamyka pętlę: bedmage alerty trafiają jako Discord DMs do user'a, death announcements trafiają jako embed messages w per-guild kanale ustawionym przez `/deaths threshold`. Discord REST API używany bezpośrednio z Celery worker'a (bot proces nadal tylko inbound; outbound NIE wymaga gateway connection).

### W zakresie M8:
- `apps/notifications/discord_client.py` z `DiscordRESTClient` (httpx, bot token, `send_dm` + `send_channel_message`).
- `DiscordDMHandler` impl `BedmageNotificationHandler` Protocol — zastępuje `LoggingHandler` jako default w `settings.BEDMAGE_NOTIFICATION_HANDLER`.
- NEW `DeathAnnouncementHandler` Protocol + `DiscordChannelHandler` impl + `LoggingHandler` test variant + `get_death_handler()` resolver — analogicznie do M5 wzorca.
- `DeathEvent.announced_on_discord` field + migracja.
- `announce_unannounced_deaths()` service w `apps/deaths/services.py` z multi-guild iteration.
- `scrape_deaths` Celery task wywołuje announce inline po subprocess parse (M5 pattern repeat).
- `httpx` dependency dorzucony do `pyproject.toml`.

### Poza zakresem M8 (do M-future):
- **Multi-guild M2M tracking** — aktualnie 1 dev guild, `announced_on_discord` boolean wystarczy. M-future konwersja na `DeathAnnouncement(death_event, discord_channel, sent_at, message_id)` z data migration backfill.
- **Embed batching** — Discord pozwala 10 embeds per message. YAGNI dla pojedynczych deaths.
- **Message delete/edit** — wymaga `message_id` storage. Bot mógłby usuwać/edytować ogłoszenia (character "returned from dead"). M-future.
- **Discord webhooks fallback** — backup transport gdy bot token revoked. M-future.
- **`/deaths channel` slash command** — dedicated death channel różny od miejsca `/deaths threshold` invocation. Aktualnie `ctx.channel_id` z M7 jako default. M-future.
- **Email/SMS handlers** — Protocol-based abstraction pozwala, ale brak use case dla M8.
- **Async/queued send** — sync httpx blocking ~50-200ms per call. Batch retry queue gdy ruch > 100 deaths/scrape. Niska priority.
- **Bedmage UX hint** — `/bedmage add` response mógłby wspomnieć "make sure DMs from server members are enabled". M-future cleanup PR (poza scope handlerów).
- **Per-user notification preferences** — niektórzy userzy mogą wolieć channel mention zamiast DM. M-future jeśli demand.
- **`DEATH_LEVEL_THRESHOLD` env var deprecation cleanup** — po M8 env nie używany dla outbound (per-guild threshold w DiscordChannel ma precedence). M-future cleanup.

---

## §2 Architektura

### High-level diagram

```
┌─────────────────────────────┐
│  Beat schedule (M3+M5+M4)   │
└─────────────┬───────────────┘
              │ fires
              ▼
   ┌─────────────────────────┐         ┌─────────────────────────┐
   │ scrape_watched_         │         │ scrape_deaths           │
   │   characters task (M5)  │         │   task (M4)             │
   └──────────┬──────────────┘         └──────────┬──────────────┘
              │ post-scrape inline                 │ post-scrape inline (NEW M8)
              ▼                                    ▼
   ┌─────────────────────────┐         ┌─────────────────────────┐
   │ check_bedmage_watches   │         │ announce_unannounced_   │
   │ _for_character() (M5)   │         │   deaths() (NEW M8)     │
   │ ↓                       │         │ ↓                       │
   │ get_bedmage_handler()   │         │ get_death_handler()     │
   │  → handler.notify(watch)│         │  → handler.announce(    │
   │                         │         │       death_event,      │
   │                         │         │       discord_channel)  │
   └──────────┬──────────────┘         └──────────┬──────────────┘
              │ M5 LoggingHandler                  │ NEW handler abstraction
              │   → REPLACED w M8                  │
              ▼                                    ▼
       ┌──────────────────────────────────────────────────┐
       │ apps/notifications/handlers.py                   │
       │ ┌────────────────────┐  ┌─────────────────────┐  │
       │ │ DiscordDMHandler   │  │ DiscordChannel-     │  │
       │ │ (BedmageHandler    │  │   Handler           │  │
       │ │   protocol)        │  │ (DeathAnnouncement- │  │
       │ │                    │  │   Handler protocol) │  │
       │ └─────────┬──────────┘  └──────────┬──────────┘  │
       │           │   uses                  │            │
       │           ▼                         ▼            │
       │  ┌──────────────────────────────────────────┐    │
       │  │ apps/notifications/discord_client.py     │    │
       │  │ DiscordRESTClient (httpx, bot token)     │    │
       │  │ - send_dm(user_discord_id, content)      │    │
       │  │ - send_channel_message(channel_id, ...)  │    │
       │  └─────────────────┬────────────────────────┘    │
       └────────────────────┼─────────────────────────────┘
                            │ HTTPS POST
                            ▼
                  discord.com/api/v10
```

### Struktura plików (3 NEW + 6 MODIFY)

| # | Plik | Status | Zawartość |
|---|---|---|---|
| 1 | `apps/notifications/discord_client.py` | NEW | `DiscordRESTClient` z `send_dm` + `send_channel_message`, 1-retry na 5xx/429 |
| 2 | `apps/notifications/handlers.py` | MODIFY | dorzucone `DiscordDMHandler` + `DeathAnnouncementHandler` Protocol + `DiscordChannelHandler` + `LoggingHandler` death variant + `get_death_handler` resolver |
| 3 | `apps/notifications/__init__.py` | MODIFY | export `get_death_handler` obok `get_bedmage_handler` |
| 4 | `apps/deaths/models.py` | MODIFY | `announced_on_discord = BooleanField(default=False, db_index=True)` |
| 5 | `apps/deaths/migrations/0003_add_announced_on_discord.py` | NEW | `AddField` migracja |
| 6 | `apps/deaths/services.py` | MODIFY | `announce_unannounced_deaths()` z multi-guild iteration |
| 7 | `apps/deaths/tasks.py` | MODIFY | `scrape_deaths` task wywołuje announce inline po subprocess parse |
| 8 | `config/settings/base.py` | MODIFY | `BEDMAGE_NOTIFICATION_HANDLER` default flip + NEW `DEATH_NOTIFICATION_HANDLER` env |
| 9 | `.env.example` | MODIFY | `DEATH_NOTIFICATION_HANDLER=...DiscordChannelHandler` |
| 10 | `pyproject.toml` | MODIFY | `httpx >= 0.27, < 1.0` w `[project.dependencies]` |
| 11 | `tests/unit/notifications/*` + `tests/unit/deaths/test_announce_*.py` + `tests/integration/test_m8_outbound_e2e.py` | NEW | ~20 testów total |

---

## §3 Decyzje designowe (zaakceptowane 2026-05-15)

### §3.1 Discord REST API direct z Celery worker (transport)
**Wybór:** Celery worker robi `httpx.post("https://discord.com/api/v10/...", headers={"Authorization": f"Bot {settings.DISCORD_BOT_TOKEN}"})`. Bot token reused z M7 (ten sam token, różny code path — gateway dla inbound, REST dla outbound).

**Justyfikacja:** Jednolity transport dla DMs (bedmage) i channel posts (deaths). Brak coordination z bot process'em. Discord REST API nie wymaga gateway connection — outbound działa nawet gdy bot offline (przydatne podczas restart bot'a). Bot token już w env (M7-D32), brak nowych secretów.

**Odrzucone alternatywy:**
- Webhook URLs per kanał — działa tylko dla kanałów, NIE DMs. Bedmage musiałby mieć osobną drogę = duplikat code path. Plus extra UX setup dla admina (Discord client → Channel Settings → Integrations → New Webhook).
- Redis queue + bot consumer — coupling dwóch procesów. Bot offline = queue rośnie + brak SLA. Async cog runtime mieszany z queue consumer = dodatkowa złożoność.

### §3.2 Bedmage DM only, silent fail przy 403
**Wybór:** `DiscordDMHandler` próbuje DM, przy 403 (user ma DMs zablokowane od server members) loguje WARNING i swallows. Service marks `last_notified_login` mimo failure → no retry storm.

**Justyfikacja:** Zgodne z CLAUDE.md §7 ("powiadomienie do `watch.user`"). Bedmage to user-private use case, nie public alert. 403 rate observable przez Mongo `app_logs` (M6 dispatcher) — admin może wykryć "60% userów ma DM blocked" trend. Marking `last_notified_login` przy 403 unika spam (alt: NIE markować → bot wali 1 wasted request per scrape forever per blocked user).

**Odrzucone:**
- Channel mention `@user` — głośno, spam w kanale, narusza CLAUDE.md §7 intent (user-private).
- DM z fallback na channel mention — dwa code paths, dodatkowy stan, complexity. M-future upgrade path zostaje otwarty (handler swap w `apps/notifications/handlers.py` — brak breaking change kontraktów).

### §3.3 Single boolean `announced_on_discord` + single-guild assumption
**Wybór:** `DeathEvent.announced_on_discord = models.BooleanField(default=False, db_index=True)` per CLAUDE.md §5 schema sketch. Algorytm: dla każdej unannounced event'a fetch wszystkie `DiscordChannel` gdzie `threshold ≤ level_at_death`, wyślij do każdej, marknij `announced_on_discord=True` gdy ALL succeed.

**Justyfikacja:** YAGNI — aktualnie 1 dev guild. CLAUDE.md §5 explicit ma `announced_on_discord: bool` — design intent ustalony. Upgrade ścieżka jasna: gdy real multi-guild deployment, M-future konwertuje boolean → M2M `DeathAnnouncement(death_event, discord_channel, sent_at, message_id)` z data migration (każdy `announced=True` row → 1 wiersz M2M dla istniejącego guild'a).

**Znana limitation:** gdy admin DODAJE nowy DiscordChannel z niższym threshold PO ogłoszeniu, historyczne śmierci `announced_on_discord=True` NIE są retroaktywnie wysłane do nowego guild'a. **Akceptowalne dla M8** — backfill out of scope. Documented w services.py docstring.

**"No applicable guilds" semantyka:** gdy DeathEvent ma level poniżej WSZYSTKICH guild thresholds → mark `announced_on_discord=True` mimo braku message'a. Powód: alt "stay False forever" spamuje query każdym scrape cycle. Marking = "evaluated and skipped".

**Odrzucone:**
- `DeathAnnouncement` M2M od początku — overengineering dla 1 guild. Jeden migration na boolean now, drugi migration na M2M plus data migration potem (gdy ewentualnie multi-guild). Złoty środek: incremental schema evolution.
- `JSONField announced_to_guilds: list[int]` — single-table multi-guild ale Postgres JSONField queries mniej eleganckie + JSONField w django-stubs nie jest strict-friendly. Niewspółmierne pomiędzy A i B.

### §3.4 Inline announce na końcu `scrape_deaths` Celery task
**Wybór:** `scrape_deaths` task po `subprocess.run(scrape_deaths)` + JSON parse wywołuje `announce_unannounced_deaths()` service w tym samym task body. Jedna Beat schedule entry (już istnieje z M4-D21).

**Justyfikacja:** Spójność z M5 bedmage pattern (scrape → notify inline). Natychmiastowy announce po nowych eventach, lepszy UX. Minimum mechaniki — jedna Beat entry, jeden task body. `announced_on_discord` flag i tak zapewnia idempotency przy crash/retry — nawet gdy announce failuje w środku batch'a, retry next cycle nie duplikuje.

**Odrzucone:**
- Celery chain `scrape_deaths → announce_unannounced_deaths.apply_async(...)` — więcej Celery machinery dla małego zysku decoupling'u.
- Osobny Beat schedule `announce_deaths` co 5 min — delay między scrape a announce, dodatkowa Beat config. Resilient ale niepotrzebny przy stable scrape flow.

### §3.5 Mirror M5 Protocol pattern dla deaths (`DeathAnnouncementHandler`)
**Wybór:** NEW Protocol `DeathAnnouncementHandler` z metodą `announce(death_event, discord_channel)` w `apps/notifications/handlers.py`. Default impl: `DiscordChannelHandler` (httpx via `DiscordRESTClient`). Test impl: `DeathLoggingHandler` (analogiczny do M5 bedmage `LoggingHandler` ale dla death announcement contract — osobna klasa żeby nie konflikt nazw z istniejącym `LoggingHandler`). `settings.DEATH_NOTIFICATION_HANDLER` env var pozwala swap (`@override_settings` w testach unit).

**Justyfikacja:** Symetria z M5 bedmage Protocol — utrzymuje mental model: każdy notification type ma `Protocol + Handler + settings switch`. M5 retro lekcja: handler abstraction już ratował testy. Boilerplate w M8 to ~10 linii, nie justifies asymmetry.

**Wspólny dla obu Protocol-ów:** low-level `DiscordRESTClient` w `apps/notifications/discord_client.py` z metodami `send_dm` + `send_channel_message`. Handlery używają tego klienta jako dependency injected przez import.

**Odrzucone:**
- Service function używa `DiscordRESTClient` bezpośrednio bez Protocol layer — niesymetryczne z bedmage, settings nie pozwala swap'ować na `LoggingHandler` dla testów (musimy mockować lower level).

---

## §4 Model + service signatures

### §4.1 `apps/deaths/models.py` (modify)

```python
class DeathEvent(models.Model):
    # ... existing fields ...
    announced_on_discord = models.BooleanField(default=False, db_index=True)

    # __str__ i Meta bez zmian
```

### §4.2 `apps/notifications/discord_client.py` (new)

```python
class DiscordRESTClient:
    """Sync httpx client dla Discord REST API.

    Singleton-friendly (każda metoda otwiera/zamyka httpx.Client przez context
    manager — connection pooling lokalne dla jednego callu). Bot token z
    settings.DISCORD_BOT_TOKEN. Brak gateway connection — outbound działa
    nawet gdy bot proces offline.
    """

    BASE_URL = "https://discord.com/api/v10"
    DEFAULT_TIMEOUT = 5.0

    def __init__(self, bot_token: str | None = None) -> None:
        self.bot_token = bot_token or settings.DISCORD_BOT_TOKEN

    def send_dm(self, user_discord_id: int, content: str) -> bool:
        """Wyślij DM do user'a po Discord snowflake.

        Returns True przy 2xx, False przy 4xx/5xx (po retry). Wymaga 2 calls:
        POST /users/@me/channels (create DM channel) → POST /channels/X/messages.
        """

    def send_channel_message(
        self, channel_id: int, content: str | None = None, embed: dict | None = None
    ) -> bool:
        """Wyślij wiadomość do kanału przez channel_id (BigInt snowflake).

        Returns True przy 2xx, False przy 4xx/5xx. Content LUB embed (oba dozwolone).
        1-retry na 5xx/429 (Retry-After header respect). Brak retry na 4xx
        (permanent — wrong channel_id, wrong perms).
        """
```

### §4.3 `apps/notifications/handlers.py` (modify)

```python
# Existing M5:
class BedmageNotificationHandler(Protocol):
    def notify(self, watch: BedmageWatch) -> None: ...

class LoggingHandler:  # bedmage variant
    def notify(self, watch: BedmageWatch) -> None: ...

# NEW M8:
class DiscordDMHandler:
    """Implements BedmageNotificationHandler. Wysyła DM przez DiscordRESTClient."""

    def notify(self, watch: BedmageWatch) -> None:
        client = DiscordRESTClient()
        content = self._render(watch)
        try:
            user_discord_id = int(watch.user.discord_id)
        except (TypeError, ValueError):
            logger.error("Invalid discord_id for user %s", watch.user.pk)
            return
        ok = client.send_dm(user_discord_id, content)
        if not ok:
            logger.warning(
                "Bedmage DM failed for user=%s character=%s — service still marks last_notified_login",
                watch.user.username, watch.character.name,
            )

    def _render(self, watch: BedmageWatch) -> str:
        return (
            f"🛏️ Your bedmage **{watch.character.name}** has been logged out for "
            f"{settings.BEDMAGE_REGEN_MINUTES} minutes — mana fully regenerated.\n"
            f"Last login: {watch.character.last_login:%Y-%m-%d %H:%M UTC}"
        )


# NEW Protocol for deaths:
class DeathAnnouncementHandler(Protocol):
    def announce(self, death_event: DeathEvent, discord_channel: DiscordChannel) -> bool: ...


class DiscordChannelHandler:
    """Implements DeathAnnouncementHandler. Posts embed do per-guild kanału."""

    def announce(self, death_event: DeathEvent, discord_channel: DiscordChannel) -> bool:
        client = DiscordRESTClient()
        embed = self._render_embed(death_event)
        return client.send_channel_message(
            channel_id=discord_channel.channel_id, embed=embed,
        )

    def _render_embed(self, death_event: DeathEvent) -> dict:
        return {
            "title": f"💀 {death_event.character_name} (level {death_event.level_at_death})",
            "description": death_event.killed_by or "Cause unknown",
            "timestamp": death_event.died_at.isoformat(),
            "color": 0xDC143C,  # crimson
        }


class DeathLoggingHandler:
    """Test/dev variant — logs only, no Discord call."""

    def announce(self, death_event: DeathEvent, discord_channel: DiscordChannel) -> bool:
        logger.info(
            "DEATH ANNOUNCE: %s (lvl %s) → guild=%s channel=%s",
            death_event.character_name, death_event.level_at_death,
            discord_channel.guild_id, discord_channel.channel_id,
        )
        return True
```

### §4.4 `apps/notifications/__init__.py` (modify)

```python
def get_bedmage_handler() -> BedmageNotificationHandler:  # M5 existing
    ...

def get_death_handler() -> DeathAnnouncementHandler:  # NEW M8
    handler_class = import_string(settings.DEATH_NOTIFICATION_HANDLER)
    return cast(DeathAnnouncementHandler, handler_class())
```

### §4.5 `apps/deaths/services.py` (modify)

```python
def announce_unannounced_deaths() -> dict[str, int]:
    """Iterate unannounced DeathEvents, fan-out do applicable guildów, mark announced.

    Multi-guild fan-out: dla każdej unannounced event'a fetch wszystkie
    DiscordChannel gdzie threshold <= level_at_death. Wyślij do każdej guild
    (rate-limited 200ms sleep). Mark announced_on_discord=True gdy ALL succeed.
    Failed event stays False — retry next scrape cycle.

    "No applicable guilds" semantyka: gdy 0 guildów ma threshold <= level,
    mark announced=True mimo braku message'a (semantyka "evaluated + skipped").
    Unikamy retry storm w queryach każdego scrape cycle.

    Returns: {"events_announced": N, "events_skipped": M, "fail_count": K}
    """
```

### §4.6 `apps/deaths/tasks.py scrape_deaths` (modify)

```python
@shared_task(bind=True, max_retries=2)
def scrape_deaths(self: Task) -> dict[str, int]:
    # ... existing subprocess + JSON parse ...

    summary["returncode"] = result.returncode
    logger.info("scrape_deaths: %s", summary)

    # NEW M8: announce inline po scrape
    try:
        announce_summary = announce_unannounced_deaths()
        summary.update(announce_summary)
    except Exception:
        logger.exception("announce_unannounced_deaths raised — events stay unannounced for next cycle")

    return summary
```

### §4.7 `config/settings/base.py` (modify)

```python
# Existing M5 (default flip):
BEDMAGE_NOTIFICATION_HANDLER = env(
    "BEDMAGE_NOTIFICATION_HANDLER",
    default="apps.notifications.handlers.DiscordDMHandler",  # M5 default LoggingHandler → M8 DiscordDMHandler
)

# NEW M8:
DEATH_NOTIFICATION_HANDLER = env(
    "DEATH_NOTIFICATION_HANDLER",
    default="apps.notifications.handlers.DiscordChannelHandler",
)
```

---

## §5 D-task split (preview — szczegóły w implementation plan)

| # | ID | Tytuł | Czas | Zależy od |
|---|---|---|---|---|
| 1 | M8-D36 | `apps/notifications/discord_client.py` — `DiscordRESTClient` + httpx dep + 6 testów | 2-3h | M7 closed |
| 2 | M8-D37 | `DiscordDMHandler` + bedmage notification message format + 3 testy + `BEDMAGE_NOTIFICATION_HANDLER` default flip | 1-2h | D36 |
| 3 | M8-D38 | `DeathEvent.announced_on_discord` migracja + `DeathAnnouncementHandler` Protocol + `DiscordChannelHandler` + 3 testy | 2h | D37 |
| 4 | M8-D39 | `announce_unannounced_deaths` service + `scrape_deaths` integration + 7 testów | 2-3h | D38 |
| 5 | M8-D40 | M8 e2e + closure (PROGRESS.md retro + milestone close + manual smoke 4 punkty) | 2h | D39 |

**Total:** ~9-12h, ~2 dni roboczych (porównywalne z M7).

---

## §6 Error handling

### §6.1 `DiscordRESTClient` failure modes

| Failure | Handling |
|---|---|
| 5xx server error | 1 retry, jeśli wciąż 5xx → return False, log WARNING |
| 429 Rate Limited | sleep `Retry-After` header value (clamp do 5s), 1 retry → if wciąż 429, return False |
| 403 Forbidden | return False, log ERROR (channel: "bot lost perms"; DM: "user DMs disabled") |
| 404 Not Found | return False, log ERROR ("channel_id X / user_id X invalid — admin needs to re-run /deaths threshold") |
| 400 Bad Request | return False, log ERROR z response body (debug payload format) |
| `httpx.TimeoutException` | return False, log WARNING (likely network, transient) |
| `httpx.ConnectError` | return False, log WARNING (Discord down or DNS issue) |

### §6.2 `DiscordDMHandler` failure modes

| Failure | Service-level handling |
|---|---|
| `client.send_dm` returns False | log WARNING ("bedmage DM failed for user=X char=Y"), service marks `last_notified_login` mimo to (no retry storm) |
| `int(discord_id)` raises | log ERROR "Invalid discord_id format for user X", return early, service marks `last_notified_login` (permanent invalid) |
| `client` raises (unexpected) | M5 service `check_bedmage_watches_for_character` ma już `except Exception: logger.exception; continue` — handler błąd nie zatrzymuje batch'a |

### §6.3 `DiscordChannelHandler` + `announce_unannounced_deaths` failure modes

| Failure | Handling |
|---|---|
| `client.send_channel_message` returns False dla 1 guild | event stays `announced_on_discord=False` → retry next scrape cycle (cały batch dla event'a leci od nowa) |
| `client` returns False dla wszystkich guildów | event stays False, log per-guild WARNING |
| Handler raises (unexpected) | service `announce_unannounced_deaths` wrapped w `try/except: logger.exception; continue` — pojedynczy event nie zatrzymuje batch'a |
| `scrape_deaths` task announce phase raises | task summary jest still returned (subprocess part success), `logger.exception("announce_unannounced_deaths raised")` |

### §6.4 Idempotency guarantees

- **Bedmage:** `last_notified_login` per-watch per-login-session. Re-scrape gdy character się nie relogował → noop. Re-login → new cycle.
- **Death:** `announced_on_discord` per-event boolean. Re-scrape after partial failure → unannounced events retried, announced skipped.
- **Crash mid-send:** Celery task crash → `event.save(update_fields=["announced_on_discord"])` jest atomic single-row update, NIE w explicit transaction. Jeśli announce'owaliśmy do guild A successfully ale crash przed save → next cycle wyśle ponownie do guild A (duplicate). Trade-off accepted — Celery worker crash mid-task rare, duplicate alert lepszy niż lost alert.

### §6.5 Rate limiting strategy

- **Bedmage:** ~10-50 watches per scrape cycle, 1 DM per watch → max 50 DMs/hour. Discord global rate limit 50 req/s — well below. Sleep 200ms between bedmage DMs jako defensive.
- **Deaths:** ~10-100 new events per scrape, × 1 guild (M8 assumption) = max ~100 channel posts/hour. Per-channel rate limit 5 msg/5s → należy przestrzegać. Sleep 200ms between sends.
- Sleep implementation: plain `time.sleep(0.2)` w sync Celery worker. Async/batch optimization odroczone do M-future.

---

## §7 Testing strategy

### §7.1 Stack
- `pytest-django` + `@pytest.mark.django_db` dla DB-touching tests
- `monkeypatch.setattr` dla `DiscordRESTClient` mocking w handler tests (consistent z M5 `_get_bedmage_handler` mocking pattern)
- `httpx.MockTransport` dla `DiscordRESTClient` własnych testów — symuluje response bez real HTTP

### §7.2 Test files (~20 testów total)

**`tests/unit/notifications/test_discord_client.py` (~6 testów):**
- `test_send_dm_creates_channel_then_posts_message` — `MockTransport` symuluje 2-step flow (POST `/users/@me/channels` → channel_id → POST `/channels/X/messages`), assert 2 requests + final 200
- `test_send_dm_returns_false_on_403_user_dms_disabled` — MockTransport zwraca 403, assert returns False, log WARNING captured
- `test_send_channel_message_posts_and_returns_true_on_success`
- `test_send_channel_message_returns_false_on_404_channel_not_found`
- `test_client_retries_once_on_5xx` — first response 503, second 200, assert 2 requests + final success
- `test_client_respects_retry_after_on_429` — 429 z `Retry-After: 1` header, mock `time.sleep`, assert sleep called z 1s

**`tests/unit/notifications/test_discord_dm_handler.py` (~3 testy):**
- `test_handler_notify_calls_client_send_dm_with_user_discord_id`
- `test_handler_notify_renders_message_with_character_name_and_last_login`
- `test_handler_notify_swallows_send_failure_silently`

**`tests/unit/notifications/test_discord_channel_handler.py` (~3 testy):**
- `test_handler_announce_calls_client_send_channel_message_with_embed`
- `test_handler_announce_renders_embed_with_character_level_killed_by`
- `test_handler_announce_returns_false_on_send_failure`

**`tests/unit/deaths/test_announce_unannounced_deaths.py` (~6 testów):**
- `test_announce_processes_only_unannounced_events`
- `test_announce_marks_event_as_announced_on_success`
- `test_announce_keeps_unannounced_on_handler_failure`
- `test_announce_iterates_all_applicable_guilds_per_event`
- `test_announce_marks_event_announced_when_no_applicable_guilds` (semantyka "evaluated + skipped")
- `test_announce_stays_unannounced_when_any_guild_fails`

**`tests/unit/deaths/test_scrape_deaths_task.py` (modify existing ~1 test):**
- `test_scrape_deaths_calls_announce_after_subprocess` — monkeypatch announce service, assert called once po subprocess parse

**`tests/integration/test_m8_outbound_e2e.py` (~1 test):**
- `test_bedmage_alert_calls_discord_client_via_handler_chain` — full chain: User+BedmageWatch+Character → `check_bedmage_watches_for_character` → handler resolved via setting → DiscordRESTClient (mocked) → assert `send_dm` called z expected args

### §7.3 Coverage cel
- `apps/notifications/discord_client.py`: 100%
- `apps/notifications/handlers.py`: 100%
- `apps/deaths/services.py` (M8 parts): 100%
- Cumulative M8 ≥ 95%

### §7.4 NIE testujemy real Discord API
Per CLAUDE.md §11: "Testy nie mogą hitować żywych stron Tibiantis ani żywego Discorda". Wszystkie testy mockują na `DiscordRESTClient` level (granica testowania); kod klienta testujemy osobno z `httpx.MockTransport`. Manual smoke w dev guildzie pokrywa real-API path.

---

## §8 Definition of Done M8

- [ ] **5 D-tasków zamkniętych** (#D36-#D40) + closure PR
- [ ] **`apps/notifications/discord_client.py`** z `DiscordRESTClient` (httpx, bot token z settings, send_dm + send_channel_message, 1-retry na 5xx/429)
- [ ] **`apps/notifications/handlers.py`** rozszerzony o `DiscordDMHandler` + `DeathAnnouncementHandler` Protocol + `DiscordChannelHandler` + `DeathLoggingHandler` test variant
- [ ] **`apps/notifications/__init__.py`** export `get_death_handler()` resolver
- [ ] **`apps/deaths/models.py`** z `announced_on_discord = BooleanField(default=False, db_index=True)` + migracja `0003_add_announced_on_discord.py`
- [ ] **`apps/deaths/services.py`** rozszerzony o `announce_unannounced_deaths()` z multi-guild iteration
- [ ] **`apps/deaths/tasks.py scrape_deaths`** wywołuje announce inline po subprocess parse
- [ ] **`config/settings/base.py`**:
  - `BEDMAGE_NOTIFICATION_HANDLER` default zmienia się z `LoggingHandler` na `DiscordDMHandler`
  - NEW `DEATH_NOTIFICATION_HANDLER = env(..., default="apps.notifications.handlers.DiscordChannelHandler")`
- [ ] **`pyproject.toml`** dorzucone `httpx >= 0.27, < 1.0`
- [ ] **`.env.example`** rozszerzone o `DEATH_NOTIFICATION_HANDLER=apps.notifications.handlers.DiscordChannelHandler`
- [ ] **Pre-commit + CI zielone** dla wszystkich PR-ów
- [ ] **Coverage cumulative `apps/notifications/*` + `apps/deaths/services.py` parts ≥ 95%**
- [ ] **PROGRESS.md** rozszerzony o sekcję M8 z retro per Issue
- [ ] **Manual smoke** udokumentowany w closure PR (4 punkty z §9 poniżej)
- [ ] **Milestone M8 zamknięty** na GitHub via `gh api -X PATCH .../milestones/8 -f state=closed`

---

## §9 Manual smoke checklist (dev guild)

W closure PR body (D40):

1. Add bedmage watch dla character z `last_login > 100min` ago (manual DB row lub `/bedmage add` z post-hoc DB tweak) → po następnym scrape cycle (manual trigger via `manage.py shell`) → bot DM-uje cię z "🛏️ Your bedmage..."
2. Block DMs od bota w Discord, repeat → log w `app_logs` Mongo z WARNING, `last_notified_login` mimo to zaktualizowane (no retry storm — sanity przez ponowne wywołanie `check_bedmage_watches_for_character` w shell)
3. Insert manual DeathEvent z level=60 do bazy → run `scrape_deaths` task (Celery shell call) → bot post embed `💀 Yhral (level 60)` w kanale dev guild ustawionym przez `/deaths threshold`
4. Insert DeathEvent z level=20 (poniżej guild threshold 30) → po scrape → event `announced_on_discord=True` ale 0 wiadomości w Discord (semantyka "evaluated + skipped")

---

## §10 References / precedensy

- **CLAUDE.md §5** — `DeathEvent.announced_on_discord` field spec'd ale nie zaimplementowane (M8 wreszcie dorzuca)
- **CLAUDE.md §7** — "wyślij powiadomienie Discord do `watch.user`" (bedmage DM design) + "zbiorczą wiadomość na skonfigurowany kanał Discord" (death channel design)
- **CLAUDE.md §8** — "bot nie wysyła powiadomień sam z siebie — robi to Celery task" (rozstrzyga: outbound przez Celery, NIE przez bot process)
- **M5-D25** — Protocol-based handler abstraction (M5 ustanowił wzorzec, M8 dorzuca DeathAnnouncementHandler równolegle)
- **M5-D26** — inline notification w scrape task (M5 wzorzec scrape → notify, M8 powtarza dla deaths)
- **M6-D28** — graceful disable handlers przy braku resource (np. empty `MONGO_URL` → `NullHandler`). M8 analogicznie: empty `DISCORD_BOT_TOKEN` → handler robi log WARNING zamiast crash
- **M7-D31** — `DiscordChannel` model już zaprojektowany per-guild z `channel_id` + `death_level_threshold`. M8 finally używa tych pól dla outbound
- **M7 retro lekcja: manual smoke jako jedyna sieć dla py-cord integration** — M8 outbound przez REST API jest **easier do testowania** (mock httpx) niż py-cord intercept. Coverage gap z M7 nie wraca w M8.
