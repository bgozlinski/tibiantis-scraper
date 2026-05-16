# Tibiantis Monitor — Developer runbook

Local dev workflow + Windows + Git Bash gotchas consolidated from M3–M9 retros.
For production deployment on Hetzner, see [`deploy-runbook.md`](deploy-runbook.md).

## §1 Local dev setup

### 1.1 Prerequisites

- Python 3.13.x (`python --version`)
- Poetry 2.0.x (`poetry --version`)
- Docker Desktop (Windows/macOS) or Docker Engine + docker-compose-plugin (Linux)
- Git + Git Bash (Windows)

### 1.2 First-time setup

```bash
git clone https://github.com/bgozlinski/tibiantis-scraper.git
cd tibiantis-scraper
poetry install

# Copy + edit .env with DEV defaults (localhost ports):
cp .env.example .env
# Edit:
#   DJANGO_SECRET_KEY    — generate alphanumeric (see §6)
#   DISCORD_BOT_TOKEN    — only if running the bot locally
#   DATABASE_URL=postgres://tibiantis:tibiantis@localhost:5435/tibiantis
#   REDIS_URL=redis://localhost:6379/0
#   MONGO_URL=mongodb://localhost:27017

# Start DB-only services (dev compose exposes ports to localhost):
docker compose -f docker-compose.dev.yml up -d

# Apply migrations:
poetry run python manage.py migrate

# Start web (dev runserver):
poetry run python manage.py runserver
```

In separate terminals (each command attaches to its own process):

```bash
# Worker — note -P solo on Windows, see §2
poetry run celery -A config worker -P solo -l info

# Beat scheduler
poetry run celery -A config beat -l info

# Discord bot (requires real DISCORD_BOT_TOKEN in .env)
poetry run python manage.py run_discord_bot
```

### 1.3 Day-to-day commands

```bash
# Lint + format
poetry run ruff check .
poetry run ruff format .

# Type-check (strict mode for apps/)
poetry run mypy apps/

# Tests
poetry run pytest                  # full suite
poetry run pytest apps/bedmages    # one app

# Migrations
poetry run python manage.py makemigrations
poetry run python manage.py migrate

# Manual scrape for debugging (bypasses Celery)
poetry run scrapy crawl character -a name=Yhral
poetry run scrapy crawl deaths
```

## §2 Celery on Windows — `-P solo` required (M3-D17)

**Symptom:** `poetry run celery -A config worker -l info` crashes with `WinError 5` or `WinError 6` and `billiard.exceptions.WorkerLostError` shortly after startup.

**Cause:** Celery's default prefork pool forks child processes. Windows doesn't support POSIX `fork()` semantics; `billiard` emulates it and the emulation is fragile under load.

**Workaround:** force the single-threaded pool with `-P solo`:

```bash
poetry run celery -A config worker -P solo -l info
```

Trade-off: one task at a time, no parallelism. Acceptable for dev workflow — the broker still queues messages, you just process them serially.

**Production (Linux container) uses default prefork.** `-P solo` is *not* in the `Dockerfile` `CMD` or `docker-compose.yml` `command:` — only in this dev workflow.

## §3 Git Bash MSYS path conversion (M9-D43)

**Symptom:**

```bash
docker compose exec celery_beat ls /tmp/
# Error: cannot access 'C:/Users/.../AppData/Local/Temp/'
```

Git Bash's MSYS runtime translates POSIX-looking paths like `/tmp/` into Windows paths *before* `docker` sees the argument. The container never gets a chance to interpret `/tmp/` itself.

**Workaround 1 — disable MSYS path conversion for that command:**

```bash
MSYS_NO_PATHCONV=1 docker compose exec celery_beat ls /tmp/
```

**Workaround 2 — escape with a double slash (MSYS leaves `//` alone):**

```bash
docker compose exec celery_beat ls //tmp/
```

**Scope:** Git Bash on Windows only. Paths in `docker-compose.yml` volumes/healthchecks pass through the Docker daemon (not a Git Bash shell) and don't need this workaround. Affects only commands you type interactively where the leading `/` is the first character of an argument.

## §4 `pre-commit clean` after dep changes (M7-D33)

