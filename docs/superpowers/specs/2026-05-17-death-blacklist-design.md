# Death Blacklist (DeathWatch) — Design

**Data:** 2026-05-17
**Robocza nazwa feature:** Death blacklist (kodowa nazwa apki: `apps/deathwatch/`).
**Poprzednie milestone'y istotne dla kontekstu:** M4 (deaths monitor na tibiantis.info), M5 (bedmage tracker na tibiantis.online), M7/M8 (Discord bot + outbound notifications via Bot Token).

---

## 1. Cel

Dodać czwartą funkcjonalność biznesową aplikacji — **per-user blacklist postaci z 1-minutowym monitoringiem nowych śmierci** na stronie `https://tibiantis.online/?page=character&name=<nick>`. Po wdrożeniu backend potrafi:

1. User przez Discord slash command `/deathwatch add <character>` zapisuje, że chce być powiadamiany o **każdej nowej śmierci** danej postaci (bez progu levela).
2. Co 1 min Celery Beat odpala `scrape_for_watched_deaths` — task iteruje unikalne postacie z aktywnych watchy, scrapuje tibiantis.online (subprocess + spider), parsuje sekcję "Latest Deaths" na profilu, zapisuje `WatchedDeathEvent`.
3. Tylko śmierci z `died_at > watch.created_at` (czyli "po dodaniu na blacklist") są zapisywane — historyczne deaths z tabeli profilu są ignorowane.
4. Notyfikacje idą na **wspólny kanał Discord per-guild** (`DeathWatchChannel`, admin konfiguruje komendą `/deathwatch channel`). Bot dispatchuje przez istniejący `DiscordRESTClient.send_channel_message` z Bot Tokenem — **nie webhook**.
5. Dedup notyfikacji: 10 userów obserwujących Yhral'a = **1 wiadomość per event** na kanał, flag `WatchedDeathEvent.announced_on_discord` jest źródłem prawdy.

**Świadomie wąski scope:**
- **Niezależność od deaths feature (M4).** Nie ruszamy `DeathEvent`, nie reusujemy `DiscordChannel` model (deaths feature trzyma tam `death_level_threshold` którego deathwatch nie potrzebuje). Osobne tabele, osobne komendy, osobny handler. User explicit: "feature niech nie współdziała z death list niech oba programy działają niezależnie".
- **Brak filtra po levelu.** User świadomie dodaje konkretne postacie — `DEATH_LEVEL_THRESHOLD` z M4 nie ma tu zastosowania.
- **Brak per-watch custom thresholds** (level, interval) — global cap i global cadence wystarczą dla MVP.

**Świadomie odroczone (Out of scope):**
- Konsolidacja scrape gdy postać jest jednocześnie na bedmage list i deathwatch — dwa osobne requesty do tej samej strony w różnych cadence (1 min vs 1 h). Trigger refactora: >5 postaci na obu listach jednocześnie w prod.
- Per-user `/deathwatch threshold <level>` — celowo wyłączone, semantyka "watch konkretnej postaci" tego nie potrzebuje.
- Web dashboard z listą watched + historią ogłoszeń — nie MVP.
- Soft delete + audit retention — obecnie hard delete (zgodnie z bedmages pattern).
- Auto-deactivation watcha po N failed scrape (postać usunięta z Tibiantis) — heurystyka kruche, manual `/remove` na razie.
- Email/SMS alternative — globalny TODO z CLAUDE.md §16.
- Multi-tenant routing per `DeathWatch.guild_id` (gdzie user dodał = tam ogłoszenie) — obecnie ogłoszenie idzie na **wszystkie** skonfigurowane `DeathWatchChannel`. W praktyce dla single-guild deployment = jeden kanał.

---

## 2. Scope

**W scope:**

- Nowa aplikacja `apps/deathwatch/` zarejestrowana w `INSTALLED_APPS` jako `apps.deathwatch.apps.DeathWatchConfig`.
- **Trzy modele** w `apps/deathwatch/models.py`:
  - `DeathWatch(user FK, character FK, created_at auto_now_add, active default=True)` + unique constraint `(user, character)`.
  - `WatchedDeathEvent(character FK, level_at_death PositiveIntegerField, killed_by TextField, died_at DateTime db_index, scraped_at auto_now_add, announced_on_discord Bool db_index)` + unique constraint `(character, died_at)`.
  - `DeathWatchChannel(guild_id BigInteger, channel_id BigInteger, created_at, updated_at)` + unique constraint `(guild_id)`.
