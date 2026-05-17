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
#   POSTGRES_HOST=localhost
#   POSTGRES_PORT=5435   — host port w docker-compose.dev.yml (NOT 5432)
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

The same constraint applies to `POSTGRES_PASSWORD`: alphanumeric avoids compose `$VAR` interpolation. Post-#163 the password lives in exactly one env var (no `DATABASE_URL` URL-encoding to also worry about), but the alphanumeric rule remains useful as a defence against compose interpolation.

## §7 DeathWatch smoke test (M12)

Manual post-deploy smoke for the per-character death blacklist feature.
Verifies the full pipeline: Discord slash command → DB watch row → Celery
task fires → spider scrapes Tibiantis → pipeline filters/persists →
notification handler posts purple embed to configured channel.

CLAUDE.md §15.6 — żaden automated test nie hituje live Tibiantis. Smoke
**MUSI** być manual (po deploy, przed claiming feature działa w prod).

### 7.1 Wybór trybu

Dwa konteksty — wybierz przed startem:

**A. Local dev (docker-compose.dev.yml)** — szybkie, bezpieczne, ale wymaga
że dev bot ma rzeczywisty Discord token i jest dołączony do testowego serwera
(`DISCORD_DEV_GUILD_ID` w `.env`). Wybierz dla pierwszego testu po nowych
zmianach modeli/spider/services.

**B. Prod (Hetzner)** — testuje real deploy + real DB + real Discord bot.
Wymaga SSH tunnel do Django admin (port 8000) — patrz `deploy-runbook.md`
§9 lub memory `reference_hetzner_vm`. Wybierz dla post-merge confirmation.

Kroki poniżej są identyczne dla obu trybów — różni się tylko **gdzie
uruchamiasz komendy** (local shell vs SSH na VM).

### 7.2 Pre-flight (musi być przed dotknięciem Discord)

**Lokalne dev:**
```bash
# Stack up
docker compose -f docker-compose.dev.yml up -d postgres redis mongo

# Migrate (powinno być no-op jeśli świeży master, ale defensywnie)
poetry run python manage.py migrate

# Sprawdź że seed PeriodicTask jest w DB (z DW-5 seed migration)
poetry run python manage.py shell -c "from django_celery_beat.models import PeriodicTask; pt = PeriodicTask.objects.get(name='deathwatch.scrape_for_watched_deaths'); print(f'enabled={pt.enabled} every={pt.interval.every} period={pt.interval.period}')"
```
Expected: `enabled=False every=1 period=minutes`. Jeśli `enabled=True` — ktoś
już włączył ten task wcześniej, **przejdź do kroku 7.5 z istniejącym stanem**
(nie restartuj Celery).

**Prod (Hetzner):**
```bash
ssh deploy@178.105.122.18
cd /opt/tibiantis
docker compose ps  # potwierdź wszystkie serwisy "healthy"
docker compose exec web python manage.py shell -c "from django_celery_beat.models import PeriodicTask; pt = PeriodicTask.objects.get(name='deathwatch.scrape_for_watched_deaths'); print(f'enabled={pt.enabled} every={pt.interval.every} period={pt.interval.period}')"
```

**Uruchom workery (tylko local dev):**
```bash
# Terminal 1 — Celery worker (Windows: -P solo per §2)
poetry run celery -A config worker -l info -P solo

# Terminal 2 — Celery beat
poetry run celery -A config beat -l info

# Terminal 3 — Discord bot
poetry run python manage.py run_discord_bot
```

W bot logach **MUSISZ** zobaczyć `Synced commands to dev guild <ID>` przed
przejściem dalej — bez tego `/deathwatch` nie pojawi się w Discord UI.

### 7.3 Step 1 — Skonfiguruj kanał Discord (admin-only)

Na testowym serwerze Discord, **w kanale gdzie mają iść ogłoszenia**:

1. Wpisz `/deathwatch channel`.
2. Expected: public ack `💀👀 DeathWatch announcements will be posted to this channel.`
3. Verify w DB (osobne terminal):
   ```bash
   # Local
   poetry run python manage.py shell -c "from apps.deathwatch.models import DeathWatchChannel; [print(f'guild={c.guild_id} channel={c.channel_id}') for c in DeathWatchChannel.objects.all()]"
   # Prod
   docker compose exec web python manage.py shell -c "..."
   ```
   Expected: jeden wpis z `guild_id` + `channel_id` matchującymi Discord.

**Negative test (skip w prod):** wpisz `/deathwatch channel` jako **non-admin
user**. Expected: ephemeral `❌ Only server admins can set the deathwatch channel.`

### 7.4 Step 2 — Dodaj watcha (per-user)

W dowolnym kanale lub DM (bot ma slash commands globalnie):

1. Wybierz **postać która rzeczywiście umiera** w grze. Najlepsze targety:
   - high-level character na PvP-enabled świecie (`Yhral`, `Bubble`, znana
     postać twojej gildii),
   - albo świadomie zaakceptuj że może nie być deathów przez parę godzin.
