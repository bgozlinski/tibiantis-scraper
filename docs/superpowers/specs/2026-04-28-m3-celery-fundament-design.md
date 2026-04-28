# M3 — Celery infrastructure + scheduled character scrape — Design

**Data:** 2026-04-28
**Milestone:** M3 (GitHub milestone TBD)
**Budżet:** 5 dni roboczych (~16-20h, plus bufor po lekcji M2 = 4d budżet → 5d real)
**Poprzedni milestone:** M2 — Auth + GraphQL fundament (zamknięty 2026-04-27)

---

## 1. Cel

Postawić infrastrukturę zadań cyklicznych — **Celery worker + Celery Beat + Redis broker** — i wpiąć w nią pierwszy scheduled task: cykliczny scrape postaci z `Character.objects.all()`. Po M3 wszystkie kolejne milestones (deaths, bedmage, notifications) reuse'ują tę infrastrukturę bez ponownej walki z konfigiem.

**Świadomie wąski scope:** brak nowej domeny, brak Discord, brak nowych modeli. Reuse M1 spider + M2 service. M3 to "drugi event loop dochodzi do projektu" — Twisted (Scrapy) już mamy z M1, dochodzi Celery worker pool.

---

## 2. Scope

**W scope:**
- `poetry add celery redis django-celery-beat`
- Redis lokalnie (Memurai na Windows, lub WSL2 redis-server)
- `config/celery.py` — Celery app config + autodiscover
- `config/__init__.py` — Celery app load przy starcie Django
- `apps/characters/tasks.py` — task `scrape_watched_characters()` iterujący po wszystkich Character w DB
- Beat schedule przez `django-celery-beat` (DB-backed) — domyślny interval konfigurowalny w admin
- Ping task (sanity smoke) `apps.characters.tasks.ping`
- Management command runner instrukcje w README (`celery -A config worker -P solo` itd.)
- Testy: unit (eager mode `CELERY_TASK_ALWAYS_EAGER`), integration trigger-and-assert side effects

**Poza scope (post-M3):**
- Bedmage tracker (M4)
- Deaths spider + monitor (M4 lub M5)
- Discord webhook publisher (M5+)
- Production deployment (Dockerfile + docker-compose) — zostaje na M-final
- Mongo logging integration (M5+, na razie standardowy Python logging do stdout)
- Real-broker integration tests w CI (na razie tylko eager mode tests; CI nie odpala live workera)

---

## 3. Decyzje technologiczne

| Obszar | Wybór | Dlaczego |
|---|---|---|
| Broker | Redis | CLAUDE.md §2 mandatory. Mature, prosty, znany. |
| Result backend | Redis (ten sam serwer, inna DB index, np. `db=2`) | CLAUDE.md §2 nie precyzuje, najlżejsza opcja. Alternatywa: `django-db` jeśli chcemy mieć results w Postgres — odrzucone, dokłada IO do Postgres bez wartości na ten moment. |
| Beat schedule | `django-celery-beat` (DB-backed) | CLAUDE.md §6: "konfiguracja w bazie przez `django-celery-beat`, żeby zmieniać interwały bez deployu". Trade-off: dodatkowe migracje + zależność, ale unblockuje runtime tuning. |
| Worker pool (Windows dev) | `--pool=solo` | Windows nie wspiera prefork (`fork()` brak). Solo jest single-threaded ale wystarczy dla M3 dev. W prod (Linux Docker) wrócimy do prefork. |
| Worker pool (CI) | Brak — eager mode w testach | CI nie odpala live workera. Real-broker integration tests = post-M3. |
| Spider integration w taskach | **`subprocess.run(["python", "manage.py", "scrape_character", ...])`** | M1 retro #8: Celery + Twisted + asyncio = 3 event loopy. Subprocess izoluje Twisted — worker nie widzi Twisted reactor wcale. Alternatywa `CrawlerRunner + crochet` w-process miała 3 gotchas Windows. Subprocess prostszy. Cost: spawn overhead ~0.5s/postać, akceptowalne dla schedule godzinowego. |
| Watchlist source | `Character.objects.all()` (bez nowego modelu) | M3 to infra. `BedmageWatch` / `WatchedCharacter` dochodzi w M4. Tymczasowo iterujemy po wszystkich Character (admin seeds via `scrape_character` ręcznie). |
| Async task body | `def` (sync) — Celery 5.x oficjalnie nie wspiera `async def` task functions | Subprocess i tak blokuje. ORM calls przez sync API w taskach. |