- **Migracja initial** + **migracja seed PeriodicTask** "deathwatch.scrape_for_watched_deaths" co 1 min, `enabled=False` domyślnie (admin włącza świadomie).
- **Services** `apps/deathwatch/services.py`:
  - `add_death_watch(user, character_name) → DeathWatch` — canonicalize name (reuse `apps.characters.models._canonicalize_name`), cap check (raises `ValueError` przy `>= settings.DEATHWATCH_MAX_WATCHED_CHARACTERS`), `Character.objects.get_or_create`, `DeathWatch.objects.get_or_create` z reactivate gdy inactive. Cap check **wewnątrz `transaction.atomic()`** — atomicity przeciwko race condition jednoczesnych `/add`.
  - `remove_death_watch(user, character_name) → bool` — hard delete (idempotent).
  - `list_death_watches(user) → QuerySet[DeathWatch]` — filter+select_related, order by `-created_at`.
  - `set_deathwatch_channel_for_guild(guild_id, channel_id) → DeathWatchChannel` — `update_or_create`.
  - `record_watched_death(item: CharacterDeathItem) → WatchedDeathEvent | None` — pipeline-side: walidacja Character istnieje, filtr `exists()` aktywnego watcha z `created_at < died_at`, `get_or_create` event (unique constraint deduplikuje natural). Zwraca event jeśli new, None jeśli dropped.
  - `notify_watched_deaths_for_character(character) → int` — iteracja kanałów × pending events, call handler, atomic flag-set po sukcesie na **wszystkich** kanałach. Returns count fired.
- **Notifications** w `apps/notifications/handlers.py`:
  - `DeathWatchAnnouncementHandler` Protocol — `announce(event, channel) → bool`.
  - `DeathWatchChannelHandler` — implementacja używająca `DiscordRESTClient.send_channel_message(channel_id, embed=...)`. Embed wzorcem z `DiscordChannelHandler._render_embed`: title=character.name, url=tibiantis.online profile (urlencoded), description z level/`died_at` w Europe/Warsaw/killed_by, color=`0x8B008B` (purpura — wizualne odróżnienie od deaths crimson `0xDC143C`).
  - `DeathWatchLoggingHandler` — test/dev variant, logger.info only.
- **Factory** `apps/notifications/__init__.py::get_deathwatch_handler()` — dotted-path resolution z `settings.DEATHWATCH_NOTIFICATION_HANDLER` (wzorzec z `get_bedmage_handler`).
- **Spider** `scrapers/tibiantis_scrapers/spiders/character_deaths_spider.py`:
  - `name = "character_deaths"`, accepts `-a name=<character>`.
  - Parsuje sekcję "Latest Deaths" pod profilem (selektor zwalidowany na fixture HTML).
  - Yields `CharacterDeathItem(character_name, died_at, level_at_death, killed_by)`.
  - Reuse parser daty z `scrapers/.../utils/dates.py` (nowy moduł — refactor wyciągający `_parse_last_login` z `character_spider.py`).
- **Items** `scrapers/.../items.py` — dodać `CharacterDeathItem`.
- **Pipeline** `scrapers/.../pipelines.py` — nowy branch dla `CharacterDeathItem` → `apps.deathwatch.services.record_watched_death(item)`. Pipeline **nie** pisze bezpośrednio do ORM (CLAUDE.md §6).
- **Management command** `apps/deathwatch/management/commands/scrape_character_deaths.py` — wzorzec z `apps/characters/management/commands/scrape_character.py`, `CrawlerRunner` + crochet, exit 0/1.
- **Celery task** `apps/deathwatch/tasks.py::scrape_for_watched_deaths`:
  - `bind=True, max_retries=2, acks_late=True`.
  - Redis lock via `django.core.cache.cache.add("deathwatch_scrape_lock", "1", timeout=55)` — zapobiega nakładającym się fire'om gdy cycle > 1 min.
  - Hard cap check (defense-in-depth: serwisowa walidacja przy `/add` powinna zatrzymać, ale task self-guards).
  - Freshness gate: skip Characters z `last_scraped_at > now - DEATHWATCH_FRESHNESS_SECONDS` (default 50s).
  - Subprocess `manage.py scrape_character_deaths <name>` z `timeout=30`, per-character.
  - Po sukcesie scrape: call `notify_watched_deaths_for_character(character)`.
  - Zwraca summary dict `{"checked", "skipped", "scraped", "failed", "events_announced"}` dla observability.
