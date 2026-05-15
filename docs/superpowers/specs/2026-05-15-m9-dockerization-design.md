# M9 — Dockeryzacja + prod-ready — Design spec

**Data:** 2026-05-15
**Status:** ACCEPTED (decyzje §3.1-3.7 zaakceptowane przez developera 2026-05-15 w sesji M9 brainstorm)
**Plan:** [`docs/superpowers/plans/2026-05-15-m9-implementation-plan.md`](../plans/2026-05-15-m9-implementation-plan.md) (next step po tym spec'u)
**Milestone:** M9 — Dockeryzacja + prod-ready

---

## §1 Cel + scope

Po M0-M8 mamy pełen backend (Django + Celery + Scrapy + py-cord) + Discord outbound + Mongo logging. Wszystko uruchamiane **lokalnie**: `poetry run python manage.py runserver`, `poetry run celery -A config worker`, `poetry run python manage.py run_discord_bot`, plus `docker-compose.dev.yml` z postgres/redis/mongo. **Brak deployable artefaktu** — nikt poza developerem nie umie tego uruchomić bez 30-min onboardingu.

M9 zamyka pętlę "deployable artifact": każdy serwis backendowy (web/celery_worker/celery_beat/discord_bot + dependencies postgres/mongo/redis) startuje przez `docker compose up` z pre-built image; ten sam image jest publikowany do `ghcr.io/bgozlinski/tibiantis-scraper` po merge na master. Po M9 mamy gotowy `docker compose pull && docker compose up -d` flow dla VPS-a — wystarczy operator z dostępem do `.env` i jeden tag image'a.

### W zakresie M9:
- `apps/core/health/` — nowy Django app z `/health/` view (DB + Redis ping, 200 OK / 503 fail) i 4 unit tests.
- `Dockerfile` multi-stage (builder + runtime), jeden image dla web/celery_worker/celery_beat/discord_bot — różnią się tylko `command`.
- `.dockerignore` excluding `.git`, `.venv`, `__pycache__`, `tests/`, `docs/`, `.env*`, scratch files.
- Production `docker-compose.yml` z 7 application services + 1 one-shot migrate service.
- Healthchecki per service (zob. §3.3).
- `.env.example` aktualizacja: Docker DNS hostnames (`postgres`/`redis`/`mongo`) zamiast `localhost`.
- `.github/workflows/docker.yml` — build na PR + push do `ghcr.io/bgozlinski/tibiantis-scraper:<tag>` na push do `master` + tag `v*`.
- PROGRESS.md retro M9 + manual smoke (5 punktów z §9) + milestone close.

### Poza zakresem M9 (do M10 lub M-future):
- **nginx + TLS** — YAGNI per execution plan §6.2. Dopiero przy real VPS deploy (M-future po wynajęciu hosta).
- **Image security scanning** (Trivy/Snyk/Docker Scout) — kandydat na M10 Hardening.
- **Static files w prod** (`collectstatic` + WhiteNoise) — admin może być za SSH tunelem; pełna obsługa w M10 (lub M-future jeśli admin nie potrzebny w prod).
- **Multi-arch builds** (`linux/amd64,linux/arm64`) — YAGNI dopóki single deploy target (`amd64`).
- **Docker secrets / Vault / SOPS** — env strategy zostaje `env_file: .env` (single-host prod, M-future jeśli multi-node).
- **Auto-scaling, replicas, swarm/k8s** — out of scope, M-future jeśli będzie potrzeba.
- **Semantic version tagging** (`v1.2.3`) w docker.yml — start z `:master` rolling tag, semver dorzucimy gdy będzie pierwsze realne deploy + release flow.
- **Real production deploy** — out of scope, M-future po wynajęciu VPS-a.

---

## §2 Architektura

### High-level diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                          Operator host                          │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │            docker compose stack (7 services + 1 OS)       │  │
│  │                                                           │  │
│  │   ┌───────────┐   ┌─────────┐   ┌─────────┐   ┌────────┐  │  │
│  │   │ postgres  │   │  redis  │   │  mongo  │   │migrate │  │  │
│  │   │  :5432    │   │  :6379  │   │ :27017  │   │one-shot│  │  │
│  │   └─────┬─────┘   └────┬────┘   └────┬────┘   └────┬───┘  │  │
│  │         │              │             │             │      │  │
│  │         └──────────────┼─────────────┼─────────────┘      │  │
│  │                        │             │                    │  │
│  │   ┌────────────────────▼─────────────▼─────────────────┐  │  │
│  │   │      Application services (shared image)           │  │  │
│  │   │  ┌──────┐  ┌──────────────┐  ┌────────┐  ┌──────┐  │  │  │
│  │   │  │ web  │  │celery_worker │  │ beat   │  │ bot  │  │  │  │
│  │   │  │:8000 │  │   (worker)   │  │ (Beat) │  │      │  │  │  │
│  │   │  └──────┘  └──────────────┘  └────────┘  └──────┘  │  │  │
│  │   │  CMD: gunicorn  CMD: celery worker  CMD: beat      │  │  │
│  │   │       CMD: run_discord_bot                         │  │  │
│  │   └────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  .env (DJANGO_SECRET_KEY, DISCORD_BOT_TOKEN, POSTGRES_PASSWORD) │
└─────────────────────────────────────────────────────────────────┘

                    ▲
                    │ docker pull
                    │
        ┌───────────┴────────────┐
        │  ghcr.io/bgozlinski/   │
        │    tibiantis-scraper   │
        │  :master :sha-acaa3c9  │
        └───────────┬────────────┘
                    │ docker push (GHA on master)
                    │
        ┌───────────┴────────────┐
        │   GitHub Actions       │
        │   docker.yml workflow  │
        │   (build + push)       │
        └────────────────────────┘
```

### Struktura plików (3 NEW Django + 4 NEW infra)

**Nowe pliki (Django):**
- `apps/core/__init__.py`
- `apps/core/apps.py` (`CoreConfig`)
- `apps/core/health.py` (view: `health_check(request) -> JsonResponse`)
- `apps/core/urls.py` (path `/health/`)
- `apps/core/tests/__init__.py`
- `apps/core/tests/test_health.py` (4 tests)

**Nowe pliki (infra):**
- `Dockerfile`
- `.dockerignore`
- `docker-compose.yml` (prod)
- `.github/workflows/docker.yml`

**Modyfikowane pliki:**
- `config/urls.py` — dorzucenie `path("health/", include("apps.core.urls"))`
- `config/settings/base.py` — dorzucenie `"apps.core"` do `LOCAL_APPS`
- `.env.example` — Docker hostnames (`postgres`/`redis`/`mongo`) + komentarze które wartości operator musi wypełnić
- `pyproject.toml` — dorzucenie `gunicorn (>=23.0,<24.0)` jako prod dependency (aktualnie brak — `web` w Dockerfile używa). Plus opcjonalnie `types-redis` w dev deps gdy mypy zgłosi missing stubs dla `redis.Redis` w `health.py` (`redis` już jest direct dep z M5 → `redis (>=7.4.0,<8.0.0)`, nie trzeba dorzucać).

---

## §3 Decyzje designowe (zaakceptowane 2026-05-15)

### §3.1 Dockerfile multi-stage (builder + runtime) z requirements.txt export

```dockerfile
FROM python:3.13-slim-bookworm AS builder
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 POETRY_VERSION=2.0.1
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}" "poetry-plugin-export>=1.8"
WORKDIR /build
COPY pyproject.toml poetry.lock ./
RUN poetry export --without-hashes --only=main -o requirements.txt
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PATH="/home/app/.local/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod
RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --shell /bin/bash --uid 1000 app
USER app
WORKDIR /app
COPY --from=builder --chown=app:app /root/.local /home/app/.local
COPY --chown=app:app . /app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS http://localhost:8000/health/ || exit 1
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--timeout", "60"]
```

**Dlaczego `poetry export → requirements.txt` w builder zamiast `poetry install` w runtime:**
- Builder ma `poetry` (~60MB install). Runtime go nie potrzebuje — tylko `pip install -r requirements.txt`.
- Mniejszy runtime image (~150-200MB vs ~350MB z poetry-in-runtime).
- Lock file pozostaje source of truth (export wynik deterministyczny z lock'a).

**Odstąpienie od CLAUDE.md §10** ("Nie eksportuj do `requirements.txt`"): kontekst tego zakazu to DEV workflow (developer nie powinien używać `requirements.txt` zamiast `poetry install`). W BUILD stage exportujemy wyłącznie jako transient hand-off do `pip` w runtime stage — lock file zostaje canonical. **Spec aktualizacja CLAUDE.md §10** (osobny PR w M9 lub follow-up): notka "no requirements.txt" dotyczy dev workflow; multi-stage Docker build może exportować dla image slimming.

**Non-root user `app` (UID 1000)** — defense-in-depth. `chown -R app:app` w COPY → +50MB layer transient, akceptowalny trade-off.

**Single image dla 4 application services:** `web`/`celery_worker`/`celery_beat`/`discord_bot` używają **tego samego obrazu**, różnią się tylko `command:` w docker-compose. Jeden Dockerfile, jeden build, jeden push do registry — zgodne z CLAUDE.md §10.

### §3.2 `web` — gunicorn (WSGI), nie uvicorn (ASGI)

Aktualnie 0 async views, 0 async resolvers. Gunicorn `--workers 2 --threads 2 --timeout 60` wystarcza dla single-host workload. Jeśli kiedyś dorzucimy async Strawberry resolvers — switch na `gunicorn -k uvicorn.workers.UvicornWorker` to 1-line zmiana w `CMD`. Per CLAUDE.md §2 "ASGI: uvicorn jeśli potrzebujemy async" — nie potrzebujemy teraz, więc YAGNI.

### §3.3 Healthchecki per service

| Service | Test | Interval | Timeout | Retries | Start period | Notes |
|---|---|---|---|---|---|---|
| `postgres` | `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB` | 10s | 5s | 5 | 30s | (kontynuacja z dev compose) |
| `redis` | `redis-cli ping` | 10s | 5s | 5 | - | (kontynuacja z dev compose) |
| `mongo` | `mongosh --quiet --eval 'db.adminCommand("ping").ok'` | 10s | 5s | 5 | 30s | (kontynuacja z dev compose) |
| `migrate` | **brak** — one-shot, `restart: 'no'` | - | - | - | - | Exit 0 sygnalizuje `service_completed_successfully` dla `web` |
| `web` | `curl -fsS http://localhost:8000/health/` | 15s | 5s | 3 | 60s | Django + DB + Redis startup ≈ 30-45s, 60s start period dla bezpieczeństwa |
| `celery_worker` | `celery -A config inspect ping -d celery@$HOSTNAME` | 30s | 10s | 3 | 60s | High overhead (~3s per call) → 30s interval |
| `celery_beat` | `test -f /tmp/celerybeat.pid && ps -p $(cat /tmp/celerybeat.pid) > /dev/null` | 30s | 5s | 3 | 60s | Beat ma `--pidfile=/tmp/celerybeat.pid` w command |
| `discord_bot` | **brak** | - | - | - | - | Long-running gateway connection bez exposed port. py-cord obsługuje heartbeat sam. `restart: unless-stopped` reboot przy crashu. M-future: dorzucić Mongo heartbeat write + custom healthcheck script. |