2. `/deathwatch add Yhral` (zamień `Yhral` na real character).
3. Expected: ephemeral `👀 Now watching \`Yhral\` for new deaths.`
4. `/deathwatch list` — verify postać widoczna. Lista jest **publiczna**
   (każdy user widzi watches od wszystkich) po PR #206 (M12 follow-up).
   Output jest **ephemeral** (tylko Ty widzisz w UI, nikt inny w kanale).

   Expected sample output (3 watches, cap 20):
   ```
   Active deathwatches (3/20):
   • `Yhral` (added by <@123>)
   • `Bubble` (added by <@456>)
   • `Eternal oblivion` (added by <@123>)
   ```
   - `(N/20)` — count unikalnych characters vs `DEATHWATCH_MAX_WATCHED_CHARACTERS`
     cap (spec §3.5). Reminder że cap jest **shared across all users**.
   - `<@discord_id>` — Discord mention syntax, renderuje się jako "@alice".
     **Sanity check:** Discord NIE powinien pingować user'ów przy `/list` —
     bot wysyła z `allowed_mentions=AllowedMentions.none()` (spec §3.3).
     Jeśli widzisz @ping → handler routing broken.
   - Empty state (zero watches w systemie):
     ```
     No active deathwatches. Add one with `/deathwatch add <name>`.
     ```

5. Verify w DB:
   ```bash
   poetry run python manage.py shell -c "from apps.deathwatch.models import DeathWatch; [print(f'{w.user.username} → {w.character.name} (active={w.active}, created_at={w.created_at})') for w in DeathWatch.objects.all()]"
   ```
   Expected: row z `active=True`, `created_at` = teraz.

**Pułapka §3.6 ("po dodaniu"):** historyczne śmierci z tabeli profilu (sprzed
`created_at`) zostaną **zignorowane**. Tabela Latest Deaths na tibiantis.online
pokazuje ostatnie ~10 deaths — spider wszystkie sczyta, service'y odrzucą
te sprzed dodania watcha. Jeśli postać ostatnio umarła wczoraj, nic się nie
pojawi dopóki nie umrze **ponownie**.

### 7.5 Step 3 — Włącz PeriodicTask (admin Django)

**Local dev (przez admin UI):**
1. Otwórz `http://localhost:8000/admin/django_celery_beat/periodictask/`.
2. Kliknij `deathwatch.scrape_for_watched_deaths`.
3. Check `Enabled` checkbox → Save.

**Prod (SSH tunnel + admin UI):**
1. Setup tunnel — patrz tunnel z naszej wcześniejszej sesji:
   ```bash
   ssh -N -L 3001:localhost:3001 -L 5432:localhost:5432 deploy@178.105.122.18
   ```
   (jeśli web ma localhost-only binding na VM, dologuj `-L 8000:localhost:8000`).
2. `http://localhost:8000/admin/django_celery_beat/periodictask/` → enable.

**Alternatywnie z shell (bez UI):**
```bash
poetry run python manage.py shell -c "from django_celery_beat.models import PeriodicTask; pt = PeriodicTask.objects.get(name='deathwatch.scrape_for_watched_deaths'); pt.enabled = True; pt.save(); print(f'enabled={pt.enabled}')"
```
Expected: `enabled=True`.

### 7.6 Step 4 — Verify task fires (1-2 min waiting)

Beat scheduler pollsuje co `BEAT_MAX_LOOP_INTERVAL` (default 5 sec) i odpala
task na początku każdej pełnej minuty. Pierwszy fire możesz zobaczyć w **0-60s**.

**Watch Celery worker logs** (gdzie task wykonuje się):
```
[INFO/ForkPoolWorker-1] Task apps.deathwatch.tasks.scrape_for_watched_deaths[<uuid>] received
[INFO/ForkPoolWorker-1] scrape_for_watched_deaths: {'checked': 1, 'skipped': 0, 'scraped': 1, 'failed': 0, 'events_announced': 0, 'locked': False}
[INFO/ForkPoolWorker-1] Task apps.deathwatch.tasks.scrape_for_watched_deaths[<uuid>] succeeded
```

`events_announced=0` jest **OK** dla pierwszego fire'u — żaden nowy death
jeszcze nie wpadł (filtr "po dodaniu").

**Verify `last_deaths_scraped_at` updateowane** (proves task ran + subprocess
worked):
```bash
poetry run python manage.py shell -c "from apps.characters.models import Character; c = Character.objects.get(name='Yhral'); print(f'last_deaths_scraped_at={c.last_deaths_scraped_at}')"
```
Expected: timestamp z ostatnich ~1 min.

**Jeśli `last_deaths_scraped_at` is None po 2 min:**
- Sprawdź worker logs za `subprocess` errors (timeout, returncode != 0).
- Sprawdź Mongo `scrape_logs` collection za HTTP errors:
  ```bash
  poetry run python manage.py shell -c "from logs_backend.client import get_collection; [print(d) for d in get_collection('scrape_logs').find().sort('started_at', -1).limit(3)]"
  ```
