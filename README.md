# Tibiantis Monitor

Backend application that scrapes two Tibiantis services on a schedule, stores character data and events in a database, and communicates with users through a Discord bot.

## Core features

1. **Character monitoring** — profile scraper for [`tibiantis.online`](https://tibiantis.online).
2. **Death monitoring** — death-list scraper for [`tibiantis.info`](https://tibiantis.info/stats/deaths).
3. **Bedmage tracker** — reminds users when 100 minutes have passed since a character's last login (end of in-bed mana regeneration).
4. **Discord bot** — user-facing interface: notifications about high-level character deaths and commands for managing the bedmages list.

The application is modular — more features are planned, so the architecture must be extensible.

## Tech stack

Python 3.13 · Django 6 · PostgreSQL · MongoDB (logs only) · Scrapy · Celery + Redis · Strawberry-Django (GraphQL) · DRF (auth only) · discord.py · Docker.

## Local development

The dev environment uses `docker-compose.dev.yml` with two services: **postgres** (16-alpine, host port **5435** → container 5432) and **redis** (7-alpine, port 6379, ephemeral — no persistent volume).

### Prerequisites

- Docker Desktop (Windows/Mac) or Docker Engine (Linux)
- Python 3.13 and Poetry 2.x

### Commands

```bash
docker compose -f docker-compose.dev.yml up -d      # start in the background
docker compose -f docker-compose.dev.yml ps         # status — both services should be `(healthy)`
docker compose -f docker-compose.dev.yml logs -f    # follow logs from both services
docker compose -f docker-compose.dev.yml down       # stop (named volumes preserved)
docker compose -f docker-compose.dev.yml down -v    # stop + wipe Postgres volume (re-init from POSTGRES_* env)
```

Once the containers report `(healthy)`, install dependencies, apply migrations, and start Django:

```bash
poetry install
poetry run python manage.py migrate
poetry run python manage.py runserver
```

### Why port 5435 (not 5432)

A locally installed Postgres on 5432 and other Docker projects on 5433–5434 can run alongside this stack without conflict. The container still listens on 5432 internally; only the host-side mapping is `5435`. Make sure `.env` has `DATABASE_URL=postgres://...@localhost:5435/...`.

### Resetting Postgres credentials



The Postgres image runs `initdb` **only on the first start against an empty volume**. If you later change `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_DB` in `.env`, the new values are silently ignored — the container keeps using the credentials baked in on first init. To pick up the new values, wipe the volume and recreate:

```bash
docker compose -f docker-compose.dev.yml down -v
docker compose -f docker-compose.dev.yml up -d
```

`-v` drops the named volume, triggering a fresh `initdb` with the current env vars. Destructive — only safe in dev, where seed data is regenerable.

### Running Celery dev

Worker + beat as separate processes. On Windows the worker pool **must** be `solo` (Win32 lacks `fork()`):

```bash
# Terminal 1: worker
poetry run celery -A config worker -l info -P solo

# Terminal 2: beat (scheduler)
poetry run celery -A config beat -l info

# Terminal 3 (optional): Django runserver
poetry run python manage.py runserver
```

The worker logs `[tasks] . apps.characters.tasks.ping` once `autodiscover_tasks` finds the task. Beat logs
`Scheduler: ... DatabaseScheduler` and reads `PeriodicTask` rows from the database.

#### Adding/changing scheduled tasks

`PeriodicTask`/`IntervalSchedule`/`CrontabSchedule` rows are managed via Django admin
(`/admin/django_celery_beat/`). Beat polls the DB every 5 seconds (`CELERY_BEAT_MAX_LOOP_INTERVAL`), so admin
changes propagate without restart.

#### Why `-P solo` on Windows

Default Celery worker pool is `prefork` — relies on `os.fork()`, missing on Win32. Using `prefork` raises
`PermissionError: [WinError 5] Access is denied`. `-P solo` runs the worker single-threaded in the main
process. Linux Docker prod (M9) will use prefork.

## Documentation

- [`CLAUDE.md`](./CLAUDE.md) — full project specification (stack, structure, conventions, CI rules).
- [`docs/superpowers/specs/2026-04-17-tibiantis-execution-plan-design.md`](./docs/superpowers/specs/2026-04-17-tibiantis-execution-plan-design.md) — execution process (roles, workflow, milestones).
- [`docs/superpowers/plans/2026-04-17-m0-m1-implementation-plan.md`](./docs/superpowers/plans/2026-04-17-m0-m1-implementation-plan.md) — detailed plan for M0 + M1.
- [`PROGRESS.md`](./PROGRESS.md) — current milestone status.

## Status

Work in progress. See `PROGRESS.md` and [open issues](https://github.com/bgozlinski/tibiantis-scraper/issues) for the current state.