---

## 4. Strategia dekompozycji

**Bottom-up, 5 Issues, strict chain D13 → D14 → D15 → D16 → D17.** Spójne z M2 (D9-D12). Zero paralelizmu — każdy Issue czeka na merge poprzedniego.

Alternatywy rozważone i odrzucone:
- **4 Issues (zlanie D13+D14)** — łączy "deps add" z "celery app config" w jeden Issue. Odrzucone: D13 ma rzeczywiste pre-flight ryzyka (Redis na Windows), warto je odpracować osobno przed dotykaniem Django config.
- **6 Issues (split D16 na "task body" + "Beat schedule")** — przesadny, oba siedzą w tym samym pliku, common context.
- **Vertical slice** (jeden PR z całością) — niezgodny z workflow M0-M2 i nie da się review'ować odcinkami.

---

## 5. Breakdown — 5 Issues

### D13 — [M3-D13] Redis + Celery dependencies + django-celery-beat (~3h)
**Branch:** `feat/<N>-celery-deps`

**Pre-flight (przed startem):** Sprawdzić czy Redis działa lokalnie. **Decyzja Memurai vs WSL2** zapisana w body Issue:
- **Memurai** (Windows-native, drop-in Redis 7.x replacement) — zalecane dla solo-dev na Windows, instalacja przez `winget install Memurai.MemuraiDeveloper` lub MSI. Free Developer edition.
- **WSL2 redis-server** — wymaga WSL2 setup, ale to "prawdziwy" Redis. Jeśli już używasz WSL2 do innych rzeczy, prostszy wybór.

Acceptance criteria:
- Redis dostępny lokalnie pod `redis://localhost:6379/`. Smoke: `redis-cli ping` → `PONG`.
- `poetry add celery redis django-celery-beat` zacommitowane (w jednej operacji, jeden PR).
- `INSTALLED_APPS += ["django_celery_beat"]` w `config/settings/base.py`.
- `python manage.py migrate` aplikuje migracje `django_celery_beat` (tworzy tabele `PeriodicTask`, `IntervalSchedule`, `CrontabSchedule` itd.) — bez custom migration artifact w `apps/`.
- `.env.example` rozszerzone o `REDIS_URL=redis://localhost:6379/0`, `CELERY_BROKER_URL=redis://localhost:6379/1`, `CELERY_RESULT_BACKEND=redis://localhost:6379/2` (3 osobne DB w jednym Redis instance — broker, results, future cache).
- `config/settings/base.py` czyta te 3 zmienne przez `env(...)`.
- Commit message zawiera info o Memurai/WSL2 wybranym lokalnie.
- Test: brak — to PR czysto dependency.

**Pułapka A:** `redis-py` (Python client) ma od 4.x wymagane parametry connection (`decode_responses` itp.). Celery wewnętrznie obsługuje to sam, ale jeśli kiedyś dodasz direct `redis.Redis(...)` w app code — sprawdź dokumentację. Na M3 nie dotykamy direct Redis client.

**Pułapka B:** `django-celery-beat` ma `migrations/` z `PeriodicTask` itp. — pierwszy `migrate` na świeżej bazie zadziała, ale jeśli ktoś ma już bazę z M2 — `python manage.py migrate django_celery_beat` musi być explicit.

