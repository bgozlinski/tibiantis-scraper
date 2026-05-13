# M7 — Discord bot commands — Implementation plan

**Data:** 2026-05-13
**Spec:** [`docs/superpowers/specs/2026-05-13-m7-discord-bot-commands-design.md`](../specs/2026-05-13-m7-discord-bot-commands-design.md)
**Status:** READY (spec accepted, decyzje §3.1-3.8 zaakceptowane przez developera 2026-05-13).

---

## Źródła

- **CLAUDE.md** §1 (4. Discord Bot jako kluczowa funkcja), §2 (`discord.py (py-cord)` w stosie), §3 (`discord_bot/` top-level struktura z `cogs/`, `bot.py`, `management/commands/`), §4 (model `DiscordChannel` zapowiedziany), §7 (próg poziomu edytowalny przez admina), §8 (4 slash commands + bot rules + auto-create user default), §10 (`DISCORD_BOT_TOKEN`, `DISCORD_DEFAULT_CHANNEL_ID` env vars w `.env.example`), §15.2 (logika biznesowa w services.py).
- **Design spec M7** — kluczowy dokument referencyjny. Każdy issue body linkuje do spec'a §X.
- **Precedensy z M0-M6:**
  - M2-D11 — `sync_to_async(...)` boundary pattern w GraphQL async resolverach. M7 cogi reusing dla ORM calls.
  - M5-D23 — pierwszy app po stubs.py reform: `UniqueConstraint(name=...)` w `Meta.constraints` (NIE deprecated `unique_together`), `unique=True` nie razem z UniqueConstraint na tym samym polu.
  - M5-D24 — services type-hint convention: direct `from apps.accounts.models import User` (memory `feedback_services_user_type_hint.md`).
  - M5-D25 — Protocol-based handler abstraction (`apps/notifications/`) — M8 zamieni `LoggingHandler` na `DiscordHandler`. M7 NIE rusza `apps/notifications/`.
  - M6-D28 — top-level Python package wzorzec (`logs_backend/`); M7 dodaje pierwszy **top-level Django app** (różnica: ma `apps.py` + `models.py` + `INSTALLED_APPS` entry).
  - M6-D29 retro lekcja #1 — eager resource lookup w `__init__` (twice w M6: `MongoLogHandler.__init__`, `MongoStatsExtension.__init__`). M7 unika: bot bootstrap lazy w `setup_bot()`, services z lazy User fetch.
  - M6 retro lekcja #2 — `propagate: False` cisza pytest caplog. M7 LOGGING edit explicit `propagate: True` na `"discord_bot"` logger.

---

## Pre-flight checklist (przed startem D31)