### §3.4 Migration jako one-shot service z `service_completed_successfully` dependency

```yaml
services:
  migrate:
    image: ghcr.io/bgozlinski/tibiantis-scraper:master
    command: python manage.py migrate --noinput
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
    restart: "no"

  web:
    image: ghcr.io/bgozlinski/tibiantis-scraper:master
    command: gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --threads 2
    env_file: .env
    ports: ["8000:8000"]
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
      migrate: { condition: service_completed_successfully }
```

**Dlaczego separate service, nie inline `bash -c "migrate && gunicorn"`:**
- **Idempotent** — `migrate` exit 0 czy migracja była no-op, czy applied. Recompose `docker compose up -d` po update'cie image'a → tylko `migrate` runs (`migrate` ma nową image SHA), reszta unchanged.
- **No race condition** — jak `web` jest scaled na N replicas (M-future), wszystkie depends_on tego samego `migrate` exit code. Bez race na `migrate.lock` w PG.
- **Czytelny `docker compose logs migrate`** — explicit migration log, nie zmieszany z gunicorn output.
- **Trade-off:** dorzucamy 1 service do compose. Akceptowalny — czystszy lifecycle management.

### §3.5 Image tagging strategy

CLAUDE.md §13.2 spec'uje `docker/metadata-action@v5`:
```yaml
tags: |
  type=ref,event=branch          # ghcr.io/.../tibiantis-scraper:master
  type=semver,pattern={{version}}  # ghcr.io/.../tibiantis-scraper:1.2.3 (tylko gdy git tag v1.2.3)
  type=sha,prefix=sha-,format=short  # ghcr.io/.../tibiantis-scraper:sha-acaa3c9
```