### D14 — [M3-D14] Celery app config + ping task (~3h)
**Branch:** `feat/<N>-celery-app`
**Zależy od:** D13 merged

Acceptance criteria:
- `config/celery.py`:
  ```python
  import os
  from celery import Celery
  os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
  app = Celery("tibiantis")
  app.config_from_object("django.conf:settings", namespace="CELERY")
  app.autodiscover_tasks()
  ```
- `config/__init__.py`:
  ```python
  from .celery import app as celery_app
  __all__ = ("celery_app",)
  ```
  (Wymagane — Django importuje `config/__init__.py` przy starcie, co triggeruje rejestrację Celery app.)
- `config/settings/base.py` — `CELERY_TIMEZONE = "UTC"`, `CELERY_TASK_TRACK_STARTED = True`, `CELERY_TASK_TIME_LIMIT = 60 * 30` (30min hard limit per task — sanity dla future scrape tasks).
- `apps/characters/tasks.py` — `@shared_task` dekorator + funkcja `ping() -> str` zwracająca `"pong"`.
- Smoke: w 2 terminalach
  - Terminal 1: `poetry run celery -A config worker -l info -P solo`
  - Terminal 2: `poetry run celery -A config inspect ping` → odpowiedź z worker.
- Smoke: `poetry run python -c "from apps.characters.tasks import ping; print(ping.delay().get(timeout=5))"` → `pong`.
- Test: `tests/unit/characters/test_tasks.py::test_ping_task_returns_pong` z `CELERY_TASK_ALWAYS_EAGER=True` (override w `pytest.ini` lub `conftest.py`).

**Pułapka A:** `os.environ.setdefault("DJANGO_SETTINGS_MODULE", ...)` MUSI być **przed** `Celery(...)` — Celery przy starcie czyta settings, jeśli env var nieobecna → `ImproperlyConfigured`.

**Pułapka B:** `app.autodiscover_tasks()` szuka modułu `tasks` w każdej aplikacji z `INSTALLED_APPS`. Jeśli plik nazywa się inaczej (np. `celery_tasks.py`) — nie znajdzie. Trzymać konwencję `tasks.py`.

**Pułapka C:** `CELERY_TASK_ALWAYS_EAGER=True` w testach **NIE** wymaga workera — task wykonuje się synchronicznie w procesie testowym. Idealne dla unit tests; nie sprawdza serializacji broker→worker. Real-broker tests post-M3.

### D15 — [M3-D15] Worker + Beat dev runners (~2-3h)
**Branch:** `feat/<N>-celery-runners`
**Zależy od:** D14 merged

Acceptance criteria:
- README.md (lub osobny `docs/celery.md`) — sekcja "Running Celery dev" z dokładnymi komendami:
  ```
  # Terminal 1: Worker (Windows: -P solo mandatory)
  poetry run celery -A config worker -l info -P solo

  # Terminal 2: Beat (scheduler)
  poetry run celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler

  # Terminal 3 (optional): Flower monitoring UI
  # poetry run celery -A config flower (po dodaniu flower jako dev-dep, post-M3)
  ```
- `config/settings/base.py` — `CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"` (żeby `--scheduler` flag był optional w runtime).
- Smoke: Beat startuje, loguje "beat: Starting...", po kilku sekundach "DatabaseScheduler: Schedule changed." (bo schedule pusty, ale beat działa).
- Worker startuje, podpięty do brokera, ready to accept tasks.

**Pułapka A:** `--pool=solo` na Windows MANDATORY. Bez tego: `PermissionError: [WinError 5] Access is denied` przy próbie `fork()`. Dokumentacja CLAUDE.md cheatsheet §14 pokazuje samo `worker -l info` — to dla Linux/Docker. README dev musi mieć `-P solo` explicit.

**Pułapka B:** `Beat` z `DatabaseScheduler` przy pustym schedule wciąż loguje "Scheduler: Sending due task...". Może być confusing — to nie spam, to sanity check. Jeśli przeszkadza w dev — `-l warning` zamiast `info`.