**Symptom:** after adding a new dependency (e.g., `poetry add httpx`), pre-commit's mypy hook flags lines with `# type: ignore` as `unused-ignore` — the *opposite* of what you'd expect. Subsequent runs report unrelated false-positives that disappear if you delete the cache.

**Cause:** the pre-commit mypy hook runs in its own isolated venv with a persistent cache. When you change deps in the main Poetry venv, the hook's cache still references stale stub knowledge and emits stale diagnostics.

**Workaround:**

```bash
poetry run pre-commit clean                       # wipes all hook caches
poetry run pre-commit run mypy --all-files        # rebuild fresh
```

**Decision tree when mypy reports an error you don't believe:**

1. Run `pre-commit clean` + `pre-commit run mypy --all-files`. If the error stays — it's real, fix the code.
2. If the error goes away after `clean` — it was stale cache. No code change needed.
3. If a third-party lib genuinely has no stubs and the error persists after `clean`, add an override in `pyproject.toml`:
   ```toml
   [[tool.mypy.overrides]]
   module = ["the_lib_name"]
   ignore_missing_imports = true
   ```
   Established pattern in this repo: `environ`, `celery`, `discord`, `redis`.

## §5 `docker compose build` then `up -d --no-build` (M9-D43)

**Symptom:** running `docker compose up -d` from scratch (no cached image) with hybrid `image:` + `build:` services — when 5+ services share the same image — fails with:

```
target celery_beat: failed to solve: image "bgozl/tibiantis-scraper:master": already exists
```

**Cause:** Compose triggers parallel buildx jobs for every service that has a `build:` section. They all tag the result as the same `bgozl/tibiantis-scraper:master`. First one wins, the rest hit "already exists" race conditions.

**Workaround — split build and up:**

```bash
# 1. Optional: clean partial state if a previous attempt left orphans
docker compose down -v

# 2. Build ONCE — buildx sees a single job, no race
docker compose build

# 3. Up without re-building — uses the just-built local image
docker compose up -d --no-build
```

`--no-build` prevents `up` from triggering its own parallel builds.

**Scope:** this is a dev-iteration concern (local image build). In production the operator runs `docker compose pull` (image fetched from Docker Hub, no local build path) and the race never happens.

## §6 Generate alphanumeric `SECRET_KEY` (M9-D43)

**Symptom:** `docker compose up -d` emits warnings like:

```
The "v4" variable is not set. Defaulting to a blank string.
The "zj6" variable is not set. Defaulting to a blank string.
```

Repeated for every compose subcommand.

**Cause:** Compose v2 does shell-style `$VAR` interpolation on values inside `.env` *before* passing them to containers via `env_file:`. Django's `get_random_secret_key()` can include `$` characters (e.g. `abc$v4def`); compose sees `$v4` as a variable reference, substitutes empty, prints the warning.

**Impact:** the warnings are cosmetic for `env_file:` passthrough (the container gets the raw value), but ANY compose context that does its own interpolation on `.env` values (top-level `environment:`, `command:` with `${VAR}`) will see the corrupted version. Easy to misdebug.

**Fix — always generate alphanumeric SECRET_KEY:**

```bash
python -c "import string, secrets; print(''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(50)))"
```

Use this for dev `.env` AND for production `.env` on the Hetzner VM. Same generator is documented in `deploy-runbook.md` §4.3 — single source of truth.

The same constraint applies to `POSTGRES_PASSWORD` (especially in prod where it's embedded in `DATABASE_URL`): alphanumeric avoids both compose interpolation and URL-encoding inside `postgres://...`.

---

**Retro sources:**

- [M3-D17] Celery on Windows — `-P solo` (see `PROGRESS.md` retro M3)
- [M7-D33] `pre-commit clean` workflow (see `PROGRESS.md` retro M7)
- [M9-D43] MSYS path conversion + compose build race + `$VAR` interpolation (see `PROGRESS.md` retro M9)

**Related docs:**

- [`deploy-runbook.md`](deploy-runbook.md) — production deploy flow (reuses the same gotchas in `.env` + compose contexts)
- `CLAUDE.md` — project conventions + stack