- **Discord cog** `discord_bot/cogs/deathwatch.py`:
  - `SlashCommandGroup("deathwatch", ...)`.
  - `/deathwatch add <character_name>` — user-scoped, ephemeral ack.
  - `/deathwatch remove <character_name>` — user-scoped, ephemeral ack.
  - `/deathwatch list` — user-scoped, ephemeral embed.
  - `/deathwatch channel` — admin-only (server admin permission check jak `deaths threshold`), public ack.
  - Auth wzorcem `discord_bot/cogs/bedmages.py`: `discord_id → User` resolve via `sync_to_async`, auto-create przy pierwszej komendzie.
  - Każda komenda łapie `ValueError` z services → user-friendly response, bez stack trace.
- **Bot register** — dodaj cog w `discord_bot/bot.py`.
- **GraphQL** `apps/deathwatch/schema.py` (wzorzec `apps/bedmages/schema.py`):
  - Queries: `myDeathWatches: [DeathWatchType!]!` (JWT-auth), `watchedDeaths(characterName, limit=20): [WatchedDeathEventType!]!` (JWT-auth).
  - Mutations: `addDeathWatch(characterName: String!): DeathWatchType!`, `removeDeathWatch(characterName: String!): Boolean!`, `setDeathWatchChannel(guildId, channelId): DeathWatchChannelType!` (admin/superuser).
  - Typy: `DeathWatchType`, `WatchedDeathEventType`, `DeathWatchChannelType`.
  - Scal w `config/schema.py`.
- **Admin** `apps/deathwatch/admin.py` — registracje 3 modeli z `list_display`, `list_filter`, `search_fields`. **Bez `ModelAdmin[Foo]` generic subscripta** (django-stubs runtime trap — feedback memory).
- **Settings** w `config/settings/base.py`:
  - `DEATHWATCH_MAX_WATCHED_CHARACTERS = env.int(..., default=20)`
  - `DEATHWATCH_FRESHNESS_SECONDS = env.int(..., default=50)`
  - `DEATHWATCH_NOTIFICATION_HANDLER = env(..., default="apps.notifications.handlers.DeathWatchChannelHandler")`
  - Reuse `DISCORD_BOT_TOKEN` (M7/M8).
- **Settings stubs** `config/settings/stubs.py` — mirror nowych zmiennych (feedback_stubs_py_backend_overrides memory: brak override → CI mypy ModuleNotFoundError).
- **`.env.example`** — `DEATHWATCH_MAX_WATCHED_CHARACTERS=20`, `DEATHWATCH_FRESHNESS_SECONDS=50`.
- **Tests** w `tests/unit/deathwatch/` i `tests/integration/deathwatch/` — pełne pokrycie modeli, services, spider, pipeline, task, handler, GraphQL, cog (target ≥85% coverage dla `apps/deathwatch/`).
- **Fixture HTML** `tests/fixtures/tibiantis_online/character_with_deaths.html` — ręczny snapshot strony postaci z ≥2 deaths, commitowany. **Testy spidera bez fixture nie istnieją** (CLAUDE.md §15.6).
- **PROGRESS.md** — retro + DoD checklist + podsumowanie po wdrożeniu.

**Poza scope:** patrz "Świadomie odroczone" w §1.

---

## 3. Decisions (z brainstormingu)

