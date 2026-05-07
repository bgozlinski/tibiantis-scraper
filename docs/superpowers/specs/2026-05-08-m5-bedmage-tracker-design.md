# M5 — Bedmage tracker (backend) — Design

**Data:** 2026-05-08
**Milestone:** M5 (GitHub milestone TBD)
**Budżet:** 5 dni roboczych (~16-20h, mirror M4 budgetu po lekcji "świadomie wąski scope" zadziałała w 3 dni real time).
**Poprzedni milestone:** M4 — Deaths monitor (backend) (zamknięty 2026-05-07, retro w `PROGRESS.md`).
**Następny:** M6 — Discord bot integration (dorzuca real Discord publisher ponad notification abstraction z M5).

---

## 1. Cel

Dodać trzecią funkcjonalność biznesową aplikacji — **bedmage tracker** — przypominanie użytkownikom, że minęło 100 minut od logowania ich obserwowanej postaci (koniec regeneracji many w łóżku). Po M5 backend potrafi:

1. User przez GraphQL `addBedmageWatch(characterName)` zapisuje "obserwuję postać X".
2. Co 1h Beat fires `scrape_watched_characters` (M3 infra) — tylko Characters które mają BedmageWatch'e są w to scope, nie cały DB (mitigation: nie scrape'uj postaci nikomu nie potrzebnych).
3. Po każdym successful scrape postaci, tracker wywołuje `check_bedmage_watches_for_character(character)` — sprawdza czy `now - character.last_login >= 100 min` AND czy notyfikacja dla tego logowania jeszcze nie poszła.
4. Gdy oba warunki spełnione, tracker wywołuje `BedmageNotificationHandler.notify(watch)` — w M5 default `LoggingHandler` loguje do app logs, w M6 `DiscordHandler` publikuje przez webhook do user'owego DM.
5. `last_notified_login = character.last_login` ustawione → nie spamujemy każdym scrape (idempotency per logowanie).

**Świadomie wąski scope:** zero Discord, zero realnej komunikacji z user'em, zero discord_id mapping. Backend tylko wykrywa + flag'uje + odpala dummy handler. M6 wymieni handler na real Discord publisher.

**Świadomie odroczone:**
- Discord bot proces, slash commands `/bedmage add|list|remove` (M6) — wymaga osobnego container'a, py-cord vs discord.py decision, OAuth lub auto-create User mapping.
- Real Discord webhook publisher (M6) — wymieni `LoggingHandler` na `DiscordHandler` przez settings switch.
- Per-watch custom interval (60/100/150 min override) — domyślnie 100 min hardcoded w settings; przyszłe `BedmageWatch.regen_minutes: PositiveIntegerField(null=True)` field z fallback do `settings.BEDMAGE_REGEN_MINUTES`.
- Multi-tenant Discord (multiple servers) — UserY na serwerze A vs B widzi inne BedmageWatch'e? Decyzja: nie, BedmageWatch jest per-User, niezależnie od serwera Discord. M6 wybierze gdzie powiadomić.
- Pause/resume bulk operations (`pauseAllBedmages` GraphQL mutation) — `active` field jest set/unset przez add/remove, batch ops poza M5.

---

## 2. Scope

**W scope:**
- Nowa aplikacja `apps/bedmages/` zarejestrowana w `INSTALLED_APPS` jako `apps.bedmages.apps.BedmagesConfig`.
- Model `BedmageWatch` (`user FK`, `character FK`, `created_at auto_now_add`, `last_notified_login DateTime null`, `active BooleanField default=True`) + migracja initial + Django admin + `unique_together = ("user", "character")`.
- Service `apps/bedmages/services.py`:
  - `add_bedmage_watch(user, character_name)` — auto-create `Character` jeśli nie istnieje (lazy fetch, scrape przez najbliższy Beat fire), tworzy `BedmageWatch` lub raise jeśli juz istnieje.
  - `remove_bedmage_watch(user, character_name)` — soft delete przez `active=False` lub hard delete (decyzja w `decisions` poniżej).
  - `check_bedmage_watches_for_character(character)` — invoke'owane post-scrape; iteruje aktywne watche dla character, sprawdza delta + idempotency, wywołuje notification handler.
