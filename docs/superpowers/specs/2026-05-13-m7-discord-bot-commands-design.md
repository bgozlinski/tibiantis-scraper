# M7 — Discord bot commands — Design spec

**Data:** 2026-05-13
**Status:** ACCEPTED (decyzje §3.1-3.8 zaakceptowane przez developera 2026-05-13 w sesji M7 brainstorm)
**Plan:** [`docs/superpowers/plans/2026-05-13-m7-implementation-plan.md`](../plans/2026-05-13-m7-implementation-plan.md) (ten sam PR)
**Milestone:** [#7 — Discord bot commands](https://github.com/bgozlinski/tibiantis-scraper/milestone/7)

---

## §1 Cel + scope

Wprowadzić Discord bot jako **osobny proces** (CLAUDE.md §8) obsługujący **4 slash commands** definiowane w CLAUDE.md §8:

- `/bedmage add <character_name>` — dodaje postać do listy bedmages caller'a (auto-create Django User po `discord_id`).
- `/bedmage remove <character_name>` — usuwa postać z listy.
- `/bedmage list` — wyświetla listę aktywnych bedmages caller'a.
- `/deaths threshold <level>` — ustawia próg powiadomień o śmierciach dla serwera (Discord Server Admin permission required).

Zgodnie z CLAUDE.md §3 — `discord_bot/` jest **top-level Django app** (NIE pod `apps/`, analogicznie do `scrapers/` i `logs_backend/`). Bot tylko nasłuchuje na slash commands — outbound notifications (bedmage / death events) są scope'em M8.

### W zakresie M7:
- Top-level Django app `discord_bot/` z `INSTALLED_APPS = [..., "discord_bot"]`.
- Model `DiscordChannel` (per-guild config, jeden wiersz per Discord server).
- Service layer (`discord_bot/services.py`) z 5 funkcjami: `get_or_create_user_by_discord_id`, `add_bedmage_for_discord_user`, `remove_bedmage_for_discord_user`, `list_bedmages_for_discord_user`, `set_death_threshold_for_guild`.
- Bot bootstrap (`discord_bot/bot.py`) z `on_ready` event handlerem auto-syncującym commands.
- Dwa cogi: `BedmageCog` (3 commands), `DeathsCog` (1 command).
- Management command `python manage.py run_discord_bot` jako entry point.
- Global error listener (`on_application_command_error`) — clean ephemeral message + log do MongoDB przez M6 LOGGING.
- Edycja `config/settings/base.py` LOGGING dict — dodanie `"discord_bot"` named logger handler do `console`+`mongo` (analogicznie do `"apps"`).

### Poza zakresem M7 (do M8+):
- **Outbound notifications** — bedmage alerts + death announcements → M8 zamieni `LoggingHandler` z M5 na `DiscordHandler` używający `DiscordChannel.channel_id`/webhook.
- **JWT linking** Discord ↔ Django User dla istniejących kont — auto-create wystarczy dla M7 (CLAUDE.md §8 default).
- **Per-channel threshold** — M7 trzyma per-guild (`unique=guild_id`); M-future jeśli pojawi się potrzeba różnych progów w różnych kanałach jednego serwera.
- **Bot service w `docker-compose.dev.yml`** — bot dev workflow to lokalny `manage.py run_discord_bot` z terminala. Bot trafia do `docker-compose.yml` (prod) w M9 (Dockeryzacja).
- **Discord OAuth flow** dla self-service linkowania — M-future.
- **Per-server granularity** dla bedmage commands — bedmage list user'a jest globalna (cross-server, jeden Discord user = jeden Django User).

---

## §2 Architektura

### High-level diagram

```
┌──────────────────────┐    slash command    ┌────────────────────┐
│ Discord user         │ ──────────────────> │ Discord Gateway    │
└──────────────────────┘                     └─────────┬──────────┘
                                                       │
                                                       ▼
                                       ┌─────────────────────────────┐
                                       │ Bot process (py-cord)       │
                                       │ - on_ready → sync_commands  │
                                       │ - on_application_command_   │
                                       │   error (global)            │
                                       └──────┬──────────────────────┘
                                              │
                                              ▼
              ┌───────────────────────────────────────────────────┐
              │ Cogs (cienkie wrappery)                           │
              │ ┌─────────────────┐  ┌────────────────────────┐   │
              │ │ BedmageCog      │  │ DeathsCog              │   │
              │ │ /bedmage add    │  │ /deaths threshold      │   │
              │ │ /bedmage remove │  │ (admin perm check)     │   │
              │ │ /bedmage list   │  │                        │   │
              │ └────────┬────────┘  └──────────┬─────────────┘   │
              └──────────┼─────────────────────┼─────────────────-┘
                         │ sync_to_async(...)  │
                         ▼                     ▼
              ┌────────────────────────────────────────────────┐
              │ discord_bot/services.py (Discord-friendly)     │
              │ - get_or_create_user_by_discord_id             │
              │ - add_bedmage_for_discord_user                 │
              │ - remove_bedmage_for_discord_user              │
              │ - list_bedmages_for_discord_user               │
              │ - set_death_threshold_for_guild                │
              └──────┬─────────────────────────┬───────────────┘
                     │                         │
                     ▼                         ▼
       ┌──────────────────────────┐  ┌──────────────────────────┐
       │ apps.bedmages.services   │  │ discord_bot.models       │
       │ (untouched M5 code)      │  │ DiscordChannel           │
       │ - add_bedmage_watch      │  │ (per-guild config)       │
       │ - remove_bedmage_watch   │  └──────────────────────────┘
       └──────────────────────────┘
```

### Struktura plików (5 NEW + 5 MODIFY)

| # | Plik | Status | Zawartość |
|---|---|---|---|
| 1 | `discord_bot/__init__.py` | NEW | Pusty marker |
| 2 | `discord_bot/apps.py` | NEW | `AppConfig(name="discord_bot")` |
| 3 | `discord_bot/models.py` | NEW | `DiscordChannel(guild_id, channel_id, death_level_threshold, created_at, updated_at)` z `unique=True` na `guild_id` |
| 4 | `discord_bot/admin.py` | NEW | `DiscordChannelAdmin` w Django admin |
| 5 | `discord_bot/services.py` | NEW | 5 services (lista §1 + §3.2) |
| 6 | `discord_bot/migrations/0001_initial.py` | NEW | `makemigrations` output |
| 7 | `discord_bot/bot.py` | NEW | `bot = discord.Bot(intents=...)` + `on_ready` + `on_application_command_error` + `setup_bot()` |
| 8 | `discord_bot/cogs/__init__.py` | NEW | Pusty marker |
| 9 | `discord_bot/cogs/bedmages.py` | NEW | `BedmageCog` z 3 commands |
| 10 | `discord_bot/cogs/deaths.py` | NEW | `DeathsCog` z 1 command |
| 11 | `discord_bot/management/__init__.py` | NEW | Pusty marker |
| 12 | `discord_bot/management/commands/__init__.py` | NEW | Pusty marker |
| 13 | `discord_bot/management/commands/run_discord_bot.py` | NEW | `Command.handle()` → `bot.run(settings.DISCORD_BOT_TOKEN)` |
| 14 | `config/settings/base.py` | MODIFY | `"discord_bot"` w `LOCAL_APPS`, `DISCORD_BOT_TOKEN` + `DISCORD_DEV_GUILD_ID` env reads, LOGGING dict `"discord_bot"` named logger |
| 15 | `.env.example` | MODIFY | `DISCORD_BOT_TOKEN=` + `DISCORD_DEV_GUILD_ID=` |
| 16 | `pyproject.toml` | MODIFY | `py-cord` dependency |
| 17 | `tests/unit/discord_bot/*` | NEW | 7 plików testowych (~28 testów, §7) |

---

## §3 Decyzje designowe (zaakceptowane 2026-05-13)

### §3.1 Top-level Django app `discord_bot/` (NIE pod `apps/`)
**Wybór:** `discord_bot/` jako top-level Django app, registered jako `"discord_bot"` w `LOCAL_APPS`.

**Justyfikacja:** CLAUDE.md §3 explicit pokazuje `discord_bot/` na top-level (analogicznie do `scrapers/` i `logs_backend/`). Management commands wymagają Django app structure (`management/commands/*.py`) — `discord_bot/` musi być Django app, nie pure Python package. Top-level convention już ustalona przez `scrapers/`.

**Odrzucone alternatywy:**
- `apps/discord_bot/` (pod `apps/`) — sprzeczne z CLAUDE.md §3 strukturalnym dictum.
- Top-level non-app + osobny `apps/discord/` na modele — duplikat naming, nielogiczne rozdzielanie.

### §3.2 Wrapper services w `discord_bot/services.py`, NIE modyfikacja `apps.bedmages.services`
**Wybór:** Nowe service'y w `discord_bot/services.py` opakowują istniejące `apps.bedmages.services.*` zamiast modyfikacji tych ostatnich. Wrapper handluje `discord_id` → `User` auto-create + tłumaczenie wyjątków.

**Justyfikacja:** `apps.bedmages.services.add_bedmage_watch` rzuca `ValueError` na duplicate active watch — z Discord UX punkt widzenia to NIE jest błąd ("dodajesz coś już dodanego"), tylko `ℹ️` info. Wrapper łapie `ValueError` → zwraca `(existing_watch, False)`. Bedmages service'y zostają niezależne od Discord context, łatwiej testowalne osobno (M5 testy nietknięte).

**Odrzucone:**
- Refactor `apps.bedmages.services.add_bedmage_watch` → tuple `(watch, created)` — modyfikacja istniejącego API, ryzyko regresji M5 testów.

### §3.3 Auto-create Django User po `discord_id`
**Wybór:** Pierwszy slash command od nieznanego Discord usera tworzy Django User w services warstwie:
```python
user, created = User.objects.get_or_create(
    discord_id=author.id,
    defaults={
        "username": f"discord_{author.id}",
        "email": "",
        # set_unusable_password() po create
    },
)
```

**Justyfikacja:** CLAUDE.md §8 default: "auto-tworzenie albo prosi o link przez OAuth (do ustalenia — **domyślnie** auto-tworzenie)". Discord ID (snowflake 64-bit) jest stabilny niezależnie od username change'u. Username `discord_{id}` unika collision z istniejącymi Django username'ami (np. `bgozlinski`). Email pusty bo Discord nie zawsze udostępnia.

**Odrzucone:**
- OAuth-only linkowanie (`/link <jwt>` command) — extra friction, wymaga setup JWT generation flow. M-future jeśli pojawi się use case "połącz Discord z istniejącym Django kontem".
- `username=author.name` — Discord username changes; collision z Django username (`unique=True`).

### §3.4 `DiscordChannel` model per-guild (NIE per-channel)
**Wybór:** Jeden wiersz `DiscordChannel` per Discord server (`unique=True` na `guild_id`). Threshold `death_level_threshold` to per-guild config. `channel_id` zapisywany przy każdym `/deaths threshold` (= `ctx.channel.id`) — M8 użyje go jako default channel dla outbound notifications.

**Justyfikacja:** CLAUDE.md §7 "Próg poziomu ma być edytowalny przez admina" sugeruje singular threshold per server. Per-channel byłby YAGNI dla pierwszej iteracji — wymaga UX decyzji "skąd command pobiera target channel" i mnoży wiersze. Per-guild model trzyma `DiscordChannel` jako naturalny holder dla późniejszych M8 fields (`webhook_url`, `notification_enabled`).

**Odrzucone:**
- `SiteConfig` singleton — globalny threshold ignorujący multi-server context. Throwaway gdy M8 doda per-server logic.
- Redis cache override env var — ulotne, nie persistence.

### §3.5 Discord Server Admin permission dla `/deaths threshold`
**Wybór:** Cog handler sprawdza `ctx.author.guild_permissions.administrator` przed wykonaniem commanda. Bez admin perms → ephemeral "❌ Only server admins can change this." + early return.

**Justyfikacja:** CLAUDE.md §8 "tylko admin kanału" — najpracownicze tłumaczenie to "Discord Administrator permission" na poziomie guild. Nie wymaga setupu Django-side (`User.is_superuser` flag wymagałby pre-linkowania, sprzeczne z auto-create z §3.3). Standard pattern w Discord botach.

**Odrzucone:**
- `User.is_superuser` flag — wymaga pre-linkowania, friction.
- Konkretna Discord rola (`@TibiantisAdmin`) — wymaga env var z role ID, extra setup per-server.

### §3.6 Per-guild command sync na `on_ready` w devie, globalnie w prod
**Wybór:** `on_ready` handler odpala `bot.sync_commands(guild_ids=[DISCORD_DEV_GUILD_ID])` jeśli env var ustawiony, inaczej globalnie. Dev guild sync = instant propagacja, global = do 1h.

**Justyfikacja:** Discord rate-limity global command sync — globalnie commands propagują się do 1h, killing iteracji w devie. Per-guild sync to instant. Standard discord.py / py-cord dev pattern: `DISCORD_DEV_GUILD_ID` env var oddziela środowiska.

**Odrzucone:**
- Osobny management command `manage.py sync_discord_commands` — extra step manualnie, łatwo zapomnieć po code change.
- Globalnie zawsze — niepoprawne UX dla devu.

### §3.7 Bot tylko **command-handling** w M7 (NIE outbound notifications)
**Wybór:** Bot NIE wysyła wiadomości z własnej inicjatywy w M7 — tylko odpowiada na slash commands. Outbound notifications (bedmage alerts, death announcements) lecą w M8 jako `DiscordHandler` (zamiana M5 `LoggingHandler` przez `BEDMAGE_NOTIFICATION_HANDLER` settings switch + nowy handler dla deaths).

**Justyfikacja:** Czysta separacja "inbound (bot) vs outbound (Celery → Discord API)" z CLAUDE.md §8. M7 + M8 to dwa milestone'y oddzielone na GitHubie. M7 dostarcza command surface + storage (`DiscordChannel.death_level_threshold`); M8 konsumuje storage do filtrowania outbound.

**Odrzucone:**
- M7 includes basic outbound (np. echo ack że "scheduled scrape completed") — scope creep, M8 ma swój oddzielny milestone.

### §3.8 LOGGING dict — dodać `"discord_bot"` named logger
**Wybór:** `config/settings/base.py` LOGGING dict rozszerzony o:
```python
"loggers": {
    "apps": { "handlers": ["console", "mongo"], ... },
    "discord_bot": { "handlers": ["console", "mongo"], "level": "INFO", "propagate": True },
}
```

**Justyfikacja:** M6 LOGGING dispatcher attached `mongo` handler do `"apps"` family. `discord_bot/` to top-level, nie pod `apps/` — logi bota by NIE szły do MongoDB `app_logs` bez explicit wpisu. Named logger config (spójne z M6 wzorcem) jest 1-linijkowym dodatkiem. `propagate: True` zachowuje pytest caplog interop (M6 retro lesson #2).

**Odrzucone:**
- Refactor handler `mongo` attached do root + filter — większy risk regresji, niezgodne z M6 wzorcem.
- Skip — bot crashes by ginęły poza Mongo observability, sprzeczne z M6 intencją.

---

## §4 Model + service signatures

### §4.1 `discord_bot/models.py`

```python
class DiscordChannel(models.Model):
    """Per-guild Discord integration config.

    M7 stores death_level_threshold (set via /deaths threshold).
    M8 will extend with webhook_url / outbound config.
    """

    guild_id = models.BigIntegerField()
    channel_id = models.BigIntegerField()
    death_level_threshold = models.PositiveIntegerField(default=30)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["guild_id"], name="discord_channel_one_per_guild"
            ),
        ]

    def __str__(self) -> str:
        return f"Guild {self.guild_id} (threshold={self.death_level_threshold})"
```

### §4.2 `discord_bot/services.py` signatures

```python
def get_or_create_user_by_discord_id(
    discord_id: int, discord_username: str
) -> tuple[User, bool]:
    """Lazy auto-create per CLAUDE.md §8.

    Returns (user, created). Username pattern: f"discord_{discord_id}".
    Email empty, password unusable.
    """


def add_bedmage_for_discord_user(
    discord_id: int, discord_username: str, character_name: str
) -> tuple[BedmageWatch, bool]:
    """Auto-create User + delegate to apps.bedmages.services.add_bedmage_watch.

    Returns (watch, created). created=False when watch already on user's list
    (caught ValueError from apps service, idempotent ack).
    """


def remove_bedmage_for_discord_user(
    discord_id: int, character_name: str
) -> bool:
    """Auto-create User + delegate to apps.bedmages.services.remove_bedmage_watch.

    Returns True if watch existed and was deleted, False otherwise.
    Idempotent — never raises.
    """


def list_bedmages_for_discord_user(discord_id: int) -> list[BedmageWatch]:
    """Active bedmages for user (filter active=True). Empty list if user not
    in DB yet — no auto-create on read."""


def set_death_threshold_for_guild(
    guild_id: int, channel_id: int, threshold: int
) -> DiscordChannel:
    """Upsert DiscordChannel by guild_id. Updates channel_id + threshold
    (M8 will use channel_id as outbound destination)."""
```

---

## §5 D-task split (preview — szczegóły w implementation plan)

| # | ID | Tytuł | Czas | Zależy od |
|---|---|---|---|---|
| 1 | M7-D31 | `discord_bot/` app + `DiscordChannel` model + admin + initial services (user auto-create, threshold upsert) | 2-3h | M6 closed |
| 2 | M7-D32 | py-cord bootstrap + `bot.py` + `run_discord_bot` management command + on_ready sync + global error handler + LOGGING dict edit | 2-3h | D31 |
| 3 | M7-D33 | `BedmageCog` z `/bedmage add/remove/list` + `add_bedmage_for_discord_user` / `remove_*` / `list_*` services | 2-3h | D32 |
| 4 | M7-D34 | `DeathsCog` z `/deaths threshold` + admin perm check + DM rejection | 2h | D33 |
| 5 | M7-D35 | M7 e2e + closure (PROGRESS.md retro + milestone close) | 2h | D34 |

**Total:** ~10-13h, ~2 dni roboczych. Porównywalne z M5 (~13-15h, 5 D-tasków).

---

## §6 Error handling

### §6.1 Global error listener (one stop)

```python
@bot.event
async def on_application_command_error(
    ctx: discord.ApplicationContext, error: discord.DiscordException
) -> None:
    logger.exception("Slash command error in /%s: %s", ctx.command, error)
    msg = "❌ Something went wrong. The admins have been notified."
    if ctx.response.is_done():
        await ctx.followup.send(msg, ephemeral=True)
    else:
        await ctx.respond(msg, ephemeral=True)
```

CLAUDE.md §8 wymaga: "Nigdy nie pokazuj stack trace na Discordzie." Global listener łapie unhandled exceptions z każdego coga, logi z `exc_info=True` lecą do MongoDB przez M6 LOGGING dispatcher (po §3.8 edycie LOGGING dict).

### §6.2 Specific failure modes

| Failure | Handling |
|---|---|
| `DISCORD_BOT_TOKEN` empty | `manage.py run_discord_bot` stderr "DISCORD_BOT_TOKEN not set" + exit 1 (nie crash Pythonu) |
| Discord API down przy starcie | `discord.LoginFailure` raises → process exits → docker `restart: unless-stopped` retry (M9 prod), lokalnie ręczny restart |
| Discord gateway disconnect mid-flight | py-cord auto-reconnect built-in |
| Service `ValueError` w `add_bedmage_for_discord_user` (duplicate active watch) | wrapper catches → `(existing, False)` → cog returns `ℹ️ already on list` |
| Service raises unexpected | global listener → ephemeral generic msg + Mongo `exc_info` log |
| `/deaths threshold` w DM (`ctx.guild=None`) | cog-level explicit check → ephemeral "must be used in a server" |
| `/deaths threshold` non-admin caller | cog-level permission check → ephemeral "Only server admins can change…" |
| Discord rate limit (4xx response) | py-cord built-in handler — bucket-based wait, automatyczny retry |

---

## §7 Testing strategy

### §7.1 Stack
- `pytest-asyncio` (M2-D11 precedens dla GraphQL async resolvers) — `@pytest.mark.asyncio` na async test functions
- `unittest.mock.MagicMock` / `AsyncMock` — `discord.ApplicationContext` mocking
- `pytest-django` `@pytest.mark.django_db` — service testy hitujące ORM
- Real Mongo NIE wymagana — logger errors mock'owane gdzie potrzeba

### §7.2 Cog handler testing pattern (`.callback` bypass)

py-cord owraps `@command.command(...)` jako `SlashCommand` objects z atrybutem `.callback`. Bypass slash option parsing — w teście wartości podawane wprost:

```python
@pytest.mark.asyncio
async def test_bedmage_add_responds_created(monkeypatch):
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.author.id = 12345
    mock_ctx.author.name = "alice"
    mock_ctx.respond = AsyncMock()

    fake_watch = MagicMock()
    monkeypatch.setattr(
        "discord_bot.cogs.bedmages.add_bedmage_for_discord_user",
        lambda **kw: (fake_watch, True),
    )

    cog = BedmageCog(bot=MagicMock())
    await cog.add.callback(cog, mock_ctx, character_name="Yhral")

    mock_ctx.respond.assert_called_once()
    args, kwargs = mock_ctx.respond.call_args
    assert "Added `Yhral`" in args[0]
    assert kwargs["ephemeral"] is True
```

### §7.3 Test files (~28 testów total)

| Plik | Liczba testów | Pokrycie |
|---|---|---|
| `tests/unit/discord_bot/test_models.py` | ~2 | `DiscordChannel.save` + unique `guild_id` constraint enforcement |
| `tests/unit/discord_bot/test_services.py` | ~10 | 5 service'ów × 2 paths (happy + edge case) |
| `tests/unit/discord_bot/test_bedmage_cog.py` | ~7 | 3 commands × paths created/existing, removed/not, empty/populated, ephemeral assert |
| `tests/unit/discord_bot/test_deaths_cog.py` | ~5 | DM rejection, non-admin rejection, success path, threshold persisted, public ack (NOT ephemeral) |
| `tests/unit/discord_bot/test_bot_bootstrap.py` | ~2 | `on_ready` dev-guild sync vs global sync |
| `tests/unit/discord_bot/test_run_discord_bot_command.py` | ~2 | TOKEN empty exit, TOKEN set → `bot.run` called |
| `tests/unit/discord_bot/test_error_handler.py` | ~2 | service raise → ephemeral generic + `logger.exception` |

### §7.4 Coverage cel
- `discord_bot/services.py` 100%
- `discord_bot/cogs/*.py` 100%
- `discord_bot/models.py` 100%
- `discord_bot/bot.py` ~80% (`sync_commands` API hard to mock kompletnie)
- Cumulative `discord_bot/*.py` ≥ 95% (DoD).

### §7.5 NIE testujemy real Discord gateway
Per CLAUDE.md §11: "Testy nie mogą hitować żywego Discorda — używają `discord.py` w trybie test/mock". Manual smoke z dev guildem (`DISCORD_DEV_GUILD_ID=... DISCORD_BOT_TOKEN=... poetry run python manage.py run_discord_bot`) zostaje na developera, nie CI.

---

## §8 Definition of Done M7

- [ ] **5 D-tasków zamkniętych** (#31-35 + closure PR).
- [ ] **`discord_bot/` jako top-level Django app** zarejestrowany w `LOCAL_APPS`, migracja `0001_initial` aplikuje się czysto.
- [ ] **`DiscordChannel` model** z `unique=True` na `guild_id` + Django admin.
- [ ] **5 services** w `discord_bot/services.py` (user auto-create, 3× bedmage wrappers, threshold upsert).
- [ ] **4 slash commands** funkcjonalnie kompletne:
  - `/bedmage add/remove/list` — ephemeral responses, auto-create user, idempotent.
  - `/deaths threshold` — public ack, admin perm check, DM rejection, DiscordChannel upsert.
- [ ] **Bot startup** — `python manage.py run_discord_bot` loguje się do Discord, sync'uje commands per-guild (dev) lub globalnie (prod).
- [ ] **Global error handler** — unhandled exceptions z cogów → ephemeral generic msg + Mongo log z `exc_info`.
- [ ] **LOGGING dict** rozszerzony o `"discord_bot"` named logger (handlers: console + mongo).
- [ ] **Wszystkie pre-commit + CI zielone** dla każdego z 5 PR-ów.
- [ ] **Coverage cumulative `discord_bot/*` ≥ 95%** (cel 100% gdzie możliwe).
- [ ] **PROGRESS.md** rozszerzony o sekcję M7 z retro per Issue.
- [ ] **Milestone M7 zamknięty** na GitHub via `gh api -X PATCH .../milestones/7 -f state=closed`.
- [ ] **Manual smoke** — dev guild test wszystkich 4 commands po lokalnym `run_discord_bot` (wzmianka w closure PR description).

---

## §9 Open questions / future work (NIE w M7 scope)

- **JWT linking** Discord ↔ istniejące Django konto — `/link <jwt>` command po wygenerowaniu JWT w GraphQL `myProfile` mutation. M-future jeśli pojawi się use case "powiąż mój Discord z kontem stworzonym przez web signup".
- **Per-channel threshold** — różne progi w różnych kanałach jednego serwera. `DiscordChannel` zostawia struktura ready, ale logic per-guild aktualnie.
- **`DiscordChannel.notification_enabled` toggle** — admin może wyłączyć notyfikacje bez ustawiania thresholdu na 999. M-future / M8.
- **Bot service w `docker-compose.dev.yml`** — aktualnie tylko prod compose i lokalny `manage.py`. M9 (Dockeryzacja) zaadresuje.
- **Discord OAuth flow** — pełny "Sign in with Discord" zamiast auto-create. M-future.
- **Internationalization slash command responses** — aktualnie hardcoded angielski (z polskimi komentarzami w kodzie). M-future jeśli wielojęzyczna user base.
- **Permission caching dla `/deaths threshold`** — query Discord API per-invocation; rate limit niski (admin commands rzadkie), nie wymaga cache. M-future jeśli command volume wzrośnie.
- **Bot stats dashboard** — `scrape_logs`-analog dla command invocations (count per command, error rate). Kandydat M-future jeśli pojawi się observability potrzeba.
- **`DEATH_LEVEL_THRESHOLD` env var deprecation** — aktualny env var `DEATH_LEVEL_THRESHOLD=30` w `.env.example` staje się **fallback** gdy `DiscordChannel` row nie istnieje dla guild. M7 NIE removuje env'a — M8 (outbound) zdecyduje czy używać per-guild override z fallback'em na env, czy w pełni migrować do model.

---

## §10 References / precedensy

- **CLAUDE.md §3, §8** — top-level `discord_bot/` directive + 4 commands + bot rules
- **CLAUDE.md §4** — `DiscordChannel` model planowany od początku projektu (M1 spec)
- **CLAUDE.md §15.2** — services.py convention (cogi cienkie, biz logic w services)
- **M2-D11** — async/sync boundary pattern (`sync_to_async`) w GraphQL resolverach, M7 cogi reusing
- **M5-D25** — Protocol-based handler abstraction w `apps/notifications/`, M8 zamiana `LoggingHandler` → `DiscordHandler`
- **M6-D28** — top-level Python package precedens (`logs_backend/`); M7 dodaje pierwszy top-level Django app
- **M6-D29** — pułapka "eager resource lookup w `__init__`" — M7 unika powtórki (bot lazy init w `setup_bot()`, services z lazy User fetch)
- **M5/M6 retro pattern** — feature PR + closure PR z fresh master (M1-D8 lekcja)