### 3.1. Ownership modelu: per-user watch + wspólny kanał notyfikacji
Wybrane explicit przez usera. Konsekwencje:
- Wielu userów może obserwować tę samą postać (`unique_together(user, character)` zapewnia uniqueness per user, nie globalnie).
- Dedup notyfikacji musi być na poziomie `WatchedDeathEvent` (event-scoped flag), nie na watchu (per-watch flag jak w bedmages by spamował kanał).

### 3.2. Cadence: twarde 1 min + globalny cap postaci
Wybrane explicit przez usera. Default cap = 20 (= 40s cycle z `DOWNLOAD_DELAY=2s`, 50% margin w 1-min Beat interval). Cap walidowany w `add_death_watch` services + defense-in-depth w Celery tasku.

### 3.3. Brak filtra po levelu
Wybrane explicit przez usera. User świadomie dodaje konkretne postacie — nie ma ryzyka "zalewu noobami" jak w deaths feature.

### 3.4. Architektura: pełna separacja od deaths feature (Wariant A)
Wybrane explicit przez usera. Nowa apka, osobne modele, osobny pipeline route, osobny handler, osobny kanał (`DeathWatchChannel`, nie reuse `DiscordChannel`).

### 3.5. Dispatch przez Bot Token, nie webhook
Wybrane explicit przez usera (w trakcie review Sekcji 2). Reuse `DiscordRESTClient.send_channel_message` z M8 — identyczna mechanika jak deaths feature.

### 3.6. Filtr "po dodaniu"
Implementacja: `record_watched_death` sprawdza `DeathWatch.objects.filter(character=c, active=True, created_at__lt=died_at).exists()`. Jeśli False — drop event. Tabela "Latest Deaths" na tibiantis.online pokazuje ostatnie ~10 śmierci postaci, więc historyczne deaths sprzed dodania watcha będą widziane przez spider, ale filtrowane przez service.

### 3.7. Hard delete watcha
Konsystencja z bedmages (`remove_bedmage_watch` w `apps/bedmages/services.py:47`). Argumenty:
- Bedmages już ma hard delete + reactivate flow — predictable mental model.
- Soft delete `active=False` + re-add zmieni `created_at` tylko jeśli explicit override; hard delete reset jest jednoznaczny.
- Brak business need na audit history watchów w MVP.

### 3.8. Lazy fetch przy `/add`
Konsystencja z bedmages (`add_bedmage_watch`): `Character.objects.get_or_create(name=...)` bez synchronicznego scrape. Pierwszy automatyczny scrape przez Celery Beat uzupełni dane. Argumenty:
- Synchroniczny scrape w slash command = HTTP call w event loop py-cord = UX delay (2s+) + 2-step error handling.
- Spider sam loguje warning gdy postać nie istnieje (`character_spider.py:31`) — telemetria zachowana.

### 3.9. Multi-channel announcement: flag-set po sukcesie na wszystkich kanałach
Trade-off: bezpieczne (no event loss) ale ograniczone (permanentny 403/404 na jednym kanale utknie event). Dla MVP akceptowalne. Future evolution: per-channel announcement tracking table.

### 3.10. Redis lock przeciwko nakładającym się Beat fire'om
`django.core.cache.cache.add(key, "1", timeout=55)` — atomic add (nie set). Gdy lock istnieje, task wcześnie kończy. Bez tego dwa równoległe worker'y mogłyby równolegle bombić tibiantis.online.

### 3.11. Distinctive embed color
DeathWatch używa `0x8B008B` (purpura), DeathEvent (M4) używa `0xDC143C` (crimson). Operatorzy widzący oba feeds w prod muszą natychmiast odróżnić źródło.

### 3.12. Aktualizacja `Character.last_deaths_scraped_at`
Po `subprocess.returncode == 0` w `scrape_for_watched_deaths` **task** (nie pipeline / nie service `record_watched_death`) wykonuje `Character.objects.filter(name=name).update(last_deaths_scraped_at=timezone.now())`. Update **niezależnie** od liczby pozyskanych eventów (nawet 0 deaths to valid scrape result — postać żywa, brak nowych zgonów). Pipeline-side update byłby niewłaściwy bo per-item — postać bez deaths w ogóle nie wywoła pipeline'u.

