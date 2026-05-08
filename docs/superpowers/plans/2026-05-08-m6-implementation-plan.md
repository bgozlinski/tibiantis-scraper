# M6 — Mongo logging — Implementation plan

**Data:** 2026-05-08
**Spec:** [`docs/superpowers/specs/2026-05-08-m6-mongo-logging-design.md`](../specs/2026-05-08-m6-mongo-logging-design.md)
**Status:** READY (spec accepted, decyzje §3.1-3.6 zaakceptowane przez developera 2026-05-08).

---

## Źródła

- **CLAUDE.md** §3 (struktura `logs_backend/` planowana), §4 (Mongo dwie kolekcje: `app_logs` + `scrape_logs`, **bez** Djongo/MongoEngine), §10 (`MONGO_URL`, `MONGO_DB` env vars), §13.1 (CI mongo:7 service).
- **Design spec M6** — kluczowy dokument referencyjny. Każdy issue body linkuje do spec'a §X.
- **Precedensy z M0-M5:**
  - M3-D17 retro #5 — `auto_now_add` workaround (`update()` bypass). Niepotrzebne dla M6 (Mongo schemaless), ale wzorzec znany.
  - M4-D19/D20 — Scrapy spider/pipeline + `crawler.stats` API. D29 buduje na tym (signals zamiast pipeline'u, ale same `crawler` interface).
  - M4-D22 — async/sync boundary w Strawberry resolvers (`sync_to_async`). Niepotrzebne dla M6 (logging emit jest sync, NIE async resolver), ale wzorzec dyscypliny "boundary conversion".
  - M5-D25 — pierwszy package `apps/notifications/` jako Protocol-based abstraction. M6 robi analogiczny `logs_backend/` ale **NIE Django app** (top-level package, nie `apps/`).

---

## Pre-flight checklist (przed startem D28)

- [ ] **`logs_backend/` nie istnieje** — sprawdzone 2026-05-08, fresh creation.
- [ ] **`scrapers/tibiantis_scrapers/extensions.py` nie istnieje** — sprawdzone 2026-05-08, fresh creation.
- [ ] **`MONGO_URL` + `MONGO_DB` env vars w `.env.example`** — istnieją od M0 (CLAUDE.md §10), aktualnie nieużywane przez kod (placeholder do M6).
- [ ] **CI ma `mongo:7` service** — `ci.yml` ma `mongo` service container, ports 27017:27017, env `MONGO_URL=mongodb://localhost:27017` + `MONGO_DB=tibiantis_logs_test` (CLAUDE.md §13.1). Smoke confirmed: M5 testy nie używają Mongo, ale service jest already up — D28 unit testy mogą polegać na nim od pierwszego strzału.
- [ ] **`pymongo` w `pyproject.toml`** — sprawdź przed D28. Jeśli brak — `poetry add pymongo` w D28 (osobny commit `build(deps): add pymongo`).
- [ ] **Django LOGGING dict aktualnie nie skonfigurowany** — sprawdzone 2026-05-08, `config/settings/base.py` nie ma `LOGGING = {...}`. D28 dorzuca cały blok.
- [ ] **`scrapers/tibiantis_scrapers/settings.py` aktualnie nie ma `EXTENSIONS = {...}`** — sprawdzone 2026-05-08, fresh addition w D29.
- [ ] **PROCESS gotcha: pre-commit `no-commit-to-branch` hook** (PR #105, merged 2026-05-08) — blokuje commits na master. **Każdy D-task wymaga `git checkout -b feat/<#>-...` PRZED kodowaniem**, inaczej hook zabije commit. Zaakceptowane carry-over z M5 (D26+D27 incidenty).

---

## Otwarte pytania (rozstrzygnięte 2026-05-08, spec §3)

Wszystkie 6 decyzji designowych ze spec'a §3 zaakceptowane bez modyfikacji:

1. ✅ **§3.1** Synchronous emit (blocking insert) — NIE async/queued.
2. ✅ **§3.2** Per-spider-run granularity dla `scrape_logs` — NIE per-request.
3. ✅ **§3.3** Silent fallback do stderr przy Mongo failure (Django) / `spider.logger.error` (Scrapy).
4. ✅ **§3.4** NullHandler gdy `MONGO_URL` empty (Django) / NotConfigured (Scrapy).
5. ✅ **§3.5** Indexes na obu kolekcjach (idempotent `create_index`).
6. ✅ **§3.6** Formatted `exc_info` string (NIE structured array).

**Open questions z §9** (do M-future, NIE w M6 scope):
- TTL retention (auto-cleanup starych logów).
- GraphQL admin query do `scrape_logs`.
- Per-request `scrape_logs` (downloader middleware).
- Async/queued emit.
- Structured `exc_info`.
- Aggregation pipelines / Grafana dashboards.
- Django middleware enrichment (request user/path/method w `app_logs`).
- Mongo healthcheck w `docker-compose.dev.yml`.

---

## Risk + mitigation

| Ryzyko | Prawdopodobieństwo | Impact | Mitigation |
|---|---|---|---|
| **Mongo down podczas Django emit** | Średnie (lokalny dev bez `docker-compose up mongo`) | App `logger.info` zacząłby 500'ki | §6.1 silent fallback: `try/except → handleError` (stdlib pattern). Test `test_emit_falls_back_to_stderr_on_mongo_failure` enforce'uje. |
| **Mongo down podczas spider_closed** | Niskie (Beat schedule, prod mongo zawsze up) | Spider close blocked → Celery task hangs | §6.2 try/except → `spider.logger.error`, NO raise. Test `test_spider_closed_logs_error_on_mongo_failure`. |
| **`pymongo.MongoClient` blocks 30s na server selection gdy Mongo down** | Wysokie (default timeout) | `logger.info` w view'ie wisi 30s przed fallback'iem | §6.4 `serverSelectionTimeoutMS=2000` w `get_mongo_client()` — fail-fast 2s. |
| **Index creation race** (multiple workers wywołujące `get_collection` jednocześnie) | Niskie (lazy singleton w jednym procesie) | `create_index` zwraca już-istniejący name, idempotent | Mongo `create_index` jest idempotent. Plus singleton MongoClient = jedno wywołanie per proces, nie N. |
| **`MONGO_URL` empty w prod** (deploy bug) | Niskie (CI checks env vars) | Logi nie idą do Mongo, silent | §3.4 NullHandler — app działa, console handler dalej działa. Smoke check po deploy: `manage.py shell -c "from logs_backend import get_mongo_client; print(get_mongo_client())"` (None vs MongoClient). |
| **Logger `apps` filter pomija system logs** (Django/3rd-party) | Świadome | Brak logów z Django ORM/migrations w Mongo | Zamierzone (§3.4 reasoning) — `app_logs` to **business** observability, nie infra. Inne handlery (Django default) dalej obsługują system logs. |
| **CI Mongo service dostępny ale `MONGO_DB=tibiantis_logs_test` shared między testami** | Średnie | Test isolation problem (race między concurrent test runs) | Pytest fixture `mongo_db` z `db.collection.drop()` w teardown (autouse=False, explicit per test). M3-D17 race lesson. |

---

## Task overview

| # | ID | Tytuł | Czas | Zależy od | Branch |
|---|---|---|---|---|---|
| 1 | M6-D28 | `logs_backend/` package + `MongoLogHandler` + factory + Django LOGGING integration | 2-3h | M5 closed + chore PR #105 (no-commit-to-branch hook) merged | `feat/<#>-mongo-log-handler` |
| 2 | M6-D29 | `MongoStatsExtension` + Scrapy signals + `scrape_logs` doc | 2-3h | D28 merged | `feat/<#>-mongo-stats-extension` |
| 3 | M6-D30 | E2E smoke (live spider mocked + real Mongo) + M6 closure (PROGRESS.md retro + milestone close) | 2h | D29 merged | `feat/<#>-m6-e2e` + `docs/close-m6-mongo-logging` |

**Total:** ~7-8h, ~2 dni roboczych. Mniejszy niż M5 (5 D-tasków, 13-15h) bo M6 jest węższy: tylko logging infrastructure, brak business logic, brak GraphQL, brak Celery tasks.

---

## Task #1 — [M6-D28] `logs_backend/` package + `MongoLogHandler` + factory + Django LOGGING

### 🎯 Cel

Utworzyć `logs_backend/` jako top-level Python package (NIE Django app) z lazy MongoClient singleton, custom `MongoLogHandler` (sync emit, silent fallback do stderr) i `factory_or_null` dispatch'em. Skonfigurować Django `LOGGING` dict w `config/settings/base.py` żeby attached do logger `"apps"` (NIE root). Po D28: każdy `logger.info("...")` w `apps.*` zapisuje 1 dokument do `app_logs` collection.

### 🧠 Czego się nauczysz

- **`logging.Handler` API** — `__init__`, `emit(record)`, `format(record)`, `handleError(record)`. `emit` jest hot path — wywoływany dla każdego `logger.info(...)` call. `handleError` to default fallback path stdlib (default impl writes to stderr, dokładnie czego potrzebujemy dla §3.3).
- **`pymongo.MongoClient` config** — `serverSelectionTimeoutMS=2000` (fail-fast, §6.4), default `maxPoolSize=100` wystarczy dla low-traffic backendu, `connectTimeoutMS`/`socketTimeoutMS=2000` zaspojnione. Lazy singleton wzorzec: `MongoClient` instancja tworzona przy pierwszym `get_mongo_client()` call, cache na module level (`_client: MongoClient | None`).
- **Django `LOGGING` dict** (`logging.config.dictConfig` schema) — handler `"mongo"` przez `"()"` factory pattern (callable returning Handler instance). `loggers` config attaches `"apps"` logger do handler `"mongo"` z `"propagate": False` żeby NIE emit'ować dwukrotnie (raz przez `apps` handler, drugi przez root). PEP-8 naming: `LOGGING` (uppercase, Django convention).
- **`logging.NullHandler`** — stdlib no-op handler. `emit()` is no-op. Używamy go jako fallback gdy `MONGO_URL` empty — app działa, logi idą do default Django console handler ale NIE do Mongo.
- **Idempotent `create_index`** — Mongo `collection.create_index(keys, name=...)` jest idempotent (no-op gdy index z tym name'em już istnieje). Wywoływane w `get_collection(name)` na pierwszy call, lazy.

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m6-d28.md`.)

**Kluczowe punkty:**
- `logs_backend/__init__.py` z `get_mongo_client()` (lazy singleton, `serverSelectionTimeoutMS=2000`) + `get_collection(name)` (z idempotent `create_index` dla `app_logs.timestamp` desc i `scrape_logs.spider_name+finished_at` compound).
- `logs_backend/handlers.py` z `MongoLogHandler(logging.Handler)` (sync `insert_one`, fallback przez `self.handleError(record)`) + `factory_or_null()` (zwraca `MongoLogHandler` lub `NullHandler` w zależności od `settings.MONGO_URL`).
- `config/settings/base.py` z `LOGGING` dict — handler `"mongo"` przez `"()"` factory + logger `"apps"` z `"handlers": ["mongo"]`, `"level": "INFO"`, `"propagate": False`.
- Plus istniejący Django default console logging dla root logger (Django auto-config) — zostaje, NIE override.
- 6-7 unit testów (handler emit, exc_info formatting, Mongo fail fallback, NullHandler dispatch, index creation idempotency).

### ⚠️ Pułapki do uwagi

- **A — `logs_backend/` to NIE Django app** — top-level package. NIE dodawaj do `LOCAL_APPS` w `base.py` ani do `INSTALLED_APPS` w `stubs.py`. Plus brak `apps.py` / `models.py` / migrations. Pakiet importowany przez Django LOGGING dispatch (`'()': 'logs_backend.handlers.factory_or_null'`).
- **B — `serverSelectionTimeoutMS=2000`** w `MongoClient` config — bez tego default 30s. Każdy `logger.info` w widoku gdy Mongo down wisi 30s zanim fallback do stderr. **Test:** mock `MongoClient.insert_one` raises `ConnectionFailure`, assert handler `emit` returnuje w <2s (np. `time.monotonic()` measurement).
- **C — `propagate: False`** na logger `"apps"` w LOGGING dict — bez tego logi z `apps.*` szły by przez handler `"mongo"` ORAZ przez handlery root logger'a (np. Django console) → duplicate log entries.
- **D — Lazy singleton thread safety** — `_client: MongoClient | None = None; if _client is None: _client = MongoClient(...)`. Race między pierwszymi 2 wątkami możliwa, ale `MongoClient` jest itself thread-safe i utworzenie 2 instancji to tylko micro-leak (one zwolniona przez GC). **Mitigacja:** brak — `pymongo` MongoClient internally pool'uje, double-init jest cosmetic. Premature optimization byłby `threading.Lock`. YAGNI.
- **E — `formatException` z None record.exc_info** — `record.exc_info` jest `None` dla zwykłych logów (INFO/WARNING). `MongoLogHandler.emit()` musi conditionally dorzucić `exc_info` field tylko gdy `record.exc_info` is set (`if record.exc_info: doc["exc_info"] = self.formatter.formatException(record.exc_info)`). Bez tego `KeyError` lub `formatException(None)` exception.
- **F — `MongoLogHandler.__init__` musi przyjąć optional `formatter`** — Django LOGGING dispatch może podać formatter explicit. Jeśli brak, użyj `logging.Formatter()` default (handler MUSI mieć formatter żeby `self.format(record)` działał — fallback do stderr używa formatted text).
- **G — Test database isolation** — pytest fixture `mongo_db` (per spec §7.2) drop'uje wszystkie collections w teardown. Bez tego collateral między testami (jeden test zostawia 5 docs, drugi assert `count == 1`).
- **H — `MONGO_DB` w testach `tibiantis_logs_test` (NIE prod `tibiantis_logs`)** — CI ma osobne env var (`ci.yml` line ~80). Lokalnie: `.env` dev mongo używa `MONGO_DB=tibiantis_logs` ale pytest może override przez `pytest-django` settings. Sanity: testy NIE flush'ują prod `app_logs` (paranoja: assert `db.name == "tibiantis_logs_test"` w fixture).

### 🧪 Testing plan

`tests/unit/logs_backend/__init__.py` (pusty) + `tests/unit/logs_backend/conftest.py` (fixture `mongo_db` z drop teardown) + `tests/unit/logs_backend/test_mongo_log_handler.py`:

- `test_get_collection_returns_pymongo_collection` — sanity wrap.
- `test_get_collection_creates_index_on_first_call` — pierwsze `get_collection("app_logs")` tworzy index na `timestamp`.
- `test_get_collection_idempotent_index_creation` — drugi call NIE rzuca (Mongo create_index idempotent).
- `test_emit_writes_doc_with_expected_fields` — emit `INFO` record z `apps.test`, assert collection ma 1 doc z fields: `timestamp` (ISODate), `level="INFO"`, `logger="apps.test"`, `message`, `module`, `function`, `line`.
- `test_emit_includes_exc_info_for_error_records` — emit ERROR z `try: raise ValueError except: logger.exception(...)`, assert doc ma `exc_info` field z formatted traceback string ("Traceback..." in value).
- `test_emit_omits_exc_info_for_records_without_exception` — emit zwykły `logger.info("hi")`, assert `"exc_info" not in doc`.
- `test_emit_falls_back_to_stderr_on_mongo_failure` — mock `collection.insert_one` raises `ConnectionFailure`, assert `handler.emit(record)` NOT raised; capsys.readouterr().err zawiera formatted record string.
- `test_emit_returns_quickly_on_mongo_unreachable` — mock MongoClient z `serverSelectionTimeoutMS=100`, point at `mongodb://localhost:1` (closed port), assert `emit()` returns w <2s. (Sanity test dla §6.4.)
- `test_factory_returns_null_handler_when_mongo_url_empty` — `@override_settings(MONGO_URL="")`, `factory_or_null()` zwraca `logging.NullHandler` instance.
- `test_factory_returns_mongo_handler_when_mongo_url_set` — default settings (MONGO_URL set w `.env`), `factory_or_null()` zwraca `MongoLogHandler`.
- `test_django_logging_routes_apps_logger_to_mongo` — `import logging; logging.getLogger("apps.test").info("hello")`, assert collection.find_one(message="hello") exists. (Smoke że `LOGGING` config jest correct.)

**Coverage cel:** `logs_backend/__init__.py` 100%, `logs_backend/handlers.py` 100%.

### 📦 Definition of Done

- [ ] AC spełnione (`logs_backend/`, `MongoLogHandler`, factory, Django LOGGING).
- [ ] PR zmergowany squash (`feat(logs): add MongoLogHandler + Django LOGGING integration (M6-D28, #<#>)`).
- [ ] CI lint + test zielone.
- [ ] `logs_backend/*.py` 100% coverage.
- [ ] `pymongo` w `pyproject.toml` (osobny `build(deps)` commit jeśli brak).
- [ ] Issue zamknięty.

---

## Task #2 — [M6-D29] `MongoStatsExtension` + Scrapy signals + `scrape_logs` doc

### 🎯 Cel

Utworzyć `scrapers/tibiantis_scrapers/extensions.py` z `MongoStatsExtension` rejestrowanym przez Scrapy `EXTENSIONS` dict w `scrapers/tibiantis_scrapers/settings.py`. Extension subscribuje na `signals.spider_opened` (zapisuje `started_at`) + `signals.spider_closed` (buduje doc z `crawler.stats`, `insert_one` do `scrape_logs`). Disabled mode przez `NotConfigured` raise gdy `MONGO_URL` empty. Po D29: każdy `scrapy crawl <spider>` lub `scrapy crawl deaths` przez Celery zapisuje 1 doc do `scrape_logs`.

### 🧠 Czego się nauczysz

- **Scrapy Extensions API** — `from_crawler(cls, crawler) -> instance` factory pattern (analogicznie do Scrapy `Pipeline`). Returns `cls(...)` lub raise `scrapy.exceptions.NotConfigured` żeby Scrapy disable extension cleanly. Plus subscribe na signals przez `crawler.signals.connect(self.handler, signal=signals.spider_opened)`.
- **Scrapy signals** — `spider_opened(spider)` i `spider_closed(spider, reason)` (oba w `scrapy.signals`). `reason` może być `"finished"`, `"shutdown"`, `"cancelled"`, `"failed"` — wartościowe dla `scrape_logs.reason` field (post-M6 enhancement, ale dla M6 używamy tylko stats, nie reason).
- **`crawler.stats` API** — `crawler.stats.get_stats() -> dict` zwraca raw stats dict (~30+ kluczy). `crawler.stats.get_value(key, default)` dla pojedynczego getter'a. Wszystkie counters (downloader/request_count, item_scraped_count, log_count/ERROR, etc.) są w `get_stats()`.
- **`from logs_backend import get_collection`** — top-level import (NIE relative `from .` bo `scrapers/` to oddzielny Python tree). Współdzielenie singleton MongoClient z Django (oba procesy, gdy Scrapy uruchomione z subprocess, mają osobne MongoClient instances — to jest OK, każdy proces self-contained).

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m6-d29.md`.)

**Kluczowe punkty:**
- `scrapers/tibiantis_scrapers/extensions.py` z `MongoStatsExtension` (`__init__`, `from_crawler` z `NotConfigured` raise, `spider_opened` handler zapisuje `started_at`, `spider_closed` handler buduje doc + `insert_one`, defensive try/except → `spider.logger.error`).
- `scrapers/tibiantis_scrapers/settings.py` rozszerzone o `EXTENSIONS = {"scrapers.tibiantis_scrapers.extensions.MongoStatsExtension": 500}`.
- 5-6 unit testów (`from_crawler` NotConfigured path, `spider_opened` records timestamp, `spider_closed` flushes doc, error path on Mongo failure, doc shape matches schema §4.2).

### ⚠️ Pułapki do uwagi

- **A — `from_crawler` raise `NotConfigured`** (scrapy.exceptions) gdy `crawler.settings.get("MONGO_URL")` empty — Scrapy traktuje to jako clean disable, log "Disabled extension X (NotConfigured)". Bez raise: extension się rejestruje ale fail przy pierwszym signal.
- **B — Scrapy `crawler.settings` to NIE Django `settings`** — Scrapy używa własnego `Settings` objektu (z `tibiantis_scrapers/settings.py`). Trzeba sprawdzić jak `MONGO_URL` przepuszczone — albo dorzucić `MONGO_URL = os.environ.get("MONGO_URL", "")` do `scrapers/tibiantis_scrapers/settings.py`, albo użyć Django `settings.MONGO_URL` (wymaga `django.setup()` na top of `extensions.py` — istnieje już dla pipeline'u przez M1-D8 scaffolding). Druga opcja lepsza — single source of truth. Sprawdź `scrapers/tibiantis_scrapers/settings.py:1-10` czy `django.setup()` is called.
- **C — Lazy import `get_collection`** wewnątrz `spider_closed` handler — analogicznie do M5-D26 lazy import (cikular safety między `apps.bedmages.services` ↔ `apps.characters.tasks`). Tutaj cikular nie ma (Scrapy → logs_backend, logs_backend nie importuje Scrapy), więc top-level import OK. Wybór dla consistency: top-level import.
- **D — `started_at` thread-local vs instance attribute** — Scrapy default uruchamia spider'y w jednym thread'zie per crawl (Twisted reactor single-threaded), więc instance attribute `self.started_at` is safe. Multi-spider concurrent crawls byłyby Twisted reactor anti-pattern (M1-D8 retro #8). YAGNI — instance attribute wystarczy.
- **E — `crawler.stats.get_stats()` zawiera non-JSON-serializable types** — niektóre stats (np. `start_time`, `finish_time`) to `datetime` objects, ale Mongo BSON akceptuje `datetime` natywnie. `int`/`float`/`str` też BSON-native. Scrapy stats w 99% przypadków są clean. **Sanity:** test asercja, że `insert_one(doc)` NIE rzuca dla typowego crawl stats dict. Jeśli pojawi się exotic type (np. `Path`), defensive `_clean_stats(stats)` helper konwertujący do BSON-safe (str fallback). M6 pierwsze podejście: assume clean, dorzuć helper jeśli test ujawni problem.
- **F — Index `scrape_logs.spider_name + finished_at`** — compound, descending na `finished_at`. Tworzony przez `get_collection("scrape_logs")` w D28 (już impl'd). D29 tylko używa, nie tworzy.
- **G — Test setup wymaga `Spider` mock i `Crawler` mock** — zgodnie z Scrapy testing patterns: `from scrapy.utils.test import get_crawler`. Lub bezpośrednio mock'ować przez `MagicMock(spec=Crawler)` z `.stats.get_stats.return_value = {...}`. Druga opcja prostsza.

### 🧪 Testing plan

`tests/unit/scrapers/test_mongo_stats_extension.py`:

- `test_from_crawler_raises_not_configured_when_mongo_url_empty` — `@override_settings(MONGO_URL="")` (lub Scrapy `Settings({"MONGO_URL": ""})` mock), `MongoStatsExtension.from_crawler(crawler)` → `NotConfigured`.
- `test_from_crawler_returns_instance_when_mongo_url_set` — happy path, returns `MongoStatsExtension` instance.
- `test_from_crawler_subscribes_to_spider_opened_and_closed` — assert `crawler.signals.connect` called with both signals.
- `test_spider_opened_records_started_at` — call `extension.spider_opened(spider)`, assert `extension.started_at` is `datetime` w UTC.
- `test_spider_closed_flushes_doc_with_expected_fields` — call full lifecycle (open + close), assert collection ma 1 doc z `spider_name`, `started_at`, `finished_at`, `duration_seconds` (>=0), `items_scraped`, `items_dropped`, `stats` (dict), `errors` (list).
- `test_spider_closed_logs_error_on_mongo_failure` — mock `insert_one` raises `ConnectionFailure`, assert `spider.logger.error` called z "Mongo flush failed", assert NOT raised.
- `test_spider_closed_populates_errors_when_log_count_error_nonzero` — Stats z `log_count/ERROR=2`, assert `doc["errors"]` is non-empty list (przy fakcie że stats nie zawierają string'owych errorów per-message — zostawić empty list jeśli stats nie tracking, dorzucić TODO dla M-future).

**Coverage cel:** `scrapers/tibiantis_scrapers/extensions.py` 100%.

### 📦 Definition of Done

- [ ] AC spełnione (`MongoStatsExtension`, EXTENSIONS dict, signals, error handling).
- [ ] PR zmergowany squash (`feat(logs): add MongoStatsExtension for Scrapy scrape_logs (M6-D29, #<#>)`).
- [ ] CI lint + test zielone.
- [ ] `scrapers/tibiantis_scrapers/extensions.py` 100% coverage.
- [ ] Issue zamknięty.

---

## Task #3 — [M6-D30] E2E smoke (live spider mocked + real Mongo) + M6 closure

### 🎯 Cel

E2E integration test pokrywający pełny chain: Django `apps.bedmages` logger → MongoLogHandler → `app_logs`; **plus** mocked subprocess crawler → Scrapy signals → MongoStatsExtension → `scrape_logs`. Walidacja że oba paths współdzielą Mongo connection i piszą poprawnie do różnych collections. Plus M6 closure — `PROGRESS.md` rozszerzone o sekcję M6 z retro per Issue, milestone closed via `gh api`.

D30 ma **2 PR-y w 1 issue** (M5-D27 pattern):
1. **Feature PR** — `tests/integration/test_m6_logging_e2e.py` + ewentualne minor fixy odkryte przez E2E.
2. **Closure PR** — `PROGRESS.md` retro + milestone close.

### 🧠 Czego się nauczysz

- **E2E test patterns** — full-chain test bez bypass (real Mongo, real Django LOGGING dispatch, real Scrapy Extension). Mock tylko external services (subprocess Scrapy crawl jeśli używamy z Celery — analog M3-D17 + M4-D22 e2e). Plus pytest fixture rozszerzony żeby reset OBA `app_logs` i `scrape_logs`.
- **Django LOGGING dict reload w testach** — `LOGGING` jest applied przy Django startup. Override przez `@override_settings(LOGGING=...)` może wymagać `logging.config.dictConfig(settings.LOGGING)` po override żeby zmiana wzięła. Lub: zostawić default LOGGING, dispatch przez logger explicit (`logging.getLogger("apps.test").info(...)`) który dispatchuje do mongo handler attached już przy bootstrap'ie.
- **`gh api -X PATCH` REST API direct** — `gh milestone close` nie istnieje w gh CLI, używamy raw REST: `gh api -X PATCH repos/:owner/:repo/milestones/<#> -f state=closed`. M5-D27 precedens.
- **Closure PR od fresh master** — `git checkout master && git pull && git checkout -b docs/close-m6-mongo-logging`. M1-D8 ops blunder (PR #26 duplicate) lekcja, pamiętana przez M5-D27.

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m6-d30.md`.)

### Feature PR (`feat/<#>-m6-e2e`)

**Required (2 testy — Django logger e2e):**
- `tests/integration/test_m6_logging_e2e.py`:
  - `test_e2e_django_logger_persists_to_app_logs` — `logging.getLogger("apps.test").info("hi")`, assert `app_logs` collection ma 1 doc z `message="hi"`, `level="INFO"`, `logger="apps.test"`.
  - `test_e2e_django_logger_with_exception_persists_traceback` — `try: raise ValueError("boom") except: logging.getLogger("apps.test").exception("failed")`, assert doc ma `exc_info` z "ValueError" + "boom" (§3.6 formatted exc_info).

**Optional (Scrapy extension e2e — Twisted reactor experiment):**
- E2E dla `MongoStatsExtension` jest trudny ze względu na Twisted reactor isolation w pytest. Trzy approaches z trade-offs (subprocess vs `get_crawler` vs skip). **Rekomendacja:** skip — D29 unit testy pokrywają flow extension'a z mockiem; M6 closure dokumentuje "manual smoke" jako alternatywę (admin uruchamia `scrapy crawl deaths` lokalnie + sprawdza `scrape_logs.count_documents` w mongoshell). Pragmatyczne dla minimum viable scope. Pełna dyskusja opcji w issue body D30.

### Closure PR (`docs/close-m6-mongo-logging`)

**Kluczowe punkty:**
- `PROGRESS.md` rozszerzone:
  - Header sekcji M6: `## 🎉 Milestone M6 — Mongo logging COMPLETED (2026-MM-DD)`.
  - `### Ukończone (M6)` — lista 3 issues + PR linki + squash hashes.
  - `### Notatki z retro M6` — per Issue D28-D30.
  - `### Definition of Done M6` (ze spec'a §8) — wszystkie [x].
  - `### Podsumowanie M6` (data range, dni vs budżet, lekcje).
  - `### Tech debt z M6` (do M7+ carry-over).
- Milestone close: `gh api -X PATCH repos/bgozlinski/tibiantis-scraper/milestones/6 -f state=closed`.
- Sanity: `gh issue list --milestone "M6 — Mongo logging" --state open` → empty.

### ⚠️ Pułapki do uwagi

- **A — `LOGGING` dict reload w testach** — jeśli E2E nie widzi Mongo handler attached, sprawdź czy Django zaaplikował config (`logging.config.dictConfig(settings.LOGGING)` w app startup lub `conftest.py` fixture). M5-D17 precedens dla Celery worker config reload.
- **B — Test isolation** — pytest fixture `mongo_db` (z D28) drop'uje `app_logs` + `scrape_logs` w teardown. Bez tego E2E test #4 (`isolated`) failuje gdy poprzednie testy zostawiły docs w jednej z collections.
- **C — Closure branch od fresh master** (M1-D8 lekcja) — `git checkout master && git pull && git checkout -b docs/close-m6-mongo-logging`. NIE od feature brancha D30. Inaczej: closure PR zawiera duplikat squash D30 jako "no-op" commit (M1-D8 PR #26 problem).
- **D — `gh api PATCH milestone`** — wymaga uprawnień `repo` w token'ie, nie `public_repo`. Sanity przed call'em: `gh auth status` pokazuje permissions. Plus correct milestone number (`6` dla M6, sprawdź `gh api repos/.../milestones --jq '.[] | select(.title|contains("M6")) | .number'`).
- **E — Milestone "M6 — Mongo logging"** — exact title match dla `gh issue list --milestone "..."`. Sprawdziłem 2026-05-08, milestone #6 ma tytuł "M6 — Mongo logging" (check przed zamknięciem aby nie missnąć).

### 🧪 Testing plan

E2E tests w `tests/integration/test_m6_logging_e2e.py` (4 testy per AC). Plus uruchom **wszystkie** testy z M6 (D28 + D29 + D30 e2e) + cumulative coverage check:

```bash
poetry run pytest tests/unit/logs_backend/ tests/unit/scrapers/test_mongo_stats_extension.py tests/integration/test_m6_logging_e2e.py --cov=logs_backend --cov=scrapers.tibiantis_scrapers.extensions --cov-report=term
```

**Coverage cel:** Cumulative `logs_backend/*` + `scrapers/tibiantis_scrapers/extensions.py` ≥ 95%.

### 📦 Definition of Done

#### Feature PR
- [ ] AC spełnione (E2E test, all 4 cases passing).
- [ ] **Feature PR** zmergowany squash (`feat(logs): M6 e2e integration test (M6-D30, #<#>)`).
- [ ] CI lint + test zielone.
- [ ] Cumulative `logs_backend/*` + `scrapers/.../extensions.py` ≥ 95% coverage.

#### Closure PR
- [ ] **Closure PR** zmergowany squash (`docs(progress): close M6 — Mongo logging COMPLETED + retro D28-D30`).
- [ ] CI lint zielony.
- [ ] PROGRESS.md sekcja M6 dorzucona.
- [ ] Milestone M6 zamknięty na GitHub via `gh api -X PATCH .../milestones/6 -f state=closed`.
- [ ] Wszystkie M6 issues CLOSED (`gh issue list --milestone "M6 — Mongo logging" --state open` → empty).

---

## Spec section refs

| Spec section | Realizowane przez |
|---|---|
| §2 architektura komponenty | All tasks |
| §3.1 sync emit | D28 |
| §3.2 per-spider-run granularity | D29 |
| §3.3 silent fallback (Django) | D28 |
| §3.3 silent fallback (Scrapy) | D29 |
| §3.4 NullHandler / NotConfigured | D28 (Django) + D29 (Scrapy) |
| §3.5 indeksy idempotent | D28 |
| §3.6 formatted exc_info | D28 |
| §4.1 app_logs schema | D28 |
| §4.2 scrape_logs schema | D29 |
| §5 D-task split | This document |
| §6.1-6.3 error handling | D28 + D29 |
| §6.4 connection timeout | D28 |
| §7 testing strategy | D28 + D29 + D30 e2e |
| §8 DoD M6 | M6 closure (D30 closure PR) |
| §9 Open questions | M-future, NIE w M6 |
