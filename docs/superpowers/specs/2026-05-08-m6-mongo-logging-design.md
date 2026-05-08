# M6 — Mongo logging — Design spec

**Data:** 2026-05-08
**Status:** ACCEPTED (decyzje §4.1-4.5 zaakceptowane przez developera 2026-05-08, brainstorming w sesji M6 brainstorm)
**Plan:** [`docs/superpowers/plans/2026-05-08-m6-implementation-plan.md`](../plans/2026-05-08-m6-implementation-plan.md) (ten sam PR)
**Milestone:** [#6 — Mongo logging](https://github.com/bgozlinski/tibiantis-scraper/milestone/6)

---

## §1 Cel + scope

Wprowadzić MongoDB jako observability backend dla aplikacji Tibiantis Monitor. Dwie kolekcje:

- **`app_logs`** — Python logging output z `apps.*` loggers (poziomy INFO+).
- **`scrape_logs`** — historia uruchomień Scrapy spiderów (1 dokument per `scrapy crawl <spider>` invocation).

Zgodnie z CLAUDE.md §4 — Mongo trzyma **wyłącznie logi**, nigdy dane domenowe. `pymongo` bezpośrednio (NIE Djongo, NIE MongoEngine).

### W zakresie M6:
- Custom `MongoLogHandler(logging.Handler)` w `logs_backend/`.
- `MongoStatsExtension` jako Scrapy Extension hookujący `spider_opened` + `spider_closed` signals.
- Indeksy na obu kolekcjach (idempotent `create_index` przy pierwszym `get_collection` call).
- Disabled mode gdy `MONGO_URL` empty (`NullHandler` dla Django, `NotConfigured` dla Scrapy).
- Silent fallback do stderr przy Mongo failure (logging never breaks the app).
- Real Mongo w testach (CI service już skonfigurowany w `ci.yml`).

### Poza zakresem M6 (do M-future):
- TTL indexes / retention policy — unbounded growth, do adresowania post-traffic-data.
- GraphQL query do `scrape_logs` (admin observability) — może być w M7+.
- Per-request granularity dla `scrape_logs` (każdy URL fetch = 1 doc) — odrzucone na rzecz prostoty.
- Async/queued emit — sync wystarczy dla low-traffic backendu.
- Structured `exc_info` (file/line/type/msg array) — formatted string wystarczy dla debug.
- Aggregation pipelines / dashboards.

---

## §2 Architektura

### High-level diagram

```
┌──────────────────────┐                 ┌────────────────────┐
│ Django (web/celery)  │                 │ Scrapy (spiders)   │
│ logger.info(...)     │                 │ crawler signals    │
└──────────┬───────────┘                 └─────────┬──────────┘
           │                                       │
           ▼                                       ▼
┌──────────────────────┐                 ┌────────────────────┐
│ MongoLogHandler      │                 │ MongoStatsExtension│
│ (logs_backend/)      │                 │ (scrapers/.../     │
│ - INFO+ from apps.*  │                 │  extensions.py)    │
│ - sync insert_one    │                 │ - spider_opened    │
│ - try/except → stderr│                 │ - spider_closed    │
└──────────┬───────────┘                 └─────────┬──────────┘
           │                                       │
           └─────────────┬─────────────────────────┘
                         ▼
                ┌─────────────────┐
                │ pymongo client  │
                │ (lazy singleton │
                │ w logs_backend) │
                └────────┬────────┘
                         ▼
                ┌──────────────────┐
                │ MongoDB          │
                │ DB: tibiantis_   │
                │     logs         │
                │ ┌──────────────┐ │
                │ │ app_logs     │ │
                │ │ scrape_logs  │ │
                │ └──────────────┘ │
                └──────────────────┘
```

### Komponenty (5 plików, 1 modyfikacja)

| # | Plik | Status | Zawartość |
|---|---|---|---|
| 1 | `logs_backend/__init__.py` | NEW | `get_mongo_client()` lazy singleton; `get_collection(name)` helper z idempotent `create_index` na pierwszy call. |
| 2 | `logs_backend/handlers.py` | NEW | `MongoLogHandler(logging.Handler)` (`emit` + format dict + sync insert + try/except → stderr); `factory_or_null()` callable zwracające `NullHandler` gdy `MONGO_URL` empty. |
| 3 | `scrapers/tibiantis_scrapers/extensions.py` | NEW | `MongoStatsExtension` (`from_crawler` raises `NotConfigured` gdy `MONGO_URL` empty; subscribe na `spider_opened` + `spider_closed`; flush 1 doc na zamknięcie). |
| 4 | `config/settings/base.py` | MODIFY | Dodać `LOGGING` dict z handler `"mongo"` przez dotted path do `factory_or_null`, attached do logger `"apps"` (NIE root — eliminuje Django/3rd-party noise). |
| 5 | `scrapers/tibiantis_scrapers/settings.py` | MODIFY | Dodać `EXTENSIONS = {"scrapers.tibiantis_scrapers.extensions.MongoStatsExtension": 500}`. |

**Note:** `logs_backend/` to top-level Python package, NIE Django app — żadnej edycji `LOCAL_APPS` w `config/settings/base.py` ani `INSTALLED_APPS` w `config/settings/stubs.py`. Pakiet jest importowany przez Django LOGGING dispatch (`'()': 'logs_backend.handlers.factory_or_null'`) i Scrapy EXTENSIONS — żadna z tych dróg nie wymaga rejestracji w Django app registry.

---

## §3 Decyzje designowe (zaakceptowane 2026-05-08)

### §3.1 Synchronous emit (blocking insert)
**Wybór:** `MongoLogHandler.emit()` robi `collection.insert_one(...)` synchronously w call'ującym thread'zie.

**Justyfikacja:** Low-traffic backend (deaths co 5 min, characters monitor, GraphQL queries z admin interface) — network roundtrip do Mongo (5-50ms na localhost) jest negligible. Async via background queue dorzuciłby threading complexity (queue overflow, daemon thread lifecycle, shutdown flush) bez aktualnego perf benefit. **YAGNI** — async może być M-future jeśli traffic wzrośnie.

**Odrzucone alternatywy:**
- Async background queue (Python `queue.Queue` + daemon thread) — over-engineering dla M6 traffic.
- Sync teraz, async w follow-up — nie dorzucamy chore PR'a "na zapas", przyjdzie naturalnie z M-future signals.

### §3.2 Per-spider-run granularity dla `scrape_logs`
**Wybór:** 1 dokument per `scrapy crawl <spider>` invocation, flushed w `signals.spider_closed`.

**Justyfikacja:** Low document volume (~6 docs/dzień: deaths co 5 min × 24h przy enabled Beat = 288, characters co 1h = 24; nawet przy oba enabled to <500 docs/dzień, manageable). Pasuje pod CLAUDE.md §4 "liczba pozyskanych rekordów" (cumulative metric per crawl). Per-request granularity (każdy URL = 1 doc) wymagałby Scrapy `DOWNLOADER_MIDDLEWARE` i wygenerowałby ~1500 docs/dzień bez wyraźnego debug benefit (failed URLs i tak są w `crawler.stats.downloader/exception_count`).

**Odrzucone alternatywy:**
- Per-request — zbyt duży volume, Scrapy `crawler.stats` już aggreguje to samo bez per-doc cost.
- Hybrid (run header + nested per-request array) — Mongo doc size limit 16MB nie jest realnym blockerem, ale querying nested arrays jest awkward (`$elemMatch` + index na nested fields). YAGNI.

### §3.3 Silent fallback do stderr przy Mongo failure
**Wybór:** `MongoLogHandler.emit()` owija `insert_one` w `try/except (pymongo.errors.PyMongoError, Exception)` → na fail flush'uje record do `sys.stderr.write(self.format(record))`.

**Justyfikacja:** Standard Python logging philosophy — `logging.Handler.handleError` default catches exceptions w emit i pisze do stderr. App nigdy nie crashuje od logu. Mongo down jest observability problem, NIE app blocker. Dla scrape extension: na fail `spider.logger.error("Mongo flush failed: %s", e)` zamiast stderr (bo Scrapy ma własny logger context).

**Odrzucone alternatywy:**
- Fail-fast (raise) — `logger.info` w widoku rzucałby 500 dla całego request flow gdy Mongo down. Niepraktyczne dla prod.
- "Disable handler po pierwszym fail" — wymaga restart żeby logi wróciły, problemy z observability gdy Mongo wstanie ale handler dalej disabled.

### §3.4 NullHandler gdy `MONGO_URL` empty
**Wybór:** `logs_backend.handlers.factory_or_null()` zwraca `logging.NullHandler` gdy `settings.MONGO_URL` empty/missing, `MongoLogHandler(...)` gdy set. Scrapy: `MongoStatsExtension.from_crawler` raise `scrapy.exceptions.NotConfigured` przy empty `MONGO_URL` → Scrapy ciche disable extension.

**Justyfikacja:** Lokalne dev workflow bez Docker / bez Mongo running — app powinien startować i pisać do console. `MONGO_URL` jako required env var byłoby invasive (każdy `manage.py runserver` smoke wymagałby Mongo up). Stderr/console handler dalej działa (Django `LOGGING` default).

**Odrzucone alternatywy:**
- `MONGO_URL` REQUIRED (`ImproperlyConfigured` jak brak) — invasive dla dev.
- Default `mongodb://localhost:27017` — w prod gdzie env var jest missing app cicho zapisuje do nieistniejącego localhost'a → silent fallback do stderr od pierwszego logu, mylące dla operatora.

### §3.5 Indeksy na obu kolekcjach
**Wybór:** Tworzone przy pierwszym `get_collection(name)` call w `logs_backend/__init__.py` przez `collection.create_index(...)` (idempotent w Mongo — no-op gdy index już istnieje).

**Indexes:**
- `app_logs.timestamp` — descending (najnowsze pierwsze; debug query "ostatnie 100 logów").
- `scrape_logs.spider_name + finished_at` — compound index (descending na `finished_at`); query "ostatnie 10 deaths runów".

**Justyfikacja:** Bez indeksów full collection scan na każdy debug query. M-future moglibyśmy dorzucić TTL index dla retention; teraz priorytet na prosty debug experience.

**Odrzucone:** Brak indeksów — przyszłe debug session'y (np. "czemu Yhral failowało wczoraj") wymagałyby `collection.find({"logger": "..."}).sort("timestamp", -1).limit(100)` na full scan.

### §3.6 Formatted `exc_info` string (NIE structured)
**Wybór:** `MongoLogHandler.emit()` formatuje `record.exc_info` przez `self.formatter.formatException(record.exc_info)` (standardowy `logging.Formatter` API) i zapisuje jako string field `exc_info`.

**Justyfikacja:** Tradycyjny logging output, czytelny dla człowieka, jeden field zamiast N. M-future structured (file/line/type/msg array) jeśli pojawi się observability tool który tego wymaga (np. Sentry alternative).

---

## §4 Document schemas

### §4.1 `app_logs`

Jeden dokument per `logger.info(...)`/`.warning(...)`/`.error(...)`/`.critical(...)` call gdzie:
- Logger name zaczyna się od `apps.` (filter w `LOGGING` dict — handler `"mongo"` attached do logger `"apps"`).
- Level ≥ INFO.

**Schema:**

```json
{
  "_id": ObjectId,
  "timestamp": ISODate,                     // datetime.fromtimestamp(record.created, UTC)
  "level": "INFO",                          // record.levelname
  "logger": "apps.bedmages.services",       // record.name
  "message": "BedmageWatch created for ...",  // record.getMessage()
  "module": "services",                     // record.module
  "function": "add_bedmage_watch",          // record.funcName
  "line": 23,                               // record.lineno
  "exc_info": "Traceback (most recent call last):\n  ..."  // OPTIONAL — only when record.exc_info, formatted via formatter.formatException
}
```

**Indexes:**
- `{ timestamp: -1 }` — descending dla "ostatnie N logów" query pattern.

### §4.2 `scrape_logs`

Jeden dokument per spider crawl invocation, flushed w `signals.spider_closed` przez `MongoStatsExtension`.

**Schema:**

```json
{
  "_id": ObjectId,
  "spider_name": "deaths",                  // crawler.spider.name
  "started_at": ISODate,                    // captured w spider_opened
  "finished_at": ISODate,                   // captured w spider_closed
  "duration_seconds": 3.5,                  // (finished_at - started_at).total_seconds()
  "items_scraped": 50,                      // crawler.stats.get_value("item_scraped_count", 0)
  "items_dropped": 0,                       // crawler.stats.get_value("item_dropped_count", 0)
  "stats": {                                // crawler.stats.get_stats() — raw dict, schemaless
    "downloader/request_count": 1,
    "downloader/response_status_count/200": 1,
    "log_count/INFO": 5,
    "log_count/ERROR": 0,
    "scheduler/dequeued/memory": 1,
    "elapsed_time_seconds": 3.5,
    "...": "..."
  },
  "errors": [                               // populated only if log_count/ERROR > 0
    "Failed to parse character page: ..."
  ]
}
```

**Indexes:**
- `{ spider_name: 1, finished_at: -1 }` — compound; supports query "ostatnie 10 runów dla `deaths` spider'a".

---

## §5 D-task split

| # | ID | Tytuł | Czas | Branch | Zależy od |
|---|---|---|---|---|---|
| 1 | M6-D28 | `logs_backend/` package + `MongoLogHandler` + factory + Django LOGGING integration + tests | 2-3h | `feat/<#>-mongo-log-handler` | M5 closed |
| 2 | M6-D29 | `MongoStatsExtension` + Scrapy signals + `scrape_logs` doc + tests | 2-3h | `feat/<#>-mongo-stats-extension` | D28 |
| 3 | M6-D30 | E2E smoke (live spider mocked subprocess + real Mongo) + M6 closure (PROGRESS.md retro + milestone close) | 2h | `feat/<#>-m6-e2e` + `docs/close-m6-mongo-logging` (M5-D27 pattern: 2 PR-y w 1 issue) | D29 |

**Total:** ~7-8h, ~2 dni roboczych. Mniejsze niż M5 (5 D-tasków, ~13-15h) bo M6 jest wąsko zakresowy (logging only, no business logic).

### Spec section refs do D-tasków (mapping)

| Spec section | Realizowane przez |
|---|---|
| §3.1 sync emit | D28 |
| §3.2 per-spider-run | D29 |
| §3.3 silent fallback (Django side) | D28 |
| §3.3 silent fallback (Scrapy side) | D29 |
| §3.4 NullHandler / NotConfigured | D28 (Django) + D29 (Scrapy) |
| §3.5 indeksy | D28 (`get_collection` z `create_index`) |
| §3.6 formatted exc_info | D28 |
| §4.1 app_logs schema | D28 |
| §4.2 scrape_logs schema | D29 |
| §6 error handling | D28 + D29 |
| §7 testing | D28 + D29 + D30 e2e |

---

## §6 Error handling

### §6.1 Mongo down podczas Django `logger.emit()`
```python
def emit(self, record: logging.LogRecord) -> None:
    try:
        doc = self._build_doc(record)
        self.collection.insert_one(doc)
    except (PyMongoError, Exception):  # broad on purpose — never break app
        # Standard logging.Handler.handleError fallback semantics
        self.handleError(record)  # default impl writes to sys.stderr
```

### §6.2 Mongo down podczas Scrapy `spider_closed`
```python
def spider_closed(self, spider: Spider, reason: str) -> None:
    doc = self._build_doc(spider, reason)
    try:
        self.collection.insert_one(doc)
    except (PyMongoError, Exception):
        spider.logger.error("Mongo flush failed: %s", e, exc_info=True)
        # Don't raise — spider close must not block on observability layer
```

### §6.3 `MONGO_URL` empty
- **Django:** `factory_or_null()` zwraca `NullHandler` → `logger.info()` is no-op (relative do Mongo); console handler dalej działa.
- **Scrapy:** `MongoStatsExtension.from_crawler` raise `scrapy.exceptions.NotConfigured` → Scrapy log "Extension X disabled (NotConfigured)" + crawl continues normalnie bez `scrape_logs` flush.

### §6.4 Connection pool exhausted / slow
`pymongo.MongoClient` ma default `maxPoolSize=100`, `serverSelectionTimeoutMS=30000`. Dla low-traffic backendu (M6) wystarczy default. Konfiguracja w `logs_backend/__init__.py:get_mongo_client()`:

```python
return MongoClient(
    settings.MONGO_URL,
    serverSelectionTimeoutMS=2000,  # FAST fail — log handler nie może wisieć 30s na każdy emit
    connectTimeoutMS=2000,
    socketTimeoutMS=2000,
)
```

`serverSelectionTimeoutMS=2000` zamiast default 30s — gdy Mongo niedostępne, fail-fast 2s zamiast blokować emit thread na 30s. Po fail: silent fallback do stderr (§6.1).

---

## §7 Testing strategy

### §7.1 Real Mongo (NIE mongomock)

CI ma `mongo:7` service (już skonfigurowany w `ci.yml` per CLAUDE.md §13.1):
- `MONGO_URL: mongodb://localhost:27017`
- `MONGO_DB: tibiantis_logs_test`

Lokalnie: `docker-compose.dev.yml` ma Mongo. `mongomock` library odrzucony — real Mongo szybkie (insert+drop ~10ms), CI service już skonfigurowany, bypass real driver bug surface.

### §7.2 Pytest fixture

```python
# tests/unit/logs_backend/conftest.py (local scope — fixture nie potrzebny dla testów apps/*)
import pytest
from logs_backend import get_mongo_client

@pytest.fixture
def mongo_db():
    """Yield clean test DB. Drops all collections in teardown."""
    client = get_mongo_client()
    db = client[settings.MONGO_DB]
    yield db
    for collection_name in db.list_collection_names():
        db[collection_name].drop()
```

### §7.3 Test scenarios

**`tests/unit/logs_backend/test_mongo_log_handler.py`:**
- `test_emit_writes_doc_with_expected_fields` — emit `INFO` record, assert collection has 1 doc z poprawnymi fields.
- `test_emit_includes_exc_info_for_error_records` — emit ERROR z `exc_info`, assert doc ma formatted traceback string.
- `test_emit_falls_back_to_stderr_on_mongo_failure` — mock `MongoClient.insert_one` raises `ConnectionFailure`, assert NOT raised; check stderr capture (capsys).
- `test_factory_returns_null_handler_when_mongo_url_empty` — `@override_settings(MONGO_URL="")`, factory zwraca `NullHandler`.
- `test_factory_returns_mongo_handler_when_mongo_url_set` — factory zwraca `MongoLogHandler`.

**`tests/unit/logs_backend/test_indexes.py`:**
- `test_get_collection_creates_indexes_on_first_call` — pierwsze `get_collection("app_logs")` tworzy index na `timestamp`.
- `test_get_collection_idempotent_index_creation` — drugi call NIE rzuca (Mongo `create_index` is idempotent).

**`tests/unit/scrapers/test_mongo_stats_extension.py`:**
- `test_extension_raises_not_configured_when_mongo_url_empty` — `MongoStatsExtension.from_crawler(crawler)` z empty `MONGO_URL` → `NotConfigured`.
- `test_spider_opened_records_started_at` — call `spider_opened`, assert internal state ma `started_at` datetime.
- `test_spider_closed_flushes_doc_with_stats` — call full lifecycle, assert collection ma 1 doc z `spider_name`, `started_at`, `finished_at`, `stats`.
- `test_spider_closed_logs_error_on_mongo_failure` — mock `insert_one` raises, assert spider.logger.error called, no raise propagation.

**`tests/integration/test_m6_logging_e2e.py`:**
- `test_e2e_django_logger_persists_to_mongo` — `apps.bedmages` logger emits, assert doc w `app_logs`.
- `test_e2e_spider_run_persists_to_scrape_logs` — full crawl (mocked subprocess + fixture spider), assert doc w `scrape_logs`.

### §7.4 Coverage cel

- `logs_backend/__init__.py` 100%
- `logs_backend/handlers.py` 100%
- `scrapers/tibiantis_scrapers/extensions.py` 100%
- Cumulative `logs_backend/*.py` ≥ 95% (DoD).

---

## §8 Definition of Done M6

- [ ] **3 PR merged, 3 Issues zamknięte** (D28-D30 + closure PR).
- [ ] **`logs_backend/` package** (`__init__.py` + `handlers.py`) z lazy `MongoClient` singleton + `MongoLogHandler` + `factory_or_null`.
- [ ] **`scrapers/tibiantis_scrapers/extensions.py`** z `MongoStatsExtension` rejestrowanym w `EXTENSIONS` dict.
- [ ] **Django `LOGGING`** w `base.py` z handler `"mongo"` attached do logger `"apps"`.
- [ ] **`MONGO_URL` empty** → app startuje normalnie (NullHandler dla Django, NotConfigured dla Scrapy).
- [ ] **`MONGO_URL` set** + Mongo running → `logger.info(...)` w `apps.*` zapisuje doc do `app_logs`; `scrapy crawl <spider>` zapisuje doc do `scrape_logs`.
- [ ] **Mongo down** → app NIE crashuje, fallback do stderr (Django) / `spider.logger.error` (Scrapy).
- [ ] **Indexes** stworzone idempotentnie przy pierwszym `get_collection` call.
- [ ] **Wszystkie pre-commit + CI zielone** dla każdego PR-a.
- [ ] **Coverage cumulative `logs_backend/*` ≥ 95%** (cel 100%).
- [ ] **PROGRESS.md** rozszerzony o sekcję M6 z retro per Issue.
- [ ] **Milestone M6 zamknięty** na GitHub via `gh api -X PATCH .../milestones/6 -f state=closed`.

---

## §9 Open questions / future work (NIE w M6 scope)

- **TTL retention** — `app_logs` 30 dni, `scrape_logs` 90 dni. Implementation: TTL index na `timestamp`/`finished_at`. Decyzja przy pierwszej observability sesji gdy Mongo storage rośnie.
- **GraphQL admin query** dla `scrape_logs` — `recentScrapeRuns(spider: String, limit: Int)` JWT-protected, admin-only. Może być w M7+ (Discord bot dashboard).
- **Per-request `scrape_logs`** — Scrapy `DOWNLOADER_MIDDLEWARE` z `process_response`/`process_exception`. Decyzja dopiero gdy per-spider-run okaże się niewystarczający dla debug session'a.
- **Async/queued emit** — `queue.Queue` + daemon thread + batch insert. Decyzja przy pierwszym wzroście traffic'u (10x current).
- **Structured `exc_info`** (file/line/type/msg array) — gdy podłączymy Sentry/alternative observability tool który zinterpretuje structured errors lepiej niż formatted string.
- **Aggregation pipelines / dashboard** — Grafana/Metabase dashboardy nad `scrape_logs` (success rate per spider, daily volume). M-future po wdrożeniu Discord bot (stabilna baseline traffic'u).
- **`logs_backend.middleware`** — Django middleware capturing request user/path/method dla `app_logs` enrichment. Kandydat na M7+ (tied do JWT/admin observability).
- **Docker compose** — Mongo healthcheck w `docker-compose.dev.yml`. Carry-over do M9 (Dockeryzacja).
