# M9 — Dockeryzacja + prod-ready — Implementation plan

**Data:** 2026-05-15
**Spec:** [`docs/superpowers/specs/2026-05-15-m9-dockerization-design.md`](../specs/2026-05-15-m9-dockerization-design.md)
**Status:** READY (spec accepted, decyzje §3.1-3.7 zaakceptowane przez developera 2026-05-15).

---

## Źródła

- **CLAUDE.md** §2 (Django 6.0 + Gunicorn WSGI, ASGI uvicorn YAGNI), §10 (Docker stack, multi-stage Dockerfile, 7 services + healthchecki + volumes, `.env` strategy), §13.2 (`docker.yml` workflow template z `docker/metadata-action@v5` + `docker/build-push-action@v6`), §15 reguła #1 (nie modyfikuj stosu bez zgody — gunicorn jako nowa prod dep wymaga note'y w spec'u).
- **Design spec M9** — kluczowy dokument referencyjny. Każdy issue body linkuje do spec'a §X.
- **Precedensy z M0-M8:**
  - **M0-D3** — pre-commit `gitleaks` blokuje commits z secret'ami (wartości w `.env` real, w `.env.example` blank). M9 dorzuca komentarz "Operator wypełnia" do każdego sekretu w `.env.example`.
  - **M0-D2** — `docker-compose.dev.yml` z postgres+redis+mongo + healthchecki. M9 prod compose **extends** ten pattern dla 4 app services (web/celery_worker/celery_beat/discord_bot).
  - **M2-D11** — `config/urls.py` routing zaprojektowany z `apps.accounts.urls` jako template. M9 dorzuca `path("health/", include("apps.core.urls"))`.
  - **M3-D17** — Celery worker uruchamiany lokalnie przez `poetry run celery -A config worker -l info -P solo` (Windows pool fix, `feedback_celery_windows_pool` memory). M9 w Linux container używa **default prefork pool** — `-P solo` to Windows dev only, NIE w Dockerfile CMD.
  - **M3-D17** — `django-celery-beat` DB-backed scheduler (`--scheduler django_celery_beat.schedulers:DatabaseScheduler` w command). M9 `celery_beat` service używa tego samego scheduler'a.
  - **M5-D24** — `services.py` type-hint convention: direct `from apps.accounts.models import User` (memory `feedback_services_user_type_hint`). M9 `apps/core/health.py` nie używa User (DB cursor + Redis raw client), no relevance.
  - **M6-D28** — graceful disable handlers przy braku resource (empty `MONGO_URL` → `NullHandler`, eager resource lookup w `__init__` to pułapka). M9 `health.py` używa lazy `redis.Redis.from_url(...)` per request (no eager singleton).
  - **M6 retro lekcja #2** — `propagate: True` na named logger keeps pytest caplog working. M9 `apps/core/health.py` używa `logging.getLogger(__name__)` = `apps.core.health` — propagacja do root → Mongo dispatch via M6.
  - **M7-D31** — pierwszy top-level Django app (`discord_bot/` — bez `apps.` prefix). M9 `apps/core/` to **standardowy nested app pod `apps/`** (jak `apps/notifications/`, NIE jak `discord_bot/`). Powód: `apps/core/` nie ma modeli ani `migrations/`, tylko view + urls + tests. `LOCAL_APPS = [..., "apps.core"]` (z `apps.` prefix).
  - **M7-D32** — django-environ `env.int(...)` z empty env var crashuje (Pułapka H). M9 `.env.example` musi mieć komentarz "Operator wypełnia" przy każdym **wymaganym** secrecie, inaczej `env("DJANGO_SECRET_KEY")` crashuje przy `docker compose up` jeśli operator skopiuje `.env.example → .env` bez fill-in.
  - **M7-D32** — Python range narrowing `>=3.13,<3.14` w `pyproject.toml`. M9 Dockerfile używa `python:3.13-slim-bookworm` (matching).
  - **M7-D33 + hotfix #124** — manual smoke jest jedyną siecią dla py-cord cogów. M9 manual smoke (D44 closure) jest jedyną siecią dla **full Docker stack** (Dockerfile build + 7 services up + healthchecki green + ghcr.io push). Nie testujemy real deploy.
  - **M8-D36** — `httpx` jako direct dep z tighter pin `(>=0.28.1,<0.29.0)` zamiast spec'owego `(>=0.27,<1.0)`. M9 `gunicorn` analogicznie: spec mówi `(>=23.0,<24.0)`, faktyczna wersja zalezna od `poetry add gunicorn` z najnowszego dostępnego release'a.
  - **M8-D37/D38 lazy import dla pre-commit mypy isolated venv** — `from apps.notifications.discord_client import DiscordRESTClient` inside `notify()` zamiast top-level. M9 `health.py` używa `import redis` top-level — `redis` jest już direct dep z M5, więc mypy isolated venv ma stub'y (no lazy import needed). Verify: `pre-commit run mypy --files apps/core/health.py` po implementacji.
  - **M8-D40 pattern: feature PR + closure PR w 1 issue** (M5-D27 + M6-D30 + M7-D35 lineage). M9-D44 powtarza pattern: feature PR (`feat/<#>-docker-ci`) + closure PR (`docs/close-m9-dockerization`).
  - **M5-D27 + M6-D30 + M7-D35 + M8-D40 closure pattern** — `git checkout master && git pull && git checkout -b docs/close-mN-...` PRZED PROGRESS.md edycją (Pułapka C utrwalona przez 5 milestone'ów).

---

## Pre-flight checklist (przed startem D41)

- [ ] **`apps/notifications/` istnieje** — sprawdzone 2026-05-15 (z M5). M9 dorzuca **siostrzany** `apps/core/` (osobny, no shared code).
- [ ] **`docker-compose.dev.yml` istnieje** — sprawdzone 2026-05-15, ma postgres+redis+mongo + healthchecki. M9 prod compose **NIE zastępuje** dev compose — oba pliki coexist. Operator wybiera `docker compose -f docker-compose.dev.yml` (dev) lub `docker compose -f docker-compose.yml` (prod).
- [ ] **`pyproject.toml` — `gunicorn` NIE jest jeszcze dependencją** — sprawdzone 2026-05-15 (po `grep gunicorn pyproject.toml` empty). M9-D42 dorzuca jako `gunicorn (>=23.0,<24.0)` w osobnym `build(deps)` commit.
- [ ] **`pyproject.toml` — `redis (>=7.4.0,<8.0.0)` JUŻ jest direct dep** — sprawdzone 2026-05-15 (`pyproject.toml:22`, z M5). M9 NIE dorzuca redis ponownie.
- [ ] **`config/settings/prod.py` istnieje** — sprawdzone 2026-05-15, minimal (`from .base import *` + `DEBUG = False`). M9 Dockerfile ustawia `ENV DJANGO_SETTINGS_MODULE=config.settings.prod`.
- [ ] **`.env.example` exists** — sprawdzone 2026-05-15 (37 linii). M9-D43 aktualizuje na Docker hostnames (`postgres`/`redis`/`mongo`) zamiast `localhost`.
- [ ] **`.github/workflows/ci.yml` istnieje** — sprawdzone 2026-05-15 (jedyny workflow w repo). M9-D44 dorzuca `docker.yml` jako **drugi** workflow (no zmiany w `ci.yml`).
- [ ] **`docker buildx` available** — wymagane dla `docker/build-push-action@v6` w CI (multi-platform support, layer cache). Local sanity: `docker buildx version` na laptopie. Docker Desktop ma buildx built-in.
- [ ] **`gh auth status` z `repo` + `write:packages` scopes** — wymagane dla `ghcr.io` push z GHA. CI używa `GITHUB_TOKEN` z auto-generowanego scope (per workflow `permissions: contents: read, packages: write`).
- [ ] **PROCESS: pre-commit `no-commit-to-branch` hook** (PR #105 M5) — blokuje commits na master. **Każdy D-task wymaga `git checkout -b feat/<#>-...` PRZED kodowaniem** (CLAUDE.md §12).
- [ ] **PROCESS: `pre-commit clean` przed `# type: ignore` na nowych mypy errors** (M7 retro lekcja #3) — stale cache po fresh `gunicorn` install może false-positive'ować. `poetry run pre-commit clean` przed flagowaniem nowych errors jako blocker.

---

## Otwarte pytania (rozstrzygnięte 2026-05-15, spec §3)

Wszystkie 7 decyzji designowych ze spec'a §3 zaakceptowane bez modyfikacji:

1. ✅ **§3.1** Dockerfile multi-stage z `poetry export → requirements.txt` w builder (odstąpienie od CLAUDE.md §10 "no requirements.txt" — kontekst BUILD stage, nie dev workflow).
2. ✅ **§3.2** Gunicorn WSGI dla `web` (`--workers 2 --threads 2 --timeout 60`). Uvicorn ASGI to YAGNI.
3. ✅ **§3.3** Per-service healthchecki (8 services włącznie z `migrate`, ale `migrate` nie ma healthcheck — one-shot exit). `discord_bot` świadomie BEZ healthcheck (restart policy wystarcza).
4. ✅ **§3.4** Migration jako osobny one-shot service `migrate` z `service_completed_successfully` dependency dla `web`.
5. ✅ **§3.5** Rolling `:master` tag + `:sha-<commit>` audit. Semver `:v1.2.3` to M-future.
6. ✅ **§3.6** `env_file: .env` strategy. Docker secrets / Vault to M-future.
7. ✅ **§3.7** Non-root user `app` (UID 1000) w runtime stage. Distroless image to M-future.

**Open questions z §11** (do M9 retro, NIE w M9 scope):
- `STATIC_URL` / collectstatic — admin SSH tunnel workflow w M9, WhiteNoise w M10
- Image size target (150-200MB target, hard data po D42)
- Image scanning (Trivy/Snyk) — kandydat na M10
- `web:8000` exposed `ports:` vs `expose:` — M9 daje `ports:` dla local smoke, M-future + nginx zmienia
- Celery beat scheduler choice — `django-celery-beat` DB-backed zostaje (M3-D17 setup, no change w M9)

---

## Risk + mitigation

| Ryzyko | Prawdopodobieństwo | Impact | Mitigation |
|---|---|---|---|
| **`gunicorn` resolver pulls niezgodne `setuptools`/`packaging`** | Niskie (gunicorn ma stable ~10+ years deps) | `poetry add` fails, blokuje D42 start | Spec specifies `gunicorn (>=23.0,<24.0)` jako stable range. Verify: `poetry add gunicorn; poetry show gunicorn` — sanity check no transitive conflict z httpx/celery deps. |
| **`poetry export` plugin missing w fresh Poetry 2.x install** | Wysokie (Poetry 2.0+ wyłączył `export` jako built-in, wymaga `poetry-plugin-export`) | `poetry export` w Dockerfile builder fail | Dockerfile builder explicit `pip install "poetry==${POETRY_VERSION}" "poetry-plugin-export>=1.8"`. Bez tego export rzuci "command not found". |
| **`apt-get install curl` w runtime stage zwiększa image size** | Średnie | Image +20-30MB (curl + deps) | Trade-off accepted — curl jedyna stabilna opcja dla HEALTHCHECK CMD. Alternative: użyć Python httpx w HEALTHCHECK (`CMD python -c "import httpx; httpx.get('http://localhost:8000/health/').raise_for_status()"`) — zachowa rozmiar, ale wolniejsze (Python interpreter startup ~200ms vs curl ~20ms). Decyzja: zostać przy curl, audit rozmiaru po D42 manual smoke (sanity point #2). |
| **`mypy strict + redis.Redis missing stubs`** | Wysokie (redis-py od 5.x ma własne stub'y, ale isolated venv może nie widzieć) | `pre-commit run mypy --files apps/core/health.py` red | `pre-commit clean` przed flagowaniem (M7 retro lekcja #3). Jeśli nadal red — dorzucić `types-redis` do `[tool.poetry.group.dev.dependencies]` w D41. NIE dodawać `# type: ignore` jako pierwszą reakcję. |
| **`docker compose up` deadlock — wszystkie services czekają na siebie** | Niskie (depends_on ma directed acyclic chain) | Cały stack hang, manual `docker compose down` | Spec §3.4 chain: `postgres+redis+mongo` → `migrate` → `web` → reszta. Bez cykli. Sanity: `docker compose config --quiet` (walidacja YAML + chain) w D43 PR przed merge. |
| **Healthcheck `web` curl fails bo gunicorn startuje wolno** | Średnie (60s start_period to luźna estymata) | Service flapuje `starting → unhealthy`, restart loop | Spec §3.3: `start_period: 60s` daje margines. Manual smoke D43: ile faktycznie trwa od container start do `curl /health/` 200? Jeśli > 60s, bump na 90s. Jeśli < 30s, można obniżyć. Empiryczne po D43 manual smoke. |
| **`celery_beat` healthcheck pidfile race** | Średnie (pidfile może nie istnieć przez pierwsze ~5s po start) | Healthcheck fails podczas startup | `start_period: 60s` + `command: celery -A config beat --pidfile=/tmp/celerybeat.pid --schedule=/tmp/celerybeat-schedule --scheduler ...`. Beat tworzy pidfile w ~1s. Healthcheck retries 3x z 30s interval = 90s tolerance po `start_period`. |
| **`ghcr.io push` fails — auth scope missing** | Średnie przy pierwszym setup | Workflow red, image NIE w registry | Spec §13.2 i M9-D44 issue body explicit: `permissions: { contents: read, packages: write }` w workflow + `username: ${{ github.actor }} password: ${{ secrets.GITHUB_TOKEN }}` w login-action. Brak custom PAT (auto-token wystarcza). Verify: workflow run logs pokazują "Login Succeeded" przed push. |
| **`.env` w container empty/missing przy `docker compose up`** | Wysokie przy pierwszym deploy (operator nie ma `.env`) | Cały stack crashuje na `env("DJANGO_SECRET_KEY")` (django-environ default behavior — raise) | `.env.example` ma `# Operator MUSI wypełnić` komentarz przy każdym wymaganym secrecie. Plus `docker compose up` bez `.env` rzuca explicit error "env file .env not found". |
| **Migration race podczas operator restart** | Niskie (Postgres ma migration locks via `django_migrations` table) | Dwa `migrate` services próbują równocześnie | Django `migrate` używa Postgres advisory locks. Drugi `migrate` czeka albo no-op (`No migrations to apply`). Akceptowalne. |
| **CI workflow podwójnie triggered (pull_request + push to master)** | Średnie | 2× build = 2× GHA minutes spent | Spec §13.2 ma `concurrency: cancel-in-progress`. M9 `docker.yml` dorzuca same `concurrency` group. Plus `push:` trigger explicit `branches: [master]` + `tags: ["v*"]`. PR-only build (na branch !master) NIE pushuje. Net: PR build (verify) + master merge build+push = 2 builds per merge, akceptowalne. |
| **`migrate` service zamknięty z exit 1 (legitimate migration error)** | Niskie (M0-M8 migracje testowane lokalnie) | `web` nie startuje (`service_completed_successfully` not met) | Spec §6.2: operator widzi `docker compose logs migrate` → fix migration lokalnie → rebuild image → retry. Brak auto-rollback (M-future). |
| **D43 compose manual smoke wymaga `.env` z real Discord token** | Średnie (operator może nie mieć dev guild ready) | D43 manual smoke punkt #2 incomplete | D43 issue body explicit: jeśli brak `DISCORD_BOT_TOKEN`, `discord_bot` service nie startuje OK (gateway connection fail). Akceptowalne dla manual smoke — `docker compose ps` pokazuje 6/7 healthy + 1 restarting. Real token only dla post-merge prod deploy. |

---

## Task overview

| # | ID | Tytuł | Czas | Zależy od | Branch |
|---|---|---|---|---|---|
| 1 | M9-D41 | `apps/core` healthcheck app + `/health/` endpoint + 4 testy | 2-3h | M8 closed | `feat/<#>-health-endpoint` |
| 2 | M9-D42 | Multi-stage `Dockerfile` + `.dockerignore` + `gunicorn` dep + local container smoke | 3-4h | D41 merged | `feat/<#>-dockerfile` |
| 3 | M9-D43 | Production `docker-compose.yml` + 7 services + migrate one-shot + healthchecki + `.env.example` Docker hostnames | 3-4h | D42 merged | `feat/<#>-prod-compose` |
| 4 | M9-D44 | `docker.yml` CI workflow (build + push ghcr.io) + M9 e2e (full stack smoke) + closure (PROGRESS.md retro + milestone close) | 3-4h | D43 merged | `feat/<#>-docker-ci` + `docs/close-m9-dockerization` |

**Total:** ~11-15h, ~3 dni roboczych. Mieści się w 16h M9 budget (4 dni × 4h).

---

## Task #1 — [M9-D41] `apps/core` healthcheck app + `/health/` endpoint + 4 testy

### 🎯 Cel

Utworzyć nowy nested Django app `apps/core/` z minimalnym scope: `apps.py` (`CoreConfig`), `health.py` (view `health_check` zwracający 200 + `{"db": "ok", "redis": "ok"}` po sprawdzeniu DB cursor + Redis ping; 503 + `{"db": "fail"|"ok", "redis": "fail"|"ok", "error": "..."}` przy fail), `urls.py` (`path("", health_check)`). Dorzucenie `path("health/", include("apps.core.urls"))` w `config/urls.py` + `"apps.core"` w `LOCAL_APPS`. 4 unit testy w `apps/core/tests/test_health.py`. Po D41: endpoint `/health/` osiągalny lokalnie (`poetry run python manage.py runserver`, `curl http://localhost:8000/health/` → 200), gotowy do użycia w Docker HEALTHCHECK w D42.

### 🧠 Czego się nauczysz

- **Minimal Django app structure** — `apps/core/` to **drugi** nested app bez modeli i migracji (po `apps/notifications/` z M5). Tylko `apps.py` + view + urls + tests. Pattern dla cross-cutting concerns (utils, health checks, monitoring endpoints).
- **`@require_GET` decorator** — Django built-in `from django.views.decorators.http import require_GET` ogranicza view na metody HTTP (POST/PUT/DELETE → 405 Method Not Allowed). Defensywne dla health endpoint — load balancer'y i Docker HEALTHCHECK używają GET, ale klient może wysłać POST przez pomyłkę.
- **`django.db.connection.cursor()` jako sync DB check** — niski koszt (~1-2ms), sprawdza ze połączenie z PG działa + uprawnienia. `cursor.execute("SELECT 1")` to canonical "ping" dla relational DBs. Wyłapuje `OperationalError` gdy PG down lub auth fail.
- **`redis.Redis.from_url(url).ping()` jako sync Redis check** — `redis-py` (już direct dep z M5) ma synchronous `ping()` method. `socket_timeout=2` defensive (~2s max wait jeśli Redis nie odpowiada). Rzuca `ConnectionError`/`TimeoutError` — handled.
- **`JsonResponse` z explicit `status=`** — Django default status=200, można nadpisać `status=503` dla unhealthy. Body zostaje JSON, content-type `application/json` auto.
- **`pytest-django` mocking DB/Redis przez `unittest.mock.patch`** — D41 testy mockują `django.db.connection.cursor` i `redis.Redis.from_url` żeby symulować fail bez crashowania real DB/Redis. Pattern: `mock.patch("django.db.connection.cursor", side_effect=OperationalError("simulated"))`.

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m9-d41.md`.)

**Kluczowe punkty:**

- `apps/core/__init__.py` — empty.
- `apps/core/apps.py`:
  ```python
  from django.apps import AppConfig

  class CoreConfig(AppConfig):
      default_auto_field = "django.db.models.BigAutoField"
      name = "apps.core"
  ```
- `apps/core/health.py` — view `health_check(request) -> JsonResponse` z `@require_GET` dekoratorem, sprawdza DB (cursor.execute "SELECT 1") + Redis (Redis.from_url(REDIS_URL, socket_timeout=2).ping()), zwraca 200 z `{"db": "ok", "redis": "ok"}` lub 503 z `{"db": "fail"|"ok", "redis": "fail"|"ok", "error": str}`. Pełna sygnatura w spec §4.1.
- `apps/core/urls.py` — `urlpatterns = [path("", health_check, name="health-check")]`.
- `config/urls.py` — dorzucenie `path("health/", include("apps.core.urls"))`. Sanity: `curl http://localhost:8000/health/` (NIE `/health` bez slash — Django default `APPEND_SLASH=True` redirect'uje, ale Docker HEALTHCHECK powinien hit'ować final URL bezpośrednio).
- `config/settings/base.py` — `LOCAL_APPS` rozszerzone o `"apps.core"`.
- `apps/core/tests/test_health.py` — 4 tests:
  - `test_health_returns_200_when_db_and_redis_ok` — happy path, JSON shape `{"db": "ok", "redis": "ok"}`, status 200, content-type application/json.
  - `test_health_returns_503_when_db_fails` — mock `connection.cursor` → `OperationalError("connection refused")`, expects 503 + `"db": "fail"` + `"error"` containing "connection refused".
  - `test_health_returns_503_when_redis_fails` — mock `redis.Redis.from_url(...).ping()` → `ConnectionError("Connection refused")`, expects 503 + `"redis": "fail"`.
  - `test_health_response_shape_keys_locked` — JSON keys lock test (forward-compat dla M-future Mongo/Celery checks): assert keys w response są subset `{"db", "redis", "error"}`.
- Coverage `apps/core/health.py` ≥ 95%.

### ⚠️ Pułapki do uwagi

- **A — `LOCAL_APPS = [..., "apps.core"]` z `apps.` prefix.** Nie `"core"` (top-level top-level jak `discord_bot/`). `apps/core/` to **nested** app pod `apps/`, `INSTALLED_APPS` musi mieć dotted path `apps.core`. Bez tego Django `apps.get_app_config("core")` rzuca `LookupError`.
- **B — `apps/core/apps.py CoreConfig.name = "apps.core"`** — nie `"core"`. Spójność z M5/M6/M7 nested apps. Jeśli zostawisz `"core"`, Django startup crash z `LookupError: No installed app with label 'apps'`.
- **C — `redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2)`** — `socket_timeout` jest kluczowe. Bez niego, gdy Redis down + DNS resolves → `ping()` może wisieć 30s na default TCP timeout. Healthcheck musi return w < 5s (HEALTHCHECK `timeout=5s` w Dockerfile).
- **D — `from django.db import OperationalError` w except** — NIE `psycopg.OperationalError`. Django ORM wraps DBAPI exceptions w własną hierarchie. `OperationalError` z `django.db` to canonical exception.
- **E — `JsonResponse` body order** — Python dict order to insertion order (3.7+), więc `{"db": "ok", "redis": "ok"}` JSON renderuje keys w tej kolejności. Testy assertujące JSON shape powinny używać `json.loads()` + dict comparison, NIE string comparison (bo whitespace/key order może się różnić od assumed).
- **F — `@require_GET` dekorator import** — `from django.views.decorators.http import require_GET`. Nie `require_http_methods(["GET"])` (works ale verbose). `require_GET` to canonical.
- **G — mypy + `redis.Redis.from_url`** — redis-py 5.x ma własne stub'y (`from redis import Redis`). Jeśli pre-commit mypy zgłosi `Cannot find implementation`, najpierw `poetry run pre-commit clean` (M7 retro). Dopiero jeśli nadal red — dorzucić `types-redis (>=4.6.0,<5.0.0)` do `[tool.poetry.group.dev.dependencies]` w tym samym PR.
- **H — `connection.cursor()` context manager** — `with connection.cursor() as cursor: cursor.execute("SELECT 1")`. Bez `with`, cursor pozostaje open → potential connection leak w test'ach (`pytest-django` reuse connection).
- **I — Test mocking `connection.cursor` to mock context manager**, nie raw function. `mock.patch.object(connection, "cursor")` zwraca MagicMock; configure `mock_cursor.return_value.__enter__.return_value.execute.side_effect = OperationalError(...)` — ale prościej: `mock.patch("django.db.connection.cursor", side_effect=OperationalError(...))` — wtedy `connection.cursor()` calls side_effect → raises bezpośrednio (no context manager entry). Test obu wariantów.

### 🧪 Testing plan

```bash
# Unit testy
poetry run pytest apps/core/tests/test_health.py -v

# Coverage
poetry run pytest apps/core/tests/ --cov=apps.core.health --cov-report=term-missing

# Smoke manual
poetry run python manage.py runserver
# w drugim terminalu:
curl -i http://localhost:8000/health/
# expected: HTTP/1.1 200 OK, Content-Type: application/json, body {"db": "ok", "redis": "ok"}

# Failure mode smoke (zatrzymaj postgres)
docker compose -f docker-compose.dev.yml stop postgres
curl -i http://localhost:8000/health/
# expected: HTTP/1.1 503, body {"db": "fail", "redis": "ok", "error": "..."}
docker compose -f docker-compose.dev.yml start postgres
```

**Coverage cel:** `apps/core/health.py` ≥ 95%.

### 📦 Definition of Done

- [ ] AC spełnione (4 tests passing, manual smoke 200 + 503).
- [ ] PR zmergowany squash (`feat(core): add /health/ endpoint with DB + Redis ping (M9-D41, #<#>)`).
- [ ] CI lint + test zielone.
- [ ] `apps/core/health.py` coverage ≥ 95%.
- [ ] Healthcheck endpoint testable z laptopu (manual smoke confirmed).

---

## Task #2 — [M9-D42] Multi-stage `Dockerfile` + `.dockerignore` + `gunicorn` dep + local container smoke

### 🎯 Cel

Dorzucić `gunicorn` jako prod dependency w osobnym `build(deps)` commit. Utworzyć `Dockerfile` multi-stage (builder + runtime) zgodny ze spec §3.1: builder stage instaluje poetry + poetry-plugin-export, exportuje `poetry.lock → requirements.txt`, `pip install --user`; runtime stage używa `python:3.13-slim-bookworm`, dorzuca curl dla HEALTHCHECK, tworzy non-root user `app` (UID 1000), COPY z builder, COPY app code, `EXPOSE 8000`, `HEALTHCHECK` curl `/health/`, `CMD gunicorn config.wsgi:application`. Plus `.dockerignore` excluding `.git`, `.venv`, `__pycache__`, `tests/`, `docs/`, `.env*`, scratch files. Po D42: `docker build -t tibiantis:dev .` exit 0, image size ~150-200MB, `docker run --rm tibiantis:dev python manage.py check` exit 0.

### 🧠 Czego się nauczysz

- **Multi-stage Dockerfile semantics** — `FROM X AS builder` + `FROM X AS runtime` + `COPY --from=builder` daje layered build, tylko `runtime` ląduje w final image. Builder layers (poetry, build deps) discarded → mniejszy final image. Standard pattern dla Python apps.
- **`pip install --user` w builder + COPY `/root/.local`** — `--user` instaluje w `~/.local/`, łatwe do COPY do runtime userspace. Trade-off: ścieżki binary muszą być w `PATH` (`/home/app/.local/bin`). Plus dyrektywy `--chown=app:app` przy COPY zapewniają non-root ownership.
- **`HEALTHCHECK` Dockerfile instruction** — Docker built-in (zob. `HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=3 CMD curl ...`). Container status `healthy` widoczny w `docker ps`. Healthcheck command exit code: 0=healthy, 1=unhealthy, 2=reserved.
- **Non-root user pattern** — `RUN useradd --create-home --shell /bin/bash --uid 1000 app` + `USER app`. UID 1000 to typical Linux user (matches host user na większości distrosach), eliminuje host volume permission issues.
- **`.dockerignore` semantyka** — analogiczne do `.gitignore`, ale dla `docker build` context. Excludes wykluczone z `COPY . /app` → mniejszy build context (faster transfer to daemon), brak secrets w image, brak `.git` (16MB+).
- **Poetry 2.x export plugin** — w Poetry 1.x export był built-in. Poetry 2.0+ wymaga `poetry-plugin-export` jako separate install. Bez tego `poetry export` rzuca "command not found".
- **Layer caching strategy** — `COPY pyproject.toml poetry.lock ./` PRZED `COPY . /app` w builder oznacza, że zmiana w kodzie nie unieważnia poetry install cache (deps install reuse'uje warstwy z poprzedniego buildu).

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m9-d42.md`.)

**Kluczowe punkty:**

- **Dependency commit (osobny):**
  - `poetry add "gunicorn (>=23.0,<24.0)"` — dorzuca do `[project.dependencies]`.
  - Sanity: `poetry show gunicorn` — verify version w zakresie + no transitive conflict z django/celery.
  - Osobny commit `build(deps): add gunicorn for prod WSGI server (M9-D42, #<#>)`.

- **`Dockerfile`** — pełna zawartość ze spec §3.1 (cytuj literally). Multi-stage builder + runtime, non-root user `app` UID 1000, HEALTHCHECK curl `/health/`, CMD gunicorn.
- **`.dockerignore`** — excludes:
  ```
  .git
  .gitignore
  .venv
  __pycache__
  *.pyc
  *.pyo
  .pytest_cache
  .mypy_cache
  .ruff_cache
  tests/
  docs/
  .env
  .env.*
  !.env.example
  .idea/
  .vscode/
  .claude/
  *.md
  !README.md
  *.log
  ```
- **Local smoke (w PR description):**
  - `docker build -t tibiantis:dev .` → exit 0.
  - `docker image ls tibiantis:dev` → image size raport. Target ~150-200MB. Jeśli > 300MB, audit warstw (potencjalnie `apt-get` `--no-install-recommends` missing, builder layers leak).
  - `docker run --rm -e DJANGO_SECRET_KEY=test -e DATABASE_URL=sqlite:///:memory: tibiantis:dev python manage.py check` → exit 0 + "System check identified no issues".
  - `docker inspect tibiantis:dev --format '{{.Config.User}}'` → `app` (non-root verified).

### ⚠️ Pułapki do uwagi

- **A — `poetry-plugin-export` MUSI być explicit installed** w builder stage. Poetry 2.x wyłączył `poetry export` jako built-in. Bez `pip install "poetry-plugin-export>=1.8"`, `poetry export` rzuca "command not found". Spec §3.1 ma to w Dockerfile.
- **B — `requirements.txt` w builder jest TRANSIENT** — NIE commituj do repo. Jeśli przypadkowo commit'niesz, dorzuć do `.gitignore`. Trade-off: trzymamy go tylko w builder layer, runtime nie ma `requirements.txt`.
- **C — `apt-get install curl` w runtime musi mieć `&& rm -rf /var/lib/apt/lists/*`** — cache APT zwiększa image o ~10MB. Standard cleanup w Docker recipes.
- **D — `--no-install-recommends` flag w `apt-get`** — bez tego curl ciągnie recommended packages (~5-10MB transitive). Zawsze dorzucaj dla slim images.
- **E — `COPY --chown=app:app . /app` to wolniejsze niż `COPY . /app && chown -R`** — kompromis: chown w trakcie COPY działa w jednym kroku (no separate RUN layer), `chown -R` to dodatkowy layer. Wybieramy `--chown=` (less layers = smaller image).
- **F — `EXPOSE 8000` to dokumentacja, NIE actual port mapping** — to tylko hint dla `docker run -P`. Real port binding w compose `ports: ["8000:8000"]`. Bez EXPOSE wszystko działa, ale `docker inspect` nie pokaże intended port.
- **G — `HEALTHCHECK --start-period=60s` musi pokrywać Django startup + DB connect** — gunicorn `--workers 2` startuje ~3-5s, ale pierwsze GET `/health/` ciągnie DB pool + Redis client init → +20-40s. 60s daje margines. Empiryczne tuning po D43 manual smoke.
- **H — `CMD ["gunicorn", "config.wsgi:application", ...]` syntax — exec form (JSON array)**, nie shell form. Exec form NIE używa `sh -c ...` wrappera, więc PID 1 to gunicorn directly (signal handling: `SIGTERM` w `docker stop` → gunicorn graceful shutdown). Shell form (`CMD gunicorn ...`) wrap'uje w `sh`, PID 1 = sh, sygnały nie propagują.
- **I — `pip install --user --no-cache-dir`** — `--no-cache-dir` ważne, bez tego pip trzyma ~30-50MB w `/root/.cache/pip`. Builder cache discardujemy, ale defensive.
- **J — `.dockerignore` `.env*` z `!.env.example`** — wykluczamy real `.env` (secrets!), ale dorzucamy `.env.example` (template). Bez tego: albo `.env` w image (security disaster) albo brak `.env.example` w image (operator nie ma template'u).
- **K — `python:3.13-slim-bookworm` NIE `python:3.13-slim`** — explicit Debian codename (`bookworm` = Debian 12). Bez codename Docker pull latest, ale gdy Debian 13 wyjdzie i tag aliased zmieni się — break. Pin codename = reproducible builds.

### 🧪 Testing plan

```bash
# Build smoke
docker build -t tibiantis:dev .
docker image ls tibiantis:dev   # size sanity ~150-200MB

# Layer audit (optional, gdy size > target)
docker history tibiantis:dev --no-trunc

# Run smoke (no DB needed dla `manage.py check`)
docker run --rm -e DJANGO_SECRET_KEY=test -e DATABASE_URL=sqlite:///:memory: tibiantis:dev python manage.py check

# Non-root user verify
docker inspect tibiantis:dev --format '{{.Config.User}}'
# expected: app

# HEALTHCHECK config verify
docker inspect tibiantis:dev --format '{{.Config.Healthcheck.Test}}'
# expected: [CMD-SHELL curl -fsS http://localhost:8000/health/ || exit 1]
```

**Brak unit testów** (Dockerfile to infra, nie kod). Manual smoke w PR description.

### 📦 Definition of Done

- [ ] AC spełnione (Dockerfile builds, smoke passes, image size < 250MB target).
- [ ] PR zmergowany squash (2 commity: `build(deps)` gunicorn + `feat(docker)` Dockerfile/.dockerignore).
- [ ] CI lint + test zielone (test job NIE wymaga zmian — Dockerfile nie jest testowany w CI w D42, dopiero D44 wprowadzi docker.yml).
- [ ] Image size report w PR body (`docker image ls tibiantis:dev`).
- [ ] Non-root user confirmed (`docker inspect`).

---

## Task #3 — [M9-D43] Production `docker-compose.yml` + 7 services + migrate one-shot + healthchecki + `.env.example` Docker hostnames

### 🎯 Cel

Utworzyć `docker-compose.yml` (prod, **różny** od istniejącego `docker-compose.dev.yml`) z 7 application services + 1 one-shot `migrate` service. Hybrid `image: ghcr.io/...:master` + `build: .` dla D43 dev iteration (registry tag NIE istnieje przed D44 push). Healthchecki per service zgodnie ze spec §3.3. `depends_on` chain ze spec §3.4. Update `.env.example` na Docker DNS hostnames (`postgres`/`redis`/`mongo` zamiast `localhost`) + komentarze "Operator wypełnia" przy każdym sekrecie. Manual smoke "full stack up" w PR description (5 punktów ze spec §9, częściowy — punkt #5 ghcr.io push czeka na D44).

### 🧠 Czego się nauczysz

- **`docker-compose.yml` vs `docker-compose.dev.yml`** — różne pliki dla różnych workflowów. Operator wybiera `-f docker-compose.dev.yml` (DB only, app w `poetry run`) lub `-f docker-compose.yml` (full prod stack). Compose `-f` default to `docker-compose.yml`, więc prod jest default.
- **Hybrid `image:` + `build:` pattern** — gdy `image:` nie istnieje lokalnie ani w registry, compose fallback'uje na `build:` (per Compose v2.20+ spec). Pozwala lokalnie iterować bez registry, prod tylko pull.
- **`depends_on` z conditions** — `service_healthy` (czeka na healthcheck pass), `service_started` (czeka na container start, no healthcheck check), `service_completed_successfully` (czeka na one-shot service exit 0). Compose v2 syntax.
- **One-shot service pattern** — `restart: "no"` + command runs once + exits. `migrate` ma `service_completed_successfully` jako gate dla `web`. Idempotentne (migrate no-op gdy migracje up-to-date).
- **`celery_beat` PID file healthcheck** — Celery Beat tworzy pidfile (`--pidfile=/tmp/celerybeat.pid`), proces żyje. Healthcheck `test -f $PID && ps -p $(cat $PID)` verifies. Bez pidfile beat nie ma "isAlive" API.
- **`celery -A config inspect ping`** — Celery worker built-in inspection. Wysyła ping message przez broker (Redis), oczekuje pong od named worker. Identyfikuje hung workerów (proces żyje, ale nie consume'uje queue).
- **`env_file: .env` w compose** — Docker compose ładuje `.env` automatycznie + per-service `env_file:`. Single source of truth: `.env`.

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m9-d43.md`.)

**Kluczowe punkty:**

- **`docker-compose.yml`** (prod, w root repo) — 7 services + 1 `migrate`:
  - `postgres` (image `postgres:16-alpine`, healthcheck pg_isready, volume `postgres_data`, env_file `.env`)
  - `redis` (image `redis:7-alpine`, healthcheck redis-cli ping)
  - `mongo` (image `mongo:7`, healthcheck mongosh ping, volume `mongo_data`)
  - `migrate` (image `ghcr.io/bgozlinski/tibiantis-scraper:master` + `build: .`, command `python manage.py migrate --noinput`, depends_on postgres healthy, restart: "no")
  - `web` (same image + build, command `gunicorn ... --bind 0.0.0.0:8000 ...`, ports `["8000:8000"]`, depends_on postgres+redis healthy + migrate completed, healthcheck `curl /health/`)
  - `celery_worker` (same image + build, command `celery -A config worker -l info`, depends_on postgres+redis healthy, healthcheck `celery inspect ping`)
  - `celery_beat` (same image + build, command `celery -A config beat ...`, depends_on postgres+redis healthy, healthcheck pidfile)
  - `discord_bot` (same image + build, command `python manage.py run_discord_bot`, depends_on postgres+mongo healthy, brak healthcheck, `restart: unless-stopped`)
  - Volumes: `postgres_data`, `mongo_data` (volume named, deklarowane na końcu pliku).
- **`.env.example`** zaktualizowane:
  - `DATABASE_URL=postgres://tibiantis:tibiantis@postgres:5432/tibiantis` (był `localhost:5435`)
  - `REDIS_URL=redis://redis:6379/0` (był `redis://localhost:6379/0`)
  - `CELERY_BROKER_URL=redis://redis:6379/1` (analog)
  - `MONGO_URL=mongodb://mongo:27017` (był `localhost:27017`)
  - Komentarz nad każdym secret'em `# Operator MUSI wypełnić — generowane lub z dashboardu`:
    - `DJANGO_SECRET_KEY=` — przepis na generację w komentarzu (`python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`)
    - `DISCORD_BOT_TOKEN=` — link do Discord Developer Portal
    - `POSTGRES_PASSWORD=` — generowane lokalnie
- **Manual smoke w PR description** (punkty 1-4 ze spec §9; punkt #5 ghcr.io pull odroczony do D44):
  - `cp .env.example .env` + fill in real values
  - `docker compose -f docker-compose.yml up -d`
  - `docker compose ps` → wszystkie 7 services `Up healthy` po ≤90s (oprócz `migrate` które exit 0 po ~5s)
  - `docker compose logs migrate` → "Applying X..." lines, exit 0
  - `docker compose exec web curl -fsS http://localhost:8000/health/` → 200 + JSON
  - `docker compose exec web python manage.py showmigrations --plan | grep '\[ \]'` → empty (no pending)
  - `docker compose down -v` cleanup

### ⚠️ Pułapki do uwagi

- **A — `docker compose -f docker-compose.yml`** vs **`docker-compose.dev.yml`** — dwa różne pliki, dwa workflowy. Operator MUSI wiedzieć który użyć. README/dev runbook ma to opisać (post-M9).
- **B — `image: ghcr.io/.../master` + `build: .` hybrid** — przed D44 push do registry, `image:` tag nie istnieje. Compose najpierw spróbuje `docker pull` — fail (network/auth). Drugi fallback to `build:` z local Dockerfile. Sanity w D43: `docker compose -f docker-compose.yml build` (explicit build) PRZED `up -d`, żeby `up` od razu wziął cached image.
- **C — `depends_on` chain musi mieć directed acyclic graph** — bez cykli. Sanity: `docker compose config --quiet` (walidacja YAML + chain). Cykl rzuca "circular dependency detected".
- **D — `service_completed_successfully` wymaga Compose v2.20+** — verify lokalnie `docker compose version`. Docker Desktop 4.20+ ma to wbudowane.
- **E — `celery_beat` `--pidfile=/tmp/celerybeat.pid`** musi być EXPLICITLY w command. Bez `--pidfile` Celery beat nie zapisuje pidfile → healthcheck fails. Plus `--schedule=/tmp/celerybeat-schedule` (db-scheduler nie używa file ale Beat domyślnie zapisuje crontab tracking — explicit ścieżka żeby tmp był writable dla user'a `app`).
- **F — `celery_worker` healthcheck `celery -A config inspect ping`** wymaga `redis_url` accessible (broker). `depends_on redis: healthy` zapewnia. Healthcheck overhead ~3s per call — `interval: 30s` defensive (nie 10s).
- **G — `discord_bot` brak healthcheck** świadomy — long-running gateway connection bez exposed port. `restart: unless-stopped` policy + py-cord internal heartbeat wystarczy. M-future: dorzucić Mongo heartbeat write + healthcheck script reading Mongo collection.
- **H — `postgres` użytkownik i hasło w `.env`** — z M0 `POSTGRES_USER=tibiantis POSTGRES_PASSWORD=tibiantis`. Nadal tak (prod operator zmieni). M-future: rotation strategy.
- **I — `volumes:` declared TWICE** — raz per-service (`volumes: [postgres_data:/var/lib/...]`), raz top-level (`volumes: postgres_data:`). Bez top-level declaration, Compose używa anonymous volume (re-creates per `docker compose down`). Top-level = named, persists.
- **J — Compose default network** — Compose tworzy bridge network per project automatically. Wszystkie services mogą resolve'ować się po service name (`postgres`, `redis`, `mongo`). Bez explicit `networks:` declaration, default działa.
- **K — `.env.example` `DATABASE_URL=postgres://tibiantis:tibiantis@postgres:5432/tibiantis`** — `postgres` to **service name w compose**, nie `localhost`. W dev compose port `:5435` (host port avoid conflict z lokalnym PG), w prod compose port wewnętrzny `:5432` (no host port mapping required). Update `.env.example` musi pokazać prod hostname; comment "for dev use port 5435 with localhost".

### 🧪 Testing plan

```bash
# Validate YAML + chain
docker compose -f docker-compose.yml config --quiet
# expected: exit 0, no output (no errors)

# Build all (forces D43 dev iteration, before D44 push)
docker compose -f docker-compose.yml build

# Full stack up (wymaga .env z real secrets)
docker compose -f docker-compose.yml up -d

# Sanity (≤90s)
docker compose ps
# expected:
#   postgres    Up healthy
#   redis       Up healthy
#   mongo       Up healthy
#   migrate     Exited (0)
#   web         Up healthy
#   celery_worker  Up healthy
#   celery_beat    Up healthy
#   discord_bot    Up (no healthcheck) — może być Restarting jeśli DISCORD_BOT_TOKEN niepoprawny

# Migration verify
docker compose logs migrate | tail -20
docker compose exec web python manage.py showmigrations --plan | grep '\[ \]' || echo "All migrations applied"

# Health endpoint
docker compose exec web curl -fsS http://localhost:8000/health/

# Cleanup
docker compose -f docker-compose.yml down -v
```

**Brak unit testów** (compose to infra). Manual smoke w PR description.

### 📦 Definition of Done

- [ ] AC spełnione (compose validates, full stack up <= 90s, healthchecki green, /health/ 200).
- [ ] PR zmergowany squash (`feat(docker): production compose with 7 services + migrate one-shot (M9-D43, #<#>)`).
- [ ] CI lint + test zielone.
- [ ] Manual smoke 4 punkty (z 5 spec'owanych — punkt #5 odroczony do D44) w PR body.
- [ ] `.env.example` Docker hostnames + "Operator wypełnia" komentarze.

---

## Task #4 — [M9-D44] `docker.yml` CI workflow (build + push ghcr.io) + M9 e2e (full stack smoke) + closure

### 🎯 Cel

Utworzyć `.github/workflows/docker.yml` ze spec §13.2 (CLAUDE.md verbatim — build na PR + push do `ghcr.io/bgozlinski/tibiantis-scraper:<tag>` na push do master + tag v*; `docker/metadata-action@v5` dla tags: branch, semver, sha-short). M9 e2e smoke (closure PR description): full stack via `docker compose pull && docker compose up -d` z pre-built image z registry — potwierdzenie end-to-end push → pull → run flow. Closure PR od fresh master (M5-D27 + M6-D30 + M7-D35 + M8-D40 pattern repeat) — PROGRESS.md sekcja M9 z retro per Issue + 5-punkt manual smoke + Tech debt M9 + milestone close via `gh api`.

D44 ma **2 PR-y w 1 issue** (M5-D27 + M6-D30 + M7-D35 + M8-D40 pattern):

1. **Feature PR** (`feat/<#>-docker-ci`) — `.github/workflows/docker.yml`.
2. **Closure PR** (`docs/close-m9-dockerization` od **fresh master** po feature merge) — PROGRESS.md retro + manual smoke + milestone close.

### 🧠 Czego się nauczysz

- **`docker/metadata-action@v5`** — generuje image tags na podstawie GitHub event context. `type=ref,event=branch` → `:master` na push do master. `type=semver,pattern={{version}}` → `:1.2.3` tylko gdy git tag `v1.2.3`. `type=sha,prefix=sha-,format=short` → `:sha-acaa3c9` zawsze (audit trail).
- **`docker/build-push-action@v6`** — buildx-based build z support na multi-platform, layer cache, registry push. M9 używa `cache-from: type=gha + cache-to: type=gha,mode=max` (GitHub Actions native cache, zamiast registry cache).
- **`packages: write` permission** — workflow potrzebuje permission do publikowania do `ghcr.io`. `permissions: { contents: read, packages: write }` w job-level. `GITHUB_TOKEN` auto-generated ma scope, bez custom PAT.
- **`gh api -X PATCH .../milestones/9 -f state=closed`** — M5-D27 + M6-D30 + M7-D35 + M8-D40 precedens (5. raz). Wymaga `repo` scope w `gh auth`.
- **`gh api -X PATCH milestones`** vs **`gh api -X DELETE`** — PATCH zmienia state (closed/open), DELETE usuwa kompletnie. M9 close (nie delete) — `state=closed` zachowuje historię + audit.

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m9-d44.md`.)

**Feature PR kluczowe punkty:**

- `.github/workflows/docker.yml`:
  ```yaml
  name: Docker build

  on:
    pull_request:
      paths:
        - "Dockerfile"
        - ".dockerignore"
        - "docker-compose.yml"
        - "pyproject.toml"
        - "poetry.lock"
        - ".github/workflows/docker.yml"
    push:
      branches: [master]
      tags: ["v*"]

  concurrency:
    group: ${{ github.workflow }}-${{ github.ref }}
    cancel-in-progress: true

  jobs:
    build:
      runs-on: ubuntu-latest
      permissions:
        contents: read
        packages: write
      steps:
        - uses: actions/checkout@v4
        - uses: docker/setup-buildx-action@v3
        - uses: docker/login-action@v3
          if: github.event_name != 'pull_request'
          with:
            registry: ghcr.io
            username: ${{ github.actor }}
            password: ${{ secrets.GITHUB_TOKEN }}
        - uses: docker/metadata-action@v5
          id: meta
          with:
            images: ghcr.io/${{ github.repository }}
            tags: |
              type=ref,event=branch
              type=semver,pattern={{version}}
              type=sha,prefix=sha-,format=short
        - uses: docker/build-push-action@v6
          with:
            context: .
            push: ${{ github.event_name != 'pull_request' }}
            tags: ${{ steps.meta.outputs.tags }}
            labels: ${{ steps.meta.outputs.labels }}
            cache-from: type=gha
            cache-to: type=gha,mode=max
  ```
- PR build (PR-only event): `push: false`, image build sanity ale NIE push do registry.
- Master push event: `push: true`, image leci do `ghcr.io/bgozlinski/tibiantis-scraper:master` + `:sha-<commit>`.
- Tag push event (`v1.0.0`): image leci jako `:1.0.0` + `:sha-<commit>` + `:master` (master branch).

**Closure PR kluczowe punkty:**

- `PROGRESS.md` rozszerzone o:
  - `## 🎉 Milestone M9 — Dockeryzacja + prod-ready COMPLETED (2026-MM-DD)` header.
  - `### Ukończone (M9)` — lista 4 issues + PR linki + squash hashes.
  - `### Notatki z retro M9 (dopisywane progresywnie)` — per Issue D41-D44.
  - `### Definition of Done M9` (ze spec'a §8) — wszystkie [x] poza ostatnim ("milestone closed" — TODO post-merge).
  - `### Podsumowanie M9` (data range, dni vs budżet, najwartościowsze lekcje).
  - `### Tech debt z M9` (carry-over do M10+).
- **Manual smoke** udokumentowany w closure PR description (5 punktów z spec §9):
  1. Local `docker build .` → exit 0, image size ~150-200MB
  2. Local `docker compose -f docker-compose.yml up -d` → wszystkie 7 services healthy w ≤90s
  3. `docker compose logs migrate` → exit 0, migrations applied
  4. `curl /health/` z hosta przez exposed `web:8000` → 200 + JSON
  5. Post-master-merge: `docker pull ghcr.io/bgozlinski/tibiantis-scraper:master` z lokalu → success (end-to-end CI push → local pull confirmed)
- **Po merge closure PR'a:** `gh api -X PATCH repos/bgozlinski/tibiantis-scraper/milestones/9 -f state=closed`.
- **Sanity:** `gh issue list --milestone "M9 — Dockeryzacja + prod-ready" --state open` → empty.

### ⚠️ Pułapki do uwagi

- **A — `paths:` filter w `pull_request` trigger** — workflow odpala TYLKO gdy PR dotyka wymienionych ścieżek. Bez tego każdy PR (np. docs-only) triggeruje docker build → marnotrawstwo CI minutes. Spec lista: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `pyproject.toml`, `poetry.lock`, `.github/workflows/docker.yml`.
- **B — `if: github.event_name != 'pull_request'` na login-action** — login do ghcr.io NIE na PR build (wystarczy build sanity, no push). Bez tego forki PR mogłyby próbować login z forked workflow → security issue.
- **C — `push: ${{ github.event_name != 'pull_request' }}` na build-push-action** — push TYLKO na master/tag, NIE na PR. Spec pattern z CLAUDE.md §13.2.
- **D — `concurrency: cancel-in-progress: true`** — drugi push na ten sam ref zabija pierwszy run. Oszczędność CI minutes przy szybkich consecutive merges.
- **E — `cache-from: type=gha + cache-to: type=gha,mode=max`** — GitHub Actions native cache (no registry cache push). `mode=max` cache'uje wszystkie warstwy (default `mode=min` tylko final layers).
- **F — `docker/metadata-action@v5` `images:` lower-case** — `ghcr.io/${{ github.repository }}` resolves do `ghcr.io/bgozlinski/tibiantis-scraper`. GitHub username case-sensitive ale ghcr lower-cases. Sanity: `docker pull ghcr.io/bgozlinski/tibiantis-scraper:master` (lowercase).
- **G — First push po merge może fail jeśli `packages: write` scope nie auto-aktywuje** — workflow-level permissions wymaga **branch protection rule** lub manual repo settings: Settings → Actions → General → Workflow permissions → "Read and write permissions". Sanity po pierwszym merge: workflow run logs pokazują "Login Succeeded" przed push. Jeśli "Permission denied" — fix repo settings.
- **H — Closure branch od fresh master** (Pułapka C, M1-D8 + M5-D27 + M6-D30 + M7-D35 + M8-D40 lekcja repeat 6. raz) — `git checkout master && git pull && git checkout -b docs/close-m9-dockerization` PRZED edycją PROGRESS.md. Wzorzec utrwala się.
- **I — `gh api -X PATCH milestones/9`** — `9` to **number** milestone'a, nie title. Verify: `gh api repos/bgozlinski/tibiantis-scraper/milestones --jq '.[] | select(.title|startswith("M9")) | .number'` → `9`.
- **J — Milestone exact title match** — `gh issue list --milestone "M9 — Dockeryzacja + prod-ready"` wymaga dokładnego tytułu (z em-dashem `—`, NIE myślnikiem `-`). Title z `gh api repos/.../milestones --jq '.[] | .title'`.

### 🧪 Testing plan

**Feature PR:**

```bash
# Local sanity (po PR push do ghcr.io)
# Workflow runs auto na PR
gh pr checks <PR-#>
# expected: "Docker build" job → pass (build only, no push)

# Post-merge sanity (master push)
gh run list --workflow=docker.yml --limit 1
# expected: status: completed, conclusion: success

# Verify image w registry
docker pull ghcr.io/bgozlinski/tibiantis-scraper:master
docker image inspect ghcr.io/bgozlinski/tibiantis-scraper:master --format '{{.Created}}'
```

**Closure PR — Manual smoke (operator's laptop):**

W closure PR body zacytuj wyniki (zrzut ekranu lub verbatim transcript):

1. **Local build:**
   ```bash
   docker build -t tibiantis:dev .
   docker image ls tibiantis:dev
   ```
   → exit 0, image ~150-200MB.

2. **Full stack up:**
   ```bash
   cp .env.example .env
   # fill DJANGO_SECRET_KEY, DISCORD_BOT_TOKEN, POSTGRES_PASSWORD
   docker compose -f docker-compose.yml up -d
   sleep 90
   docker compose ps
   ```
   → wszystkie 7 services `Up healthy` (oprócz `migrate` `Exited (0)`).

3. **Migration:**
   ```bash
   docker compose logs migrate
   docker compose exec web python manage.py showmigrations --plan | grep '\[ \]' || echo "All applied"
   ```
   → exit 0 in logs, "All applied" w stdout.

4. **Health endpoint:**
   ```bash
   curl -fsS http://localhost:8000/health/
   ```
   → `{"db": "ok", "redis": "ok"}` + HTTP 200.

5. **Post-master-merge registry pull:**
   ```bash
   docker login ghcr.io -u bgozlinski   # z PAT z read:packages scope
   docker pull ghcr.io/bgozlinski/tibiantis-scraper:master
   docker image inspect ghcr.io/bgozlinski/tibiantis-scraper:master
   ```
   → success.

### 📦 Definition of Done

**Feature PR:**
- [ ] AC spełnione (`docker.yml` workflow exists, PR build sanity, master push triggers ghcr.io push).
- [ ] Feature PR zmergowany squash (`feat(ci): docker.yml workflow with ghcr.io build + push (M9-D44, #<#>)`).
- [ ] CI lint + test zielone.
- [ ] Image visible at `https://github.com/bgozlinski/tibiantis-scraper/pkgs/container/tibiantis-scraper`.

**Closure PR:**
- [ ] Closure PR zmergowany squash (`docs(progress): close M9 — Dockeryzacja + prod-ready COMPLETED + retro D41-D44`).
- [ ] CI lint zielony.
- [ ] PROGRESS.md sekcja M9 dorzucona.
- [ ] Manual smoke description w closure PR body (5 punktów z testing plan).
- [ ] Milestone M9 zamknięty na GitHub via `gh api -X PATCH .../milestones/9 -f state=closed`.
- [ ] Wszystkie M9 issues CLOSED (`gh issue list --milestone "M9 — Dockeryzacja + prod-ready" --state open` → empty).

---

## Tech debt do flag'owania w M9 retro

Te kandydaci mogą surface'ować podczas M9 implementacji (zaznacz w PROGRESS.md "Tech debt z M9"):

- **Image size > 200MB** — jeśli D42 manual smoke pokaże > 200MB, audit warstw. Potencjalne wins: usuń curl (użyj Python httpx w HEALTHCHECK), explicit `apt-get clean`, multi-arch build slim.
- **`celery_beat` pidfile race** — gdy beat restart'uje, pidfile może być stale. M-future: dorzucić `healthcheck` z `celery -A config status` (per-worker ping) zamiast pidfile check.
- **`discord_bot` brak healthcheck** — `restart: unless-stopped` to band-aid. M-future: bot zapisuje heartbeat do Mongo co 60s, healthcheck script odczytuje recent timestamp.
- **`.env` w prod jako single source of truth** — M-future: Docker secrets / Vault / SOPS gdy multi-host deploy.
- **Static files broken w prod** — admin CSS/JS nie działa bez WhiteNoise / nginx. M10 kandydat.
- **Image scanning** — Trivy w docker.yml workflow. M10 Hardening kandydat.
- **Multi-arch builds** — `linux/amd64,linux/arm64` w `docker/build-push-action@v6 platforms:`. M-future jeśli deploy target ARM (Raspberry Pi, M-class Macs).
- **`docker compose pull` strategy w prod runbook** — M-future docs/dev-runbook.md fragment "jak deploy update'u na VPS".
- **`gunicorn --access-logfile - --error-logfile -`** — domyślnie gunicorn loguje do plików. W container chcemy stdout (Docker logs). Sanity post-D42: czy gunicorn writes do stdout out-of-the-box? Jeśli nie — explicit flags w CMD.

---

## Skill usage map

| D | Skills wymagane | Skills opcjonalne |
|---|---|---|
| D41 | `test-driven-development` (TDD przy 4 testach health endpoint) | `using-git-worktrees` (jeśli paralelne taski) |
| D42 | `verification-before-completion` (manual smoke przed PR ready) | — |
| D43 | `verification-before-completion` (full stack smoke przed PR ready) | `systematic-debugging` (jeśli healthcheck flapuje) |
| D44 | `verification-before-completion` (workflow run + registry pull verify) | `requesting-code-review` (multi-stage Dockerfile review) |

---

## Closing notes

- **Strict chain:** D41 → D42 → D43 → D44 (każdy wymaga merge poprzedniego). Brak parallelism (Dockerfile zależy od healthcheck endpoint, compose zależy od Dockerfile, CI zależy od compose).
- **4 PR-y feature + 1 PR closure** = 5 PRs total. Plus ewentualne hotfixy (M7/M8 wzorzec — 1-2 hotfixy per milestone).
- **Manual smoke jest jedyną siecią dla full Docker stack** (M7 retro lekcja replicated). Nie testujemy real VPS deploy.
- **Closure PR pattern od fresh master** to **6. raz pod rząd** (M1-D8 → M5-D27 → M6-D30 → M7-D35 → M8-D40 → M9-D44). Wzorzec utrwalony.