### 3.13. "Sukces" w multi-channel announcement
`handler.announce(event, channel) → bool` — `True` oznacza Discord API zwróciło 2xx (`DiscordRESTClient.send_channel_message` already handles retry + 4xx/5xx semantics). `announced_on_discord` jest ustawiana gdy **wszystkie** kanały zwróciły `True` w danej iteracji. Częściowy sukces (np. 2 z 3 kanałów OK) NIE oznacza flagi — następny task fire retry **na wszystkich** kanałach (idempotency Discord side: ten sam embed treść = duplicate message, jeśli to problem patrz §9.5).

---

## 4. Implementation outline

### 4.1. Files to create

```
apps/deathwatch/
├── __init__.py
├── apps.py                                 # DeathWatchConfig
├── admin.py                                # 3 model registracje
├── models.py                               # DeathWatch, WatchedDeathEvent, DeathWatchChannel
├── services.py                             # 6 funkcji (sekcja 2)
├── schema.py                               # GraphQL queries+mutations
├── tasks.py                                # scrape_for_watched_deaths
├── migrations/
│   ├── __init__.py
│   ├── 0001_initial.py
│   └── 0002_seed_periodic_task.py
└── management/
    ├── __init__.py
    └── commands/
        ├── __init__.py
        └── scrape_character_deaths.py

scrapers/tibiantis_scrapers/
├── spiders/character_deaths_spider.py     # nowy spider
└── utils/
    ├── __init__.py
    └── dates.py                            # wydzielony _parse_last_login

discord_bot/cogs/deathwatch.py             # 4 slash commands

tests/
├── fixtures/tibiantis_online/character_with_deaths.html   # manual snapshot
├── unit/deathwatch/
│   ├── test_models.py
│   ├── test_services.py
│   ├── test_spider.py
│   └── test_handlers.py
└── integration/
    ├── deathwatch/
    │   ├── test_pipeline.py
    │   ├── test_celery_task.py
    │   └── test_notify.py
    └── discord_bot/test_deathwatch_cog.py
```

### 4.2. Files to modify

- `config/settings/base.py` — `DEATHWATCH_*` settings.
- `config/settings/stubs.py` — mirror (mypy CI guard).
- `config/schema.py` — scal `apps.deathwatch.schema`.
- `scrapers/tibiantis_scrapers/items.py` — `CharacterDeathItem`.
- `scrapers/tibiantis_scrapers/pipelines.py` — route dla nowego itemu.
- `scrapers/tibiantis_scrapers/spiders/character_spider.py` — refactor `_parse_last_login` → reuse z `utils/dates.py`.
- `discord_bot/bot.py` — register `DeathWatchCog`.
- `apps/notifications/handlers.py` — `DeathWatchAnnouncementHandler` Protocol + `DeathWatchChannelHandler` + `DeathWatchLoggingHandler`.
- `apps/notifications/__init__.py` — `get_deathwatch_handler()` factory.
- `.env.example` — dwie nowe zmienne.

### 4.3. Build sequence (sugerowana kolejność PR-ów / Issue'sów)

1. **D1** — Models + migracje + admin (no logic yet).
2. **D2** — Services (add/remove/list + cap atomicity) + unit tests.
3. **D3** — Spider + management command + fixture HTML + unit test spidera.
4. **D4** — Pipeline route + `record_watched_death` + integration test pipeline E2E.
5. **D5** — Celery task + Redis lock + freshness gate + seed migration + integration test task.
6. **D6** — Handler (Protocol + impl + logging variant) + factory + `notify_watched_deaths_for_character` + unit test handler + integration test notify.
7. **D7** — Discord cog (4 slash commands) + auth wzorcem bedmages + integration test cog.
8. **D8** — GraphQL schema (queries+mutations+typy) + scal w config/schema.py + unit tests.
9. **D9** — Settings stubs.py mirror + `.env.example` + PROGRESS.md retro.

Each Issue: scope + DoD + tests required. Format jak M5-M10 Issues w `.github/issue-bodies/`.

---

## 5. Edge cases (z udokumentowaną decyzją)

