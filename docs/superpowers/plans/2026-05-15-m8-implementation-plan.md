# M8 — Discord outbound notifications — Implementation plan

**Data:** 2026-05-15
**Spec:** [`docs/superpowers/specs/2026-05-15-m8-outbound-notifications-design.md`](../specs/2026-05-15-m8-outbound-notifications-design.md)
**Status:** READY (spec accepted, decyzje §3.1-3.5 zaakceptowane przez developera 2026-05-15).

---

## Źródła

- **CLAUDE.md** §5 (`DeathEvent.announced_on_discord` schema sketch wreszcie domknięte), §7 (bedmage DM intent + death channel announcement), §8 (bot tylko inbound, outbound przez Celery task — design decision lock'd).
- **Design spec M8** — kluczowy dokument referencyjny. Każdy issue body linkuje do spec'a §X.
- **Precedensy z M0-M7:**
  - M5-D25 — Protocol-based handler abstraction (`BedmageNotificationHandler` + `LoggingHandler` default + `get_bedmage_handler()` resolver via `settings.BEDMAGE_NOTIFICATION_HANDLER` import_string). M8 dorzuca `DeathAnnouncementHandler` Protocol równolegle + `DiscordChannelHandler` impl.
  - M5-D26 — inline notification w scrape task (`check_bedmage_watches_for_character` invoked from `scrape_watched_characters`). M8 powtarza pattern dla deaths (`announce_unannounced_deaths` invoked from `scrape_deaths`).
  - M5-D24 — services type-hint convention: direct `from apps.accounts.models import User` (memory `feedback_services_user_type_hint.md`). Dotyczy `DiscordDMHandler.notify` accessing `watch.user.discord_id`.
  - M6-D28 — graceful disable handlers przy braku resource (empty `MONGO_URL` → `NullHandler`). M8 wzorzec: empty `DISCORD_BOT_TOKEN` → handler robi log WARNING zamiast crash. Lazy `DiscordRESTClient.__init__` NIE waliduje token'a (M6 retro: eager resource lookup w `__init__` to recurring pułapka — dwukrotnie złapana w D28+D29).
  - M6 retro lekcja #2 — `propagate: True` na named logger keeps pytest caplog working. `apps.notifications` logger już istnieje, M8 nie dodaje nowych named loggerów (Mongo dispatch pokrywa).
  - M7-D31 — `User.discord_id` to `CharField(max_length=32)` (M2 design choice). M8 service `DiscordDMHandler.notify` musi `int(watch.user.discord_id)` z try/except dla edge case None/invalid format.
  - M7-D33 — cog test pattern via `.callback` bypass omija py-cord registration path (manual smoke gap). M8 NIE używa cogów dla outbound — Celery worker bezpośrednio robi HTTP. **Easier do testowania** niż py-cord intercept (mock httpx via `httpx.MockTransport`).
  - M7 hotfix #124 — `from __future__ import annotations` w py-cord cogach crashuje runtime. M8 outbound code (`apps/notifications/`, `apps/deaths/`) NIE jest py-cord-dependent — `from __future__ import annotations` BEZPIECZNE i zalecane (jak w innych `apps/*`).

---

## Pre-flight checklist (przed startem D36)

- [ ] **`apps/notifications/` istnieje** — sprawdzone 2026-05-15 (z M5), zawiera `__init__.py` + `handlers.py` + `apps.py`.
- [ ] **`apps/deaths/models.py` DeathEvent** — sprawdzone 2026-05-15, **BRAK** field'a `announced_on_discord` (CLAUDE.md §5 spec'd ale nie zmigrowane). M8-D38 dorzuca.
- [ ] **`DISCORD_BOT_TOKEN` w env** — wymagane od M7-D32. M8 reuse tego samego token'a dla REST API outbound (zamiast inbound gateway).
- [ ] **`pyproject.toml` — `httpx` nie jest jeszcze dependencją** — sprawdzone 2026-05-15 (po `grep httpx pyproject.toml` empty). M8-D36 dorzuca jako `httpx (>=0.27,<1.0)`.
- [ ] **`DiscordChannel` model** — z M7-D31, ma `guild_id` + `channel_id` + `death_level_threshold`. M8 finally używa tych pól dla outbound.
- [ ] **`BedmageWatch.last_notified_login`** — z M5-D23, używane jako per-login-session idempotency dla bedmage. M8 zachowuje semantykę (marks even przy 403, no retry storm).
- [ ] **PROCESS: pre-commit `no-commit-to-branch` hook** (PR #105, merged M5) — blokuje commits na master. **Każdy D-task wymaga `git checkout -b feat/<#>-...` PRZED kodowaniem** (CLAUDE.md §12).
- [ ] **PROCESS: `pre-commit clean` przed `# type: ignore` na nowych mypy errors** (M7 retro lekcja #3) — stale cache po fresh `httpx` install może false-positive'ować. `poetry run pre-commit clean` przed flagowaniem nowych errors jako blocker.

---

## Otwarte pytania (rozstrzygnięte 2026-05-15, spec §3)

Wszystkie 5 decyzji designowych ze spec'a §3 zaakceptowane bez modyfikacji:

1. ✅ **§3.1** Discord REST API direct z Celery worker (bot token reused, brak coordination z bot process'em).
2. ✅ **§3.2** Bedmage DM only z silent fail przy 403, mark `last_notified_login` mimo failure (no retry storm).
3. ✅ **§3.3** Single boolean `DeathEvent.announced_on_discord` + single-guild assumption. M-future upgrade do M2M `DeathAnnouncement`.
4. ✅ **§3.4** Inline announce na końcu `scrape_deaths` Celery task (spójność z M5 bedmage pattern).
5. ✅ **§3.5** Mirror M5 Protocol pattern dla deaths (`DeathAnnouncementHandler` + `DiscordChannelHandler` + `DeathLoggingHandler` test variant + `get_death_handler()` resolver).

**Open questions z §1** (do M-future, NIE w M8 scope) wymienione w spec'u — multi-guild M2M, embed batching, message delete/edit, webhooks fallback, `/deaths channel`, email/SMS handlers, async/queued send, bedmage UX hint, per-user prefs, `DEATH_LEVEL_THRESHOLD` deprecation cleanup.

---

## Risk + mitigation

| Ryzyko | Prawdopodobieństwo | Impact | Mitigation |
|---|---|---|---|
| **`httpx` resolver pulls niezgodne `httpcore`** (similar do M7 py-cord Python version conflict) | Średnie (httpx ma stable Python support) | `poetry add` fails, blokuje D36 start | Spec specifies `httpx (>=0.27,<1.0)` jako stable range (0.27 z 2024-06, 1.0 jeszcze nie wydany). Verify: `poetry add httpx; poetry show httpx` — sanity check no transitive conflict z django-stubs/strawberry stubs. |
| **Mypy strict + httpx union types** (po analogii D34 `union-attr`) | Średnie | CI mypy red dla `Response` attribute access | httpx ma first-class type stubs od 0.18+. `response.status_code: int`, `response.headers: Headers`, `response.json(): Any`. Mypy strict powinno przejść bez ignore'ów. Jeśli pojawi się `valid-type` na httpx annotations — `pre-commit clean` przed flagowaniem (M7 retro). |
| **Discord REST 401 Unauthorized** przy testowym/wrong tokenie | Niskie (M7-D32 manual smoke confirmed token valid) | Wszystkie outbound failą, log spam | `DiscordRESTClient` returns False, logs ERROR z status_code + response body. Service swallows (bedmage marks anyway, death stays unannounced). Admin sees Mongo `app_logs` ERROR rate → debug. |
| **Mid-batch crash duplikuje announce** | Niskie (Celery rzadko crashuje mid-task) | Discord duplicate alerts | Trade-off accepted w spec §6.4. `event.save(update_fields=...)` atomic single-row update. Duplikaty preferred nad lost events. Documented w services.py docstring. |
| **`int(watch.user.discord_id)` raises** dla User stworzonego via Django admin (manual, bez discord_id) | Niskie (auto-create w M7-D31 zawsze ustawia) | `DiscordDMHandler.notify` crash → unhandled exception w handler chain | `try: int(...) except (TypeError, ValueError): logger.error + return`. Watch dla user'a bez discord_id po prostu nie dostanie DM, ale service marks last_notified_login (permanent invalid, no retry). Edge case rare. |
| **Rate limit 429 burst** przy nagłym napływie deaths (np. server-wide PK event) | Średnie przy ruchu, niskie przy obecnym wolumenie | Część announces failuje | Spec §6.5: `time.sleep(0.2)` defensive between sends + 1 retry na 429 z `Retry-After` header respect. Při burst > 10 events w jednej Celery task, 200ms × 10 = 2s sleep total. Akceptowalne. M-future jeśli ruch znacząco wzrośnie. |
| **`announce_unannounced_deaths` brak DiscordChannel rows (brak guildów skonfigurowanych)** | Wysokie przed pierwszym `/deaths threshold` invocation | Service działa ale 0 sendów per event | Iteracja po events: `applicable_guilds.count() == 0` → mark event `announced_on_discord=True` (semantyka "evaluated + skipped"). Loguje INFO ze stats. Brak crash. |
| **Test mocking `httpx.Client` w setup-level** | Średnie (M4-D22 test mocking complexity) | Test failures, false-positive coverage | `httpx.MockTransport` API jest documented, działa per-call (no global monkey-patch). Pattern: `transport = MockTransport(handler); client = httpx.Client(transport=transport)`. Granularne. Plus dla handler tests — `monkeypatch.setattr("apps.notifications.handlers.DiscordRESTClient", MockClass)`. |
| **`scrape_deaths` task announce phase raises uncaught** | Niskie (services wrappers w try/except) | Cały Celery task fails, max_retries=2 wykorzystany | Spec §6.3: announce phase wrapped w `try/except: logger.exception` w task body. Subprocess summary still returned. Task NIE retry'uje na announce failure. |
| **Test `apps.notifications.handlers.DiscordRESTClient` module-level import** powoduje że monkeypatch na string path nie działa | Średnie | Test mock'i nie propagują się | Standard Python: monkeypatch.setattr na "module.attribute" string rebinduje atrybut w module __dict__. Function-level resolve via `import_string(settings.X)` w `get_*_handler` zapewnia że Class jest pobierana fresh per call (no cache). M5-D25 pattern reused. |

---

## Task overview

| # | ID | Tytuł | Czas | Zależy od | Branch |
|---|---|---|---|---|---|
| 1 | M8-D36 | `apps/notifications/discord_client.py` — `DiscordRESTClient` + httpx dep + 6 testów | 2-3h | M7 closed | `feat/<#>-discord-rest-client` |
| 2 | M8-D37 | `DiscordDMHandler` + bedmage message format + 3 testy + `BEDMAGE_NOTIFICATION_HANDLER` default flip | 1-2h | D36 merged | `feat/<#>-discord-dm-handler` |
| 3 | M8-D38 | `DeathEvent.announced_on_discord` migracja + `DeathAnnouncementHandler` Protocol + `DiscordChannelHandler` + 3 testy | 2h | D37 merged | `feat/<#>-death-announcement-handler` |
| 4 | M8-D39 | `announce_unannounced_deaths` service + `scrape_deaths` integration + 7 testów | 2-3h | D38 merged | `feat/<#>-announce-deaths-service` |
| 5 | M8-D40 | M8 e2e + closure (PROGRESS.md retro + milestone close + manual smoke 4 punkty) | 2h | D39 merged | `feat/<#>-m8-e2e` + `docs/close-m8-outbound-notifications` |

**Total:** ~9-12h, ~2 dni roboczych. Porównywalne z M7 (~10-13h, 5 D-tasków + 1 hotfix).

---

## Task #1 — [M8-D36] `apps/notifications/discord_client.py` — `DiscordRESTClient` + httpx dep + 6 testów

### 🎯 Cel

Dorzucić `httpx` jako dependency (osobny `build(deps)` commit), utworzyć `apps/notifications/discord_client.py` z klasą `DiscordRESTClient` (sync httpx, bot token z `settings.DISCORD_BOT_TOKEN`, dwie metody: `send_dm(user_discord_id, content)` z 2-step flow utworzenia DM channel'a + `send_channel_message(channel_id, content?, embed?)`). Implementacja 1-retry na 5xx/429 (z `Retry-After` header respect). Pełne unit testy via `httpx.MockTransport` (NIE real HTTP). Po D36: klient gotowy do reuse'u w D37 i D38 handlerach.

### 🧠 Czego się nauczysz

- **`httpx.MockTransport` dla test'owania HTTP clients** — first-class testing primitive w httpx, brak konieczności `responses` / `respx` external lib. Pattern: `transport = MockTransport(handler_fn); client = httpx.Client(transport=transport)`. Handler dostaje `httpx.Request`, zwraca `httpx.Response`.
- **Discord REST API quirks** — bot token w header `Authorization: Bot {token}` (literal "Bot " prefix), versioned URL `https://discord.com/api/v10/...`, content type JSON, rate limit headers (`X-RateLimit-Remaining`, `Retry-After` on 429).
- **DM 2-step flow** — `POST /users/@me/channels {"recipient_id": int}` zwraca `{"id": channel_id}`, potem `POST /channels/{channel_id}/messages {"content": "..."}` faktycznie wysyła. Channel jest persistent (subsequent DMs reuse'ują), ale defensywnie tworzymy każdorazowo (Discord API tolerates).
- **Sync httpx vs requests** — `httpx.Client` API parallel do `requests` ale typed first-class (mypy strict-friendly bez external stubs). `httpx.post(url, json={...}, headers={...}, timeout=5.0)`. `response.status_code: int`, `response.json(): Any`.

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m8-d36.md`.)

**Kluczowe punkty:**

- **`pyproject.toml` osobny `build(deps)` commit** dodający `httpx (>=0.27,<1.0)` do `[project.dependencies]`. `poetry add httpx`. Sanity: `poetry show httpx` — verify `httpcore`, `anyio`, `h11`/`h2` jako transitive deps, brak konfliktu z django-stubs/strawberry.
- **`apps/notifications/discord_client.py`** z klasą `DiscordRESTClient`:
  - `__init__(self, bot_token: str | None = None)` — token lazy z `settings.DISCORD_BOT_TOKEN` jeśli not provided.
  - `BASE_URL = "https://discord.com/api/v10"`, `DEFAULT_TIMEOUT = 5.0`.
  - `send_dm(self, user_discord_id: int, content: str) -> bool` — 2-step: create DM channel, then post message. Returns True przy 2xx, False przy 4xx/5xx (po retry).
  - `send_channel_message(self, channel_id: int, content: str | None = None, embed: dict | None = None) -> bool` — jednorazowy POST. Content LUB embed (oba dozwolone). Returns True przy 2xx, False przy 4xx/5xx (po retry).
  - Private `_post(url, json_body) -> httpx.Response | None` — wspólny helper z retry logic (1 retry na 5xx/429 z Retry-After respect).
  - `logger = logging.getLogger(__name__)` module-level. Log levels: 4xx → ERROR (permanent), 5xx → WARNING (transient), 429 → INFO (retried).
- **6 unit testów** w `tests/unit/notifications/test_discord_client.py`:
  - `test_send_dm_creates_channel_then_posts_message` — MockTransport symuluje 2-step flow, assert 2 requests + final True
  - `test_send_dm_returns_false_on_403_user_dms_disabled` — MockTransport 403 na step 1, assert False + log ERROR (caplog)
  - `test_send_channel_message_posts_and_returns_true_on_success` — happy path, assert request body content/embed
  - `test_send_channel_message_returns_false_on_404_channel_not_found` — MockTransport 404, assert False + log ERROR
  - `test_client_retries_once_on_5xx` — first response 503, second 200, assert 2 requests + final True
  - `test_client_respects_retry_after_on_429` — 429 z `Retry-After: 1`, mock `time.sleep`, assert sleep called z 1.0

### ⚠️ Pułapki do uwagi

- **A — Authorization header literal `"Bot {token}"`** — Discord wymaga prefix "Bot " (literal "Bot" + space + token). Bez prefix'a → 401 Unauthorized. Łatwe zapomnieć.
- **B — JSON body NIE form-encoded** — `httpx.post(url, json={...})` (NIE `data={...}`). `data` w httpx wysyła form-encoded; Discord oczekuje JSON.
- **C — Default timeout 5.0s** — Discord REST API typically odpowiada < 1s, ale 5s daje margin na slow network. Sleep z `Retry-After` powinno mieć osobny clamp `min(retry_after, 5.0)` żeby nie czekać 30s+.
- **D — `Retry-After` header parsing** — Discord wysyła sekundy jako int lub float string. `float(response.headers.get("Retry-After", "1"))` z fallback. Brak header'a → 429 bez retry hint, użyj default 1.0s.
- **E — `httpx.MockTransport` handler signature** — `def handler(request: httpx.Request) -> httpx.Response`. Handler decyduje response based na `request.url.path`/`request.method`. Multi-step handler (DM flow): introspect `request.url` żeby rozróżnić `/users/@me/channels` vs `/channels/X/messages`.
- **F — `time.sleep` mocking** — testy MUSZĄ mockować `time.sleep` żeby NIE blokować na real seconds. `monkeypatch.setattr("time.sleep", lambda s: None)` w teście. Alt: `from unittest.mock import patch; patch("time.sleep")`.
- **G — DM channel response shape** — `POST /users/@me/channels` zwraca pełny DM Channel obiekt, ale my potrzebujemy tylko `response.json()["id"]`. Defensive `try/except (KeyError, TypeError)` jeśli Discord zmieni payload (low risk, ale 1 linia).
- **H — Eager `httpx.Client()` w `__init__`** — **NIE** twórz client'a jako instance attribute w `__init__` (M6 retro lekcja: eager resource lookup). Każdy `send_*` call otwiera/zamyka client przez context manager (`with httpx.Client() as client: ...`) — connection pooling lokalne, no leak risk. Trade-off: slight overhead per call (TLS handshake), akceptowalne przy 1-100 calls/hour.
- **I — Bot token z empty string** — gdy `DISCORD_BOT_TOKEN=` empty w env, `httpx.post` z `Authorization: Bot ` (empty token) → Discord 401. Defense: `if not self.bot_token: logger.error("DISCORD_BOT_TOKEN empty"); return False` early w `_post` helper. Spec §6.1 implicit ("empty token gracefully degraded").
- **J — `Content-Type: application/json` automatic przy `json=`** — httpx ustawia header automatycznie. NIE musisz dorzucać manually. Plus `Accept: application/json` defensywnie dla edge cases.

### 🧪 Testing plan

`tests/unit/notifications/__init__.py` (już istnieje z M5) + `tests/unit/notifications/test_discord_client.py` (NEW):

**Test setup pattern:**
```python
import httpx
import pytest

from apps.notifications.discord_client import DiscordRESTClient


def _make_handler(responses: list[httpx.Response]):
    """Cycles through provided responses (1 per call). Use for retry tests."""
    iterator = iter(responses)
    def handler(request: httpx.Request) -> httpx.Response:
        return next(iterator)
    return handler


def _capture_handler() -> tuple[list[httpx.Request], callable]:
    """Captures all requests for later assertion."""
    requests: list[httpx.Request] = []
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        # Default 200 OK with empty body
        return httpx.Response(200, json={"id": "12345"})
    return requests, handler
```

**Coverage cel:** `apps/notifications/discord_client.py` 100%.

### 📦 Definition of Done

- [ ] AC spełnione (httpx dep, DiscordRESTClient, 6 testów).
- [ ] **2 commity osobne:** `build(deps): add httpx for Discord REST outbound (M8-D36, #<#>)` + `feat(notifications): DiscordRESTClient for Discord REST API (M8-D36, #<#>)`.
- [ ] PR zmergowany squash.
- [ ] CI lint + test zielone.
- [ ] `apps/notifications/discord_client.py` 100% coverage.
- [ ] Issue zamknięty.

---

## Task #2 — [M8-D37] `DiscordDMHandler` + bedmage message format + 3 testy + settings default flip

### 🎯 Cel

Dorzucić `DiscordDMHandler` (implementuje `BedmageNotificationHandler` Protocol z M5) do `apps/notifications/handlers.py`. Handler renderuje content message dla bedmage alert ("🛏️ Your bedmage **{name}** has been logged out..."), używa `DiscordRESTClient.send_dm` z M8-D36. Konwertuje `watch.user.discord_id: str` na `int` z try/except. Swallows send failures (logs WARNING, no raise) żeby M5 service nadal mark `last_notified_login`. Plus default flip w `settings.BEDMAGE_NOTIFICATION_HANDLER` z `LoggingHandler` na `DiscordDMHandler`. Po D37: bedmage alerts faktycznie idą do Discord w prod (M5 LoggingHandler test variant zachowany dla testów).

### 🧠 Czego się nauczysz

- **Protocol implementation w Python 3.13** — `class DiscordDMHandler:` nie wymaga explicit `BedmageNotificationHandler` base; structural typing wystarczy. mypy verify'uje conformance via `Protocol` definition w handlers.py.
- **Message rendering w handlerze** — separate `_render` private method, łatwo testowalne osobno (`test_handler_renders_message_with_character_name_and_last_login` izolowane od HTTP).
- **`int(watch.user.discord_id)` edge cases** — `User.discord_id` to `CharField(max_length=32, null=True)`. M7-D31 auto-create zawsze ustawia, ale Django admin może utworzyć User bez (np. manual via createsuperuser). Defense: `try: int(...) except (TypeError, ValueError): logger.error + return`.
- **Settings default flip pattern** — zmiana `BEDMAGE_NOTIFICATION_HANDLER` default w `base.py` z `"apps.notifications.handlers.LoggingHandler"` na `"...DiscordDMHandler"`. Bez zmian w env.example (klucz już istnieje od M5). Test isolation: testy używające M5 `LoggingHandler` muszą explicitly `@override_settings(BEDMAGE_NOTIFICATION_HANDLER="apps.notifications.handlers.LoggingHandler")` lub mock'ować handler.

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m8-d37.md`.)

**Kluczowe punkty:**

- **`apps/notifications/handlers.py`** rozszerzony o:
  ```python
  class DiscordDMHandler:
      """Implements BedmageNotificationHandler. Sends DM via DiscordRESTClient.

      Failures (403 user blocked DMs, 5xx Discord down, invalid discord_id)
      logged but NOT re-raised — M5 service marks last_notified_login anyway
      to avoid retry storm on every scrape cycle.
      """

      def notify(self, watch: BedmageWatch) -> None:
          try:
              user_discord_id = int(watch.user.discord_id)
          except (TypeError, ValueError):
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
                  watch.user.username, watch.character.name,
              )

      def _render(self, watch: BedmageWatch) -> str:
          return (
              f"🛏️ Your bedmage **{watch.character.name}** has been logged out for "
              f"{settings.BEDMAGE_REGEN_MINUTES} minutes — mana fully regenerated.\n"
              f"Last login: {watch.character.last_login:%Y-%m-%d %H:%M UTC}"
          )
  ```
- **`config/settings/base.py`** flip default:
  ```python
  BEDMAGE_NOTIFICATION_HANDLER = env(
      "BEDMAGE_NOTIFICATION_HANDLER",
      default="apps.notifications.handlers.DiscordDMHandler",  # was LoggingHandler in M5
  )
  ```
- **3 unit testy** w `tests/unit/notifications/test_discord_dm_handler.py`:
  - `test_handler_notify_calls_client_send_dm_with_int_discord_id_and_rendered_content` — monkeypatch `DiscordRESTClient` na MagicMock, assert `send_dm(int(...), content)` called.
  - `test_handler_notify_renders_message_with_character_name_and_last_login` — assert returned content z `_render` zawiera character.name + last_login formatted.
  - `test_handler_notify_logs_error_and_returns_when_discord_id_not_numeric` — User z `discord_id=None`, assert `send_dm` NIE called + log ERROR captured.
  - (bonus 4. test: `test_handler_notify_swallows_send_failure_silently_with_warning_log` — client returns False, assert no raise + log WARNING)

### ⚠️ Pułapki do uwagi

- **A — `BedmageWatch.user.discord_id` to str, NIE int** — CharField storage. Cast w handlerze: `int(watch.user.discord_id)`. Edge case: User stworzony przez Django admin bez discord_id → `discord_id=None` → `int(None)` raises TypeError. Defense w try/except (TypeError, ValueError).
- **B — `BedmageWatch.character.last_login` może być None** — Character może mieć `last_login=None` przed pierwszym scrape. M5 service `check_bedmage_watches_for_character` guard'uje `if character.last_login is None: return 0` na początku — handler nigdy nie dostanie watch z None last_login. Ale defensive `{watch.character.last_login:%Y-%m-%d %H:%M UTC}` gdy None → AttributeError. Akceptowalne — jeśli M5 contract brake'uje, fail loud.
- **C — `BEDMAGE_REGEN_MINUTES` z settings** — `from django.conf import settings; settings.BEDMAGE_REGEN_MINUTES`. M5-D24 added default 100. Render używa current value, nie hardcoded "100".
- **D — Settings default flip jest BREAKING CHANGE dla testów używających `LoggingHandler` jako default** — M5 testy (`tests/unit/bedmages/test_services.py`, `tests/integration/test_m5_bedmages_e2e.py`) mogą zależeć od `LoggingHandler` jako resolved handler. Sprawdź czy testy używają `@override_settings(BEDMAGE_NOTIFICATION_HANDLER=...)` — jeśli tak, OK. Jeśli rely na default, dorzuć explicit override.
- **E — `LoggingHandler` z M5 NIE jest usuwany** — zostaje w `handlers.py` jako test variant. Default flip tylko zmienia env var default, oba handlery coexist.
- **F — `DiscordRESTClient()` instantiation w `notify`** — każdy call tworzy nową instancję. To OK (cheap object), ale alternatywa: instance attribute `self._client = DiscordRESTClient()` w `__init__`. Spec §4.3 example pokazuje per-call instantiation, M8 zostaje przy tym pattern (eager `__init__` byłby M6 retro pułapka anti-pattern).
- **G — Handler nie raises** — Critical contract: M5 `check_bedmage_watches_for_character` wrappuje `handler.notify(watch)` w `try: ... except Exception: logger.exception; continue`. Jeśli `DiscordDMHandler.notify` raise'uje, service skipuje cały batch dla character'a (NIE marks `last_notified_login`). Defense: handler internally catches everything, NEVER re-raises.

### 🧪 Testing plan

`tests/unit/notifications/test_discord_dm_handler.py`:

**Test fixture pattern:**
```python
@pytest.fixture
def watch(db):
    from apps.accounts.models import User
    from apps.bedmages.models import BedmageWatch
    from apps.characters.models import Character
    from django.utils import timezone

    user = User.objects.create_user(
        username="discord_12345", email="", discord_id="12345"
    )
    character = Character.objects.create(name="Yhral", last_login=timezone.now())
    return BedmageWatch.objects.create(user=user, character=character)


def test_handler_notify_calls_client_send_dm_with_int_discord_id_and_rendered_content(
    watch, monkeypatch, caplog,
) -> None:
    mock_client = MagicMock()
    mock_client.send_dm.return_value = True
    monkeypatch.setattr(
        "apps.notifications.handlers.DiscordRESTClient",
        lambda *args, **kwargs: mock_client,
    )

    handler = DiscordDMHandler()
    handler.notify(watch)

    mock_client.send_dm.assert_called_once()
    call_args = mock_client.send_dm.call_args
    assert call_args.args[0] == 12345  # int, not str
    assert "Yhral" in call_args.args[1]
    assert "🛏️" in call_args.args[1]
```

**Coverage cel:** `apps/notifications/handlers.py` (D37 część — DiscordDMHandler) 100%.

### 📦 Definition of Done

- [ ] AC spełnione (DiscordDMHandler, _render, settings default flip, 3-4 testy).
- [ ] PR zmergowany squash (`feat(notifications): DiscordDMHandler for bedmage Discord DMs (M8-D37, #<#>)`).
- [ ] CI lint + test zielone.
- [ ] `apps/notifications/handlers.py` DiscordDMHandler parts 100% coverage.
- [ ] M5 testy regression check (`pytest tests/unit/bedmages/ tests/integration/test_m5_bedmages_e2e.py`) — wszystkie zielone po settings flip.
- [ ] Issue zamknięty.

---

## Task #3 — [M8-D38] `DeathEvent.announced_on_discord` migracja + `DeathAnnouncementHandler` Protocol + `DiscordChannelHandler` + 3 testy

### 🎯 Cel

Dorzucić field `announced_on_discord = models.BooleanField(default=False, db_index=True)` do `DeathEvent` model'a (CLAUDE.md §5 finally — wcześniej spec'd ale nie zaimplementowane od M4). Wygenerować migracja `0003_add_announced_on_discord.py`. Plus NEW `DeathAnnouncementHandler` Protocol w `apps/notifications/handlers.py` (z metodą `announce(death_event, discord_channel) -> bool`), implementacja `DiscordChannelHandler` (renderuje embed, używa `DiscordRESTClient.send_channel_message`), test variant `DeathLoggingHandler` (logs only), plus `get_death_handler()` resolver w `apps/notifications/__init__.py`. Plus NEW env var `DEATH_NOTIFICATION_HANDLER` z default `apps.notifications.handlers.DiscordChannelHandler`. Po D38: model + handlery gotowe; D39 dorzuca service który ich używa.

### 🧠 Czego się nauczysz

- **`db_index=True` na boolean field** — Postgres B-tree index na boolean kolumnie jest efektywny dla queryów typu `filter(announced_on_discord=False)` (selektywność wysoka gdy większość rzędów True). Bez indexu sequential scan; z indexem index scan po False values.
- **Django migration z `db_index` flag** — `makemigrations` generuje `AddField` z `db_index=True`. Apply: jeden `CREATE INDEX` poza `CREATE COLUMN`. Atomic w jednej transakcji.
- **Multi-Protocol w jednym pliku handlers.py** — M5 ma `BedmageNotificationHandler` Protocol. M8 dorzuca `DeathAnnouncementHandler` Protocol obok. Oba Protocols + impl klasy coexist w handlers.py. Symetria.
- **Discord Embed dict structure** — `{"title": str, "description": str, "timestamp": ISO8601, "color": int (0xRRGGBB)}`. Send via `embed` kwarg do `send_channel_message`. Discord renderuje pretty card.
- **`import_string(settings.DEATH_NOTIFICATION_HANDLER)`** — Django utility do dynamic import po dotted path. M5 `get_bedmage_handler` używa, M8 powtarza. Per-call resolution (nie cached) żeby `@override_settings` w testach działało.

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m8-d38.md`.)

**Kluczowe punkty:**

- **`apps/deaths/models.py`** dorzucone:
  ```python
  class DeathEvent(models.Model):
      # ... existing fields ...
      announced_on_discord = models.BooleanField(default=False, db_index=True)
  ```
- **Migracja `apps/deaths/migrations/0003_add_announced_on_discord.py`** wygenerowana przez `poetry run python manage.py makemigrations deaths`. Apply check: `migrate deaths --plan` → single `AddField` + index creation.
- **`apps/notifications/handlers.py`** dorzucone:
  ```python
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

      def announce(
          self, death_event: DeathEvent, discord_channel: DiscordChannel
      ) -> bool:
          logger.info(
              "DEATH ANNOUNCE: %s (lvl %s) → guild=%s channel=%s",
              death_event.character_name, death_event.level_at_death,
              discord_channel.guild_id, discord_channel.channel_id,
          )
          return True
  ```
- **`apps/notifications/__init__.py`** rozszerzony:
  ```python
  from apps.notifications.handlers import (
      BedmageNotificationHandler,
      DeathAnnouncementHandler,
  )


  def get_bedmage_handler() -> BedmageNotificationHandler:
      handler_class = import_string(settings.BEDMAGE_NOTIFICATION_HANDLER)
      return cast(BedmageNotificationHandler, handler_class())


  def get_death_handler() -> DeathAnnouncementHandler:
      handler_class = import_string(settings.DEATH_NOTIFICATION_HANDLER)
      return cast(DeathAnnouncementHandler, handler_class())
  ```
- **`config/settings/base.py`**:
  ```python
  DEATH_NOTIFICATION_HANDLER = env(
      "DEATH_NOTIFICATION_HANDLER",
      default="apps.notifications.handlers.DiscordChannelHandler",
  )
  ```
- **`.env.example`** dorzucone (sekcja Discord):
  ```
  DEATH_NOTIFICATION_HANDLER=apps.notifications.handlers.DiscordChannelHandler
  ```
- **3 unit testy** w `tests/unit/notifications/test_discord_channel_handler.py`:
  - `test_handler_announce_calls_client_send_channel_message_with_embed` — monkeypatch DiscordRESTClient, assert `send_channel_message(channel_id=..., embed=...)` called.
  - `test_handler_announce_renders_embed_with_character_level_killed_by_color` — assert `_render_embed` returns dict z expected keys i `0xDC143C` color.
  - `test_handler_announce_returns_false_on_send_failure` — client returns False, assert handler.announce zwraca False.

### ⚠️ Pułapki do uwagi

- **A — `DiscordChannel.channel_id` to `BigIntegerField`** — passes as int do `send_channel_message`, nie jako string. M7-D31 model używa BigInteger dla snowflake.
- **B — Migration `db_index=True` może powodować wolny migrate na dużej tabeli** — `DeathEvent` aktualnie ma 0-100 rzędów (dev), migration instant. W prod gdy 100k+ rzędów, `CREATE INDEX CONCURRENTLY` byłoby preferred (non-blocking). M8 nie używa concurrent variant (Django Postgres index handling default), akceptowalne dla aktualnego scale'a. Note M-future: gdy traffic wzrośnie, rozważyć `AddIndex(..., concurrently=True)`.
- **C — `Embed` dict — color jako int, NIE hex string** — `0xDC143C` to int (decimal 14423100). NIE `"0xDC143C"` ani `"#DC143C"`. Discord API zwraca 400 jeśli string. Plus mypy strict: dict literal type inference dla `0xDC143C` to int (OK).
- **D — `death_event.died_at.isoformat()`** — Django `DateTimeField` zwraca `datetime` aware (TZ-aware bo `USE_TZ=True` default). `isoformat()` ze TZ → `"2026-05-15T14:30:00+00:00"`. Discord parsuje ISO8601 + TZ correctly.
- **E — `death_event.killed_by or "Cause unknown"` fallback** — `killed_by` to `TextField(blank=True, default="")`. Empty string is falsy → fallback do "Cause unknown". `None` nie wystąpi (default="").
- **F — `import_string` cache** — `django.utils.module_loading.import_string` jest cached na poziomie Python's import cache. Per-call `import_string` z `get_death_handler()` szybkie (sub-millisecond). OK przy każdym task fire.
- **G — `DeathLoggingHandler` w handlers.py NIE jest LoggingHandler** — żeby nie konflikt z M5 bedmage `LoggingHandler`. Inne nazwy = czystszy code. M5 zostaje untouched.
- **H — Protocol w `from __future__ import annotations` files** — Protocol klasy są normalnie evaluated runtime (M7 hotfix #124 lekcja BEZ zastosowania tu, bo to nie py-cord cog file). Notifications `handlers.py` może zachować `from __future__ import annotations` bezpiecznie.

### 🧪 Testing plan

`tests/unit/notifications/test_discord_channel_handler.py`:

**Test fixture pattern:**
```python
@pytest.fixture
def death_event(db):
    from apps.deaths.models import DeathEvent
    from django.utils import timezone
    return DeathEvent.objects.create(
        character_name="Yhral",
        level_at_death=60,
        killed_by="a dragon lord",
        died_at=timezone.now(),
    )


@pytest.fixture
def discord_channel(db):
    from discord_bot.models import DiscordChannel
    return DiscordChannel.objects.create(
        guild_id=111, channel_id=222, death_level_threshold=30,
    )
```

**Coverage cel:** `apps/notifications/handlers.py` (D38 część) 100%.

### 📦 Definition of Done

- [ ] AC spełnione (migracja, DeathAnnouncementHandler Protocol, DiscordChannelHandler, DeathLoggingHandler, get_death_handler, settings env var, 3 testy).
- [ ] PR zmergowany squash (`feat(deaths,notifications): DeathAnnouncementHandler + DiscordChannelHandler + announced_on_discord field (M8-D38, #<#>)`).
- [ ] CI lint + test zielone.
- [ ] Migracja `0003_add_announced_on_discord.py` w PR (CLAUDE.md §11: migracja + model zmiana razem).
- [ ] `apps/notifications/handlers.py` (D38 część) 100% coverage.
- [ ] M4 testy regression check (`pytest tests/unit/deaths/`) — wszystkie zielone (migracja nie wpływa na existing testy).
- [ ] Issue zamknięty.

---

## Task #4 — [M8-D39] `announce_unannounced_deaths` service + `scrape_deaths` integration + 7 testów

### 🎯 Cel

Dorzucić `announce_unannounced_deaths()` service do `apps/deaths/services.py`. Service iteruje `DeathEvent.objects.filter(announced_on_discord=False)`, dla każdego event'a fetch'uje applicable `DiscordChannel`'e (gdzie `death_level_threshold <= level_at_death`), wywołuje `handler.announce(event, channel)` per guild (z `time.sleep(0.2)` defensive rate-limit), marks event `announced_on_discord=True` gdy ALL succeed (lub gdy 0 applicable guildów — "evaluated + skipped" semantyka). Returns summary dict. Plus integracja w `apps/deaths/tasks.py scrape_deaths` — inline call po subprocess JSON parse, summary merged do task return value. Po D39: end-to-end death announce flow działa (Beat → scrape_deaths task → spider subprocess → announce service → Discord embed); D40 e2e + closure.

### 🧠 Czego się nauczysz

- **Multi-guild fan-out pattern** — single event może mieć 0/1/N target channels. Iteracja: `for channel in applicable_guilds: ok = handler.announce(...); all_ok = all_ok and ok`. Mark event True tylko gdy `all_ok` (atomicity per-event).
- **"No applicable guilds" semantyka** — gdy event level poniżej WSZYSTKICH guild thresholds, mark True bez sendów. Unika retry storm w queryach każdego scrape cycle. Documented inline w docstring.
- **Inline announce w Celery task** — `scrape_deaths` po subprocess parse wywołuje service, merge summary do return value. `try/except: logger.exception` żeby announce failure NIE retry'owało scrape phase.
- **`select_related("user")` w bedmage** vs flat query w deaths — bedmage używa M5 (M5-D27 retro), deaths NIE potrzebuje join (DiscordChannel queries są osobne).

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m8-d39.md`.)

**Kluczowe punkty:**

- **`apps/deaths/services.py`** dorzucone:
  ```python
  import time

  from apps.notifications import get_death_handler
  from discord_bot.models import DiscordChannel


  def announce_unannounced_deaths() -> dict[str, int]:
      """Iterate unannounced DeathEvents, fan-out do applicable guildów, mark announced.

      Multi-guild fan-out: dla każdej unannounced event'a fetch wszystkie
      DiscordChannel gdzie threshold <= level_at_death. Wyślij do każdej guild
      (rate-limited 200ms sleep). Mark announced_on_discord=True gdy ALL succeed.
      Failed event stays False — retry next scrape cycle.

      "No applicable guilds" semantyka: gdy 0 guildów ma threshold <= level,
      mark announced=True mimo braku message'a (semantyka "evaluated + skipped").
      Unikamy retry storm w queryach każdego scrape cycle.

      Known limitation (§3.3): gdy admin dodaje nowy DiscordChannel z niższym
      threshold PO ogłoszeniu, historyczne śmierci `announced_on_discord=True`
      NIE są retroaktywnie wysłane. Backfill out of scope dla M8 — M-future
      conversion do M2M tracking model.

      Returns: {"events_announced": N, "events_skipped": M, "fail_count": K}
      """
      handler = get_death_handler()
      events_announced = 0
      events_skipped = 0
      fail_count = 0

      unannounced = DeathEvent.objects.filter(announced_on_discord=False).order_by("died_at")
      for event in unannounced:
          applicable_guilds = DiscordChannel.objects.filter(
              death_level_threshold__lte=event.level_at_death
          )

          if not applicable_guilds.exists():
              event.announced_on_discord = True
              event.save(update_fields=["announced_on_discord"])
              events_skipped += 1
              continue

          all_ok = True
          for channel in applicable_guilds:
              try:
                  ok = handler.announce(event, channel)
              except Exception:
                  logger.exception(
                      "DeathAnnouncementHandler.announce raised for event=%s channel=%s",
                      event.pk, channel.pk,
                  )
                  ok = False
              all_ok = all_ok and ok
              time.sleep(0.2)  # rate limit defensive

          if all_ok:
              event.announced_on_discord = True
              event.save(update_fields=["announced_on_discord"])
              events_announced += 1
          else:
              fail_count += 1

      summary = {
          "events_announced": events_announced,
          "events_skipped": events_skipped,
          "fail_count": fail_count,
      }
      logger.info("announce_unannounced_deaths: %s", summary)
      return summary
  ```
- **`apps/deaths/tasks.py scrape_deaths`** integracja:
  ```python
  from apps.deaths.services import announce_unannounced_deaths

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
          logger.exception(
              "announce_unannounced_deaths raised — events stay unannounced for next cycle"
          )

      return summary
  ```
- **7 unit testów** w `tests/unit/deaths/test_announce_unannounced_deaths.py`:
  - `test_announce_processes_only_unannounced_events` — 2 events (1 announced, 1 not), mock handler returns True, assert handler called 1x dla unannounced one.
  - `test_announce_marks_event_as_announced_on_success` — mock handler True, assert `announced_on_discord=True` po call.
  - `test_announce_keeps_unannounced_on_handler_failure` — mock handler False, assert event stays False.
  - `test_announce_iterates_all_applicable_guilds_per_event` — 2 channels (threshold 30 + 50), event level 60 → 2x handler call, event marked True (all succeeded).
  - `test_announce_marks_event_announced_when_no_applicable_guilds` — event level 20, all channels threshold ≥ 30 → 0x handler call, event marked True (semantyka skipped).
  - `test_announce_stays_unannounced_when_any_guild_fails` — 2 channels, handler True for first + False for second → event stays False.
  - `test_announce_summary_dict_reports_counts` — 3 events (1 announce success, 1 skipped, 1 fail), assert summary dict matches.

- **1 test update** w `tests/unit/deaths/test_scrape_deaths_task.py`:
  - `test_scrape_deaths_calls_announce_after_subprocess_and_merges_summary` — monkeypatch announce service, assert called once po subprocess parse, assert summary contains both subprocess keys (yielded, duplicates) AND announce keys (events_announced, ...).

### ⚠️ Pułapki do uwagi

- **A — `applicable_guilds.exists()` vs `.count() == 0`** — `.exists()` jest jednoznacznie szybsze (Postgres `LIMIT 1`), `.count()` robi pełny COUNT. Preferred dla early-return.
- **B — `update_fields=["announced_on_discord"]` w `save()`** — single-column atomic write. Performance + clear intent. NIE używaj `event.save()` bez `update_fields` bo to atualizuje ALL fields włącznie z `scraped_at` (auto_now_add nie touch'uje, ale defensive).
- **C — `time.sleep(0.2)` w Celery worker** — sync sleep blokuje worker thread na 0.2s. Przy 50 events × 1 guild = 10s extra w task. Akceptowalne (Celery task ~30s już z scraping). Note: jeśli ruch znacząco wzrośnie, M-future async batch.
- **D — Order events by `died_at`** — chronological order zapewnia że Discord pokazuje śmierci w sensible kolejności. Plus deterministic test execution (bez ordering testy mogą flake'ować).
- **E — Handler raise wraps w `try/except Exception`** — defensive bo handler może rzucić unexpected (np. httpx.ConnectError w lower-level klienta nie złapane). Service NIE retry'uje, mark fail_count, kontynuuje batch.
- **F — `scrape_deaths` task return value backward compat** — istniejące M4 testy expectają `{"yielded": int, "duplicates": int, "returncode": int}`. M8 dodaje keys, NIE usuwa. Test M4 regression check (`pytest tests/unit/deaths/test_scrape_deaths_task.py`) musi być zielony.
- **G — `time.sleep` w testach** — must mockowane. `monkeypatch.setattr("time.sleep", lambda s: None)` na początku test'u lub conftest fixture.
- **H — Empty unannounced queryset** — gdy 0 events unannounced (typical między scrapes), pętla NIE odpala, summary `{"events_announced": 0, ...}`. Service NIE crashuje. Test: `test_announce_returns_zero_summary_when_no_unannounced_events` (opcjonalny bonus 8.).
- **I — Handler resolution per-call w service** — `handler = get_death_handler()` na początku service, NIE per-event. Avoid re-import on each event (negligible perf, ale cleaner).

### 🧪 Testing plan

`tests/unit/deaths/test_announce_unannounced_deaths.py`:

**Test pattern:**
```python
@pytest.mark.django_db
def test_announce_marks_event_as_announced_on_success(monkeypatch) -> None:
    from apps.deaths.models import DeathEvent
    from discord_bot.models import DiscordChannel
    from django.utils import timezone

    monkeypatch.setattr("time.sleep", lambda s: None)
    DiscordChannel.objects.create(guild_id=111, channel_id=222, death_level_threshold=30)
    event = DeathEvent.objects.create(
        character_name="Yhral", level_at_death=60,
        killed_by="dragon", died_at=timezone.now(),
    )

    mock_handler = MagicMock()
    mock_handler.announce.return_value = True
    monkeypatch.setattr(
        "apps.deaths.services.get_death_handler", lambda: mock_handler,
    )

    summary = announce_unannounced_deaths()

    event.refresh_from_db()
    assert event.announced_on_discord is True
    assert summary == {"events_announced": 1, "events_skipped": 0, "fail_count": 0}
```

**Coverage cel:** `apps/deaths/services.py` (M8 D39 część) 100%.

### 📦 Definition of Done

- [ ] AC spełnione (service, scrape_deaths integration, 7 testów + 1 update).
- [ ] PR zmergowany squash (`feat(deaths): announce_unannounced_deaths service + scrape_deaths integration (M8-D39, #<#>)`).
- [ ] CI lint + test zielone.
- [ ] `apps/deaths/services.py` (M8 część) 100% coverage.
- [ ] M4 task regression check (`pytest tests/unit/deaths/test_scrape_deaths_task.py`) zielony.
- [ ] Issue zamknięty.

---

## Task #5 — [M8-D40] M8 e2e + closure (PROGRESS.md retro + milestone close + manual smoke 4 punkty)

### 🎯 Cel

E2e sanity test pokrywający full bedmage flow (BedmageWatch → check service → DiscordDMHandler → DiscordRESTClient mocked → assert send_dm called) i death flow (DeathEvent + DiscordChannel → announce service → DiscordChannelHandler → DiscordRESTClient mocked → assert send_channel_message called). Plus M8 closure — `PROGRESS.md` rozszerzony o sekcję M8 z retro per Issue (D36-D40), milestone closed via `gh api`.

D40 ma **2 PR-y w 1 issue** (M5-D27 + M6-D30 + M7-D35 pattern):

1. **Feature PR** (`feat/<#>-m8-e2e`) — `tests/integration/test_m8_outbound_e2e.py` z 1-2 testami sanity.
2. **Closure PR** (`docs/close-m8-outbound-notifications` od **fresh master** po feature merge) — `PROGRESS.md` retro + milestone close + manual smoke notes w PR description.

### 🧠 Czego się nauczysz

- **End-to-end test integracji 3 layerów** — service → handler (via settings) → client (mocked). Asercja: handler resolution chain działa, client called z expected args. Granica testowania: real Discord API NIE hit'owany.
- **`@override_settings(BEDMAGE_NOTIFICATION_HANDLER=..., DEATH_NOTIFICATION_HANDLER=...)`** — testy mogą explicitly forcować handler bez polegania na env defaults. Robust przeciwko env changes.
- **`gh api -X PATCH milestone state=closed`** — M5-D27 + M6-D30 + M7-D35 precedens. Wymaga `repo` scope w token'ie.

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m8-d40.md`.)

**Feature PR kluczowe punkty:**

- `tests/integration/test_m8_outbound_e2e.py`:
  ```python
  """E2E sanity for M8 — handler chain delegates to DiscordRESTClient correctly.

  Mocks DiscordRESTClient at module-level import. Verifies that:
  1. Bedmage service → DiscordDMHandler resolution → client.send_dm called with int discord_id + content
  2. Deaths service → DiscordChannelHandler resolution → client.send_channel_message called with embed
  No real Discord API hit.
  """

  from __future__ import annotations

  from unittest.mock import MagicMock
  from datetime import timedelta

  import pytest
  from django.test import override_settings
  from django.utils import timezone


  @pytest.mark.django_db
  @override_settings(BEDMAGE_NOTIFICATION_HANDLER="apps.notifications.handlers.DiscordDMHandler")
  def test_bedmage_flow_calls_send_dm_via_handler_chain(monkeypatch) -> None:
      from apps.accounts.models import User
      from apps.bedmages.models import BedmageWatch
      from apps.bedmages.services import check_bedmage_watches_for_character
      from apps.characters.models import Character

      mock_client = MagicMock()
      mock_client.send_dm.return_value = True
      monkeypatch.setattr(
          "apps.notifications.handlers.DiscordRESTClient",
          lambda *args, **kwargs: mock_client,
      )

      user = User.objects.create_user(username="discord_42", email="", discord_id="42")
      character = Character.objects.create(
          name="Yhral", last_login=timezone.now() - timedelta(minutes=120),
      )
      BedmageWatch.objects.create(user=user, character=character)

      fired = check_bedmage_watches_for_character(character)

      assert fired == 1
      mock_client.send_dm.assert_called_once()
      args = mock_client.send_dm.call_args.args
      assert args[0] == 42
      assert "Yhral" in args[1]


  @pytest.mark.django_db
  @override_settings(DEATH_NOTIFICATION_HANDLER="apps.notifications.handlers.DiscordChannelHandler")
  def test_death_flow_calls_send_channel_message_via_handler_chain(monkeypatch) -> None:
      from apps.deaths.models import DeathEvent
      from apps.deaths.services import announce_unannounced_deaths
      from discord_bot.models import DiscordChannel

      monkeypatch.setattr("time.sleep", lambda s: None)
      mock_client = MagicMock()
      mock_client.send_channel_message.return_value = True
      monkeypatch.setattr(
          "apps.notifications.handlers.DiscordRESTClient",
          lambda *args, **kwargs: mock_client,
      )

      DiscordChannel.objects.create(guild_id=111, channel_id=222, death_level_threshold=30)
      DeathEvent.objects.create(
          character_name="Yhral", level_at_death=60,
          killed_by="a dragon lord", died_at=timezone.now(),
      )

      summary = announce_unannounced_deaths()

      assert summary["events_announced"] == 1
      mock_client.send_channel_message.assert_called_once()
      call_kwargs = mock_client.send_channel_message.call_args.kwargs
      assert call_kwargs["channel_id"] == 222
      assert "Yhral" in call_kwargs["embed"]["title"]
  ```
- Cumulative coverage `apps/notifications/*` + `apps/deaths/services.py` parts ≥ 95%.

**Closure PR kluczowe punkty:**

- `PROGRESS.md` rozszerzone o:
  - `## 🎉 Milestone M8 — Discord outbound notifications COMPLETED (2026-MM-DD)` header.
  - `### Ukończone (M8)` — lista 5 issues + PR linki + squash hashes.
  - `### Notatki z retro M8 (dopisywane progresywnie)` — per Issue D36-D40.
  - `### Definition of Done M8` (ze spec'a §8) — wszystkie [x] poza ostatnim ("milestone closed" — TODO post-merge).
  - `### Podsumowanie M8` (data range, dni vs budżet, najwartościowsze lekcje).
  - `### Tech debt z M8` (carry-over do M9+).
- **Manual smoke** udokumentowany w closure PR description (4 punkty z spec §9):
  1. Bedmage DM happy path: User + BedmageWatch + Character z `last_login=120min ago` → run `check_bedmage_watches_for_character` w shell → bot DM-uje cię.
  2. Bedmage DM blocked: zablokuj DMs od bota → repeat → log WARNING w `app_logs` Mongo, `last_notified_login` zaktualizowane.
  3. Death announce happy: insert manual DeathEvent z level=60 → run `scrape_deaths` task w shell → bot post embed w kanale.
  4. Death announce skipped: insert DeathEvent z level=20 (poniżej threshold 30) → po scrape → event `announced_on_discord=True` ale 0 wiadomości.
- **Po merge closure PR'a:** `gh api -X PATCH repos/bgozlinski/tibiantis-scraper/milestones/8 -f state=closed`.
- **Sanity:** `gh issue list --milestone "M8 — Discord outbound notifications" --state open` → empty.

### ⚠️ Pułapki do uwagi

- **A — `monkeypatch.setattr("apps.notifications.handlers.DiscordRESTClient", ...)`** — patch'uje binding w handlers.py module namespace. `DiscordDMHandler.notify` robi `client = DiscordRESTClient()` które resolves przez module __dict__ → mock zwracany. Standard Python.
- **B — `time.sleep` mocking w deaths e2e** — `announce_unannounced_deaths` ma `time.sleep(0.2)`. W teście monkeypatch z lambda.
- **C — Closure branch od fresh master** (M1-D8 + M5-D27 + M6-D30 + M7-D35 lekcja repeat) — `git checkout master && git pull && git checkout -b docs/close-m8-outbound-notifications` PRZED edycją PROGRESS.md. Pattern utrwala się.
- **D — `gh api PATCH milestone`** wymaga `repo` scope. Sanity: `gh auth status`. Plus correct milestone number — `gh api repos/bgozlinski/tibiantis-scraper/milestones --jq '.[] | select(.title|startswith("M8")) | .number'`.
- **E — Milestone exact title match** — `gh issue list --milestone "M8 — Discord outbound notifications"` wymaga dokładnego tytułu (z em-dashem `—`).
- **F — Test isolation: handler resolution** — `@override_settings` w testach wymusza explicit handler. Bez tego defaults z env.example mogą się różnić w testach lokalnych vs CI.
- **G — `check_bedmage_watches_for_character` ma early return gdy `character.last_login is None`** — test fixture musi ustawić `last_login` (nie None).
- **H — Test fixture `Character.last_login` z `now() - 120min`** — żeby `delta >= BEDMAGE_REGEN_MINUTES (default 100)`. Mniejszy delta → service nie fires handler.

### 🧪 Testing plan

**Feature PR:**

```bash
poetry run pytest tests/integration/test_m8_outbound_e2e.py -v
poetry run pytest tests/unit/notifications/ tests/unit/deaths/ tests/integration/test_m8_outbound_e2e.py --cov=apps.notifications --cov=apps.deaths.services --cov-report=term
```

**Closure PR — Manual smoke (dev guild):**

W closure PR body zacytuj wyniki testów (zrzut ekranu albo verbatim transcript):

1. **Bedmage DM happy path:**
   ```
   poetry run python manage.py shell -c "
   from apps.characters.models import Character
   from apps.bedmages.services import check_bedmage_watches_for_character
   from django.utils import timezone
   from datetime import timedelta
   c = Character.objects.get(name='Yhral')
   c.last_login = timezone.now() - timedelta(minutes=120)
   c.save()
   print(check_bedmage_watches_for_character(c))
   "
   ```
   → 1 fired, DM otrzymany w Discord.

2. **Bedmage DM blocked:** ustaw "Privacy & Safety → Direct Messages: Disable" w Discord dla dev guildu, repeat → log w `app_logs` Mongo z `Bedmage DM failed`, `last_notified_login` zaktualizowane.

3. **Death announce happy:**
   ```
   poetry run python manage.py shell -c "
   from apps.deaths.models import DeathEvent
   from django.utils import timezone
   DeathEvent.objects.create(character_name='TestChar', level_at_death=60, killed_by='a dragon', died_at=timezone.now())
   from apps.deaths.tasks import scrape_deaths
   print(scrape_deaths())
   "
   ```
   → embed visible w dev guild channel.

4. **Death announce skipped:** insert DeathEvent z `level_at_death=20`, repeat → summary `events_skipped=1`, 0 messages w Discord, DB row `announced_on_discord=True`.

**Coverage cel:** Cumulative `apps/notifications/*` + `apps/deaths/services.py` (M8 część) ≥ 95%.

### 📦 Definition of Done

**Feature PR:**
- [ ] AC spełnione (2 e2e testy, wszystkie M8 testy zielone).
- [ ] Feature PR zmergowany squash.
- [ ] CI lint + test zielone.
- [ ] Cumulative `apps/notifications/*` + `apps/deaths/services.py` (M8 część) ≥ 95% coverage.

**Closure PR:**
- [ ] Closure PR zmergowany squash (`docs(progress): close M8 — Discord outbound notifications COMPLETED + retro D36-D40`).
- [ ] CI lint zielony.
- [ ] PROGRESS.md sekcja M8 dorzucona.
- [ ] Manual smoke description w closure PR body (4 punkty z testing plan).
- [ ] Milestone M8 zamknięty na GitHub via `gh api -X PATCH .../milestones/8 -f state=closed`.
- [ ] Wszystkie M8 issues CLOSED (`gh issue list --milestone "M8 — Discord outbound notifications" --state open` → empty).