**Pull strategy w prod (compose) — hybrid `image:` + `build:` dla D43 dev iteration:**
```yaml
services:
  web:
    image: ghcr.io/bgozlinski/tibiantis-scraper:master   # rolling tag (pull w prod)
    build: .                                              # fallback build z lokalnego Dockerfile
```

Docker Compose semantyka: gdy `image:` nie istnieje lokalnie ani w registry, użyje `build:` jako fallback. W D43 (przed D44 push):
- `docker compose build` → buduje z lokalnego `Dockerfile`, taguje jako `ghcr.io/bgozlinski/tibiantis-scraper:master` lokalnie
- `docker compose up -d` → używa lokalnie tagged image (registry NIE pull, bo lokal istnieje)

W prod (po D44 merge):
- `docker compose pull` → ściąga `:master` z registry (overrides lokalną wersję jeśli starsza)
- `docker compose up -d` → uruchamia świeży pull

Hybrid pattern działa dla obu workflow bez zmian w compose. M-future jeśli chcemy lock'ować prod na registry-only (no local build), usuwamy `build:` z compose.

**Trade-off rolling vs explicit:**
- `:master` rolling = każdy merge → `docker compose pull && docker compose up -d` daje fresh image. Niska ceremonia, zero release flow. **Decyzja M9.**
- `:v1.2.3` explicit = wymaga `git tag v1.2.3 && git push --tags` flow + ręczna edycja compose. M-future gdy będzie pierwsze realne deploy + chcemy rollback flow.