**Pułapka C:** Jeśli zmienisz `PeriodicTask` w admin podczas gdy Beat chodzi, Beat **NIE** podchwyci zmiany od razu — domyślnie pollingu DB co 5 sekund. Można to skrócić przez `CELERY_BEAT_MAX_LOOP_INTERVAL = 1` (sekunda), ale to zwiększa load. Domyślne 5s OK na M3.

### D16 — [M3-D16] `scrape_watched_characters` task + Beat schedule (~4h)
**Branch:** `feat/<N>-scheduled-character-scrape`
**Zależy od:** D15 merged

Acceptance criteria:
- `apps/characters/tasks.py` — funkcja `scrape_watched_characters()`:
  ```python
  @shared_task(bind=True, max_retries=2)
  def scrape_watched_characters(self) -> dict[str, int]:
      """Scrape all Character.objects.all() via subprocess scrape_character.

      Returns: {"scraped": int, "failed": int, "skipped": int}
      """
      ...
  ```
  - Iteruje po `Character.objects.values_list("name", flat=True)`.
  - Dla każdej nazwy odpala `subprocess.run([sys.executable, "manage.py", "scrape_character", "--name", name], timeout=60, check=False)`.
  - Liczy `scraped`/`failed` (subprocess returncode 0 vs non-0).
  - Loguje wynik przez `logger.info(...)` (standardowy Python logging — Mongo handler dochodzi w M5+).
  - Idempotent: jeśli `last_scraped_at` < 30 min — `skipped`, nie odpala spider'a (uniknięcie nakładania się Beat fires). **Threshold konfigurowalny przez `CELERY_SCRAPE_FRESHNESS_MINUTES` env var, default 30.**
  - `max_retries=2` na cały task (nie per-postać; per-postać błędy są policzone w `failed`, nie eskalują).