- [ ] **`discord_bot/` nie istnieje** — sprawdzone 2026-05-13, fresh creation.
- [ ] **User model `discord_id` field istnieje** — migracja `apps/accounts/migrations/0003_alter_user_discord_id.py` (sprawdź).
- [ ] **`apps/bedmages/services.py` API** — `add_bedmage_watch(user, character_name)` raises `ValueError` na duplicate active, `remove_bedmage_watch(user, character_name) -> bool` hard-delete (sprawdzone 2026-05-13). M7 wrapper'y opakowują, M5 services nietknięte.
- [ ] **`py-cord` w `pyproject.toml`** — sprawdź, brakuje. D31 dorzuca `poetry add py-cord` w osobnym `build(deps)` commit.
- [ ] **`pytest-asyncio` w `pyproject.toml`** — sprawdzone 2026-05-13, jest (M2-D11). Plus `asyncio_mode = "auto"` w `pyproject.toml` `[tool.pytest.ini_options]` (już ustawione).
- [ ] **Discord bot tworzony na Discord Developer Portal** — `DISCORD_BOT_TOKEN` musi być user-provided przed manual smoke (D35). NIE blocker dla D31-D34 (testy mockowane).
- [ ] **Dev guild ID** — user musi mieć Discord serwer testowy z bot zaproszonym, `DISCORD_DEV_GUILD_ID` env var ustawiony. NIE blocker dla unit testów.
- [ ] **PROCESS gotcha: pre-commit `no-commit-to-branch` hook** (PR #105, merged M5) — blokuje commits na master. **Każdy D-task wymaga `git checkout -b feat/<#>-...` PRZED kodowaniem** (CLAUDE.md §12).

---

## Otwarte pytania (rozstrzygnięte 2026-05-13, spec §3)

Wszystkie 8 decyzji designowych ze spec'a §3 zaakceptowane bez modyfikacji:

1. ✅ **§3.1** Top-level Django app `discord_bot/` (NIE pod `apps/`).
2. ✅ **§3.2** Wrapper services w `discord_bot/services.py`, NIE modyfikacja `apps.bedmages.services`.
3. ✅ **§3.3** Auto-create Django User po `discord_id` (`username=f"discord_{id}"`, `email=""`).
4. ✅ **§3.4** `DiscordChannel` per-guild (`unique=guild_id`).
5. ✅ **§3.5** Discord Server Admin permission dla `/deaths threshold`.
6. ✅ **§3.6** Per-guild command sync na `on_ready` w devie (env var `DISCORD_DEV_GUILD_ID`), globalnie w prod.
7. ✅ **§3.7** Bot tylko **command-handling** w M7 (NIE outbound — M8 scope).
8. ✅ **§3.8** LOGGING dict — dodać `"discord_bot"` named logger (`handlers: ["console", "mongo"]`, `propagate: True`).

**Open questions z §9** (do M-future, NIE w M7 scope):
- JWT linking Discord ↔ istniejące Django konto
- Per-channel threshold
- `DiscordChannel.notification_enabled` toggle
- Bot service w `docker-compose.dev.yml`
- Discord OAuth flow
- i18n responses
- Permission caching
- Bot command stats dashboard
- `DEATH_LEVEL_THRESHOLD` env deprecation strategy

---

## Risk + mitigation

| Ryzyko | Prawdopodobieństwo | Impact | Mitigation |
|---|---|---|---|
| **py-cord vs discord.py API confusion** | Średnie (Stack Overflow examples mieszają) | Bot wiring crash przy starcie | Spec §3 + plan AC trzymają się **py-cord 2.x API** (`discord.Bot`, `SlashCommandGroup`, `ApplicationContext`). M7 NIE używa `discord.py` (różny event handler signature). Sanity przed D32: `poetry run python -c "import discord; print(discord.__version__)"` → 2.x. |
| **Async/sync boundary w cog handlerze** | Średnie (M2-D11 lekcja dla GraphQL) | `SynchronousOnlyOperation` exception przy ORM call w async context | `sync_to_async(service)(...)` pattern w każdym cog handlerze. Testy używają `@pytest.mark.asyncio` + mocked service (nie hit ORM). |
| **LOGGING dict edit (`discord_bot` named logger) reaguje na M6 caplog regression** | Niskie (M6 fix `propagate: True`) | Cog test failures w caplog assertions | §3.8 explicit `propagate: True`. Test smoke: `caplog.records` musi capture `discord_bot.bot:logger.exception(...)` w error handler test. |
| **Mocking `discord.ApplicationContext` w testach** | Wysokie (complex API) | Testy padają lub false-positive (mock'i nie reflect real behavior) | Pattern z spec §7.2: `MagicMock(spec=discord.ApplicationContext)` + manual `ctx.author.id`/`ctx.author.name`/`ctx.respond=AsyncMock()`. `cog.<command>.callback(cog, ctx, **kwargs)` bypass slash option parsing. |
| **Bot bootstrap order (cogs added BEFORE `bot.run`, `sync_commands` AFTER `on_ready`)** | Niskie | Commands NIE pojawiają się w Discordzie | `setup_bot()` factory function dodaje cogi PRZED `bot.run()`. `sync_commands(...)` ZAWSZE w `on_ready` event handler (Discord must accept gateway connection first). |
| **`discord_bot` top-level app vs `apps.*` mypy strict** | Średnie | mypy strict regression na nowym pakecie | `[tool.mypy] strict = true, exclude = ["scrapers/"]` aktualnie. `discord_bot/` ŁAPIE strict mode (nie excluded). Plus pre-commit `mypy: files: ^apps/` — `discord_bot/` excluded z pre-commit hook (jak `logs_backend/` w M6). M7 NIE rozszerza mypy scope, ale CI run-time pełen `mypy` przejdzie `discord_bot/` przy każdym builda (sanity: lokalnie `poetry run mypy discord_bot/` przed push). |
| **Discord API rate limits przy command sync** | Niskie (per-guild) | `on_ready` retry hammers Discord API | py-cord `sync_commands` ma built-in rate limit handling. Per-guild sync używa różnego rate budget niż global. Dev guild ID env var mitigates. |
| **`asgiref.sync_to_async` thread context dla Django ORM** | Niskie (M2-D11 confirmed working) | `SynchronousOnlyOperation` lub stale data | M2-D11 pattern reused. `sync_to_async(service_fn)(...)` w cogu, services pozostają sync. |
| **User auto-create race condition** (2 concurrent commands od nowego Discord user'a) | Niskie | Duplicate User IntegrityError | `User.objects.get_or_create(discord_id=...)` w `transaction.atomic()` block. Django ORM `get_or_create` jest race-safe na `unique` field. |
| **`DISCORD_BOT_TOKEN` w `.env` ale invalid** | Średnie (typo, expired) | `discord.LoginFailure` przy starcie | Management command nie catchuje — Python crash z czytelnym traceback. User naprawia w `.env`, restart. Dla prod (M9): docker `restart: unless-stopped` + Sentry-like alert (M-future). |

---

## Task overview

| # | ID | Tytuł | Czas | Zależy od | Branch |
|---|---|---|---|---|---|
| 1 | M7-D31 | `discord_bot/` app scaffolding + `DiscordChannel` model + admin + user/threshold services | 2-3h | M6 closed | `feat/<#>-discord-app-scaffold` |
| 2 | M7-D32 | py-cord bootstrap + `bot.py` + `run_discord_bot` management command + on_ready sync + global error handler + LOGGING dict edit | 2-3h | D31 merged | `feat/<#>-discord-bot-bootstrap` |
| 3 | M7-D33 | `BedmageCog` z 3 commands (`/bedmage add/remove/list`) + bedmage wrapper services | 2-3h | D32 merged | `feat/<#>-discord-bedmage-cog` |
| 4 | M7-D34 | `DeathsCog` z `/deaths threshold` + admin perm check + DM rejection | 2h | D33 merged | `feat/<#>-discord-deaths-cog` |
| 5 | M7-D35 | M7 e2e (command registration sanity) + closure (PROGRESS.md retro + milestone close) | 2h | D34 merged | `feat/<#>-m7-e2e` + `docs/close-m7-discord-bot-commands` |

**Total:** ~10-13h, ~2 dni roboczych. Mniejszy niż M5 (13-15h, 5 D-tasków) bo M7 jest cienki (bot commands = cienkie wrappery na M5 services + jeden nowy model).

---

## Task #1 — [M7-D31] `discord_bot/` app + `DiscordChannel` model + admin + initial services

### 🎯 Cel

Utworzyć `discord_bot/` jako **top-level Django app** (CLAUDE.md §3 directive), zarejestrować w `LOCAL_APPS`, dodać model `DiscordChannel` (per-guild config, `unique=guild_id`), Django admin registration, plus dwa pierwsze services: `get_or_create_user_by_discord_id` (auto-create User per CLAUDE.md §8 default) i `set_death_threshold_for_guild` (upsert DiscordChannel). Po D31: model + services są testable osobno, **bez** discord.py jeszcze (czyste Django code, łatwiejszy start).

### 🧠 Czego się nauczysz

- **Top-level Django app pattern** — różnica od `apps/*` (path nie pod `apps/`, ale rejestrowany jako `"discord_bot"` w `INSTALLED_APPS`). M6 `logs_backend/` precedens, ale `discord_bot/` jest Django app (ma `apps.py`, `models.py`, migrations) — `logs_backend/` nie był. Mix oba pattern coexist.
- **`BigIntegerField` dla Discord snowflake** — Discord IDs są 64-bit unsigned. `BigIntegerField` wystarczy (Postgres BIGINT, signed 64-bit — Discord nie używa most-significant bit). Plus `UniqueConstraint(fields=["guild_id"], name="discord_channel_one_per_guild")` w `Meta.constraints` (M5-D23 idiom).
- **`User.objects.get_or_create(discord_id=...)`** + `User.set_unusable_password()` dla auto-created accounts — race-safe, password unusable bo user nie loguje się normalnie (tylko przez Discord).
- **Upsert pattern w services** — `DiscordChannel.objects.update_or_create(guild_id=..., defaults={"channel_id":..., "death_level_threshold":...})` zwraca `(channel, created)`. Idempotent z punktu view bot wywołania `/deaths threshold`.

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m7-d31.md`.)

**Kluczowe punkty:**
- `discord_bot/` katalog z `__init__.py`, `apps.py` (`AppConfig(name="discord_bot")`), `models.py`, `admin.py`, `services.py`, `migrations/0001_initial.py`.
- `DiscordChannel(guild_id BigInteger, channel_id BigInteger, death_level_threshold PositiveInteger default=30, created_at auto, updated_at auto)` z `UniqueConstraint(fields=["guild_id"], name="discord_channel_one_per_guild")`.
- Admin: `@admin.register(DiscordChannel)` z `list_display=("guild_id", "channel_id", "death_level_threshold", "updated_at")`, `search_fields=("guild_id",)`, `readonly_fields=("created_at", "updated_at")`.
- `LOCAL_APPS` w `config/settings/base.py` rozszerzony o `"discord_bot"` — `stubs.py` automatycznie podchwyci (M2 reform).
- Services:
  - `get_or_create_user_by_discord_id(discord_id: int, discord_username: str) -> tuple[User, bool]` — `User.objects.get_or_create(discord_id=..., defaults={"username": f"discord_{id}", "email": ""})` + `set_unusable_password()` na nowy.
  - `set_death_threshold_for_guild(guild_id: int, channel_id: int, threshold: int) -> DiscordChannel` — `update_or_create(guild_id=..., defaults={...})`.
- ~5 unit testów (model save + unique constraint enforcement + 2× get_or_create_user + 2× set_threshold).

### ⚠️ Pułapki do uwagi

- **A — Top-level NIE pod `apps/`** — `discord_bot/` katalog na tym samym poziomie co `apps/`, `scrapers/`, `logs_backend/`, NIE jako `apps/discord_bot/`. CLAUDE.md §3 strukturalnym directive. Import: `from discord_bot.models import DiscordChannel` (jednoznaczny, brak `apps.` prefix).
- **B — `LOCAL_APPS` entry to string `"discord_bot"` (bez `apps.` prefix)** — różny od `LOCAL_APPS = ["apps.characters", "apps.accounts", ...]` pattern. Po `stubs.py` reform z M2 (single source of truth), mypy automatycznie picknie nowy app — żadnej dodatkowej edycji `stubs.py` nie wymaga.
- **C — `User.discord_id` już istnieje** — migracja `apps/accounts/migrations/0003_alter_user_discord_id.py`. NIE twórz nowej migracji. Sprawdź typ field'a — jeśli `CharField` zamiast `BigIntegerField`, M7 wymaga **lekkiego refactoringu** w osobnym chore PR (carry-over, NIE w D31). Jeśli już BigInteger / unique → ok.
- **D — `UniqueConstraint(name=...)` w `Meta.constraints`, NIE `unique_together`** (M5-D23 idiom). `name="discord_channel_one_per_guild"` musi być unikalny w schemacie. NIE dorzucaj `unique=True` na sam field — dwa różne constraint dla tej samej kolumny, redundancja (M5-D23 retro punkt explicit).
- **E — `set_unusable_password()` po `User.objects.create_user(...)` lub `get_or_create(...)`** — Django default `User.objects.create(...)` ustawia password jako string raw (NIE hashed). `set_unusable_password()` ustawia password flag tak, że żadne hasło nie zaloguje user'a. Wzorzec dla bot-managed accounts.
- **F — Auto-create User w `transaction.atomic()`** — race-safe dla 2 concurrent commands od nowego Discord user'a. `get_or_create` Django ORM is itself transaction-aware, ale explicit `atomic()` block dla pewności.
- **G — Services type-hint convention** (M5-D24 memory `feedback_services_user_type_hint.md`) — `from apps.accounts.models import User` direct import w services, NIE `AbstractUser` / `get_user_model()`. mypy strict + django-stubs ekspekta concrete User type dla FK lookups.
- **H — Migracja `0001_initial.py` musi być commitowana razem ze zmianą `models.py`** (CLAUDE.md §11). `poetry run python manage.py makemigrations discord_bot` po `INSTALLED_APPS` edit, sprawdzić że nazwa `0001_initial.py` (NIE `0001_auto_<timestamp>.py` — `makemigrations` Django 6+ default).

### 🧪 Testing plan

`tests/unit/discord_bot/__init__.py` (pusty) + `tests/unit/discord_bot/test_models.py` + `tests/unit/discord_bot/test_services.py`:

**`test_models.py` (~2 testy):**
- `test_discord_channel_save_persists_all_fields` — create + retrieve, assert wszystkie pola match.
- `test_discord_channel_unique_constraint_on_guild_id` — drugi `DiscordChannel(guild_id=X)` save → `IntegrityError`. Sanity że `UniqueConstraint` enforced (`db_constraint=True` default).

**`test_services.py` D31 część (~5 testów):**
- `test_get_or_create_user_creates_new_user_with_discord_username_pattern` — pierwszy call, assert `User(discord_id=X, username="discord_X", email="")` created, `has_usable_password() == False`.
- `test_get_or_create_user_returns_existing_user_on_second_call` — drugi call z tym samym `discord_id` zwraca existing, `created=False`, NIE duplicate.
- `test_set_death_threshold_creates_new_discord_channel_on_first_call` — assert `DiscordChannel(guild_id=X, channel_id=Y, death_level_threshold=Z)` created.
- `test_set_death_threshold_updates_existing_channel` — drugi call dla tego samego guild_id z innym threshold → update_or_create updates row, NIE duplicate.
- `test_set_death_threshold_updates_channel_id_when_changed` — guild moved threshold command z innego kanału — channel_id w DB reflectuje latest.

**Coverage cel:** `discord_bot/__init__.py` 100%, `discord_bot/apps.py` 100%, `discord_bot/models.py` 100%, `discord_bot/admin.py` ~80% (admin classes hard to fully exercise w unit testach), `discord_bot/services.py` (D31 część) 100%.

### 📦 Definition of Done

- [ ] AC spełnione (app structure, model, admin, 2 services).
- [ ] PR zmergowany squash (`feat(discord): app scaffold + DiscordChannel model + initial services (M7-D31, #<#>)`).
- [ ] CI lint + test zielone.
- [ ] `discord_bot/*.py` (D31 część) 100% coverage.
- [ ] Migracja `0001_initial.py` w PR'ze.
- [ ] Issue zamknięty.

---

## Task #2 — [M7-D32] py-cord bootstrap + management command + global error handler + LOGGING edit

### 🎯 Cel

Dorzucić `py-cord` jako dependency (osobny `build(deps)` commit), utworzyć `discord_bot/bot.py` z bot instance + `on_ready` event handler (sync commands per-guild dev / globally prod) + global `on_application_command_error` listener (clean ephemeral msg + Mongo log z `exc_info`), `discord_bot/management/commands/run_discord_bot.py` jako entry point, edytować `config/settings/base.py` o `DISCORD_BOT_TOKEN` / `DISCORD_DEV_GUILD_ID` env reads + `"discord_bot"` named logger w `LOGGING` dict, dorzucić env vars do `.env.example`. **Bez cogów** — `setup_bot()` zwróci `discord.Bot` bez `add_cog(...)` calls (D33+D34 dorzucą). Po D32: management command startuje, łaczy się z Discord (jeśli token valid), nie ma żadnych slash commands jeszcze.

### 🧠 Czego się nauczysz

- **py-cord 2.x API** — `discord.Bot(intents=discord.Intents.default())` (default intents wystarczą dla slash commands), `bot.run(token)` blocks main thread, `@bot.event async def on_ready()` lifecycle hook.
- **Discord intents** — `Intents.default()` jest minimalne (no message content read). Slash commands NIE wymagają privileged intents. M-future jeśli dodamy listening na message content (np. `@bot.command()` prefix commands), wtedy wymagane `intents.message_content = True` + portal toggle.
- **`bot.sync_commands(guild_ids=[...])` vs globalny sync** — per-guild = instant propagacja (cache scope = guild), globalny = do 1h (cache scope = Discord global). Dev env var `DISCORD_DEV_GUILD_ID` przełącza tryby.
- **`on_application_command_error` global listener** — łapie unhandled exceptions z każdego coga. Alternatywa: `cog_command_error` per cog (więcej boilerplate, M7 YAGNI).
- **`ctx.response.is_done()`** — Discord interaction ma 3s deferred response window. Jeśli cog handler już respondował (przed exception), `ctx.followup.send(...)` zamiast `ctx.respond(...)` (Discord API requirement).
- **Django logging `propagate: True` z named logger** — M6 retro lekcja #2, `propagate: False` ciszy pytest caplog. M7 LOGGING edit jest 4-linijkowy:
  ```python
  "loggers": {
      "apps": { ... existing ... },
      "discord_bot": {"handlers": ["console", "mongo"], "level": "INFO", "propagate": True},
  }
  ```

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m7-d32.md`.)

**Kluczowe punkty:**
- `pyproject.toml` rozszerzone o `py-cord (>=2.6,<3.0)` w `[project.dependencies]`. Osobny commit `build(deps): add py-cord for Discord bot (M7-D32, #<#>)`.
- `.env.example` rozszerzone o:
  ```
  # Discord bot
  DISCORD_BOT_TOKEN=
  DISCORD_DEV_GUILD_ID=
  ```
- `config/settings/base.py` rozszerzone o:
  - `DISCORD_BOT_TOKEN = env("DISCORD_BOT_TOKEN", default="")`
  - `DISCORD_DEV_GUILD_ID = env.int("DISCORD_DEV_GUILD_ID", default=0)` (0 = unset, używaj global sync)
  - `LOGGING["loggers"]["discord_bot"] = {"handlers": ["console", "mongo"], "level": "INFO", "propagate": True}`.
- `discord_bot/bot.py`:
  - `bot = discord.Bot(intents=discord.Intents.default())` module-level.
  - `@bot.event async def on_ready()` — log "Bot logged in as %s (id=%s)" + sync commands per `DISCORD_DEV_GUILD_ID` (jeśli >0) lub global.
  - `@bot.event async def on_application_command_error(ctx, error)` — `logger.exception(...)` + ephemeral generic msg.
  - `setup_bot() -> discord.Bot` factory function (D32: NO cogs added; D33+D34 dorzucą).
- `discord_bot/management/__init__.py` + `discord_bot/management/commands/__init__.py` + `discord_bot/management/commands/run_discord_bot.py`:
  ```python
  class Command(BaseCommand):
      help = "Run the Discord bot (blocks until interrupted)"
      def handle(self, *args, **options):
          if not settings.DISCORD_BOT_TOKEN:
              self.stderr.write("DISCORD_BOT_TOKEN not set in env")
              return
          bot = setup_bot()
          bot.run(settings.DISCORD_BOT_TOKEN)
  ```
- ~5 unit testów (bot bootstrap + on_ready + error handler + run_discord_bot command + LOGGING smoke).

### ⚠️ Pułapki do uwagi

- **A — `py-cord` NIE `discord.py`** — PyPI: `py-cord`, import: `import discord`. **Konflikt nazwy** — gdy zarówno `discord.py` i `py-cord` są zainstalowane, Python crash przy `import discord` (oba zajmują namespace `discord`). Sprawdź `pyproject.toml` że NIE ma `discord.py` przed `poetry add py-cord`.
- **B — Default intents wystarczą dla slash commands** — `Intents.default()` nie zawiera `message_content` (privileged). Slash commands lecą przez Interaction Gateway, nie message events. NIE wymaga toggle'a w Discord Developer Portal.
- **C — `bot.sync_commands(guild_ids=[...])` jest async — musi być wewnątrz async event handler'a** (np. `on_ready`), NIE w `setup_bot()` sync function. `setup_bot()` tylko adds cogs + returns bot instance. Sync happens po `bot.run()` initiates gateway connection.
- **D — `on_ready` może odpalić **wielokrotnie**** w jednej sesji (jeśli bot reconnect'uje się). Defense: ustaw `bot.is_ready_synced = True` flag po pierwszym sync, sprawdź w handler'ze. **YAGNI dla M7** — duplicate sync to no-op po stronie Discord (cache), ale loguj że "Bot reconnected" zamiast pełnego sync flow. Decision: minimalistyczne, log tylko, pierwsze sync wystarczy (sync_commands jest idempotent).
- **E — `ctx.respond` vs `ctx.followup.send` w error handlerze** — jeśli cog już respondował przed raise, drugi `ctx.respond` rzuca `discord.errors.InteractionResponded`. Defense: `if ctx.response.is_done(): await ctx.followup.send(...)` else `await ctx.respond(...)`.
- **F — Management command `bot.run(...)` BLOCKING** — `bot.run` nigdy nie returns (poza CTRL+C). NIE wykonuj nic po `bot.run()` w `handle()`. Sygnalizacja Ctrl+C → `KeyboardInterrupt` → discord.py cleanup.
- **G — `DISCORD_BOT_TOKEN` empty w env** — management command **NIE crash'uje** Python'em (czytelne stderr + clean exit). Manual smoke: `poetry run python manage.py run_discord_bot` z empty `.env` → "DISCORD_BOT_TOKEN not set in env" + exit code 0 (clean exit), bo Django command return code default 0 chyba że raise.
- **H — `env.int("DISCORD_DEV_GUILD_ID", default=0)`** — `django-environ` `env.int` requires default jako int (NIE string). Jeśli env var empty → fallback 0. `0` (= empty/unset) → on_ready uses global sync.
- **I — Test mocking `bot.run(...)`** — `bot.run` is sync (blocking forever w real life). Mock `bot.run` z `MagicMock()` w test'ach żeby `Command.handle()` nie hang'ował. `monkeypatch.setattr("discord_bot.bot.bot.run", MagicMock())` w teście.
- **J — `pyproject.toml` deduplikacja** — `poetry add py-cord` może dorzucić `discord-py` indirect przez resolution. Sprawdź `poetry show py-cord` że NIE pulls `discord.py` parallel. Plus sprawdź `pyproject.toml` że NIE ma `discord.py` w `[project.dependencies]` aktualnie (sanity, 2026-05-13 fresh).

### 🧪 Testing plan

`tests/unit/discord_bot/test_bot_bootstrap.py` (~3 testy) + `tests/unit/discord_bot/test_run_discord_bot_command.py` (~2 testy) + `tests/unit/discord_bot/test_error_handler.py` (~2 testy):

**`test_bot_bootstrap.py`:**
- `test_setup_bot_returns_discord_bot_instance` — `setup_bot()` zwraca `discord.Bot` (NIE crash, NIE None).
- `test_on_ready_syncs_per_guild_when_dev_guild_id_set` — mock `bot.sync_commands` + `DISCORD_DEV_GUILD_ID=12345` settings override, invoke `on_ready` handler, assert `sync_commands.assert_called_with(guild_ids=[12345])`.
- `test_on_ready_syncs_globally_when_dev_guild_id_unset` — `DISCORD_DEV_GUILD_ID=0`, assert `sync_commands.assert_called_with()` (no kwargs, global sync).

**`test_run_discord_bot_command.py`:**
- `test_run_discord_bot_exits_when_token_empty` — `@override_settings(DISCORD_BOT_TOKEN="")`, `call_command("run_discord_bot", stderr=StringIO())`, assert stderr contains "DISCORD_BOT_TOKEN not set". Plus `bot.run` NIE called (mock).
- `test_run_discord_bot_calls_bot_run_when_token_set` — `@override_settings(DISCORD_BOT_TOKEN="fake-token")`, mock `bot.run`, `call_command("run_discord_bot")`, assert `bot.run.assert_called_once_with("fake-token")`.

**`test_error_handler.py`:**
- `test_error_handler_responds_with_ephemeral_generic_when_response_not_done` — mock `ctx` z `ctx.response.is_done() == False`, `ctx.respond=AsyncMock()`, invoke handler z `RuntimeError`, assert `ctx.respond(<generic msg>, ephemeral=True)` called.
- `test_error_handler_uses_followup_when_response_already_done` — mock `ctx.response.is_done() == True`, `ctx.followup.send=AsyncMock()`, assert `followup.send(<generic msg>, ephemeral=True)` called.

**Coverage cel:** `discord_bot/bot.py` ~80% (sync_commands API hard to mock kompletnie — internal py-cord logic), `discord_bot/management/commands/run_discord_bot.py` 100%.

### 📦 Definition of Done

- [ ] AC spełnione (py-cord dep, bot.py, management command, LOGGING edit, env vars).
- [ ] **2 commity osobne:** `build(deps): add py-cord` + `feat(discord): bot bootstrap + management command + LOGGING dispatcher`.
- [ ] PR zmergowany squash (jeden squash zawiera oba commity).
- [ ] CI lint + test zielone.
- [ ] Manual smoke: `DISCORD_BOT_TOKEN="" poetry run python manage.py run_discord_bot` → "DISCORD_BOT_TOKEN not set" + exit. Jeśli user ma real token: `DISCORD_BOT_TOKEN=<real> DISCORD_DEV_GUILD_ID=<dev> poetry run python manage.py run_discord_bot` → "Bot logged in as ..." + sync 0 commands (bo brak cogów jeszcze).
- [ ] Issue zamknięty.

---

## Task #3 — [M7-D33] `BedmageCog` + 3 commands + bedmage wrapper services

### 🎯 Cel

Dorzucić 3 wrapper services do `discord_bot/services.py` (`add_bedmage_for_discord_user`, `remove_bedmage_for_discord_user`, `list_bedmages_for_discord_user`) opakowujące M5 `apps.bedmages.services.*`. Utworzyć `discord_bot/cogs/bedmages.py` z `BedmageCog` rejestrującym 3 slash commands w grupie `/bedmage`. Update `setup_bot()` w `discord_bot/bot.py` aby `add_cog(BedmageCog(bot))` przed return. Po D33: `/bedmage add/remove/list` działają end-to-end w dev guildzie (manual smoke).

### 🧠 Czego się nauczysz

- **`discord.SlashCommandGroup("bedmage", "...")`** — top-level group; commands nested przez `@bedmage.command(name="add", ...)`. Discord renderuje jako `/bedmage add`, `/bedmage remove`, etc.
- **`discord.Option(type, "description", ...)` annotation** — slash command parameter validation/UI (max_length, min_value, choices). Discord client wymusza limits przed wysłaniem do bota.
- **`sync_to_async(service_fn)(...)` w async cogu** — M2-D11 pattern. Sync Django ORM call w async event loop. Bez tego: `SynchronousOnlyOperation` exception.
- **Wrapper service pattern dla idempotent UX** — `apps.bedmages.services.add_bedmage_watch` rzuca `ValueError` na duplicate. Z punkt view Discord user'a: "dodajesz coś już dodanego" = `ℹ️` info, NIE error. Wrapper `try/except ValueError` → `(existing_watch, False)`.
- **`ephemeral=True` w `ctx.respond`** — odpowiedź widoczna tylko dla caller'a. Default dla bedmage commands (user-private data).

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m7-d33.md`.)

**Kluczowe punkty:**
- `discord_bot/services.py` rozszerzone o:
  ```python
  def add_bedmage_for_discord_user(
      discord_id: int, discord_username: str, character_name: str
  ) -> tuple[BedmageWatch, bool]:
      user, _ = get_or_create_user_by_discord_id(discord_id, discord_username)
      try:
          watch = add_bedmage_watch(user, character_name)
          return watch, True
      except ValueError:
          watch = BedmageWatch.objects.get(user=user, character__name=character_name)
          return watch, False

  def remove_bedmage_for_discord_user(discord_id: int, character_name: str) -> bool:
      # auto-create User jeśli nieznany — symetria z add
      user, _ = get_or_create_user_by_discord_id(discord_id, discord_username="")
      return remove_bedmage_watch(user, character_name)

  def list_bedmages_for_discord_user(discord_id: int) -> list[BedmageWatch]:
      try:
          user = User.objects.get(discord_id=discord_id)
      except User.DoesNotExist:
          return []
      return list(
          BedmageWatch.objects.filter(user=user, active=True).select_related("character")
      )
  ```
- `discord_bot/cogs/__init__.py` (pusty) + `discord_bot/cogs/bedmages.py` z `BedmageCog(commands.Cog)`:
  - `bedmage = discord.SlashCommandGroup("bedmage", "Manage your bedmage tracking list")` class attribute.
  - `add(ctx, character_name: Option(str, max_length=64))` → wrap `add_bedmage_for_discord_user`, response `✅ Added ... ` / `ℹ️ already on list` + `ephemeral=True`.
  - `remove(ctx, character_name: Option(str, max_length=64))` → wrap `remove_bedmage_for_discord_user`, response `✅ Removed ...` / `ℹ️ wasn't on list` + `ephemeral=True`.
  - `list(ctx)` → wrap `list_bedmages_for_discord_user`, response `Your bedmages: ...` lub `empty list` hint + `ephemeral=True`.
- `discord_bot/bot.py` `setup_bot()` rozszerzony o `bot.add_cog(BedmageCog(bot))`.
- ~10 testów: 3 services × 2 paths + 3 cog handlers × 2 paths + 1 sanity (cog registers commands).

### ⚠️ Pułapki do uwagi

- **A — `discord.SlashCommandGroup` jako class attribute, NIE w `__init__`** — py-cord wymaga że group jest zadeklarowany na poziomie klasy. Inside `__init__` → cog się nie zarejestruje correctly.
- **B — `discord.Option(...)` annotation requires py-cord 2.x** — wzorzec `character_name: discord.Option(str, "description", max_length=64)`. `max_length=64` dla character_name (matches `Character.name max_length=64`).
- **C — `async def add(self, ctx, character_name)` musi być async** — Discord interaction handlers MUSZĄ być async. Sync = `RuntimeWarning` + interaction timeout (3s).
- **D — `sync_to_async(service_fn)(...)` NIE `sync_to_async(service_fn)(args)`** — `sync_to_async` zwraca async wrapper, więc call jest `await sync_to_async(fn)(...)` z **dwoma** call'ami (jeden żeby wrapper, drugi żeby invoke). M2-D11 precedens.
- **E — `list` jako Python method name shadowing** — `async def list(self, ctx):` shadows `builtins.list` w scope metody. Niegroźne (only local), ale jeśli używasz `list(...)` w body, to fail. Defense: `async def list_cmd(self, ...)` z `@bedmage.command(name="list")` decoration explicit override Discord name. Lub po prostu unikaj `list(...)` w method body (użyj `[*iterable]` zamiast).
- **F — `wrapper try/except ValueError`** — narrow exception. NIE łapaj `Exception` (replace specific failure mode z generic catch ukrywa unexpected bugs). `add_bedmage_watch` raises **tylko** `ValueError` dla duplicate active.
- **G — `remove_bedmage_for_discord_user` auto-create User** — symetryczne do `add`. Edge case: user calls `/bedmage remove X` przed `/bedmage add Y` — auto-create User dla niego, potem `remove_bedmage_watch` zwraca `False` bo nic do remove. UX: `ℹ️ wasn't on list`. NIE crash.
- **H — `list_bedmages_for_discord_user` NIE auto-create** — read-only operation, jeśli user nieznany → empty list. Defense przed niepotrzebnymi DB writes na read commandzie.
- **I — `select_related("character")` w `list_bedmages_*`** — eager load Character FK żeby cog handler nie hit'ował kolejnego query przy `w.character.name`. Plus zwraca `list(...)` materialized (NOT `QuerySet`) bo `sync_to_async` nie streamuje async iteration.
- **J — `ctx.respond` returns Interaction message, NIE coroutine** — `await ctx.respond(...)` returns `Interaction` object. NIE łańcuch awaitów. M5+ async/sync rozróżnienie reused.

### 🧪 Testing plan

`tests/unit/discord_bot/test_services.py` D33 część (~5 testów) + `tests/unit/discord_bot/test_bedmage_cog.py` (~5 testów):

**`test_services.py` D33:**
- `test_add_bedmage_for_discord_user_creates_watch_on_first_call` — happy path, `(watch, True)` returned, `BedmageWatch` w DB.
- `test_add_bedmage_for_discord_user_returns_existing_on_duplicate` — drugi call z tym samym `(discord_id, character_name)` → `(watch, False)`, NIE crash (catch `ValueError`).
- `test_remove_bedmage_for_discord_user_returns_true_on_match` — happy path, delete works.
- `test_remove_bedmage_for_discord_user_returns_false_when_not_on_list` — call dla character'a, którego user nie miał, → `False`, NIE crash.
- `test_list_bedmages_for_discord_user_returns_only_active` — utwórz 2 watches (1 active + 1 active=False), assert list zwraca tylko 1 (filter active=True).

**`test_bedmage_cog.py`:**
- `test_bedmage_add_command_responds_with_added_message` — mock `add_bedmage_for_discord_user` → `(fake_watch, True)`, `cog.add.callback(cog, mock_ctx, character_name="Yhral")`, assert `ctx.respond("✅ Added `Yhral` ...", ephemeral=True)`.
- `test_bedmage_add_command_responds_with_already_on_list_message` — mock returns `(fake_watch, False)`, assert `"already on your list"` w response.
- `test_bedmage_remove_command_responds_with_removed_message` — mock `remove_bedmage_for_discord_user` → `True`, assert `"✅ Removed"` response.
- `test_bedmage_list_command_responds_with_empty_hint_when_no_bedmages` — mock returns `[]`, assert response zawiera `"Your bedmage list is empty"`.
- `test_bedmage_list_command_responds_with_populated_list` — mock returns `[watch1, watch2]` (z `character.name` Yhral, Bart), assert response zawiera `Yhral, Bart` (lub backtick'owane).

**Coverage cel:** `discord_bot/services.py` (D33 część) 100%, `discord_bot/cogs/bedmages.py` 100%, `discord_bot/cogs/__init__.py` 100%.

### 📦 Definition of Done

- [ ] AC spełnione (3 services + cog + 3 commands + `setup_bot()` rejestracja).
- [ ] PR zmergowany squash (`feat(discord): BedmageCog + 3 bedmage wrapper services (M7-D33, #<#>)`).
- [ ] CI lint + test zielone.
- [ ] `discord_bot/cogs/bedmages.py` 100% + `discord_bot/services.py` (D33 część) 100%.
- [ ] Issue zamknięty.

---

## Task #4 — [M7-D34] `DeathsCog` + `/deaths threshold` + admin perm check

### 🎯 Cel

Utworzyć `discord_bot/cogs/deaths.py` z `DeathsCog` rejestrującym `/deaths threshold <level>` slash command. Cog handler: (1) sprawdza `ctx.guild` is None (DM rejection), (2) sprawdza `ctx.author.guild_permissions.administrator`, (3) wywołuje `set_death_threshold_for_guild` service (D31). Response: **publiczna** (NIE ephemeral) ack że "Death threshold set to level X" — żeby inni admini widzieli zmianę. Update `setup_bot()` aby `add_cog(DeathsCog(bot))`. Po D34: `/deaths threshold` działa end-to-end w dev guildzie z real admin perms (manual smoke).

### 🧠 Czego się nauczysz

- **`ctx.author.guild_permissions`** — `discord.Permissions` object z polami jak `administrator`, `manage_channels`, `kick_members`. `administrator` flag = pełen admin serwera (bypass channel-level overrides).
- **DM context** (`ctx.guild is None`) — slash command może być wywołany w prywatnej rozmowie z botem. `guild_permissions` byłby `None` → AttributeError. Defense: explicit check `if ctx.guild is None: return early`.
- **Public ack vs ephemeral** — bot config-changing commands powinny być publiczne (audit trail w channel history, inni admini widzą). User-private read commands ephemeral. Mix based na semantyce.
- **`discord.Option(int, min_value=1, max_value=999)`** — Discord client validation, użytkownik nie może wysłać poza range.

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m7-d34.md`.)

**Kluczowe punkty:**
- `discord_bot/cogs/deaths.py` z `DeathsCog(commands.Cog)`:
  - `deaths = discord.SlashCommandGroup("deaths", "Death monitor configuration")` class attribute.
  - `async def threshold(self, ctx, level: Option(int, "...", min_value=1, max_value=999))` handler.
  - Sequence: DM check → admin check → `sync_to_async(set_death_threshold_for_guild)(guild_id=ctx.guild.id, channel_id=ctx.channel_id, threshold=level)` → `ctx.respond(f"🪦 Death notification threshold set to level **{level}**.")` (publiczne).
- `discord_bot/bot.py` `setup_bot()` rozszerzony o `bot.add_cog(DeathsCog(bot))`.
- ~5 testów: DM rejection, non-admin rejection, success persist, public ack format, threshold value w DB.

### ⚠️ Pułapki do uwagi

- **A — Order of checks** — DM check **PRZED** admin check. Jeśli `ctx.guild is None`, `ctx.author.guild_permissions` byłby `None` → AttributeError. Defense:
  ```python
  if ctx.guild is None:
      await ctx.respond("❌ This command must be used in a server.", ephemeral=True)
      return
  if not ctx.author.guild_permissions.administrator:
      await ctx.respond("❌ Only server admins can change the death threshold.", ephemeral=True)
      return
  ```
- **B — Permission check responses są ephemeral** (private to caller, "❌ Only server admins..."), ale **success ack jest publiczna** — różna visibility w jednym command flow.
- **C — `ctx.guild.id` vs `ctx.guild_id`** — oba istnieją w py-cord, ale `ctx.guild_id` jest property zwracające int. `ctx.guild.id` wymaga `ctx.guild` not None (już sprawdzone wyżej). Spójność: użyj `ctx.guild.id` w kodzie post-DM-check.
- **D — `ctx.channel_id` zawsze available** — nawet w DM. Service zapisuje `channel_id` z każdego call'a `/deaths threshold` (M8 użyje jako default destination).
- **E — `level: Option(int, ...)` discord client validation** — Discord wymusza int + range przed wysłaniem do bota. Bot dostaje już validated int.
- **F — `is_done()` race condition NIE występuje tutaj** — cog handler jest atomic synchronous async function, jedna response per invocation. Global error handler z `is_done()` check jest dla recovery z partial handlers.
- **G — `set_death_threshold_for_guild` wrapper jest sync, ORM operation** — `await sync_to_async(set_death_threshold_for_guild)(...)`. M2-D11 boundary pattern.

### 🧪 Testing plan

`tests/unit/discord_bot/test_deaths_cog.py` (~5 testów):

- `test_deaths_threshold_rejects_dm_context` — `mock_ctx.guild = None`, invoke handler, assert `ctx.respond("❌ ... server ...", ephemeral=True)` called, `set_death_threshold` NIE called.
- `test_deaths_threshold_rejects_non_admin_caller` — `mock_ctx.author.guild_permissions.administrator = False`, assert `"Only server admins"` w response, `set_death_threshold` NIE called.
- `test_deaths_threshold_persists_value_on_admin_call` — admin path, mock `set_death_threshold_for_guild`, invoke handler z `level=50`, assert service called z `(guild_id=X, channel_id=Y, threshold=50)`.
- `test_deaths_threshold_responds_with_public_ack` — admin path, assert `ctx.respond(...)` called WITHOUT `ephemeral=True` (lub `ephemeral=False`).
- `test_deaths_threshold_message_format_includes_level` — admin path z `level=42`, assert message zawiera `"level **42**"` (lub bare `42`).

**Coverage cel:** `discord_bot/cogs/deaths.py` 100%.

### 📦 Definition of Done

- [ ] AC spełnione (DeathsCog + threshold command + perm checks + cog rejestracja).
- [ ] PR zmergowany squash (`feat(discord): DeathsCog + /deaths threshold + admin perm check (M7-D34, #<#>)`).
- [ ] CI lint + test zielone.
- [ ] `discord_bot/cogs/deaths.py` 100%.
- [ ] Issue zamknięty.

---

## Task #5 — [M7-D35] M7 e2e + closure (PROGRESS.md retro + milestone close)

### 🎯 Cel

E2E sanity test: bot `setup_bot()` zwraca instance z **wszystkimi 4 commands** zarejestrowanymi (`bedmage add/remove/list` + `deaths threshold`). Bez hitowania Discord gateway — sprawdza `bot.application_commands` listing in-memory po `setup_bot()`. Plus M7 closure — `PROGRESS.md` rozszerzone o sekcję M7 z retro per Issue, milestone closed via `gh api`.

D35 ma **2 PR-y w 1 issue** (M5-D27 + M6-D30 pattern):
1. **Feature PR** (`feat/<#>-m7-e2e`) — `tests/integration/test_m7_bot_e2e.py` z 1 testem sanity.
2. **Closure PR** (`docs/close-m7-discord-bot-commands` od **fresh master** po feature merge) — `PROGRESS.md` retro + milestone close + manual smoke notes w PR description.

### 🧠 Czego się nauczysz

- **`bot.application_commands` listing** — py-cord property zwracający registered slash commands (po `add_cog(...)` calls). Format: list of `SlashCommand` / `SlashCommandGroup` objects. `cmd.qualified_name` daje "bedmage add", "deaths threshold" itd.
- **In-memory integration test (NIE hitting Discord gateway)** — `setup_bot()` jest pure Python, brak network. `bot.run()` NIE wywoływane. Sanity że wiring jest correct.
- **`gh api -X PATCH milestone state=closed`** — M5-D27 + M6-D30 precedens. Wymaga `repo` scope w token'ie.

### ✅ Acceptance criteria

(Pełne AC w issue body — `.github/issue-bodies/m7-d35.md`.)

### Feature PR (`feat/<#>-m7-e2e`)

**Required AC — Bot wiring sanity (1 test):**

- [ ] `tests/integration/test_m7_bot_e2e.py`:
  ```python
  """E2E sanity for M7 — setup_bot wires all 4 slash commands."""

  from __future__ import annotations

  from discord_bot.bot import setup_bot


  def test_setup_bot_registers_all_four_slash_commands() -> None:
      """All 4 commands per spec §1 must be registered after setup_bot()."""
      bot = setup_bot()
      names = {cmd.qualified_name for cmd in bot.walk_application_commands()}
      assert "bedmage add" in names
      assert "bedmage remove" in names
      assert "bedmage list" in names
      assert "deaths threshold" in names
  ```

- [ ] **Wszystkie M7 testy** (D31 + D32 + D33 + D34 + D35 e2e) zielone:
  ```bash
  poetry run pytest tests/unit/discord_bot/ tests/integration/test_m7_bot_e2e.py \
      --cov=discord_bot --cov-report=term
  ```
- [ ] Cumulative coverage `discord_bot/*` ≥ 95%.

### Closure PR (`docs/close-m7-discord-bot-commands`)

- [ ] `PROGRESS.md` rozszerzone o:
  - `## 🎉 Milestone M7 — Discord bot commands COMPLETED (2026-MM-DD)` header.
  - `### Ukończone (M7)` — lista 5 issues + PR linki + squash hashes.
  - `### Notatki z retro M7 (dopisywane progresywnie)` — per Issue D31-D35.
  - `### Definition of Done M7` (ze spec'a §8) — wszystkie [x] poza ostatnim ("milestone closed" — TODO post-merge).
  - `### Podsumowanie M7` (data range, dni vs budżet, najwartościowsze lekcje).
  - `### Tech debt z M7` (carry-over do M8+).
- [ ] **Manual smoke** udokumentowany w closure PR description: dev guild test wszystkich 4 commands po lokalnym `run_discord_bot` (`/bedmage add Yhral`, `/bedmage list`, `/bedmage remove Yhral`, `/deaths threshold 50` z admin + `/deaths threshold 50` od non-admin — oczekiwane różne responses).
- [ ] **Po merge closure PR'a:** `gh api -X PATCH repos/bgozlinski/tibiantis-scraper/milestones/7 -f state=closed`.
- [ ] **Sanity:** `gh issue list --milestone "M7 — Discord bot commands" --state open` → empty.

### ⚠️ Pułapki do uwagi

- **A — `bot.walk_application_commands()` vs `bot.application_commands`** — `walk_*` jest recursive (descend do groups), `application_commands` zwraca top-level only. Dla group'd commands (`bedmage add` = nested w `bedmage` group), `walk_*` is correct.
- **B — `setup_bot()` w teście NIE wywołuje `bot.run()`** — tylko in-memory wiring check. Brak Discord connection.
- **C — Test może być **unit** test (`tests/unit/discord_bot/test_bot_bootstrap.py`)** zamiast integration — argument za integration: cover'uje cross-cog wiring. Argument za unit: testuje pure Python, brak external dependencies. **Decision:** integration `tests/integration/test_m7_bot_e2e.py` per consistency z M5-D27 + M6-D30 (closure PR pattern z integration test).
- **D — Closure branch od fresh master** (M1-D8 lekcja, repeat z M5-D27 + M6-D30) — `git checkout master && git pull && git checkout -b docs/close-m7-discord-bot-commands` PRZED edycją PROGRESS.md. NIE od `feat/<#>-m7-e2e`. Inaczej closure PR zawiera duplikat squash D35 jako "no-op" commit (M1-D8 PR #26 problem).
- **E — `gh api PATCH milestone`** wymaga `repo` scope (M5-D27 + M6-D30 precedens). Sanity przed call'em: `gh auth status` pokazuje scopes. Plus correct milestone number — `gh api repos/bgozlinski/tibiantis-scraper/milestones --jq '.[] | select(.title|startswith("M7")) | .number'` → `7`.
- **F — Milestone exact title match** — `gh issue list --milestone "M7 — Discord bot commands"` wymaga dokładnego tytułu (z em-dashem `—`, NIE zwykłym myślnikiem `-`). Sprawdzone 2026-05-13.

### 🧪 Testing plan

Feature PR — 1 e2e test (`test_m7_bot_e2e.py`). Plus uruchom **wszystkie** M7 testy + cumulative coverage check.

Closure PR — manual smoke dev guild (5 commands × różne wyniki):
1. `/bedmage add Yhral` od test user'a A → "✅ Added"
2. `/bedmage add Yhral` od user'a A drugi raz → "ℹ️ already on your list"
3. `/bedmage list` od user'a A → "Your bedmages: `Yhral`"
4. `/bedmage remove Yhral` od user'a A → "✅ Removed"
5. `/bedmage list` od user'a A → "empty list"
6. `/deaths threshold 50` od admin user'a → public "🪦 Death notification threshold set to level **50**."
7. `/deaths threshold 50` od non-admin user'a → ephemeral "❌ Only server admins..."
8. `/deaths threshold 50` w DM z botem → ephemeral "❌ must be used in a server"

**Coverage cel:** Cumulative `discord_bot/*` ≥ 95%.

### 📦 Definition of Done

#### Feature PR
- [ ] AC spełnione (1 e2e test, all M7 testy zielone).
- [ ] **Feature PR** zmergowany squash (`test(discord): M7 e2e bot wiring sanity (M7-D35, #<#>)`).
- [ ] CI lint + test zielone.
- [ ] Cumulative `discord_bot/*` ≥ 95% coverage.

#### Closure PR
- [ ] **Closure PR** zmergowany squash (`docs(progress): close M7 — Discord bot commands COMPLETED + retro D31-D35`).
- [ ] CI lint zielony.
- [ ] PROGRESS.md sekcja M7 dorzucona.
- [ ] Manual smoke description w closure PR body.
- [ ] Milestone M7 zamknięty na GitHub via `gh api -X PATCH .../milestones/7 -f state=closed`.
- [ ] Wszystkie M7 issues CLOSED.

---

## Spec section refs

| Spec section | Realizowane przez |
|---|---|
| §2 architektura komponenty | All tasks |
| §3.1 top-level Django app | D31 |
| §3.2 wrapper services | D33 |
| §3.3 auto-create User | D31 |
| §3.4 `DiscordChannel` per-guild | D31 |
| §3.5 admin permission check | D34 |
| §3.6 per-guild command sync dev / global prod | D32 |
| §3.7 command-handling only (no outbound) | All tasks (explicit scope-out) |
| §3.8 LOGGING dict named logger | D32 |
| §4.1 `DiscordChannel` model | D31 |
| §4.2 services signatures | D31 (user + threshold) + D33 (bedmage wrappers) |
| §5 D-task split | This document |
| §6.1-6.2 error handling | D32 (global) + D34 (DM + admin checks) |
| §7 testing strategy | D31-D34 + D35 e2e |
| §8 DoD M7 | M7 closure (D35 closure PR) |
| §9 Open questions | M-future, NIE w M7 |