- Notifications abstraction `apps/notifications/`:
  - `BedmageNotificationHandler` interface (Protocol lub ABC).
  - `LoggingHandler` default — `logger.info("BEDMAGE: user=%s character=%s last_login=%s", ...)`.
  - Settings `BEDMAGE_NOTIFICATION_HANDLER` (env-based, default `"apps.notifications.handlers.LoggingHandler"`) z dotted-path resolution.
- Settings `BEDMAGE_REGEN_MINUTES` (env-based, default 100) — używany w tracker dla delta comparison.
- Integration z `apps.characters.tasks.scrape_watched_characters` — po każdym `result.returncode == 0`, fire `check_bedmage_watches_for_character(character)` (lazy import żeby uniknąć circular).
- GraphQL w `apps/bedmages/schema.py`:
  - Query `myBedmages: [BedmageWatchType!]!` — JWT-protected, filtruje przez `request.user`.
  - Mutation `addBedmageWatch(characterName: String!): BedmageWatchType!` — JWT-protected.
  - Mutation `removeBedmageWatch(characterName: String!): Boolean!` — JWT-protected.
- Tests: unit model, unit services (3 funkcje), unit notification handler dispatch, unit GraphQL (queries + mutations + auth), integration e2e (full flow: addBedmageWatch → mocked scrape → handler fires).
- PROGRESS.md retro M5 + DoD checklist + Podsumowanie M5.

**Poza scope (post-M5):**
- Discord bot proces, slash commands, webhook publisher, channel config (M6).
- Real Discord notification handler (M6) — wymiana `LoggingHandler` na `DiscordHandler`.
- `discord_id` field już istnieje na `User` z M2-D9, ale auto-link w M5 nie używa go.
- Per-watch custom regen interval (M-future field).
- Bedmage statistics ("user X has 5 active watches, total notifications sent: 47") — backend ma logi ale brak query'ego (M6+).
- Watchdog "character no longer being scraped" alarm (M5+ tech debt).

---

## 3. Architektura

```
┌─────────────────┐     addBedmageWatch       ┌──────────────────┐
│  GraphQL client │ ────────────────────────► │ apps/bedmages/   │
│   (M6: bot)     │     myBedmages            │   schema.py      │
└─────────────────┘                           └────────┬─────────┘
                                                       │
                                              services.py
                                                       │
                                              ┌────────▼─────────┐
                                              │  BedmageWatch    │
                                              │     model        │
                                              └────────┬─────────┘
                                                       │
   Beat (5 min)                                        │
        │                                              │
        ▼                                              │
┌─────────────────┐    per scraped char               │
│ scrape_watched_ │ ──────────────────────► check_bedmage_watches_for_character(char)
│  characters     │                                    │
└─────────────────┘                          ┌─────────▼────────────┐
                                              │ delta = now - last_login
                                              │ if delta >= 100 min  │
                                              │   AND last_notified_login != last_login:
                                              │     handler.notify(watch)
                                              │     watch.last_notified_login = char.last_login
                                              └─────────┬────────────┘
                                                       │
                                              ┌────────▼─────────┐
                                              │ apps/notifications/
                                              │  LoggingHandler  │ ◄── M5 default
                                              │  DiscordHandler  │ ◄── M6 dorzuca
                                              └──────────────────┘
```

**Kluczowy invariant:** `last_notified_login` przechowuje `character.last_login` z momentu kiedy notyfikacja poszła. Każde nowe logowanie postaci (`character.last_login` się zmienia po fresh scrape) reset'uje cycle — tracker widzi `last_notified_login != character.last_login`, czeka 100 min, fires nowa notyfikacja, set'uje znowu.

---

## 4. Kluczowe decyzje designowe

### 4.1 Auto-create Character w `addBedmageWatch`

**Decyzja:** TAK, lazy fetch.

`add_bedmage_watch(user, character_name)`:
```python
character, _ = Character.objects.get_or_create(name=character_name)
watch, created = BedmageWatch.objects.get_or_create(
    user=user, character=character, defaults={"active": True}
)
if not created and watch.active:
    raise ValueError(f"BedmageWatch for {character_name} already exists")
if not created and not watch.active:
    watch.active = True
    watch.save()
return watch
```

**Why:**
- UX: user dodaje watch nie znając stanu DB. System sam handluje "Character nie istnieje".
- Pierwsza scrape postaci nadejdzie z najbliższym Beat fire (ścieżka: scrape_watched_characters → loop przez Character → spider → upsert_character ustawia `last_login`). Tracker zaczyna działać po tym pierwszym scrape.
- Edge case: postać nie istnieje na tibiantis.online (literówka, deleted account) → spider zaloguje warning, `Character.last_login = None`, tracker robi `if char.last_login is None: skip`. Watch zostaje "uśpiony" do momentu poprawienia nazwy lub usunięcia.