- Lock contention? Sprawdź Redis: `docker compose exec redis redis-cli get deathwatch_scrape_lock` — powinno być `(nil)` między fires.

### 7.7 Step 5 — Wait for actual death (variable czas)

Postać musi rzeczywiście umrzeć w grze, **po `watch.created_at`**. Może to
być sekundy (jeśli to PvP-active char) albo godziny (jeśli low-traffic).

**Gdy death wpadnie, expected:**
1. Worker logs: `events_announced=1` w następnym task summary.
2. Discord channel (skonfigurowany w 7.3): purple embed:
   - Title: **Character name** (klikalne, link do tibiantis.online profile).
   - Description:
     ```
     Died at level <N>
     <YYYY-MM-DD HH:MM:SS>
     Killed by: <killer>
     ```
   - Color: dark purple (`#8B008B`).
3. Verify w DB `WatchedDeathEvent`:
   ```bash
   poetry run python manage.py shell -c "from apps.deathwatch.models import WatchedDeathEvent; [print(f'{e.character.name} lvl {e.level_at_death} @ {e.died_at} announced={e.announced_on_discord}') for e in WatchedDeathEvent.objects.all()]"
   ```
   Expected: row z `announced_on_discord=True`.

**Visual sanity:** embed kolor MUSI być **fioletowy** (`#8B008B`), nie
crimson (`#DC143C`) — crimson to M4 deaths feature, fiolet to DW-6 (spec §3.11).
Jeśli widzisz crimson — handler routing jest broken, sprawdź
`settings.DEATHWATCH_NOTIFICATION_HANDLER`.

### 7.8 Step 6 — Cleanup

**Wyłącz PeriodicTask** (żeby nie bombić Tibiantis bez powodu):
```bash
poetry run python manage.py shell -c "from django_celery_beat.models import PeriodicTask; pt = PeriodicTask.objects.get(name='deathwatch.scrape_for_watched_deaths'); pt.enabled = False; pt.save()"
```

**Usuń test watcha:** Discord → `/deathwatch remove Yhral`.
Expected: ephemeral `🗑️ Stopped watching \`Yhral\`.`

**(Opcjonalnie) Usuń test channel config:**
```bash
poetry run python manage.py shell -c "from apps.deathwatch.models import DeathWatchChannel; DeathWatchChannel.objects.all().delete()"
```

**(Opcjonalnie) Usuń test events:**
```bash
poetry run python manage.py shell -c "from apps.deathwatch.models import WatchedDeathEvent; WatchedDeathEvent.objects.all().delete()"
```

### 7.9 Common failure modes

| Symptom | Diagnose | Fix |
|---|---|---|
| `/deathwatch` nie pojawia się w Discord | Bot logs nie pokazują "Synced commands" | Restart bot. Verify `DISCORD_DEV_GUILD_ID` w `.env`. |
| `/deathwatch add` → "Something went wrong" | Cog rzucił unhandled exception | `docker compose logs discord_bot` — szukaj traceback. Najczęściej canonicalize edge case lub User auto-create race. |
| Task fires ale `scraped=0` | Spider crashes wewnątrz subprocess | Sprawdź `manage.py scrape_character_deaths <name>` ręcznie — output pokaże traceback. |
| Task fires `scraped=1`, brak embed | Channel nie skonfigurowany / handler error / "po dodaniu" filtr drop | Verify `DeathWatchChannel` ma row. Sprawdź worker logs za handler exceptions. Sprawdź `WatchedDeathEvent` count vs `announced_on_discord=True` count. |
| Embed pojawia się ale crimson zamiast fiolet | Handler routing M4 zamiast DW-6 | Verify `settings.DEATHWATCH_NOTIFICATION_HANDLER=apps.notifications.handlers.DeathWatchChannelHandler`. |
| Task `locked=True` przez kilka fires z rzędu | Poprzedni fire crashed bez release locka | `docker compose exec redis redis-cli del deathwatch_scrape_lock`. |
| `bigint out of range` przy `setDeathWatchChannel` GraphQL mutation | Test snowflake > 2^63-1 | Użyj real Discord snowflake (zawsze < 2^63 do ~2070r). |

---

**Retro sources:**

- [M3-D17] Celery on Windows — `-P solo` (see `PROGRESS.md` retro M3)
- [M7-D33] `pre-commit clean` workflow (see `PROGRESS.md` retro M7)
- [M9-D43] MSYS path conversion + compose build race + `$VAR` interpolation (see `PROGRESS.md` retro M9)
- [M12 DW-1..9] DeathWatch smoke flow (see `PROGRESS.md` retro M12 — 10 lessons learned)

**Related docs:**

- [`deploy-runbook.md`](deploy-runbook.md) — production deploy flow (reuses the same gotchas in `.env` + compose contexts)
- `CLAUDE.md` — project conventions + stack