- `apps/characters/migrations/<N>_seed_default_periodic_task.py` — data migration tworząca:
  - `IntervalSchedule(every=1, period=IntervalSchedule.HOURS)` jeśli nie istnieje
  - `PeriodicTask(name="scrape_watched_characters", task="apps.characters.tasks.scrape_watched_characters", interval=<above>)`, `enabled=False` (domyślnie wyłączone — admin enable'uje gdy chce; sanity pre-prod).
- Smoke: w admin Django włączyć `PeriodicTask`, Beat fires task co godzinę, worker odpala subprocess, Character.last_scraped_at się aktualizuje.
- Manual trigger: `poetry run python -c "from apps.characters.tasks import scrape_watched_characters; print(scrape_watched_characters.delay().get(timeout=120))"`.

**Pułapka A:** `subprocess.run(...)` w Celery task — worker pool `solo` blokuje się na czas subprocess'a. To jest ok dla M3 (cron godzinowy, subprocess ~5s), ale jeśli watchlist urośnie do 100+ postaci, blokowanie workera ma znaczenie. Wtedy: `chord` / `group` przez chunks, OR przejście na worker pool prefork w Linux Docker. **Decyzja na M3: nie problem, ale zostawiam komentarz w docstring task'a.**

**Pułapka B:** `subprocess.run(timeout=60)` — jeśli spider się zawiesi, Twisted reactor w subprocess nie respektuje SIGTERM dobrze na Windows. `timeout=` wysyła SIGTERM i jeśli proces nie kończy w 5s → SIGKILL. Na Windows SIGTERM nie istnieje (CTRL_BREAK_EVENT zamiast). `subprocess.run` na Windows traktuje `timeout=` przez TerminateProcess — działa, ale mniej graceful. Akceptowalne dla M3.

**Pułapka C:** Race między dwoma fires — jeśli interval = 1h ale task trwa 1h+5min, drugi fire startuje gdy pierwszy wciąż działa. **Mitigacja:** `lock` w Redis przez `django-celery-beat`'s `kombu` semantics, lub prostsze — `CELERY_TASK_REJECT_ON_WORKER_LOST = True` + `task_acks_late = True`. **Decyzja M3:** prostszy lock przez DB column `Character.last_scraped_at` + freshness threshold. Jeśli taski wpadają w siebie, freshness check filtruje.

**Pułapka D:** `subprocess.run` z `sys.executable` zamiast hardcoded `"python"` — to ważne, bo poetry venv `python` może nie być na PATH worker procesu (Celery worker jest spawned przez systemd/supervisor w prod, env może być inny niż dev shell). `sys.executable` zwraca path do interpretera, który aktualnie biega — gwarantowanie te same zależności.

### D17 — [M3-D17] e2e test + M3 closure (~3h)
**Branch:** `test/<N>-celery-e2e` + osobny `docs/close-m3-tracker`
**Zależy od:** D16 merged

Acceptance criteria (testy):
- `tests/integration/test_celery_e2e.py` — test pełnego flow:
  1. `Character.objects.create(name="Yhral", level=120, last_scraped_at=now() - 2h)` — postać "stale" (starsza niż freshness threshold)
  2. `Character.objects.create(name="Tester", level=50, last_scraped_at=now() - 5min)` — "fresh", powinna być skipped
  3. `result = scrape_watched_characters.apply().get()` (eager mode, sync)
  4. `assert result["scraped"] >= 1 and result["skipped"] >= 1`
  5. `Character.objects.get(name="Tester").last_scraped_at` nie zmienione (skipped)
  - Note: subprocess `scrape_character` w teście zostanie zamockowany przez `unittest.mock.patch("apps.characters.tasks.subprocess.run")` żeby nie hitować live tibiantis.online (CLAUDE.md §11). Mock zwraca `subprocess.CompletedProcess(args=..., returncode=0)`.
- `tests/unit/characters/test_tasks.py` — unit testy:
  - `test_scrape_watched_characters_handles_subprocess_failure` (mock returncode=1)
  - `test_scrape_watched_characters_respects_freshness_threshold`
  - `test_scrape_watched_characters_handles_empty_watchlist` (Character.objects empty → result=`{"scraped": 0, ...}`)
- e2e manual smoke (poza CI):
  - Włącz Memurai/WSL2 redis-server.
  - W 3 terminalach: `runserver`, `celery worker -P solo`, `celery beat`.
  - W admin Django ustaw `PeriodicTask` interval na `IntervalSchedule(every=1, period=MINUTES)` (na czas testu — zmień z powrotem po smoke).
  - Po 2 minutach sprawdź `Character.last_scraped_at` w admin — powinno się aktualizować.
- PROGRESS.md — `🎉 Milestone M3 — Celery infrastructure COMPLETED` + retro per Issue.

---

## 6. Ryzyka i watch-outs

| # | Ryzyko | Mitigacja |
|---|---|---|
| R1 | Redis na Windows nie chodzi out-of-the-box | Pre-flight w D13 — Memurai (drop-in) lub WSL2 redis-server. Zapisać wybrany w body Issue D13. |
| R2 | Celery worker prefork na Windows wywala `PermissionError` | `--pool=solo` jako default w README dev section. Dokumentacja w D15 explicit. |
| R3 | Celery + Twisted reactor (Scrapy) konflikt event loops | M1 retro #8 lekcja — trzymać scraping w **subprocess** z `manage.py scrape_character`. Worker nie sees Twisted wcale. Decyzja w sekcji 3 i AC D16. |
| R4 | `django-celery-beat` migrations na bazie z M2 | AC D13 explicit `migrate`. Jeśli ktoś robi merge z innego brancha — `migrate django_celery_beat` w pre-merge checklist. |
| R5 | Race między dwoma fires Beat'a | Freshness threshold w taska (`last_scraped_at` < 30min → skip). AC D16, Pułapka C. |
| R6 | `CELERY_TASK_ALWAYS_EAGER=True` w testach maskuje serializacji broker↔worker (np. niezerializowalny argument task'a) | OK dla M3 (logika prosta, tylko strings i ints). Real-broker tests post-M3 jeśli kiedyś task ma złożone arg/return. |
| R7 | Subprocess overhead 0.5-1s/postać blokuje workera w pool=solo | Akceptowalne dla M3 watchlist <100 postaci + interval godzinowy. Komentarz w docstring task'a. Skalowanie: prefork w prod Docker. |
| R8 | `os.environ.setdefault("DJANGO_SETTINGS_MODULE")` zapomniane | AC D14 explicit. Bez tego ImproperlyConfigured przy starcie workera. |

---

## 7. Test strategy

- **Unit:** Celery tasks z `CELERY_TASK_ALWAYS_EAGER=True`, mock subprocess. Pokrycie ścieżek: success, subprocess failure, freshness skip, empty watchlist.
- **Integration (D17):** trigger task `apply()` synchronicznie, assert side effects w DB. Brak hitów na live broker (CI nie odpala Redis service).
- **e2e manual:** poza CI, by-the-book ręczna weryfikacja Beat → Worker → Subprocess → DB.
- **Brak hitów na live Tibiantis** w testach (CLAUDE.md §11) — subprocess mockowany na poziomie taska. Spider sam ma fixturki HTML (już w M1).
- **Coverage threshold = 70%** (po PR #51). Jeśli M3 obniży poniżej 70 — dopisać testy, nie obniżyć threshold (CLAUDE.md §15.13).

---

## 8. Definition of Done (M3)

- [ ] 5 PR merged, 5 Issues zamknięte
- [ ] `celery -A config worker -P solo` startuje, podpięty do Redis
- [ ] `celery -A config beat` startuje, podpięty do `DatabaseScheduler`
- [ ] `PeriodicTask("scrape_watched_characters")` enableable w admin, scrape'uje Character.objects.all() co interval
- [ ] Subprocess `scrape_character` aktualizuje `Character.last_scraped_at`
- [ ] Freshness threshold działa (skip jeśli < 30min od ostatniego scrape)
- [ ] Wszystkie pre-commit + CI zielone na master
- [ ] `coverage threshold = 70` zachowane
- [ ] PROGRESS.md: "🎉 M3 COMPLETED" + retro per Issue
- [ ] Milestone M3 zamknięty na GitHub

---

## 9. Zamrożony scope

Nowe pomysły poza sekcją 2 (Discord webhook, Bedmage tracker, Deaths spider, Mongo logging, Flower monitoring UI, real-broker integration tests) = osobne Issues post-M3 lub kolejne milestones (M4+). **Nie dorzucamy w trakcie milestone'u.**

Specjalnie wymienione "kuszące dodatki" które ODRZUCAMY:
- ❌ **Flower** (Celery monitoring UI) — kuszący, ale to dev tool, nie feature. Post-M3 jeśli okaże się potrzebny.
- ❌ **Sentry / error tracking** — wartościowe, ale to cross-cutting concern, osobny milestone.
- ❌ **Pusze webhooky Discord** — wymaga modelu `DiscordChannel` + bot infrastructure, M5+.
- ❌ **`asyncio` Celery tasks (Celery 6 alpha)** — niestabilne, sync tasks wystarczą dla M3.

---

## 10. Pre-flight checklist (przed startem D13)

- [ ] Redis lokalnie działa (`redis-cli ping` → `PONG`).
- [ ] **Wybór: Memurai vs WSL2** zapisany w body Issue D13.
- [ ] `poetry add celery redis django-celery-beat --dry-run` zwraca OK (brak konfliktu z Django 6, simplejwt, strawberry-django).
- [ ] `poetry run python -c "import celery; print(celery.__version__)"` po dodaniu — sanity że poetry venv widzi celery.
- [ ] `M3 GitHub milestone` utworzony, 5 Issues z linkami do tego spec'a.