**Alternative (rejected):** reject jeśli Character nie istnieje. UX gorszy ("manualnie scrape postaci, dopiero potem watch") + race condition (postać scrape'owana między user'a check a watch creation = niepotrzebny error).

### 4.2 Soft vs hard delete dla `removeBedmageWatch`

**Decyzja:** HARD delete.

```python
def remove_bedmage_watch(user, character_name) -> bool:
    deleted, _ = BedmageWatch.objects.filter(
        user=user, character__name=character_name
    ).delete()
    return deleted > 0
```

**Why:**
- M5 nie ma "history of watches" jako feature — soft delete byłby YAGNI.
- Hard delete + `unique_together("user", "character")` znaczy że `addBedmageWatch` tej samej postaci później = fresh start (cycle resetuje, `last_notified_login = None`).
- Soft delete (`active=False`) by complikował `addBedmageWatch` (re-activation logic) bez korzyści.

**`active` field zostaje** — używany dla "pause" przyszłych operacji (M-future), w M5 zawsze `True` po `addBedmageWatch`. Hard delete usuwa wpis całkowicie.

### 4.3 Notification handler abstraction w M5

**Decyzja:** TAK, `apps/notifications/` package z Protocol-based interface + `LoggingHandler` default.

```python
# apps/notifications/handlers.py
from typing import Protocol
import logging

logger = logging.getLogger(__name__)


class BedmageNotificationHandler(Protocol):
    def notify(self, watch: "BedmageWatch") -> None: ...


class LoggingHandler:
    def notify(self, watch: "BedmageWatch") -> None:
        logger.info(
            "BEDMAGE: user=%s character=%s last_login=%s",
            watch.user.username, watch.character.name, watch.character.last_login,
        )


# apps/notifications/__init__.py
from django.conf import settings
from django.utils.module_loading import import_string


def get_bedmage_handler() -> BedmageNotificationHandler:
    handler_class = import_string(settings.BEDMAGE_NOTIFICATION_HANDLER)
    return handler_class()
```

Service `check_bedmage_watches_for_character`:
```python
from apps.notifications import get_bedmage_handler

handler = get_bedmage_handler()  # cached at module level lub per-call?
handler.notify(watch)
```

**Why:**
- Otwiera M6 path bez M5 refactor — M6 doda `DiscordHandler` w `apps/notifications/handlers.py`, zmienia `BEDMAGE_NOTIFICATION_HANDLER=apps.notifications.handlers.DiscordHandler` w `.env`, rebuild — koniec.
- Test'owalność — w M5 testach wsadzamy `mock.patch("apps.notifications.get_bedmage_handler")` i sprawdzamy że został wywołany.
- Settings switch jest standard Django pattern (mirror `CACHES['default']['BACKEND']`).

**Alternative (rejected):** dummy handler bez abstraction (just `logger.info` w service). Daje shorter M5, ale M6 wymaga refactor service'u — coupling tracker logic do Discord. Reject — abstraction kosztuje 30 linii w M5, oszczędza dni refactoru w M6.

### 4.4 Tracker fire trigger — gdzie wywołać `check_bedmage_watches`?

**Decyzja:** Wewnątrz `scrape_watched_characters` task (M3-D16), per-character po `result.returncode == 0`.

```python
# apps/characters/tasks.py — D26 modification
result = subprocess.run([...])
if result.returncode == 0:
    scraped += 1
    character = Character.objects.get(name=name)
    from apps.bedmages.services import check_bedmage_watches_for_character
    check_bedmage_watches_for_character(character)
```

**Why:**
- Coupling natural — tracker depends na świeżo updated `character.last_login`. Najświeższy moment to **right after scrape**.
- Reuse infrastruktury — Beat schedule, worker pool, error handling z M3 są zachowane.
- Single failure mode — jeśli tracker rzuci exception, scrape counter'y nie są dotknięte (subprocess już succeed). Tracker exceptions logowane, nie eskalują do retry.

**Alternative (rejected):**
- (A) Osobny periodic task `check_bedmages` co 5 min — duplicates Beat traffic, race condition gdy scrape interval pokrywa się z check interval.
- (B) Django signal post_save na Character — implicit coupling, trudniejsze do debugowania, signal handlers ciężko mockować w testach.
- (C) Query-time tracker (lazy fetch w `myBedmages`) — nie wysyła notyfikacji proactively.

