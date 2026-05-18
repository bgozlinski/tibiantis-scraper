# Tibiantis Monitor

A backend application that scrapes two Tibiantis services on a schedule, stores character data and events in a database, and communicates with users through a Discord bot.

## About the project

Tibiantis is a retro Tibia world. This application aggregates data that the game client itself does not expose and delivers it to players reactively — through Discord channels and DMs.

### Core features

1. **Character monitoring** — profile scraper for [`tibiantis.online`](https://tibiantis.online) (level, vocation, last login, account status, guild, residence, etc.).
2. **Death monitoring** — scraper of the public death list at [`tibiantis.info/stats/deaths`](https://tibiantis.info/stats/deaths) with deduplication on `(character_name, died_at)`.
3. **Bedmage tracker** — reminds users when **100 minutes** have passed since a monitored character's last login (end of in-bed mana regeneration).
4. **DeathWatch** — public list of characters watched for deaths; notifications are pushed to a dedicated Discord channel.
5. **Discord bot** — user-facing interface: slash commands (`/bedmage add`, `/bedmage remove`, `/bedmage list`, `/deathwatch …`, `/deaths threshold`) and notification delivery.

The architecture is **modular** — every feature lives in its own Django app (`apps/<feature>/`) with its own GraphQL schema, services, and Celery tasks.

---

## Tech stack

| Layer | Technology |
|---|---|
| Language | **Python 3.13** |
| Framework | **Django 6.0** |
| Dependency management | **Poetry 2.x** (PEP 621 `[project]`) |
| Scraping | **Scrapy** (executed from Celery via subprocess) |
| Auth API | **Django REST Framework** + `djangorestframework-simplejwt` (login / register / refresh — **auth only**) |
| Domain API | **Strawberry-Django** (GraphQL at `/graphql/`) |
| Relational database | **PostgreSQL 16** — domain data |
| Document database | **MongoDB 7** — application and scraping logs (`app_logs`, `scrape_logs`) |
| Scheduler / queue | **Celery + Celery Beat** (broker: **Redis 7**, scheduler: `django-celery-beat` backed by the DB) |
| Discord bot | **discord.py** (runs as a separate process / container) |
| Containerisation | **Docker + docker-compose** (dev + prod) |
| Lint / format / types | **Ruff** + **mypy strict** (on `apps/`) |
| CI/CD | **GitHub Actions** + **pre-commit** + **Gitleaks** |

> Full stack specification and project-wide rules (REST is auth-only, scrapers go through services, database separation, etc.) — see [`CLAUDE.md`](./CLAUDE.md).

---

## Repository layout

```
.
├── config/                 # Django project (settings, urls, celery, merged schema)
├── apps/
│   ├── accounts/           # User + REST auth (JWT)
│   ├── characters/         # Character model, scraping orchestration, GraphQL
│   ├── bedmages/           # 100-min tracker, Celery tasks, GraphQL
│   ├── deaths/             # Death monitor, configurable notification threshold
│   ├── deathwatch/         # Public watch list + channel notifications
│   ├── notifications/      # Abstract notification handlers (Discord DM/channel)
│   └── core/               # Shared utilities / mixins
├── scrapers/               # Scrapy project (spiders → pipeline → services)
├── discord_bot/            # Separate process, slash commands (cogs)
├── logs_backend/           # Logging handler → MongoDB
├── docs/                   # Specs, milestone plans, runbooks
├── tests/                  # unit / integration / e2e + HTML fixtures
├── docker-compose.dev.yml  # Local services (postgres, redis, mongo)
├── docker-compose.yml      # Production stack (web, worker, beat, bot, db, nginx)
└── CLAUDE.md               # Full project specification
```

---

## Local setup

### Prerequisites

- **Docker Desktop** (Windows/Mac) or **Docker Engine** (Linux)
- **Python 3.13**
- **Poetry 2.x** (`pipx install poetry==2.0.1` recommended)
- Git

### 1. Clone the repo and configure `.env`

```bash
git clone https://github.com/bgozlinski/tibiantis-scraper.git
cd tibiantis-scraper
cp .env.example .env
```

Must be filled in `.env`:

- `DJANGO_SECRET_KEY` — generate with:
  ```bash
  python -c "import string, secrets; print(''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(50)))"
  ```
  (alphanumeric only — a `$` in the secret breaks Compose v2 variable expansion).
- `DISCORD_BOT_TOKEN` — from the [Discord Developer Portal](https://discord.com/developers/applications) (optional if you only work on the backend).

If you run Django **outside** of compose (i.e. with `runserver` against the dev services only), also set:

```bash
POSTGRES_HOST=localhost
POSTGRES_PORT=5435       # host port mapped in docker-compose.dev.yml
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
MONGO_URL=mongodb://localhost:27017
```

### 2. Start the dev services (Postgres + Redis + Mongo)

```bash
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml ps              # both should be (healthy)
```

- **postgres** — host `localhost:5435` (container: `5432`); port `5435` avoids conflicts with a locally installed Postgres or other Docker projects
- **redis** — host `localhost:6379` (ephemeral, no persistent volume)
- **mongo** — host `localhost:27017`

### 3. Python dependencies

```bash
poetry install
```

### 4. Migrations + superuser

```bash
poetry run python manage.py migrate
poetry run python manage.py createsuperuser
```

### 5. Run Django

```bash
poetry run python manage.py runserver
```

Endpoints:
- REST auth: `http://localhost:8000/api/auth/...`
- GraphQL: `http://localhost:8000/graphql/`
- Django admin: `http://localhost:8000/admin/`

### 6. Celery (worker + beat)

Each runs in its own terminal. **On Windows the worker MUST use `-P solo`** (Win32 has no `fork()`, the default prefork pool crashes with `WinError 5`):

```bash
# Terminal 1 — worker
poetry run celery -A config worker -l info -P solo

# Terminal 2 — beat (scheduler)
poetry run celery -A config beat -l info
```

Beat polls `PeriodicTask` rows in the DB every 5 seconds — changes made via `/admin/django_celery_beat/` propagate without a restart.

On Linux (prod/CI) the default `prefork` pool is used — see `docker-compose.yml`.

### 7. Discord bot (optional)

The bot runs as a **separate process** that shares Django models via a management command:

```bash
poetry run python manage.py run_discord_bot
```

Requires `DISCORD_BOT_TOKEN` set in `.env`, and — to register slash commands against a single dev guild only — `DISCORD_DEV_GUILD_ID`.

### 8. Tests, linting, types

```bash
poetry run pytest                              # full suite
poetry run pytest apps/bedmages -v             # one app
poetry run ruff check . && poetry run ruff format --check .
poetry run mypy apps/
```

### 9. Pre-commit

After a fresh clone, install the hooks:

```bash
poetry run pre-commit install
poetry run pre-commit install --hook-type commit-msg     # Conventional Commits
poetry run pre-commit run --all-files                    # smoke test
```

Hook rules and CI policy — see §12–13 in [`CLAUDE.md`](./CLAUDE.md).

---

## Resetting Postgres (dev only)

Postgres only runs `initdb` **the first time it starts against an empty volume**. Changing `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` in `.env` after that point is silently ignored. To reload with the current `.env`:

```bash
docker compose -f docker-compose.dev.yml down -v   # `-v` wipes the volume
docker compose -f docker-compose.dev.yml up -d
```

Destructive — fine in dev (seed data is reproducible), **never** in production.

---

## Production

The full stack is brought up by `docker-compose.yml` (services: `web`, `celery_worker`, `celery_beat`, `discord_bot`, `postgres`, `mongo`, `redis`, `nginx`). The image is multi-stage and built through Poetry. Details — section 10 in [`CLAUDE.md`](./CLAUDE.md).

---

## Documentation

- [`CLAUDE.md`](./CLAUDE.md) — full specification: stack, structure, conventions, CI, AI-assistant rules.
- [`PROGRESS.md`](./PROGRESS.md) — current milestone status.
- [`docs/`](./docs/) — implementation plans, retros, runbooks (e.g. the M12 DeathWatch smoke-test dev-runbook).
- [Issues](https://github.com/bgozlinski/tibiantis-scraper/issues) — backlog and active work.

---

## Status

Work in progress — milestones M0–M12 are closed (auth, character scraper, bedmages, deaths, deathwatch). Current state and next steps live in [`PROGRESS.md`](./PROGRESS.md).
