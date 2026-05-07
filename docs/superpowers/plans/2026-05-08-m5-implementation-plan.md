# M5 — Bedmage tracker (backend) — Implementation plan

**Data:** 2026-05-08
**Spec:** [`docs/superpowers/specs/2026-05-08-m5-bedmage-tracker-design.md`](../specs/2026-05-08-m5-bedmage-tracker-design.md)
**Status:** READY (spec accepted, decyzje 4.1-4.7 zaakceptowane przez developera 2026-05-08).

---

## Źródła

- **CLAUDE.md** §1 (cel biznesowy: Bedmage tracker), §3 (struktura `apps/bedmages/`), §5 (model `BedmageWatch` szkic), §7 (Bedmage tracker logic — 100 min delta + idempotency), §9 (GraphQL `myBedmages` query, `addBedmageWatch` + `removeBedmageWatch` mutations), §10 (settings).
- **Design spec M5** — kluczowy dokument referencyjny. Każdy issue body linkuje do spec'a §X dla konkretnej sekcji.
- **Precedensy M2/M3/M4:**
  - M2-D9 `apps/accounts/` — app structure + custom User model + admin (mirror dla D23 BedmageWatch admin).
  - M2-D11 `apps/accounts/schema.py` — Strawberry schema + `info.context.request.user.is_authenticated` auth pattern (mirror dla D27 GraphQL).
  - M2-D12 JWT auth dispatch w `/graphql/` — auth pattern reused dla D27 mutations + queries.
  - M3-D16 `scrape_watched_characters` task — D26 modification point (post-success hook).
  - M4-D18 `apps/deaths/` model + admin — exact mirror dla D23 (apps.py + models.py + admin.py + migration).
  - M4-D20 `apps/deaths/services.py` — service pattern (transaction.atomic, IntegrityError handling) — mirror dla D24.
  - M4-D22 `apps/deaths/schema.py` — `@strawberry_django.type` + auth guard + clamping pattern. D27 dorzuca **mutations** czego M4 nie miało.

---

## Pre-flight checklist (przed startem D23)