### 4.5 Tracker scope — wszystkie Characters czy tylko z aktywnymi watch'ami?

**Decyzja:** `scrape_watched_characters` skanuje **wszystkie** Characters w DB (M3-D16 zachowanie), tracker filtruje **tylko** przez `BedmageWatch.objects.filter(character=char, active=True)`.

**Why:**
- M5 ma świadomie wąski scope. Optymalizacja "scrape only watched characters" to oszczędność zasobów ale dodaje sprzężenie (jeśli BedmageWatch nie istnieje, postać nie jest scrape'owana — co jeśli w przyszłości chcemy scrape'ować postaci dla deaths threshold lub innego feature'u?). M3 task scope = "wszystkie Characters", M5 nie zmienia.
- W praktyce: dev/test ma <50 Characters, prod może mieć kilka tysięcy ale nadal scrapowanie 1 postaci = ~3s, więc 1000 chars = ~50 min. Beat 1h interval daje bufor.
- Future optimization: M-future doda `Character.is_watched` lub query-side join (`Character.objects.filter(bedmagewatch__active=True).distinct()`) jeśli scale wymaga. M5 nie premature-optimizuje.

**Alternative (rejected):** scrape only Characters z aktywnymi BedmageWatch'ami. Sprzęga M3 (characters) z M5 (bedmages), regress'uje jeśli M-future wymaga scrape'a postaci dla innych powodów.

### 4.6 GraphQL mutations error handling

**Decyzja:** `addBedmageWatch` + `removeBedmageWatch` rzucają `Exception` (Strawberry serializuje jako `errors[]` field). Mirror M4-D22 `recentDeaths` auth pattern.

- `addBedmageWatch` z istniejącym aktywnym watch'em → `raise Exception("BedmageWatch for X already exists")`
- `removeBedmageWatch` z nieistniejącym watch'em → return `False` (idempotent), NIE raise.
- Auth fail (no JWT) → `raise Exception("Authentication required")` (mirror M4-D22 `recentDeaths`).

**Why:**
- Mutations zwracają `BedmageWatchType!` (non-null) lub `Boolean!` — error response jest semantycznie inny niż "no result".
- Idempotent remove (no-op if not exists) jest UX-friendly (user może spamować "remove" bez błędów).

### 4.7 `BedmageWatch.character` FK on_delete behavior

**Decyzja:** `on_delete=models.CASCADE` (M5 default Django convention).

**Why:**
- Jeśli ktoś usuwa Character z DB (admin operation lub future scrape failure pruning), BedmageWatch dla tego Character traci sens — cascade czyści.
- Alternative `PROTECT` blokowałby Character delete dopóki user ręcznie nie usuwa wszystkich watch'y — UX gorszy.
- `SET_NULL` wymagałby `character` field jako nullable — komplikuje query'y.

`BedmageWatch.user` FK → `on_delete=models.CASCADE` także (User delete = wszystkie watch'e idą).

---

## 5. Daily tasks split (5 D-tasks)

### D23 — `apps/bedmages/` app + `BedmageWatch` model + admin + initial migration

**Czas:** 2-3h
**Branch:** `feat/<issue#>-bedmages-app-model`
**Zależy od:** M4 closed.

- Stwórz `apps/bedmages/` z `apps.py` (`BedmagesConfig`, `default_auto_field = "django.db.models.BigAutoField"`, `name = "apps.bedmages"`, `label = "bedmages"`).
- Dodaj `"apps.bedmages"` do `LOCAL_APPS` w `config/settings/base.py` (single source of truth z chore PR #92 widzi automatycznie).
- `BedmageWatch` model:
  ```python
  class BedmageWatch(models.Model):
      user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bedmage_watches")
      character = models.ForeignKey("characters.Character", on_delete=models.CASCADE, related_name="bedmage_watches")
      created_at = models.DateTimeField(auto_now_add=True)
      last_notified_login = models.DateTimeField(null=True, blank=True)
      active = models.BooleanField(default=True)

      class Meta:
          constraints = [
              models.UniqueConstraint(
                  fields=["user", "character"],
                  name="unique_bedmage_watch_per_user_character",
              ),
          ]
          ordering = ["-created_at"]

      def __str__(self) -> str:
          return f"{self.user.username} watching {self.character.name}"
  ```
- Initial migration `0001_initial.py`.
- Django admin z `list_display=("user", "character", "active", "last_notified_login", "created_at")`, `list_filter=("active",)`, `search_fields=("user__username", "character__name")`.
- Smoke: `migrate bedmages` clean, model visible w admin, `BedmageWatch.objects.create(...)` w shell działa.

### D24 — Services: `add_bedmage_watch` + `remove_bedmage_watch` + `check_bedmage_watches_for_character`

**Czas:** 3h
**Branch:** `feat/<issue#>-bedmage-services`
**Zależy od:** D23 merged.

- `apps/bedmages/types.py` — `BedmagePayload` TypedDict mirror M1 #6 pattern (chore: nawiasem ten sam pattern poszedł odroczony w M4 dla DeathPayload, w M5 robimy go od razu).
- `apps/bedmages/services.py`:
  - `add_bedmage_watch(user, character_name)` — auto-create Character, get_or_create watch, raise jeśli already active.
  - `remove_bedmage_watch(user, character_name) -> bool` — hard delete, idempotent.
  - `check_bedmage_watches_for_character(character)` — iteruje aktywne watche, sprawdza delta + idempotency, wywołuje handler, set's `last_notified_login`.
- `BEDMAGE_REGEN_MINUTES = env.int("BEDMAGE_REGEN_MINUTES", default=100)` w `config/settings/base.py` + `.env.example`.
- Unit testy services (5-6 testów: happy path add, duplicate add raise, remove existing, remove non-existing idempotent, check fires handler when delta>=100, check skips when last_notified_login matches).
- Smoke: ręczne `add_bedmage_watch` w shell, weryfikacja DB.

### D25 — Notifications abstraction + LoggingHandler + settings switch

**Czas:** 2h
**Branch:** `feat/<issue#>-bedmage-notifications-handler`
**Zależy od:** D24 merged.

- `apps/notifications/` package: `__init__.py` (z `get_bedmage_handler()`), `handlers.py` (Protocol + LoggingHandler), `apps.py`.
- Settings: `BEDMAGE_NOTIFICATION_HANDLER = env("BEDMAGE_NOTIFICATION_HANDLER", default="apps.notifications.handlers.LoggingHandler")` w `base.py` + `.env.example`.
- D24 service `check_bedmage_watches_for_character` integruje przez `get_bedmage_handler()` zamiast direct `logger.info`.
- Unit testy: handler dispatch przez `get_bedmage_handler()` resolves correct class, `LoggingHandler.notify(watch)` emits expected log line.
- `apps.notifications` zarejestrowane w `LOCAL_APPS`.

### D26 — Integration tracker w `scrape_watched_characters` task

**Czas:** 2-3h
**Branch:** `feat/<issue#>-tracker-scrape-integration`
**Zależy od:** D25 merged.

- Modyfikacja `apps/characters/tasks.py:scrape_watched_characters`:
  ```python
  if result.returncode == 0:
      scraped += 1
      character = Character.objects.get(name=name)
      from apps.bedmages.services import check_bedmage_watches_for_character
      try:
          check_bedmage_watches_for_character(character)
      except Exception:
          logger.exception("bedmage check failed for %s", name)
          # Don't propagate — scrape itself succeeded, tracker error shouldn't bump `failed`
  ```
- Lazy import (bedmages → characters → bedmages cycle prevention).
- Defensive try/except (tracker bug nie powinien wpływać na scrape success metrics).
- Unit test extending M3-D17 `test_celery_e2e.py` — mock tracker, verify it gets called per scraped character.
- Smoke: ręcznie addBedmageWatch + force scrape, weryfikacja log entry z `LoggingHandler`.

### D27 — GraphQL: `myBedmages` query + `addBedmageWatch` + `removeBedmageWatch` mutations + e2e + M5 closure

**Czas:** 4h (longest task, 2 PR-y jak M4-D22)
**Branch:** `feat/<issue#>-bedmages-graphql` + osobny `docs/close-m5-tracker`
**Zależy od:** D26 merged.

- `apps/bedmages/schema.py`:
  - `BedmageWatchType` (`@strawberry_django.type(BedmageWatch)`, fields: `id`, `created_at`, `last_notified_login`, `active`, plus nested `character: CharacterType` via FK).
  - Query `my_bedmages` — JWT-protected, filter by `request.user`.
  - Mutation `add_bedmage_watch(character_name: str) -> BedmageWatchType` — JWT, calls service.
  - Mutation `remove_bedmage_watch(character_name: str) -> bool` — JWT, idempotent.
- `config/schema.py` rozszerzone o `Mutation` type (first time w projekcie):
  ```python
  from apps.bedmages.schema import Mutation as BedmageMutation, Query as BedmageQuery

  Query = merge_types("Query", (AccountsQuery, CharactersQuery, DeathsQuery, BedmageQuery))
  Mutation = merge_types("Mutation", (BedmageMutation,))
  schema = strawberry.Schema(query=Query, mutation=Mutation)
  ```
- 6-8 unit testów GraphQL: my_bedmages auth+filter, add success, add duplicate raise, remove existing, remove non-existing idempotent, mutation auth required, nested character resolution.
- E2E integration test `tests/integration/test_m5_bedmages_e2e.py` — full flow: addBedmageWatch (mocks Character.last_login set in past >100min) → manual call to `check_bedmage_watches_for_character` → assert handler called with expected watch.
- PROGRESS.md sekcja `## 🎉 Milestone M5 — Bedmage tracker (backend) COMPLETED (YYYY-MM-DD)` (osobny `docs/close-m5-tracker` PR).
- DoD M5 spełnione, milestone closed via `gh api -X PATCH ...milestones/<id> -f state=closed`.

---

## 6. Integration points

### 6.1 M3 `scrape_watched_characters` task
- D26 dorzuca `check_bedmage_watches_for_character(character)` po success'ie scrape.
- Lazy import + defensive try/except dla isolation.

### 6.2 M2 GraphQL schema
- D27 dorzuca `BedmageQuery` do `merge_types("Query", ...)`.
- D27 wprowadza `Mutation` type **pierwszy raz** w projekcie — dotąd tylko Query. Strawberry schema z `mutation=Mutation` parameter.
- JWT auth pattern z M2-D12 + M4-D22 reused (dispatch z `JWTAsyncGraphQLView`).

### 6.3 M4 carry-over tech debt rozważyć
- `DeathPayload` extract do `apps/deaths/types.py` (soft blocker z M4-D20 review). M5 robi to dla `BedmagePayload` od razu (good pattern), opcjonalnie chore w D24 razem dla DeathPayload.
- `celery-types` package (carry-over z M3) — jeśli D26 task modification wprowadzi mypy issues z `@shared_task`, dorzucić jako M5 chore.

### 6.4 Future M6 (Discord bot)
- M6 doda `DiscordHandler` w `apps/notifications/handlers.py` — implementuje `BedmageNotificationHandler` Protocol.
- M6 ustawia `BEDMAGE_NOTIFICATION_HANDLER=apps.notifications.handlers.DiscordHandler` w prod `.env`.
- M6 dorzuca slash commands `/bedmage add|remove|list` jako wrapper na M5 GraphQL mutations.

---

## 7. Test plan

**Unit testy:**
- D23 model: 2-3 testy (default values, unique constraint enforcement, str repr).
- D24 services: 5-6 testów (add happy/duplicate/character-doesn't-exist-yet, remove existing/non-existing, check happy/below-threshold/already-notified).
- D25 notifications: 2-3 testy (handler resolution by setting, LoggingHandler emits log).
- D26 task integration: 1-2 testy w `test_celery_e2e.py` extension (mock tracker, assert called once per scraped char).
- D27 GraphQL: 6-8 testów (my_bedmages auth+filter, add success/duplicate, remove existing/non-existing, mutation auth, nested character).

**Integration / e2e:**
- D27 `test_m5_bedmages_e2e.py` — full flow add → mock scrape sets last_login → manual check → handler called.

**Coverage cel:** `apps/bedmages/*.py` 100%, `apps/notifications/*.py` 100%, cumulative ≥ 95% (mirror M4 cel).

**Smoke manual:**
- D23: `migrate bedmages` clean, admin shows BedmageWatch.
- D24: `add_bedmage_watch(user, "TestChar")` w shell, weryfikacja DB.
- D25: `get_bedmage_handler()` resolves LoggingHandler, manual `.notify(watch)` emituje log.
- D26: `addBedmageWatch` + force `scrape_watched_characters.delay()` → log entry z `LoggingHandler`.
- D27: GraphiQL `/graphql/`: addBedmageWatch mutation + myBedmages query z JWT.

---

## 8. Definition of Done (M5)

- [ ] **5 PR merged, 5 Issues zamknięte** (D23-D27).
- [ ] **`apps.bedmages` + `apps.notifications` zarejestrowane w `INSTALLED_APPS`**, migracje aplikują się czysto.
- [ ] **`BedmageWatch` widoczne w Django admin** z list_display + filter + search.
- [ ] **`add_bedmage_watch` + `remove_bedmage_watch` + `check_bedmage_watches_for_character` działają w shell** (manual smoke).
- [ ] **Settings `BEDMAGE_REGEN_MINUTES` + `BEDMAGE_NOTIFICATION_HANDLER`** dostępne, default values działają.
- [ ] **Integration z `scrape_watched_characters`** — manual smoke pokazuje `LoggingHandler.notify` log entry po scrape postaci która ma BedmageWatch.
- [ ] **GraphQL `myBedmages` query bez JWT** → error response (mirror M4-D22 auth pattern).
- [ ] **GraphQL `addBedmageWatch` + `removeBedmageWatch` mutations** działają z JWT, error gdy bez auth.
- [ ] **Wszystkie pre-commit + CI zielone** dla każdego PR-a.
- [ ] **`coverage threshold = 70` zachowane**, lokalnie 100% dla `apps/bedmages/*.py` i `apps/notifications/*.py`.
- [ ] **PROGRESS.md** rozszerzony o sekcję M5 z retro per Issue.
- [ ] **Milestone M5 zamknięty** na GitHub.

---

## 9. Open questions / future

**Otwarte (nie blokujące M5, do decyzji w M6+):**
- **Per-watch custom interval** — `BedmageWatch.regen_minutes: PositiveIntegerField(null=True)` field z fallback do `settings.BEDMAGE_REGEN_MINUTES`. Useful gdy gracz ma postać z różnym regen rate (vocation differences, mage spell). M-future.
- **Bedmage statistics** — query `myBedmageStats` zwraca `{watches_active: 5, total_notifications_sent: 47}`. M6+ z Discord bot w play.
- **Watchdog "character no longer being scraped" alarm** — jeśli `Character.last_scraped_at < now - 1h`, BedmageWatch może być "uśpiony" (postać deleted, banned, etc). M6+ razem z notification infra.
- **Rate limit `addBedmageWatch`** — user może spam'ować mutations. M5 nie limit'uje, M-future doda `django-ratelimit` jeśli abuse się pojawi.
- **Bedmage history** — log każdej notyfikacji (`BedmageNotification` model: `watch`, `notified_at`, `delta_minutes`). Useful dla debug + statistics. M-future.
- **Discord channel routing dla M6** — czy notyfikacja idzie na DM user'a, czy na konkretny channel jaki user wybrał? Decyzja w M6.

**Z M5 pre-flight do potwierdzenia w D23:**
- Nazwa katalogu `apps/notifications/` — singular vs plural? Convention w repo: `apps/characters/` (plural), `apps/accounts/` (plural), `apps/deaths/` (plural). Plural OK.
- `BedmagesConfig.label = "bedmages"` lub `"bedmage"`? Konwencja: `characters` (plural), `accounts` (plural), `deaths` (plural). Plural.
- `apps.notifications.apps.NotificationsConfig` z `label = "notifications"`.

---

## 10. Decision points dla user'a (review request)

Przed start'em D23, **prosi review następujących decyzji** (Sekcja 4):

1. **§4.1 Auto-create Character w `addBedmageWatch`** — propozycja: TAK (lazy fetch). OK?
2. **§4.2 Hard vs soft delete dla `removeBedmageWatch`** — propozycja: HARD. OK?
3. **§4.3 Notification handler abstraction w M5** — propozycja: TAK (`apps/notifications/` package). OK?
4. **§4.4 Tracker fire trigger** — propozycja: w `scrape_watched_characters` post-success. OK?
5. **§4.5 Tracker scope** — propozycja: scrape wszystkich Characters, filter dopiero w trackerze. OK?
6. **§4.6 GraphQL mutations error handling** — propozycja: raise dla add-duplicate, idempotent dla remove. OK?
7. **§4.7 FK on_delete dla `BedmageWatch.character` + `BedmageWatch.user`** — propozycja: CASCADE oba. OK?

Plus open questions z §9 — czy któreś chcesz przesunąć do M5 (rozszerzenie scope) zamiast M-future?