| Sytuacja | Zachowanie | Uzasadnienie |
|---|---|---|
| User dodaje postać która nie istnieje na Tibiantis | Lazy fetch (jak bedmages) — `/add` zwraca sukces, pierwszy scrape spider loguje warning, brak ogłoszenia. | Spójność z `add_bedmage_watch`. Sync walidacja = UX delay. |
| Postać ma 10 historycznych deaths przed dodaniem watcha | Wszystkie zignorowane przez filtr `created_at < died_at` w `record_watched_death`. | User explicit "PO dodaniu". |
| User `/remove` i potem `/add` ponownie | Hard delete + nowy watch z nowym `created_at`. Eventy między remove/add są ignorowane retroaktywnie. | Konsystencja z bedmages. |
| Postać jednocześnie na bedmage list i deathwatch | Dwa osobne pipeline'y, dwa requesty do tej samej strony w różnych cadence. | Akceptowalne dla MVP. Future refactor — patrz §1 Out of scope. |
| Cap przekroczony (race: jednoczesne `/add` od 2 userów) | Cap check w `transaction.atomic()` block po `get_or_create`; jeśli post-create distinct count > cap → rollback. | Atomicity. Bez tego dwa parallel `/add` mogą obejść cap. |
| Discord 5xx przy ogłoszeniu | `announced_on_discord` NIE jest ustawiana → następny task fire retry. Permanentny 4xx na jednym kanale → event utknie do manual admin intervention. | Bezpieczne (no event loss), trade-off opisany w §3.9. |
| Postać usunięta z Tibiantis (404 lub puste rows) | Spider loguje warning, brak nowych eventów. Watch zostaje aktywny (user musi `/remove` ręcznie). | Bot nie wie czy 404 to perm delete czy maintenance. |
| Tibiantis timestamp w DST transition | Spider parsuje `Europe/Berlin` (CEST/CET handled przez `zoneinfo`), zapisuje UTC w DB. Display zawsze konwertowany do `Europe/Warsaw`. | Reuse istniejącej konwencji M4/M5 (#180, #181, #184). |
| `DeathWatchChannel` nie skonfigurowany | `notify_watched_deaths_for_character` early-returns gdy `channels.exists()` is False. Events czekają z `announced_on_discord=False` do skonfigurowania. | Operacyjnie: admin może włączyć kanał później i dostać "backlog" eventów. To może być pożądane lub nie — explicit decyzja: **dostają backlog** (brak garbage collection na pending events). |
| Postać scrapowana przez bedmage scraper aktualizuje `last_scraped_at` Character | Freshness gate w deathwatch task zobaczy "świeże" i pominie — ale bedmage scraper NIE parsuje sekcji Latest Deaths, więc deathwatch potrzebuje własnego scrape. **Bug** — freshness gate musi być per-source. | Rozwiązanie: nowe pole `Character.last_deaths_scraped_at` (auto_now=False, updated tylko przez deathwatch task) lub osobny tracking model. Decyzja: dodać `last_deaths_scraped_at` w 0001_initial migration. |

### 5.1. Decyzja dotycząca `last_deaths_scraped_at`

Dodaj pole `last_deaths_scraped_at: DateTimeField(null=True, blank=True)` do `Character` model (nie do `DeathWatch` — character-level state). Freshness gate w `scrape_for_watched_deaths` używa **tego pola**, nie generycznego `last_scraped_at`. Bedmage scraper i character scraper nie ruszają tego pola.

**Update odpowiedzialność:** Celery task `scrape_for_watched_deaths` aktualizuje pole po `subprocess.returncode == 0`, **niezależnie** od tego czy spider wyemitował 0 czy N itemów (patrz §3.12). Pipeline / service `record_watched_death` NIE aktualizują — byłoby per-item, postaci bez nowych deaths nigdy nie wywołałyby update.

**Migracja:** `apps/characters/migrations/0007_character_last_deaths_scraped_at.py` — nie w `apps/deathwatch/migrations/` (modyfikacja zewnętrznej apki, ale character to shared model). Alternatywnie: zamknąć w `apps/deathwatch/migrations/` z `run_before` dependency. **Wybór:** w `apps/characters/migrations/` — model należy do tamtej apki, deathwatch tylko z niego korzysta.

---

## 6. Test plan

### 6.1. Unit (`tests/unit/deathwatch/`)

- `test_models.py` — unique constraints, FK behavior, default values (3 modele).
- `test_services.py`:
  - `add_death_watch` happy path + cap exceeded raises + reactivate inactive + canonicalize name.
  - `remove_death_watch` happy + idempotent (returns False on miss).
  - `list_death_watches` filter+order.
  - `set_deathwatch_channel_for_guild` upsert.
  - `record_watched_death` — filter "po dodaniu" (3 cases: before/exactly_at/after), unique deduplication, missing Character logs+drops.
  - `notify_watched_deaths_for_character` — no channels (early return), all-success flag set, partial failure no flag.
- `test_spider.py` — `CharacterDeathsSpider` na fixture HTML, asercje per pole `CharacterDeathItem`, edge case "no deaths" pusta sekcja.
- `test_handlers.py` — `DeathWatchChannelHandler._render_embed` snapshot (color, url encoding, TZ conversion), `DeathWatchLoggingHandler` test variant.

### 6.2. Integration (`tests/integration/deathwatch/`)

- `test_pipeline.py` — `CharacterDeathItem` przez pipeline → `WatchedDeathEvent` w DB. Filter "po dodaniu" E2E (watch created → mock item with `died_at` before/after → assert DB state).
- `test_celery_task.py`:
  - Mock subprocess + mock cache (lock) + mock notify → assert correct flow.
  - Lock contention test (second fire skips when lock held).
  - Cap exceeded defense (manual DB insert past cap → task logs error, doesn't bomb tibiantis).
  - Freshness gate (Character with recent `last_deaths_scraped_at` is skipped).
- `test_notify.py` — full notify flow z multiple channels mocked, sukces/failure mix per channel.

### 6.3. Discord cog (`tests/integration/discord_bot/test_deathwatch_cog.py`)

- `discord.py` test mode + mock `DiscordRESTClient` — wszystkie 4 slash commands respond correctly, ephemeral flag right, admin-only enforcement for `/deathwatch channel`.
- `ValueError` z services → user-friendly response, no stack trace leak.

### 6.4. GraphQL

- W `tests/unit/deathwatch/test_schema.py` (lub osobny folder zgodnie z konwencją projektu): JWT-protected queries+mutations, auth resolver, typ shapes.

### 6.5. Coverage target

- `apps/deathwatch/` ≥ 85% line coverage (CLAUDE.md §13 minimum 70%, aim wyżej dla nowych modułów).
- Spider testowany **wyłącznie** na fixturce HTML — CI nie hituje żywego Tibiantis (CLAUDE.md §15.6).

---

## 7. Rate-limit i observability

### 7.1. Tibiantis-side respect

- `DOWNLOAD_DELAY=2.0` (globalny w `scrapers/.../settings.py`) — nowy spider dziedziczy automatycznie.
- Cap 20 postaci × 2s = 40s cycle, 50% margin w 1-min Beat interval. **Math sanity check:** zwiększanie cap powyżej 27 (=54s) wprowadza ryzyko cycle overrun. Redis lock zapobiega bombingowi, ale ograniczy aktualną iterację — eventy są lekko opóźnione w skrajnych przypadkach. Akceptowalne.
- `User-Agent`: reuse istniejącego `SCRAPE_USER_AGENT` z .env.

### 7.2. Mongo `scrape_logs`

Każdy fire spidera loguje (przez istniejący Scrapy extension): url, czas trwania, liczba itemów, błędy. Bez zmian.

### 7.3. Celery summary dict

Task zwraca `{"checked", "skipped" (freshness), "scraped", "failed", "events_announced"}`. Visible w Flower / log podsumowaniu (wzorzec z `scrape_watched_characters`).

### 7.4. Manual ops review

Jeśli `failed > scraped * 0.5` w godzinie → log error (`logger.error`). Auto-alerting (PagerDuty/Slack) out of scope.

---

## 8. Definition of Done

- [ ] Wszystkie modele utworzone, migracje commitowane.
- [ ] `Character.last_deaths_scraped_at` field dodany przez `apps/characters/migrations/0007_*`.
- [ ] Services 6 funkcji + ≥85% coverage.
- [ ] Spider zwalidowany na fixture HTML + test passing.
- [ ] Pipeline route + `record_watched_death` integration test passing.
- [ ] Celery task + Redis lock + seed migration `enabled=False` + integration test passing.
- [ ] Handler (3 klasy) + factory + integration test passing.
- [ ] Discord cog (4 komendy) + auth wzorcem bedmages + integration test passing.
- [ ] GraphQL schema scalony w config/schema.py + tests passing.
- [ ] Admin registracje (bez generic subscripta) + manual smoke przez `python manage.py runserver`.
- [ ] Settings + stubs.py mirror + `.env.example` zaktualizowane.
- [ ] Pre-commit `run --all-files` passing (ruff format/check, mypy strict dla `apps/deathwatch/`, gitleaks).
- [ ] CI green: lint + test + coverage ≥70% globalnie (jeśli local ≥85% to globalny próg automatycznie spełniony).
- [ ] PROGRESS.md retro + DoD checklist + podsumowanie.
- [ ] Manual smoke w prod-like env (lokalny docker-compose): `/deathwatch channel` w testowym guildzie → `/deathwatch add <test_character>` → poczekać 1 min → weryfikować że WatchedDeathEvent powstaje TYLKO dla deaths po `created_at` watcha → notyfikacja na kanale z purpurowym embedem.

---

## 9. Risks & follow-ups

### 9.1. Riziko: Tibiantis blokuje IP przez agresywny rate
**Probability:** medium dla 1-min cadence.
**Mitigation:** cap 20 + 2s delay + monitoring `scrape_logs` dla 429/503. Jeśli problem → obniżyć cap lub wprowadzić exponential backoff per-IP.

### 9.2. Ryzyko: Selektor sekcji "Latest Deaths" pęknie przy redesignie strony
**Probability:** low w krótkim horyzoncie (Tibiantis to fan-made, rzadko ruszany frontend), wzrasta w długim.
**Mitigation:** fixture HTML w CI + Mongo `scrape_logs` z zero-item count alarm; w razie problemu — update fixture + selector w jednym PR.

### 9.3. Ryzyko: Per-watch `guild_id` brakuje → multi-guild bot wysyła do wszystkich kanałów
**Probability:** zależy od scope deploymentu. Single-guild → no-op. Multi-guild → user dodał w Guild A, ogłoszenie idzie też do Guild B.
**Mitigation:** dla MVP akceptujemy. Future: dodać `DeathWatch.guild_id` field + filter w `notify_watched_deaths_for_character`.

### 9.4. Follow-up: konsolidacja scrape z bedmages
**Trigger:** >5 postaci na obu listach. Refactor: rozszerzyć `character_spider` o yield `CharacterDeathItem[]` przy okazji, deathwatch consumes its slice. Premature dla MVP — patrz §1 Out of scope.

### 9.5. Follow-up: per-channel announcement tracking
Gdy permanentny 403/404 na jednym kanale utyka event globalnie. Trigger: pierwszy incydent w prod. Refactor: nowy model `DeathWatchAnnouncement(event, channel, status)`.

### 9.6. Downstream wrapper audit (memory `feedback_canonicalization_downstream_audit`)
Po wdrożeniu service-layer canonicalize w `add_death_watch`, audyt że:
- Discord cog NIE używa `Character.objects.get(name=...)` bezpośrednio — przechodzi przez services.
- GraphQL mutations NIE bypassują canonicalize.
- REST nigdzie nie tknie (REST = tylko auth, CLAUDE.md §9).

---

## 10. References

- Bedmages design: `docs/superpowers/specs/2026-05-08-m5-bedmage-tracker-design.md` (wzorzec per-character scraping + per-user watch).
- Deaths design: `docs/superpowers/specs/2026-04-30-m4-deaths-monitor-design.md` (wzorzec dedup + announce flag).
- Outbound notifications: `docs/superpowers/specs/2026-05-15-m8-outbound-notifications-design.md` (DiscordRESTClient + handler abstraction).
- Discord bot commands: `docs/superpowers/specs/2026-05-13-m7-discord-bot-commands-design.md` (slash command + admin permission wzorzec).