- [ ] **`apps/bedmages/` nie istnieje** — sprawdzone 2026-05-08, fresh creation.
- [ ] **`apps/notifications/` nie istnieje** — sprawdzone 2026-05-08, fresh creation.
- [ ] **`Character.last_login: DateTimeField(null=True, blank=True, db_index=True)`** — istnieje od M1, indexed. Tracker query'uje przez ten atrybut.
- [ ] **`User` model ma `discord_id` field** — istnieje od M2-D9 (jeszcze niewykorzystywany, M6 użyje).
- [ ] **`scrape_watched_characters` post-success hook** — D26 dorzuca `check_bedmage_watches_for_character(char)` wywołanie po `result.returncode == 0`. M3-D16 task obecnie nie ma hook'a, ale punkt insercji jest jasny (linia ~58 w `apps/characters/tasks.py`).
- [ ] **`AUTH_USER_MODEL = "accounts.User"`** — w `config/settings/base.py:134`. `BedmageWatch.user` FK używa `settings.AUTH_USER_MODEL`, nie hard-coded import (Django convention).
- [ ] **`Mutation` GraphQL type pierwszy raz w projekcie** — D27 wprowadza, sprawdź `config/schema.py` przed D27 dla integracji `merge_types("Mutation", ...)`.
- [ ] **Stubs.py single source of truth** (chore PR #92, 2026-05-08) — nowe `LOCAL_APPS` entries dla `apps.bedmages` + `apps.notifications` + nowe settings (`BEDMAGE_REGEN_MINUTES`, `BEDMAGE_NOTIFICATION_HANDLER`) widoczne dla mypy automatycznie. Zero `stubs.py` edycji w M5.
- [ ] **`celery-types` package** (carry-over z M3 tech debt) — D26 modyfikuje task istniejący, NIE dorzuca `@shared_task`. Najpewniej nie uderzy w M5. Jeśli uderzy → side chore PR.
- [ ] **`DeathPayload` extract** (carry-over z M4 tech debt) — opcjonalny side cleanup w D24 razem z `BedmagePayload` w `apps/bedmages/types.py`. Decyzja per-task w D24.

---

## Otwarte pytania do developera (rozstrzygnięte 2026-05-08, spec §4)

Wszystkie 7 decyzji designowych ze spec'a §4 zaakceptowane bez modyfikacji:

1. ✅ **§4.1** Auto-create Character w `addBedmageWatch` — TAK (lazy fetch).
2. ✅ **§4.2** Hard delete dla `removeBedmageWatch` (idempotent), nie soft.
3. ✅ **§4.3** Notification handler abstraction `apps/notifications/` — TAK, Protocol-based.
4. ✅ **§4.4** Tracker fire trigger w `scrape_watched_characters` post-success.
5. ✅ **§4.5** Tracker scope — wszystkie Characters scrape'owane (M3 zachowanie), filter w trackerze.
6. ✅ **§4.6** GraphQL mutations error handling — `raise` dla add-duplicate, idempotent (return False) dla remove non-existing, `raise` dla auth fail.
7. ✅ **§4.7** FK `on_delete=CASCADE` dla `user` i `character`.

**Open questions z §9** (do M-future, NIE w M5 scope):
- Per-watch custom interval (`BedmageWatch.regen_minutes`).
- Bedmage statistics query.
- Watchdog "character no longer being scraped" alarm.
- Rate limit dla mutations.
- Bedmage notification history model.
- Discord channel routing dla M6.

---

## Risk + mitigation

| Ryzyko | Prawdopodobieństwo | Impact | Mitigation |
|---|---|---|---|
| **Circular import** `apps.bedmages.services ↔ apps.characters.tasks` | Średnie | Worker crash przy starcie | Lazy import w D26: `from apps.bedmages.services import check_bedmage_watches_for_character` **wewnątrz** `scrape_watched_characters`, nie na top of `tasks.py`. |
| **Strawberry mutation context** różni się od query context | Niskie | Auth dispatch może nie działać w mutation | M2-D12 dispatch jest type-agnostic (operuje na `request`, nie operation type). Ale **świadomy smoke** w D27 mutation z JWT przed unit testami. |
| **Race: `addBedmageWatch` + `scrape_watched_characters` symultanicznie** | Niskie | Watch utworzony, ale Character w trakcie scrape — `last_login` może być stale | Idempotency przez `last_notified_login` chroni. Tracker wywołany później (Beat next fire) wykrywa fresh `last_login`. |
| **Handler resolution failure** (`BEDMAGE_NOTIFICATION_HANDLER` invalid path) | Niskie | Tracker rzuca exception per scraped character | D26 ma `try/except Exception` wrapper z `logger.exception` — błąd logowany, scrape success metrics nie dotknięte. |
| **`auto_now_add=True` na `created_at`** w testach | Średnie | Test'y kontrolujące `created_at` muszą używać `update()` workaround | M3-D17 retro #5 lekcja zachowana — `BedmageWatch.objects.filter(pk=...).update(created_at=...)`. Wzmianka w D24/D27 issue bodies. |
| **Auto-create Character race** w `addBedmageWatch` | Niskie | Dwa równoczesne `add` dla tego samego user+character może spowodować IntegrityError na `unique_together` | `Character.objects.get_or_create` jest race-safe. `BedmageWatch.objects.get_or_create` także. M1-D8 race retry pattern niepotrzebny tutaj. |

---

## Task overview

| # | ID | Tytuł | Czas | Zależy od | Branch |
|---|---|---|---|---|---|
| 1 | M5-D23 | `apps/bedmages/` + `BedmageWatch` model + admin + migration | 2-3h | M4 closed + chore #92 merged | `feat/<#>-bedmages-app-model` |
| 2 | M5-D24 | Services (add/remove/check) + `BedmagePayload` types | 3h | D23 merged | `feat/<#>-bedmage-services` |
| 3 | M5-D25 | `apps/notifications/` package + `LoggingHandler` + settings switch | 2h | D24 merged | `feat/<#>-bedmage-notifications-handler` |
| 4 | M5-D26 | Tracker integration w `scrape_watched_characters` | 2-3h | D25 merged | `feat/<#>-tracker-scrape-integration` |
| 5 | M5-D27 | GraphQL `myBedmages` query + mutations + e2e + closure | 4h | D26 merged | `feat/<#>-bedmages-graphql` + `docs/close-m5-tracker` |

**Total:** ~13-15h, 5 dni roboczych z bufor'em (mirror M3/M4 budgetu, M3 = 2 dni real, M4 = 3 dni real, M5 też powinno być 2-3 dni real time).

---

## Task #1 — [M5-D23] `apps/bedmages/` + `BedmageWatch` model + admin + migration

### 🎯 Cel

Aplikacja `apps/bedmages/` zarejestrowana w Django, model `BedmageWatch` w bazie, widoczny w admin pod `/admin/bedmages/bedmagewatch/`. Migracja initial przechodzi czysto na świeżej bazie.

### 🧠 Czego się nauczysz

- **`settings.AUTH_USER_MODEL` w FK** zamiast direct `User` import — Django convention dla custom User. Bez tego runtime crashes gdy AUTH_USER_MODEL jest swapped (M2-D9 lekcja).
- **`UniqueConstraint(name=...)` w `Meta.constraints`** zamiast deprecated `unique_together` tuple — Django 4+ idiom (M4-D18 precedens dla DeathEvent).
- **`related_name="bedmage_watches"`** na FK — daje reverse access `user.bedmage_watches.all()`. Bez tego default `bedmagewatch_set` jest mniej czytelny.
- **`on_delete=CASCADE` semantics** — gdy User lub Character zostanie usunięty, BedmageWatch idzie razem. Inne opcje (PROTECT, SET_NULL) nie pasują dla M5 use case (decyzje §4.7).

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m5-d23.md`.)

**Kluczowe punkty:**
- `apps/bedmages/__init__.py`, `apps.py` (`BedmagesConfig`, label="bedmages"), `models.py`, `admin.py`, `migrations/__init__.py`.
- `LOCAL_APPS` w `base.py` rozszerzone o `"apps.bedmages"`.
- `BedmageWatch` model z 5 polami + `Meta.constraints` UniqueConstraint + `Meta.ordering` + `__str__`.
- Migration `0001_initial.py`.
- Admin `BedmageWatchAdmin` z `list_display`, `list_filter`, `search_fields`.
- Sanity: `migrate bedmages --plan`, `migrate bedmages`, `BedmageWatch.objects.create(...)` w shell.

### 📋 Sugerowane kroki

1. `git checkout -b feat/<#>-bedmages-app-model` od master.
2. `mkdir apps/bedmages apps/bedmages/migrations`, dotknij `__init__.py` w obu.
3. `apps.py` (mirror `apps/deaths/apps.py` z M4-D18).
4. `models.py` — exactly per spec §5/D23.
5. `LOCAL_APPS` extend w `base.py`.
6. `python manage.py makemigrations bedmages` — sprawdź że tworzy `0001_initial.py` z FK do `accounts.User` i `characters.Character`.
7. `admin.py` z `@admin.register(BedmageWatch)` decorator.
8. Smoke: `migrate`, admin manually create, `__str__` returns "user watching character".
9. Pre-commit + commit + push + PR.

### ⚠️ Pułapki do uwagi

- **A — `settings.AUTH_USER_MODEL` jako string, nie import:** `models.ForeignKey(settings.AUTH_USER_MODEL, ...)`. Direct `from apps.accounts.models import User` powoduje circular import jeśli accounts kiedyś zaimportuje bedmages.
- **B — `auto_now_add` w testach:** dla `created_at` field, gdy chcesz force timestamp w przeszłość → `BedmageWatch.objects.filter(pk=...).update(created_at=...)` (M3-D17 retro #5).
- **C — FK `to="characters.Character"`** jako string lub `to=Character` z import. String form jest lazy (rozwiązuje circular). Mirror M4-D18 used direct import bo wtedy Character był w innym app graph. W bedmages preferuj string — bezpieczniej.
- **D — `# type: ignore[type-arg]` na admin** — mirror `apps/characters/admin.py:6` i `apps/deaths/admin.py` (M4 tech debt: ModelAdmin generic subscript wymaga `django_stubs_ext.monkeypatch()`, jeszcze nie wdrożone).

### 🧪 Testing plan

Unit testy `tests/unit/bedmages/test_bedmage_watch_model.py`:
- `test_create_with_required_fields_works` (happy path + default `active=True`).
- `test_unique_constraint_user_character_pair` — IntegrityError przy duplikacie.
- `test_str_repr_format` — sprawdzić format `"username watching character_name"`.

(Tests w D23 są opcjonalne — model minimalny, kluczowe testy logiki w D24. Decyzja per developer's preference, M4-D18 nie miało testów modelu.)

### 🔗 Dokumentacja pomocnicza

- Django `UniqueConstraint`: https://docs.djangoproject.com/en/6.0/ref/models/constraints/#uniqueconstraint
- `settings.AUTH_USER_MODEL`: https://docs.djangoproject.com/en/6.0/topics/auth/customizing/#referencing-the-user-model
- `related_name`: https://docs.djangoproject.com/en/6.0/ref/models/fields/#django.db.models.ForeignKey.related_name

### 📦 Definition of Done

- [ ] AC spełnione (apps/bedmages/, model, admin, migration, sanity).
- [ ] PR zmergowany squash (`feat(bedmages): add BedmageWatch model + admin + initial migration (M5-D23, #<#>)`).
- [ ] CI lint + test zielone.
- [ ] `apps/bedmages/migrations/0001_initial.py` w master.
- [ ] Issue zamknięty.

---

## Task #2 — [M5-D24] Services (`add_bedmage_watch`, `remove_bedmage_watch`, `check_bedmage_watches_for_character`) + types

### 🎯 Cel

Service'y biznesowe dla bedmage tracking — add/remove watch + per-character check po scrape. Bez integracji z task'iem (D26) ani notyfikacji (D25 dorzuca handler dispatch).

### 🧠 Czego się nauczysz

- **`Character.objects.get_or_create(name=...)`** dla auto-create lazy fetch (§4.1). Race-safe w Django ORM (M1-D8 retry pattern niepotrzebny — `unique=True` + retry w models manager handluje).
- **`timezone.now() - timedelta(minutes=N)`** dla delta comparison. UTC normalizacja przez `USE_TZ = True` (default w base.py).
- **Idempotency invariant `last_notified_login != character.last_login`** — kluczowy dla M5 tracker logic (CLAUDE.md §7). Pierwsze logowanie (last_notified_login=None, char.last_login=Y) → delta check fires. Drugie scrape (te same Y) → `Y != Y` is False → skip. Trzeci scrape po fresh login (Y2) → `Y != Y2` → fires again.
- **`select_related("user", "character")`** żeby uniknąć N+1 w `check_bedmage_watches_for_character` iteracji.
- **`BedmagePayload` TypedDict pattern** mirror `CharacterPayload` z M1 #6 — types osobno od services.

### ✅ Acceptance criteria

(Pełne AC w `.github/issue-bodies/m5-d24.md`.)

**Kluczowe:**
- `apps/bedmages/types.py` z `BedmagePayload` TypedDict.
- `apps/bedmages/services.py` z 3 funkcjami:
  - `add_bedmage_watch(user, character_name) -> BedmageWatch` (auto-create Character, raise jeśli active watch already exists).
  - `remove_bedmage_watch(user, character_name) -> bool` (hard delete, idempotent).
  - `check_bedmage_watches_for_character(character)` — iteruje aktywne watche, sprawdza delta, **placeholder dla handler dispatch** (D25 dorzuca real call, w D24 zostawiamy stub `# TODO: D25 handler.notify(watch)` lub minimalistyczny direct `logger.info`).
- `BEDMAGE_REGEN_MINUTES = env.int("BEDMAGE_REGEN_MINUTES", default=100)` w `base.py` + `.env.example`.
- 5-7 unit testów (services).
- Smoke: services w shell.

### ⚠️ Pułapki do uwagi

- **A — `Character.last_login` może być `None`** (postać nie scrape'owana yet) — `check_bedmage_watches_for_character` musi `if char.last_login is None: return` early.
- **B — `last_notified_login` set BEFORE handler.notify** vs **AFTER**: jeśli handler.notify rzuci exception, czy chcemy retry? Zalecenie: set `last_notified_login` AFTER successful notify, owinąć w try/except — jeśli notify fails, watch retry na next scrape (idempotency wciąż chroni przed dup'em w happy path). Decyzja w D25 razem z handler — w D24 stub'ujemy.
- **C — `add_bedmage_watch` re-activation case** (§4.1): jeśli watch istnieje ale `active=False`, set `active=True` + return. Spec mówi "raise jeśli already active", `active=False` to inny scenariusz. W M5 hard delete przez remove znaczy że `active=False` rzadko się pojawia. Ale dla bezpieczeństwa: re-activation logic.
- **D — `select_related` nie jest potrzebny** dla single-watch lookup w `add_bedmage_watch`/`remove_bedmage_watch`, ale **JEST** w `check_bedmage_watches_for_character` żeby uniknąć N+1.

### 🧪 Testing plan

Unit testy `tests/unit/bedmages/test_services.py`:
- `test_add_bedmage_watch_creates_character_if_missing`.
- `test_add_bedmage_watch_raises_on_duplicate_active`.
- `test_add_bedmage_watch_reactivates_inactive`.
- `test_remove_bedmage_watch_deletes_existing_returns_true`.
- `test_remove_bedmage_watch_idempotent_returns_false_when_not_found`.
- `test_check_skips_when_character_has_no_last_login`.
- `test_check_skips_when_delta_below_threshold`.
- `test_check_fires_when_delta_above_threshold_and_not_yet_notified`.
- `test_check_skips_when_already_notified_for_this_login`.

(D25 doda 1-2 testy dla handler dispatch wewnątrz check.)

### 📦 Definition of Done

- [ ] AC spełnione.
- [ ] PR zmergowany squash.
- [ ] `apps/bedmages/services.py` ~100% coverage.
- [ ] Issue zamknięty.

---

## Task #3 — [M5-D25] `apps/notifications/` package + `LoggingHandler` + settings switch

### 🎯 Cel

Notifications abstraction layer — Protocol interface + LoggingHandler default + settings switch dla future M6 DiscordHandler swap.

### 🧠 Czego się nauczysz

- **Python Protocol vs ABC** dla interface'ów — Protocol jest **structural typing** (duck), ABC wymusza explicit subclassing. Protocol bardziej Pythonic dla M6 swap (DiscordHandler z M6 nie musi inheritować z LoggingHandler — wystarczy że ma `notify(watch)` method).
- **`django.utils.module_loading.import_string`** dla dotted-path resolution z settings — Django convention dla pluggable backends (mirror `CACHES['default']['BACKEND']`).
- **Lazy handler resolution** — `get_bedmage_handler()` może być cached przez `functools.lru_cache(maxsize=1)` lub re-resolved każdym call'em. Trade-off: cache = szybciej, ale `@override_settings(BEDMAGE_NOTIFICATION_HANDLER=...)` w testach nie podmieni handler'a (cache'ed). Zalecenie M5: bez cache (per-call resolution), prosta i test-friendly.

### ✅ Acceptance criteria

**Kluczowe:**
- `apps/notifications/` package: `__init__.py` (z `get_bedmage_handler()`), `apps.py` (`NotificationsConfig`), `handlers.py` (Protocol + LoggingHandler).
- `BEDMAGE_NOTIFICATION_HANDLER = env("BEDMAGE_NOTIFICATION_HANDLER", default="apps.notifications.handlers.LoggingHandler")` w `base.py` + `.env.example`.
- `LOCAL_APPS` w `base.py` rozszerzone o `"apps.notifications"`.
- `apps/bedmages/services.py:check_bedmage_watches_for_character` zintegrowane z `get_bedmage_handler().notify(watch)` (zamienia stub z D24).
- Unit testy: handler resolution, LoggingHandler emits expected log line.

### ⚠️ Pułapki do uwagi

- **A — Protocol w runtime check** — `isinstance(obj, BedmageNotificationHandler)` wymaga `@runtime_checkable` decorator na Protocol. M5 nie potrzebuje runtime check (tylko type), więc decorator zbędny.
- **B — Settings testing** — `@override_settings(BEDMAGE_NOTIFICATION_HANDLER="...")` w testach + per-call resolution = działa. Cache (`lru_cache`) by zepsuł.
- **C — Circular: `apps.notifications` importuje `BedmageWatch` for type hint?** — Protocol method signature `notify(self, watch: "BedmageWatch") -> None` używa string forward reference + `if TYPE_CHECKING: from apps.bedmages.models import BedmageWatch` block. Eliminuje circular.

### 📦 Definition of Done

- [ ] AC spełnione.
- [ ] PR zmergowany squash.
- [ ] `apps/notifications/*.py` 100% coverage.
- [ ] Issue zamknięty.

---

## Task #4 — [M5-D26] Tracker integration w `scrape_watched_characters`

### 🎯 Cel

Po każdym successful character scrape w `scrape_watched_characters` task, fire `check_bedmage_watches_for_character(char)`. Bezpieczne against tracker exceptions (defensive wrap).

### 🧠 Czego się nauczysz

- **Lazy import w funkcji** zamiast top-of-module — pattern dla unikania circular imports gdy A→B→A graph istnieje. M3-D16 task już używał lazy import dla characters/spider — kontynuacja patternu.
- **`logger.exception(...)`** vs `logger.error(...)` — `exception` automatycznie dorzuca traceback do log entry (Python logging idiom dla try/except tutaj).
- **Defensive isolation** — tracker bug nie powinien wpływać na scrape success metrics. Try/except wrap z `logger.exception`, nie re-raise.

### ✅ Acceptance criteria

- Modyfikacja `apps/characters/tasks.py:scrape_watched_characters`:
  ```python
  if result.returncode == 0:
      scraped += 1
      character = Character.objects.get(name=name)
      try:
          from apps.bedmages.services import check_bedmage_watches_for_character
          check_bedmage_watches_for_character(character)
      except Exception:
          logger.exception("bedmage check failed for %s", name)
  ```
- Unit test extending `tests/integration/test_celery_e2e.py` — mock tracker, verify called per scraped character.
- Smoke: ręczne `addBedmageWatch` (przez D24 service) + force `scrape_watched_characters.delay()` na character z fresh `last_login` → log entry z `LoggingHandler`.

### ⚠️ Pułapki do uwagi

- **A — `Character.objects.get(name=name)` po `result.returncode == 0`** — postać MUSI istnieć w DB (pętla iteruje po `Character.objects.values_list`), więc `DoesNotExist` nie powinien się zdarzyć. Ale defensive `try/except` na ten case też (deletion race).
- **B — Lazy import w pętli vs przed pętlą** — pierwszy import jest wolny (~50ms), kolejne są cached. Dla 50 characters wolisz import RAZ przed pętlą (pewny optimization), ale dla circular safety musi być wewnątrz funkcji. Sugerowane: import wewnątrz `try` block (eager przy pierwszym fire, cached na resztę).
- **C — `mock.patch` lazy importów** — `mock.patch("apps.bedmages.services.check_bedmage_watches_for_character")` nie patchuje gdy import jest lazy (patches namespace na poziomie module, lazy import czyta świeżą referencję). Workaround: `mock.patch("apps.characters.tasks.check_bedmage_watches_for_character")` po lazy import — ale wtedy import musi być na top of `tasks.py` (sprzeczne z circular safety). Compromise: rozważ czy unit test mockuje na poziomie services (`mock.patch("apps.bedmages.services.get_bedmage_handler")`) zamiast tracker function. Decyzja w D26.

### 📦 Definition of Done

- [ ] AC spełnione.
- [ ] PR zmergowany squash.
- [ ] `tests/integration/test_celery_e2e.py` extension covers tracker integration.
- [ ] Issue zamknięty.

---

## Task #5 — [M5-D27] GraphQL `myBedmages` + `addBedmageWatch` + `removeBedmageWatch` + e2e + M5 closure

### 🎯 Cel

GraphQL surface dla bedmage management — query (lista user'a) + 2 mutations (add/remove). E2E integration test pokrywa pełny flow: addBedmageWatch → mock scrape → tracker fires → handler called. M5 zamyka się z PROGRESS.md retro + milestone closed.

### 🧠 Czego się nauczysz

- **Strawberry mutation pattern:** `@strawberry.mutation` decorator (lub `@strawberry.field` w `Mutation` class). Mutations w Strawberry to też zwykłe async resolvers — kontekst dispatch identyczny jak query.
- **`merge_types("Mutation", (...))` first time** — analogicznie do `merge_types("Query", ...)` z M2/M4. `config/schema.py` rozszerza się o:
  ```python
  schema = strawberry.Schema(query=Query, mutation=Mutation)
  ```
- **Nested type resolution** — `BedmageWatchType.character` zwraca `CharacterType` z `apps.characters.schema`. Strawberry-Django auto-resolves przez FK.
- **`auto_now_add` w testach (powtórka z M3-D17 retro #5):** test'y kontrolujące `created_at` muszą używać `update()` workaround.

### ✅ Acceptance criteria

(Pełne AC w `.github/issue-bodies/m5-d27.md`.)

**Kluczowe:**
- `apps/bedmages/schema.py` z `BedmageWatchType` + `Query.my_bedmages` + `Mutation.add_bedmage_watch` + `Mutation.remove_bedmage_watch`.
- `config/schema.py` rozszerzone o `Mutation` merge + `mutation=Mutation` parameter.
- 6-8 unit testów GraphQL (mirror M4-D22 patternu).
- E2E test `tests/integration/test_m5_bedmages_e2e.py` (full flow).
- PROGRESS.md sekcja `🎉 Milestone M5 — Bedmage tracker (backend) COMPLETED (YYYY-MM-DD)` w osobnym `docs/close-m5-tracker` PR.
- Milestone closed via `gh api -X PATCH .../milestones/<#> -f state=closed`.

### ⚠️ Pułapki do uwagi

- **A — Mutation auth pattern** — `info.context.request.user.is_authenticated` (mirror M4-D22). Mutations bez JWT → `raise Exception("Authentication required")`. Strawberry serializes jako `errors[]`.
- **B — Nested `character: CharacterType` resolution** — Strawberry-Django auto-resolves FK relacje, ale **async ORM** wymaga explicit handling. Sprawdź czy `await watch.character` musi być explicit lub czy auto-prefetch działa. Test najlepszy w D27.
- **C — `merge_types("Mutation", (BedmageMutation,))` z 1 source** — `merge_types` wymaga tuple, jeden element to `(BedmageMutation,)` (z trailing comma). Bez przecinka Python parsuje `(BedmageMutation)` jako redundant parens, nie tuple.
- **D — `strawberry.Schema(query=Query, mutation=Mutation)`** — bez `mutation=` parameter, mutations nie są dostępne w GraphQL endpoint. Easy miss.
- **E — `add_bedmage_watch` test z `Character.objects.get_or_create`** — test w D27 może zakładać że Character istnieje, lub testować lazy fetch. Decyzja: testuj **oba** scenariusze (fresh + existing) żeby mieć pewność że auto-create działa.

### 🧪 Testing plan

Unit testy GraphQL `tests/unit/bedmages/test_graphql_bedmages.py`:
- `test_my_bedmages_filters_by_request_user`.
- `test_my_bedmages_requires_authentication`.
- `test_add_bedmage_watch_creates_with_existing_character`.
- `test_add_bedmage_watch_creates_character_lazily`.
- `test_add_bedmage_watch_raises_on_duplicate`.
- `test_add_bedmage_watch_requires_authentication`.
- `test_remove_bedmage_watch_returns_true_when_existing`.
- `test_remove_bedmage_watch_returns_false_when_not_found`.

E2E `tests/integration/test_m5_bedmages_e2e.py`:
- `test_e2e_add_then_scrape_then_handler_fires` — full flow z mock subprocess + manual handler verification.

### 📦 Definition of Done

- [ ] AC spełnione (Schema, Merge, Unit testy 6-8, E2E test, PROGRESS.md, Smoke manual).
- [ ] **Feature PR** zmergowany squash (`feat(bedmages): GraphQL queries + mutations + e2e (M5-D27, #<#>)`).
- [ ] **Closure PR** zmergowany squash (`docs(progress): close M5 — Bedmage tracker backend COMPLETED`).
- [ ] CI lint + test zielone na obu PR-ach.
- [ ] `apps/bedmages/*.py` cumulative coverage ≥ 95%.
- [ ] Issue zamknięty (oba — feature i closure).
- [ ] Milestone M5 zamknięty na GitHub.

---

## Spec section refs

| Spec section | Realizowane przez |
|---|---|
| §2 Scope w/poza | All tasks |
| §3 Architektura — flow diagram | D24 + D25 + D26 (full chain) |
| §4.1 Auto-create Character | D24 service `add_bedmage_watch` |
| §4.2 Hard delete | D24 service `remove_bedmage_watch` |
| §4.3 Notification handler abstraction | D25 |
| §4.4 Tracker fire trigger | D26 |
| §4.5 Tracker scope | D24 (filter logic) + D26 (integration) |
| §4.6 GraphQL mutations error handling | D27 |
| §4.7 FK on_delete | D23 |
| §5 Daily tasks split | This document |
| §6.1 M3 task integration | D26 |
| §6.2 M2 GraphQL integration + first Mutation | D27 |
| §7 Test plan | All tasks |
| §8 DoD M5 | M5 closure (D27 closure PR) |
| §9 Open questions | M-future, NIE w M5 |