`:sha-<commit>` zostaje jako audit trail (gdy chce się sprawdzić "co obecnie chodzi w prod" przez `docker inspect`).

### §3.6 `.env` strategy — `env_file`, nie Docker secrets

Compose używa `env_file: .env` (jak w dev compose). Operator deploy'u przygotowuje `.env` ręcznie z secretami:
- `DJANGO_SECRET_KEY` (generate'em z `get_random_secret_key()`)
- `DISCORD_BOT_TOKEN` (Discord Developer Portal)
- `POSTGRES_PASSWORD` (operator-generated)
- `DJANGO_ALLOWED_HOSTS` (prod domain)

`.env.example` aktualizowane:
- Docker DNS hostnames: `DATABASE_URL=postgres://tibiantis:tibiantis@postgres:5432/tibiantis` (był `localhost:5435` dla dev)
- `REDIS_URL=redis://redis:6379/0` (był `redis://localhost:6379/0`)
- `MONGO_URL=mongodb://mongo:27017` (był `mongodb://localhost:27017`)
- Komentarz nad każdą sekcją "Operator wypełnia: …" z listą wymaganych env varsach

**Nie dorzucamy Docker secrets / Vault / SOPS** — YAGNI dla single-host prod. M-future jeśli multi-node deploy. **Bezpieczeństwo:** `.env` w `.gitignore` od M0, gitleaks w pre-commit blokuje accidental commit.

### §3.7 Non-root user `app` (UID 1000) w runtime

Runtime stage:
```
RUN useradd --create-home --shell /bin/bash --uid 1000 app
USER app
COPY --chown=app:app . /app
```

**Powód:** defense-in-depth — gdy ktoś przejmie container (np. RCE w Django view), nie ma root. Plus host-volume permissions cleaner (host user 1000 = container user 1000 → no `chown` dance po `docker run`).

**Trade-off:** `chown -R app:app /app` w COPY → +~50MB transient layer (skopiowane pliki dostają attribute change). Akceptowalny.

**Nie dorzucamy** dedykowanego non-root distroless image — `python:3.13-slim-bookworm` + custom user wystarcza. Distroless to `python:3.13-distroless`-style images, M-future jeśli chcemy minimal attack surface.

---

## §4 Healthcheck endpoint — sygnatura

### §4.1 `apps/core/health.py`

```python
from __future__ import annotations
import logging
import redis
from django.conf import settings
from django.db import connection, OperationalError
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
def health_check(request) -> JsonResponse:
    """Liveness + readiness check dla Docker HEALTHCHECK i load balancer'a.

    Sprawdza:
    - DB connectivity (cursor.execute("SELECT 1"))
    - Redis connectivity (redis.Redis(...).ping())

    Returns: 200 + {"db": "ok", "redis": "ok"} gdy oba OK.
             503 + {"db": "fail|ok", "redis": "fail|ok", "error": "..."} gdy któryś fail.

    Out of scope (M-future): Mongo check (nie blokuje krytycznego flow — logging
    może gracefully degradować). Celery worker ping (osobny healthcheck per service).
    """
    status = {"db": "ok", "redis": "ok"}
    status_code = 200

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except OperationalError as exc:
        logger.exception("Health check: DB query failed")
        status["db"] = "fail"
        status["error"] = str(exc)
        status_code = 503

    try:
        r = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2)
        r.ping()
    except (redis.ConnectionError, redis.TimeoutError) as exc:
        logger.exception("Health check: Redis ping failed")
        status["redis"] = "fail"
        status["error"] = str(exc)
        status_code = 503

    return JsonResponse(status, status=status_code)
```

### §4.2 `apps/core/urls.py`

```python
from django.urls import path
from apps.core.health import health_check

urlpatterns = [
    path("", health_check, name="health-check"),
]
```

### §4.3 `config/urls.py` (modify)

Dorzuca `path("health/", include("apps.core.urls"))` — pełny URL `/health/`.

### §4.4 `redis-py` już jest direct dependency

`redis (>=7.4.0,<8.0.0)` był dorzucony jako direct dependency w M5/M6 (Celery broker + Mongo logging — `apps/notifications/...` używa pośrednio przez `redis.Redis.from_url(REDIS_URL).ping()` można reuse). Sprawdzony `pyproject.toml:22`. **Nie trzeba dorzucać.**

`types-redis` może być potrzebny w `[tool.poetry.group.dev.dependencies]` jeśli mypy zgłosi `Cannot find implementation or library stub for module redis.Redis`. Decyzja — dorzucamy reaktywnie w D41 jeśli `pre-commit run mypy --files apps/core/health.py` zgłosi.

---

## §5 D-task split (preview — szczegóły w implementation plan)

| D | Tytuł | Czas | Branch | Zależy od |
|---|---|---|---|---|
| **D41** | `apps/core` healthcheck app + `/health/` endpoint + 4 tests | ~2-3h | `feat/<#>-health-endpoint` | (start of M9) |
| **D42** | Multi-stage Dockerfile + .dockerignore + local container smoke | ~3-4h | `feat/<#>-dockerfile` | D41 merged |
| **D43** | Production `docker-compose.yml` + 7 services + migrate one-shot + healthchecki + .env.example update | ~3-4h | `feat/<#>-prod-compose` | D42 merged |
| **D44** | `docker.yml` CI workflow (build + push ghcr.io) + M9 e2e (full stack smoke) + closure PR | ~3-4h | `feat/<#>-docker-ci` + `docs/close-m9-dockerization` | D43 merged |

**Sanity ratio:** 4 D-tasks × ~3.5h = ~14h, mieści się w 16h M9 budget (4 dni × 4h) z 2h buforem.

---

## §6 Error handling

### §6.1 Healthcheck endpoint failure modes

| Failure mode | Detection | Response | Recovery |
|---|---|---|---|
| DB unreachable | `connection.cursor().execute("SELECT 1")` raises `OperationalError` | 503 + `{"db": "fail"}` | Docker `HEALTHCHECK` → restart container po N retries |
| Redis unreachable | `redis.Redis.from_url(...).ping()` raises `ConnectionError`/`TimeoutError` | 503 + `{"redis": "fail"}` | Same |
| Endpoint timeout | curl `--max-time 5s` w HEALTHCHECK | Docker marks unhealthy | LB removes from rotation (M-future), restart on N retries |
| 500 z Django view | (nie powinno) — wszystkie exceptions handled inline | 500 (Django default ErrorHandler) | Same as DB unreachable |

### §6.2 Migration service failure

`migrate` exit ≠ 0 → `web` nie startuje (`service_completed_successfully` not met). Operator widzi błąd w `docker compose logs migrate`, fix migration locally, rebuild image, retry. **Brak auto-rollback** — M-future jeśli chcemy zero-downtime migrations.

### §6.3 Image pull failure (ghcr.io down)

`docker compose pull` exit ≠ 0 → operator widzi error. Auto-fallback na lokalnie cached image (`docker compose up -d` bez `pull` używa local cache). Manual retry. **Brak retry loop w compose** — operator decyduje.

### §6.4 Discord bot crash w container

`restart: unless-stopped` policy → automatic restart po non-zero exit. py-cord obsługuje gateway reconnect po jego stronie (w-process retry). Crash zewnętrzny (OOM, SIGKILL) → Docker restart → bot reconnects, slash commands re-syncują przy startup.

### §6.5 Celery worker / beat crash

Same `restart: unless-stopped`. Beat schedule jest persistent w `django-celery-beat` (Postgres-backed) — restart nie traci jobs. Worker grabs unfinished tasks z Redis queue.

### §6.6 Static files w prod (M9 NIE rozwiązuje)

Django `STATIC_URL=/static/` ale bez `collectstatic` + WhiteNoise / nginx, admin CSS/JS będzie broken. **M9 świadomie pomija** — admin dostępny tylko przez SSH tunnel `ssh -L 8000:localhost:8000 prod.host` (dev workflow). M10 lub M-future dorzuci WhiteNoise + `collectstatic` w Dockerfile build stage.

---

## §7 Testing strategy

### §7.1 Stack

Docker M9 to **infra**, nie kod aplikacyjny — testing pattern się różni od M0-M8:

| Layer | Test type | Mechanism |
|---|---|---|
| Healthcheck endpoint | Unit + integration | pytest-django |
| Dockerfile | Smoke (local + CI) | `docker build` + `docker run` |
| docker-compose.yml | Manual smoke (closure PR) | `docker compose up -d` |
| CI workflow | GHA dry-run + post-merge push | PR triggers build, master triggers push |

### §7.2 Test files (~4 tests total + 5 manual smoke punkty)

**D41 — `apps/core/tests/test_health.py`** (4 tests):
- `test_health_returns_200_when_db_and_redis_ok` — happy path, JSON shape `{"db": "ok", "redis": "ok"}`
- `test_health_returns_503_when_db_fails` — mock `connection.cursor` → `OperationalError`, expects 503 + `"db": "fail"`
- `test_health_returns_503_when_redis_fails` — mock `redis.Redis.from_url(...).ping()` → `ConnectionError`, expects 503 + `"redis": "fail"`
- `test_health_response_shape_keys` — JSON keys pin (forward-compat dla M-future Mongo/Celery checks)

**D42 — manual smoke w PR description:**
- `docker build -t tibiantis:dev .` → exit 0
- Image size raport (`docker image ls tibiantis:dev`) — target ~150-200MB
- `docker run --rm -e DJANGO_SECRET_KEY=test -e DATABASE_URL=sqlite:///:memory: tibiantis:dev python manage.py check` → exit 0

**D43 — manual smoke w PR description (5 punktów z §9 poniżej, podzbiór):**
- `docker compose -f docker-compose.yml up -d` (z `.env` z dev secretami)
- `docker compose ps` → 7/7 services `Up healthy` po ≤90s
- `docker compose logs migrate` → exit 0, migration applied
- `docker compose exec web curl -fsS http://localhost:8000/health/` → 200
- `docker compose down -v` cleanup

**D44 — CI verification:**
- PR z dotknięciem `Dockerfile`/`docker-compose.yml`/`.github/workflows/docker.yml` triggers build job → zielony
- Po merge do master: `docker.yml` push job → `docker pull ghcr.io/bgozlinski/tibiantis-scraper:master` z lokalu działa
- M9 e2e smoke (closure PR): full stack via `docker compose pull && docker compose up -d` z pre-built image — potwierdzenie end-to-end push → pull → run flow

### §7.3 Coverage cel

- `apps/core/health/*` ≥ 95% — mały app, 4 tests powinny dać full coverage.
- Cumulative `apps/*` ≥ 70% (CI threshold, M0 baseline) — niezmienne.

### §7.4 NIE testujemy

- **Real VPS deploy** — out of scope, M-future po wynajęciu hostingu.
- **`docker compose up` na realnej maszynie zdalnej** — M-future.
- **TLS / Let's Encrypt cert flow** — M-future.
- **`ALLOWED_HOSTS=production-domain.com`** end-to-end — M-future.
- **Image security scanning** — kandydat na M10 Hardening.

---

## §8 Definition of Done M9

- [ ] **4 D-tasków zamkniętych** (#D41 + #D42 + #D43 + #D44) + closure PR
- [ ] **`apps/core/health/`** — view (`health_check`), urls (`health/`), 4 tests, ≥95% coverage
- [ ] **`config/urls.py`** dorzuca `path("health/", include("apps.core.urls"))`
- [ ] **`config/settings/base.py`** dorzuca `"apps.core"` do `LOCAL_APPS`
- [ ] **`pyproject.toml`** dorzuca `gunicorn (>=23.0,<24.0)` jako prod dependency (Dockerfile CMD używa). Plus `types-redis` w dev deps jeśli mypy zgłosi missing stubs.
- [ ] **`Dockerfile`** multi-stage (builder + runtime), non-root user `app` (UID 1000), `python:3.13-slim-bookworm` base, HEALTHCHECK via curl `/health/`
- [ ] **`.dockerignore`** excluding `.git`, `.venv`, `__pycache__`, `tests/`, `docs/`, `.env*`, `.idea/`, scratch files
- [ ] **`docker-compose.yml`** (prod) z 7 services (postgres, redis, mongo, web, celery_worker, celery_beat, discord_bot) + 1 one-shot `migrate` + healthchecki + depends_on chain
- [ ] **`.env.example`** zaktualizowane na Docker DNS hostnames (`postgres`/`redis`/`mongo`) + operator-wypełnia comments
- [ ] **`.github/workflows/docker.yml`** — build na PR + push do `ghcr.io/bgozlinski/tibiantis-scraper` na master/tag, z `docker/metadata-action@v5` tags
- [ ] **Pre-commit + CI lint + test zielone** dla wszystkich 4 PR-ów
- [ ] **Coverage `apps/core/health/*` ≥ 95%** — osiągnięte
- [ ] **PROGRESS.md** rozszerzony o sekcję M9 z retro per Issue (D41-D44) + Tech debt M9 + lekcje
- [ ] **Manual smoke** udokumentowany w closure PR description (5 punktów z §9 poniżej)
- [ ] **Milestone M9 zamknięty** na GitHub via `gh api -X PATCH .../milestones/9 -f state=closed`

---

## §9 Manual smoke checklist (operator's laptop + post-merge)

W closure PR body (D44):

1. **Local build:** `docker build -t tibiantis:dev .` → exit 0, image size ~150-200MB (`docker image ls tibiantis:dev`)
2. **Full stack up:** `cp .env.example .env`, fill in `DJANGO_SECRET_KEY` + `DISCORD_BOT_TOKEN` + `POSTGRES_PASSWORD`, then `docker compose -f docker-compose.yml up -d` → wszystkie 7 services `Up healthy` po ≤90s (verify via `docker compose ps`)
3. **Migrate one-shot:** `docker compose logs migrate` → exit 0, "Applying X..." lines, brak pending migrations po `docker compose exec web python manage.py showmigrations --plan | grep '\[ \]'` (powinno być empty)
4. **Health endpoint:** `curl -fsS http://localhost:8000/health/` z hosta przez exposed `web:8000` → 200 + `{"db": "ok", "redis": "ok"}`
5. **Post-master-merge:** `docker pull ghcr.io/bgozlinski/tibiantis-scraper:master` z lokalu (logged in to ghcr.io via `docker login ghcr.io -u bgozlinski`) → success, `docker image inspect` shows `:master` tag

---

## §10 References / precedensy

- **CLAUDE.md §10** — Docker / docker-compose reguły (multi-stage, single image dla web/celery/bot, healthchecki, volumes, .env strategy). M9 odstępuje w jednym punkcie: `requirements.txt` export w builder stage (kontekst — multi-stage, nie dev workflow). Spec update kandydat.
- **CLAUDE.md §13.2** — `docker.yml` workflow template z `docker/metadata-action@v5` i `docker/build-push-action@v6`. M9 reuses verbatim.
- **`docker-compose.dev.yml`** — istniejące postgres+redis+mongo z healthcheckami. M9 prod compose extends pattern dla 4 app services.
- **M2 — `config/urls.py`** routing setup. M9 dorzuca `path("health/", ...)`.
- **M6 — `LOGGING` dict** — health endpoint loguje failures via M6 dispatcher do Mongo `app_logs`.
- **M7-D32 lekcja** — `env(..., default="")` empty-env fallback (Pułapka H). M9 .env.example musi mieć komentarz że puste = operator wypełnia, nie default.
- **M8-D37 lazy import lekcja** — w `health.py` import `redis` na top-level OK (redis to direct dependency po §4.4, nie lazy-load potrzebny).
- **Execution plan §6.2 YAGNI** — nginx + TLS, dashboard, wykresy, multi-world — wszystko po-M9 osobne projekty.

---

## §11 Otwarte pytania dla M9 retro

- **`STATIC_URL` / collectstatic** — czy admin musi działać w prod? Jeśli tak, dorzucamy WhiteNoise w M10. Aktualnie M9 zostawia broken (SSH tunnel workflow).
- **Image size target** — 150-200MB to luźna estymata. Po pierwszym build mamy hard data; jeśli > 300MB, audit warstw (np. dorzucenie `--no-install-recommends` do `apt-get`, usuń `curl` z runtime jeśli HEALTHCHECK używa `wget` lub Python httpx).
- **Image scanning** — Trivy w M10? Albo wystarczy GHA's CodeQL? Decyzja w M10 brainstorm.
- **`web:8000` exposed port** — `ports: ["8000:8000"]` (development setup) czy `expose: 8000` (intended behind LB)? M9 daje `ports:` dla SSH-tunnel + local smoke. M-future + nginx zmienia na `expose:`.
- **Celery beat scheduler choice** — `django-celery-beat` (DB-backed schedule, current setup) czy file-backed default? Aktualne setup `--scheduler django_celery_beat.schedulers:DatabaseScheduler` w `command` zostaje.
