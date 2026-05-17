# Death Blacklist (DeathWatch) — Implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-user blacklist postaci z 1-minutowym monitoringiem nowych śmierci na `tibiantis.online`, niezależny od istniejącego deaths feature (M4).

**Architecture:** Pełna separacja (spec wariant A): nowa apka `apps/deathwatch/` + nowy spider parsujący sekcję "Latest Deaths" na profilu postaci + Celery task co 1 min z Redis lockiem + nowy embed handler dispatchujący przez istniejący `DiscordRESTClient` (Bot Token, nie webhook) + osobny model `DeathWatchChannel` per-guild. Notyfikacje deduplikowane na poziomie eventu (10 userów = 1 wiadomość).

**Tech Stack:** Django 6.0, Scrapy, Celery + Beat, Redis (cache lock), discord.py (py-cord), Strawberry-Django, PostgreSQL.

**Data:** 2026-05-17
**Spec:** [`docs/superpowers/specs/2026-05-17-death-blacklist-design.md`](../specs/2026-05-17-death-blacklist-design.md)
**Status:** READY (spec zaakceptowany 2026-05-17, wszystkie decyzje §3 z brainstormingu zatwierdzone).

---

## Źródła

- **Spec death blacklist** — referencyjny dokument, każdy task linkuje do `§X` dla konkretnej sekcji.
- **CLAUDE.md** §1 (cel biznesowy), §3 (struktura apek), §6 (scraping rules — `DOWNLOAD_DELAY ≥ 2s`, pipeline → services), §7 (logika biznesowa w services), §8 (Discord bot — osobny proces, slash commands, no stack traces), §9 (GraphQL dla domeny, REST tylko auth), §15 (zasady dla Claude).
- **Precedensy:**
  - **M4 deaths monitor** (`apps/deaths/`) — wzorzec announce flag + unique constraint + handler Protocol+Impl + admin permission check w `deaths threshold` cog.
  - **M5 bedmage tracker** (`apps/bedmages/`) — wzorzec per-user watch + per-character services + lazy fetch Character + hard delete + reactivate + cog z slash commands + auth resolve `discord_id → User`.
  - **M7 Discord bot** — `discord_bot/cogs/bedmages.py` + `cogs/deaths.py` — wzorzec ephemeral vs public ack + admin guards + `sync_to_async`.
  - **M8 outbound notifications** — `apps/notifications/handlers.py` + `apps/notifications/discord_client.py` — `DiscordRESTClient.send_channel_message` z retry/429/5xx handling.
  - **M3 scrape_watched_characters** — `apps/characters/tasks.py` — wzorzec subprocess per-character + freshness gate + per-character try/except.

---

## Pre-flight checklist (przed Task #1)

- [ ] **`apps/deathwatch/` nie istnieje** — fresh creation.
- [ ] **`Character` model ma `name`, `last_login`, `last_scraped_at`** — istnieje od M1. Nowe pole `last_deaths_scraped_at` dochodzi w Task #1 (osobna migracja w `apps/characters/migrations/`).
- [ ] **`User` model ma `discord_id`** — istnieje od M2-D9, używane przez `apps/bedmages` cog (precedens).
- [ ] **`DiscordRESTClient.send_channel_message` istnieje** — `apps/notifications/discord_client.py` (M8). Reuse 1:1, zero zmian.
- [ ] **`apps.characters.models._canonicalize_name`** — istnieje, używane przez bedmages services. Reuse w `add_death_watch`.
- [ ] **`scrapers/tibiantis_scrapers/spiders/character_spider.py:_parse_last_login`** — istnieje, ale **prywatna** metoda spidera. Task #3 ją wyciąga do `scrapers/.../utils/dates.py` i refactoruje `character_spider` do reuse.
- [ ] **`DOWNLOAD_DELAY=2.0`** globalnie w `scrapers/tibiantis_scrapers/settings.py` — nowy spider dziedziczy.
- [ ] **`SCRAPE_USER_AGENT`** w `.env` z linkiem kontaktowym (CLAUDE.md §6) — reuse.
- [ ] **`django.core.cache`** skonfigurowany na Redis backend — sprawdź w `config/settings/base.py` że `CACHES` używa Redis (broker Celery to `redis://redis:6379/1`, cache typowo `redis://redis:6379/2` lub LocMem dev). Task #5 potrzebuje atomic `cache.add()` — LocMem **nie jest** atomic między procesami, tylko Redis (lub django-redis lock primitive).
- [ ] **`config/settings/stubs.py` single source of truth** — nowe `LOCAL_APPS` entry dla `apps.deathwatch` + nowe settings widoczne dla mypy. Task #9 finalizuje stubs mirror.
- [ ] **`config/schema.py` ma już `merge_types("Mutation", ...)`** — wprowadzone przez M5-D27 dla bedmages. Task #8 dorzuca `DeathWatchMutation` do tego merge.

---

## Open questions (rozstrzygnięte 2026-05-17, spec §3)

Wszystkie decyzje designowe zaakceptowane bez modyfikacji:

1. ✅ **§3.1** Ownership: per-user watch + wspólny kanał notyfikacji.
2. ✅ **§3.2** Cadence: twarde 1 min + global cap 20 postaci.
3. ✅ **§3.3** Brak filtra po levelu.
4. ✅ **§3.4** Pełna separacja od deaths feature (wariant A).
5. ✅ **§3.5** Dispatch przez Bot Token (reuse `DiscordRESTClient`), nie webhook.
6. ✅ **§3.6** Filtr "po dodaniu": `DeathWatch.created_at < WatchedDeathEvent.died_at`.
7. ✅ **§3.7** Hard delete (idempotent).
8. ✅ **§3.8** Lazy fetch Character przy `/add`.
9. ✅ **§3.9** Multi-channel announce: flag set tylko po sukcesie na wszystkich.
10. ✅ **§3.10** Redis lock przeciwko nakładającym się Beat fire'om.
11. ✅ **§3.11** Distinctive embed color `0x8B008B` (purpura).
12. ✅ **§3.12** `Character.last_deaths_scraped_at` aktualizowane przez Celery task po subprocess success, niezależnie od liczby items.
13. ✅ **§3.13** "Sukces" = `handler.announce() → True`; flag dopiero gdy wszystkie kanały OK.

**Open questions z §9** (poza scope, do post-MVP):
- Konsolidacja scrape gdy postać na obu listach (bedmage+deathwatch).
- Per-channel announcement tracking (gdy permanent 4xx utyka event).
- `DeathWatch.guild_id` field dla multi-guild routing.
- Auto-deactivation watcha po N failed scrape.

---

## Risk + mitigation

| Ryzyko | Prob. | Impact | Mitigation |
|---|---|---|---|
| **Cap race**: dwóch userów `/add` symultanicznie obchodzi limit 20 | Średnie | Bombing tibiantis | `transaction.atomic` block + post-create distinct count check + rollback. Task #2 ma test `test_add_death_watch_cap_race_atomicity`. |
| **Beat fire overlap**: cycle > 60s, drugi worker pala równolegle | Niskie (cap 20 × 2s = 40s) | Double rate-limit hit | Redis `cache.add(lock_key, timeout=55)` w Task #5. Test `test_concurrent_task_fire_skips_when_locked`. |
| **Selektor sekcji "Latest Deaths" pęknie po redesignie strony** | Niskie krótko, wysokie długo | Zero items, log warning | Fixture HTML commitowany + Mongo `scrape_logs` z zero-item alarm w opsach. |
| **`last_deaths_scraped_at` vs `last_scraped_at` confusion** | Średnie | Freshness gate sprawdza złe pole, postacie skipowane na zawsze | Task #1 dodaje **osobne** pole. Task #5 explicit komentarz w kodzie i test `test_freshness_gate_uses_last_deaths_scraped_at_not_last_scraped_at`. |
| **Discord 5xx na jednym z N kanałów** | Średnie multi-guild, niskie single | Event utyka do retry, duplikaty w pozostałych kanałach | Akceptujemy dla MVP (§9.5 follow-up). Task #6 ma test `test_partial_channel_failure_leaves_flag_false`. |
| **Pipeline obejdzie service-layer canonicalize** | Niskie (memory `feedback_canonicalization_downstream_audit`) | Postać z różnym case zapisana jako duplikat | Pipeline NIGDY nie woła `Character.objects.get`, zawsze idzie przez `apps.deathwatch.services.record_watched_death`. Code review w Task #4. |
| **Circular import `apps.deathwatch.services ↔ apps.notifications.handlers`** | Średnie | Worker crash przy starcie | Lazy import w handlerze: `from apps.deathwatch.models import WatchedDeathEvent` wewnątrz `_render_embed`, nie na top of module. Wzorzec z M8 `handlers.py:8` (TYPE_CHECKING). |
| **`auto_now_add=True` na `created_at` w testach** | Średnie | Testy filtru "po dodaniu" nie mogą force timestamp w przeszłość | M3-D17 retro #5 lekcja: `DeathWatch.objects.filter(pk=...).update(created_at=...)`. Wzmianka w Task #2 testach. |
| **CrawlerRunner + crochet podwójne wywołanie w jednym procesie** | Niskie | M1-D8 retro: Twisted reactor nie restartuje | Subprocess wzorzec z `apps/characters/tasks.py:46` (per-character `manage.py scrape_character_deaths`). Task #5 nie używa CrawlerRunner bezpośrednio w worker'ze. |

---

## File structure (high-level)

```
apps/deathwatch/                            # NEW
├── __init__.py
├── apps.py                                 # DeathWatchConfig
├── admin.py                                # 3 model registracje
├── models.py                               # DeathWatch + WatchedDeathEvent + DeathWatchChannel
├── services.py                             # 6 funkcji biznesowych
├── schema.py                               # GraphQL queries + mutations
├── tasks.py                                # scrape_for_watched_deaths
├── types.py                                # DeathWatchPayload, WatchedDeathPayload TypedDicts
├── migrations/
│   ├── __init__.py
│   ├── 0001_initial.py                     # auto-generated
│   └── 0002_seed_periodic_task.py          # PeriodicTask "deathwatch.scrape" enabled=False
└── management/
    └── commands/
        ├── __init__.py
        └── scrape_character_deaths.py      # subprocess entry point

apps/characters/migrations/
└── 0007_character_last_deaths_scraped_at.py # NEW: osobna migracja zewn. apki

scrapers/tibiantis_scrapers/
├── items.py                                # MODIFIED: + CharacterDeathItem
├── pipelines.py                            # MODIFIED: route dla CharacterDeathItem
├── spiders/character_spider.py             # MODIFIED: refactor _parse_last_login → utils
├── spiders/character_deaths_spider.py      # NEW
└── utils/                                  # NEW
    ├── __init__.py
    └── dates.py                            # parse_tibiantis_timestamp

discord_bot/
├── bot.py                                  # MODIFIED: register DeathWatchCog
└── cogs/deathwatch.py                      # NEW

apps/notifications/
├── __init__.py                             # MODIFIED: + get_deathwatch_handler factory
└── handlers.py                             # MODIFIED: + DeathWatch{Announcement,Channel,Logging}Handler

config/
├── schema.py                               # MODIFIED: merge DeathWatchQuery + Mutation
└── settings/
    ├── base.py                             # MODIFIED: + DEATHWATCH_* settings
    └── stubs.py                            # MODIFIED: mirror (mypy CI guard)

tests/
├── fixtures/tibiantis_online/
│   └── character_with_deaths.html          # NEW: manual snapshot, commit
├── unit/deathwatch/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_services.py
│   ├── test_spider.py
│   ├── test_handlers.py
│   └── test_schema.py
└── integration/
    ├── deathwatch/
    │   ├── __init__.py
    │   ├── test_pipeline.py
    │   ├── test_celery_task.py
    │   └── test_notify.py
    └── discord_bot/test_deathwatch_cog.py

.env.example                                # MODIFIED: + DEATHWATCH_MAX_WATCHED_CHARACTERS, DEATHWATCH_FRESHNESS_SECONDS
```

---

## Task overview

| # | ID | Tytuł | Czas | Zależy od | Branch |
|---|---|---|---|---|---|
| 1 | DW-1 | Modele + migracje + admin + `Character.last_deaths_scraped_at` | 2-3h | — | `feat/<#>-deathwatch-models` |
| 2 | DW-2 | Services (`add/remove/list/channel/record/notify`) + types | 4h | DW-1 | `feat/<#>-deathwatch-services` |
| 3 | DW-3 | Spider + fixture HTML + management command + date utils refactor | 3h | DW-1 | `feat/<#>-deathwatch-spider` |
| 4 | DW-4 | Pipeline route + `record_watched_death` integration | 1-2h | DW-2, DW-3 | `feat/<#>-deathwatch-pipeline` |
| 5 | DW-5 | Celery task + Redis lock + freshness gate + seed migration | 3h | DW-2, DW-4 | `feat/<#>-deathwatch-task` |
| 6 | DW-6 | Notification handler (Protocol+Impl+Logging) + factory + notify integration | 2-3h | DW-2 | `feat/<#>-deathwatch-handler` |
| 7 | DW-7 | Discord cog (4 slash commands) + register w bot.py | 2-3h | DW-2, DW-6 | `feat/<#>-deathwatch-cog` |
| 8 | DW-8 | GraphQL schema (queries + mutations + typy) + scal w config/schema.py | 2h | DW-2 | `feat/<#>-deathwatch-graphql` |
| 9 | DW-9 | Settings stubs.py mirror + `.env.example` + PROGRESS.md + closure | 1h | DW-1..8 | `docs/<#>-deathwatch-closure` |

**Total:** ~20-24h, 5-6 dni roboczych z buforem.

**Sugerowana ścieżka równoległa (po DW-1):** DW-2 (services) i DW-3 (spider) mogą iść równolegle, łączą się w DW-4 (pipeline). DW-6 (handler) zależy tylko od DW-2 — może iść równolegle z DW-3/DW-4/DW-5.

---

## Task #1 — [DW-1] Modele + migracje + admin + `Character.last_deaths_scraped_at`

### 🎯 Cel

Trzy modele (`DeathWatch`, `WatchedDeathEvent`, `DeathWatchChannel`) w `apps/deathwatch/`, dodanie `Character.last_deaths_scraped_at`, dwie migracje (`apps/deathwatch/0001_initial`, `apps/characters/0007_*`), Django admin registracje. Po Task #1: `migrate --plan` przechodzi czysto na świeżej bazie.

### 🧠 Czego się nauczysz

- **Cross-app migration** — pole `last_deaths_scraped_at` żyje w `apps/characters/migrations/`, mimo że używa go `apps/deathwatch`. Model należy do `characters` (CLAUDE.md §3). Zwykle Django auto-generuje numerację — `python manage.py makemigrations characters` po edycji `apps/characters/models.py`.
- **`FK(to="characters.Character", on_delete=CASCADE)`** — string form jest lazy, rozwiązuje circular import. `DeathWatch.character` i `WatchedDeathEvent.character` używają lazy ref.
- **`UniqueConstraint` z `name`** — Django 4+ idiom, mirror `BedmageWatch.Meta.constraints` (`apps/bedmages/models.py:21`).
- **`# type: ignore[type-arg]` na admin** — django-stubs runtime trap (memory `feedback_django_stubs_runtime`); ModelAdmin generic subscript wymaga `django_stubs_ext.monkeypatch()` którego projekt nie ma wired up.

### ✅ Acceptance criteria

- `apps/deathwatch/__init__.py`, `apps.py` (`DeathWatchConfig`, label="deathwatch"), `models.py`, `admin.py`, `migrations/__init__.py`.
- `LOCAL_APPS` w `config/settings/base.py` rozszerzone o `"apps.deathwatch"`.
- `DeathWatch` model: 4 pola (`user`, `character`, `created_at auto_now_add`, `active default=True`) + `Meta.constraints` UniqueConstraint(`user`, `character`) + `Meta.ordering=["-created_at"]` + `__str__`.
- `WatchedDeathEvent` model: 6 pól (`character` FK, `level_at_death PositiveIntegerField`, `killed_by TextField blank=True default=""`, `died_at DateTimeField db_index=True`, `scraped_at auto_now_add`, `announced_on_discord BooleanField default=False db_index=True`) + `Meta.constraints` UniqueConstraint(`character`, `died_at`) + `Meta.ordering=["-died_at"]` + `__str__`.
- `DeathWatchChannel` model: 4 pola (`guild_id BigInteger`, `channel_id BigInteger`, `created_at auto_now_add`, `updated_at auto_now`) + `Meta.constraints` UniqueConstraint(`guild_id`) + `__str__`.
- `apps/characters/models.py:Character` ma dodane pole `last_deaths_scraped_at = DateTimeField(null=True, blank=True)`.
- `apps/deathwatch/migrations/0001_initial.py` — auto-generated, fresh.
- `apps/characters/migrations/0007_character_last_deaths_scraped_at.py` — auto-generated.
- `apps/deathwatch/admin.py` — `@admin.register(...)` dla każdego modelu + `list_display` + `list_filter` + `search_fields`. **Bez** generic subscriptu.
- Sanity: `python manage.py migrate --plan` czysto, `python manage.py migrate` przechodzi.

### 📋 TDD steps

- [ ] **Step 1: Branch + scaffold apki**

```bash
git checkout -b feat/<#>-deathwatch-models
mkdir -p apps/deathwatch/migrations apps/deathwatch/management/commands
touch apps/deathwatch/__init__.py
touch apps/deathwatch/migrations/__init__.py
touch apps/deathwatch/management/__init__.py
touch apps/deathwatch/management/commands/__init__.py
```

- [ ] **Step 2: `apps/deathwatch/apps.py`**

```python
from django.apps import AppConfig


class DeathWatchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.deathwatch"
    label = "deathwatch"
```

- [ ] **Step 3: `apps/deathwatch/models.py` — write failing test first**

`tests/unit/deathwatch/test_models.py`:

```python
import pytest
from django.db import IntegrityError
from apps.deathwatch.models import DeathWatch, WatchedDeathEvent, DeathWatchChannel
from apps.characters.models import Character
from apps.accounts.models import User


@pytest.mark.django_db
def test_death_watch_unique_user_character_pair():
    user = User.objects.create(username="alice", discord_id="1")
    character = Character.objects.create(name="Yhral")
    DeathWatch.objects.create(user=user, character=character)
    with pytest.raises(IntegrityError):
        DeathWatch.objects.create(user=user, character=character)


@pytest.mark.django_db
def test_watched_death_event_unique_character_died_at():
    from django.utils import timezone
    character = Character.objects.create(name="Yhral")
    t = timezone.now()
    WatchedDeathEvent.objects.create(character=character, level_at_death=100,
                                     died_at=t, killed_by="dragon")
    with pytest.raises(IntegrityError):
        WatchedDeathEvent.objects.create(character=character, level_at_death=100,
                                         died_at=t, killed_by="dragon")


@pytest.mark.django_db
def test_death_watch_channel_unique_per_guild():
    DeathWatchChannel.objects.create(guild_id=123, channel_id=456)
    with pytest.raises(IntegrityError):
        DeathWatchChannel.objects.create(guild_id=123, channel_id=789)
```

Run: `poetry run pytest tests/unit/deathwatch/test_models.py -v`
Expected: **FAIL** (ModuleNotFoundError — models.py jeszcze nie ma).

- [ ] **Step 4: Implement `apps/deathwatch/models.py`**

```python
from django.conf import settings
from django.db import models


class DeathWatch(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="death_watches",
    )
    character = models.ForeignKey(
        "characters.Character",
        on_delete=models.CASCADE,
        related_name="death_watches",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "character"],
                name="unique_death_watch_per_user_character",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} watching {self.character.name} for deaths"


class WatchedDeathEvent(models.Model):
    character = models.ForeignKey(
        "characters.Character",
        on_delete=models.CASCADE,
        related_name="watched_deaths",
    )
    level_at_death = models.PositiveIntegerField()
    killed_by = models.TextField(blank=True, default="")
    died_at = models.DateTimeField(db_index=True)
    scraped_at = models.DateTimeField(auto_now_add=True)
    announced_on_discord = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-died_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["character", "died_at"],
                name="unique_watched_death_per_character_time",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.character.name} (lvl {self.level_at_death}) "
            f"@ {self.died_at:%Y-%m-%d %H:%M}"
        )


class DeathWatchChannel(models.Model):
    guild_id = models.BigIntegerField()
    channel_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["guild_id"],
                name="deathwatch_channel_one_per_guild",
            ),
        ]

    def __str__(self) -> str:
        return f"DeathWatchChannel guild={self.guild_id} channel={self.channel_id}"
```

- [ ] **Step 5: Edit `apps/characters/models.py` — dodać `last_deaths_scraped_at`**

Znajdź `Character` model, dodaj pole po `last_scraped_at`:

```python
last_deaths_scraped_at = models.DateTimeField(null=True, blank=True)
```

- [ ] **Step 6: Rejestracja apki**

Edytuj `config/settings/base.py`, w `LOCAL_APPS` dodaj `"apps.deathwatch"` po `"apps.bedmages"`.

- [ ] **Step 7: Generate migrations**

```bash
poetry run python manage.py makemigrations deathwatch characters
```

Expected output: tworzy `apps/deathwatch/migrations/0001_initial.py` + `apps/characters/migrations/0007_character_last_deaths_scraped_at.py`.

- [ ] **Step 8: Run tests — expected PASS**

```bash
poetry run python manage.py migrate
poetry run pytest tests/unit/deathwatch/test_models.py -v
```

Expected: **PASS** (3 tests green).

- [ ] **Step 9: `apps/deathwatch/admin.py`**

```python
from django.contrib import admin
from apps.deathwatch.models import DeathWatch, WatchedDeathEvent, DeathWatchChannel


@admin.register(DeathWatch)
class DeathWatchAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("user", "character", "active", "created_at")
    list_filter = ("active",)
    search_fields = ("user__username", "character__name")


@admin.register(WatchedDeathEvent)
class WatchedDeathEventAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("character", "level_at_death", "died_at", "announced_on_discord")
    list_filter = ("announced_on_discord",)
    search_fields = ("character__name", "killed_by")


@admin.register(DeathWatchChannel)
class DeathWatchChannelAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("guild_id", "channel_id", "updated_at")
```

- [ ] **Step 10: Smoke**

```bash
poetry run python manage.py shell -c "from apps.deathwatch.models import DeathWatch, WatchedDeathEvent, DeathWatchChannel; print(DeathWatch._meta.constraints, WatchedDeathEvent._meta.constraints, DeathWatchChannel._meta.constraints)"
```

Expected: lista 3 UniqueConstraintów wypisana bez błędu.

- [ ] **Step 11: Pre-commit + commit + PR**

```bash
poetry run pre-commit run --all-files
git add apps/deathwatch apps/characters/models.py apps/characters/migrations/0007_* config/settings/base.py tests/unit/deathwatch/
git commit -m "feat(deathwatch): add models + admin + Character.last_deaths_scraped_at (DW-1, #<issue>)"
git push -u origin feat/<#>-deathwatch-models
gh pr create --title "feat(deathwatch): add models + admin + Character.last_deaths_scraped_at (DW-1)" --body "Closes #<issue>. See spec §2 W scope first bullet, §5.1."
```

### ⚠️ Pułapki

- **A — `Character.last_deaths_scraped_at` migracja w `apps/characters/`, nie `apps/deathwatch/`** — model należy do characters; deathwatch tylko z niego korzysta. Inaczej dependency loop w migrations resolver.
- **B — `# type: ignore[type-arg]` na `ModelAdmin`** — memory `feedback_django_stubs_runtime`; bez tego `ModelAdmin[Foo]` runtime crash gdy `django_stubs_ext.monkeypatch()` nie jest wired up (a nie jest).
- **C — `FK to="characters.Character"` string form** — direct import `from apps.characters.models import Character` w `apps/deathwatch/models.py` zadziała, ale string form bezpieczniejszy przy ewentualnym swap app structure. Mirror `apps/bedmages/models.py:12`.
- **D — `auto_now_add=True` w testach** — testy filtru "po dodaniu" w Task #2 nie mogą force `created_at` przez `objects.create(created_at=...)`. Workaround: `DeathWatch.objects.filter(pk=...).update(created_at=...)`.

### 🧪 Testing plan

Unit `tests/unit/deathwatch/test_models.py` (3 testy w Step 3) + sanity migrate.

### 📦 Definition of Done

- [ ] 3 modele + admin + 2 migracje commitowane.
- [ ] `migrate` zielony na świeżej bazie.
- [ ] 3 unit testy passing.
- [ ] Pre-commit zielony.
- [ ] PR zmergowany squash.

---

## Task #2 — [DW-2] Services + types

### 🎯 Cel

6 funkcji biznesowych w `apps/deathwatch/services.py` + `apps/deathwatch/types.py` z TypedDictami. Bez integracji z handlerem (DW-6 dorzuca handler call w `notify_watched_deaths_for_character`) ani Discord cog (DW-7). Full unit coverage.

### 🧠 Czego się nauczysz

- **Atomicity przeciwko cap race** — `transaction.atomic()` block wokół `get_or_create + count + rollback`. Naive check-then-create jest TOCTOU.
- **`_canonicalize_name` reuse** z `apps.characters.models` — single source of truth dla canonicalize, audytowany w `feedback_canonicalization_downstream_audit` memory.
- **`exists()` na filtered QuerySet** — `DeathWatch.objects.filter(...).exists()` jest cheap (LIMIT 1), nie pobiera obiektów. Używany w filtrze "po dodaniu" w `record_watched_death`.
- **Pipeline-side service contract** — service'y w `apps.deathwatch.services` są wywoływane z dwóch contextów: (a) Discord cog / GraphQL (DB transaction), (b) Scrapy pipeline (poza Django request cycle). Druga ścieżka musi być self-contained — żadnych `request.user`, żadnego `transaction.on_commit` zależnego od view'u.

### ✅ Acceptance criteria

- `apps/deathwatch/types.py` z 2 TypedDictami:
  - `DeathWatchPayload(id, character_name, created_at, active)`.
  - `WatchedDeathPayload(id, character_name, level_at_death, killed_by, died_at, announced_on_discord)`.
- `apps/deathwatch/services.py` z 6 funkcjami (signatures dokładnie jak spec §2 W scope):
  - `add_death_watch(user, character_name) → DeathWatch` (cap check w atomic, canonicalize, reactivate).
  - `remove_death_watch(user, character_name) → bool` (hard delete, idempotent).
  - `list_death_watches(user) → QuerySet[DeathWatch]` (select_related character, order by -created_at).
  - `set_deathwatch_channel_for_guild(guild_id, channel_id) → DeathWatchChannel` (update_or_create).
  - `record_watched_death(item: dict) → WatchedDeathEvent | None` (validate Character, filter "po dodaniu", get_or_create event).
  - `notify_watched_deaths_for_character(character) → int` — **stub w DW-2**, `# TODO DW-6: handler.announce()`, return 0. Real implementation w DW-6.
- `DEATHWATCH_MAX_WATCHED_CHARACTERS=20` w `config/settings/base.py` + `.env.example`.
- ≥ 10 unit testów covering happy paths + edge cases (cap race, canonicalize, reactivate, idempotent delete, "po dodaniu" filter, missing Character drop).

### 📋 TDD steps

- [ ] **Step 1: Branch**

```bash
git checkout master && git pull
git checkout -b feat/<#>-deathwatch-services
```

- [ ] **Step 2: Settings**

W `config/settings/base.py` dodaj:

```python
DEATHWATCH_MAX_WATCHED_CHARACTERS = env.int("DEATHWATCH_MAX_WATCHED_CHARACTERS", default=20)
```

W `.env.example` dodaj:

```
DEATHWATCH_MAX_WATCHED_CHARACTERS=20
```

- [ ] **Step 3: `apps/deathwatch/types.py`**

```python
from typing import TypedDict
from datetime import datetime


class DeathWatchPayload(TypedDict):
    id: int
    character_name: str
    created_at: datetime
    active: bool


class WatchedDeathPayload(TypedDict):
    id: int
    character_name: str
    level_at_death: int
    killed_by: str
    died_at: datetime
    announced_on_discord: bool
```

- [ ] **Step 4: Write failing tests dla `add_death_watch`**

`tests/unit/deathwatch/test_services.py`:

```python
import pytest
from django.db import IntegrityError
from django.test import override_settings
from apps.deathwatch.services import (
    add_death_watch, remove_death_watch, list_death_watches,
    set_deathwatch_channel_for_guild, record_watched_death,
)
from apps.deathwatch.models import DeathWatch, WatchedDeathEvent, DeathWatchChannel
from apps.characters.models import Character
from apps.accounts.models import User


@pytest.mark.django_db
def test_add_death_watch_creates_character_lazy():
    user = User.objects.create(username="alice", discord_id="1")
    watch = add_death_watch(user, "Yhral")
    assert watch.character.name == "Yhral"
    assert Character.objects.filter(name="Yhral").exists()


@pytest.mark.django_db
def test_add_death_watch_canonicalizes_name():
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "  yhral  ")
    assert Character.objects.filter(name="Yhral").exists()


@pytest.mark.django_db
def test_add_death_watch_raises_on_active_duplicate():
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")
    with pytest.raises(ValueError):
        add_death_watch(user, "Yhral")


@pytest.mark.django_db
def test_add_death_watch_reactivates_inactive():
    user = User.objects.create(username="alice", discord_id="1")
    watch = add_death_watch(user, "Yhral")
    watch.active = False
    watch.save()
    re_watch = add_death_watch(user, "Yhral")
    assert re_watch.active is True
    assert re_watch.pk == watch.pk


@pytest.mark.django_db
@override_settings(DEATHWATCH_MAX_WATCHED_CHARACTERS=2)
def test_add_death_watch_cap_exceeded_raises():
    u1 = User.objects.create(username="alice", discord_id="1")
    u2 = User.objects.create(username="bob", discord_id="2")
    add_death_watch(u1, "Yhral")
    add_death_watch(u2, "Bubble")
    with pytest.raises(ValueError, match="cap"):
        add_death_watch(u1, "Eternal Oblivion")  # 3rd unique character


@pytest.mark.django_db
@override_settings(DEATHWATCH_MAX_WATCHED_CHARACTERS=2)
def test_add_death_watch_cap_counts_unique_characters_not_watches():
    u1 = User.objects.create(username="alice", discord_id="1")
    u2 = User.objects.create(username="bob", discord_id="2")
    add_death_watch(u1, "Yhral")
    add_death_watch(u2, "Yhral")  # same character, OK
    add_death_watch(u1, "Bubble")  # 2nd unique, OK
    with pytest.raises(ValueError):
        add_death_watch(u2, "Eternal Oblivion")  # 3rd unique, fail
```

Run: `poetry run pytest tests/unit/deathwatch/test_services.py -v`
Expected: **FAIL** (ImportError — services.py nie istnieje).

- [ ] **Step 5: Implement `apps/deathwatch/services.py` — add/remove/list/channel**

```python
import logging
from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet

from apps.deathwatch.models import DeathWatch, WatchedDeathEvent, DeathWatchChannel
from apps.characters.models import Character, _canonicalize_name
from apps.accounts.models import User

logger = logging.getLogger(__name__)


def add_death_watch(user: User, character_name: str) -> DeathWatch:
    """Add DeathWatch for user+character with global cap check.

    Cap check is post-create + rollback inside `transaction.atomic()` —
    naive pre-check is TOCTOU.
    """
    character_name = _canonicalize_name(character_name)

    with transaction.atomic():
        character, _ = Character.objects.get_or_create(name=character_name)
        watch, created = DeathWatch.objects.get_or_create(
            user=user, character=character, defaults={"active": True}
        )

        if not created and watch.active:
            raise ValueError(
                f"DeathWatch for {character_name!r} already active for user "
                f"{user.username!r}"
            )
        if not created and not watch.active:
            watch.active = True
            watch.save(update_fields=["active"])

        cap = settings.DEATHWATCH_MAX_WATCHED_CHARACTERS
        unique_count = (
            DeathWatch.objects.filter(active=True)
            .values("character_id").distinct().count()
        )
        if unique_count > cap:
            raise ValueError(
                f"DeathWatch cap of {cap} unique characters exceeded "
                f"(current: {unique_count})"
            )

    return watch


def remove_death_watch(user: User, character_name: str) -> bool:
    """Hard delete DeathWatch. Idempotent — returns False if not found."""
    character_name = _canonicalize_name(character_name)
    deleted, _ = DeathWatch.objects.filter(
        user=user, character__name=character_name
    ).delete()
    return deleted > 0


def list_death_watches(user: User) -> QuerySet[DeathWatch]:
    """List user's watches, newest first, with Character preloaded."""
    return (
        DeathWatch.objects.filter(user=user)
        .select_related("character")
        .order_by("-created_at")
    )


def set_deathwatch_channel_for_guild(
    guild_id: int, channel_id: int
) -> DeathWatchChannel:
    """Upsert announcement channel for guild."""
    channel, _ = DeathWatchChannel.objects.update_or_create(
        guild_id=guild_id, defaults={"channel_id": channel_id}
    )
    return channel
```

- [ ] **Step 6: Run partial tests**

```bash
poetry run pytest tests/unit/deathwatch/test_services.py -v -k "add_death_watch or remove or list"
```

Expected: 6 first tests PASS.

- [ ] **Step 7: Write failing tests dla `record_watched_death`**

Dopisz do `test_services.py`:

```python
@pytest.mark.django_db
def test_record_watched_death_creates_when_died_at_after_watch_created_at():
    from django.utils import timezone
    from datetime import timedelta

    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")
    watch = DeathWatch.objects.get(user=user)
    # Force created_at backward via update (auto_now_add bypass)
    DeathWatch.objects.filter(pk=watch.pk).update(
        created_at=timezone.now() - timedelta(hours=1)
    )

    item = {
        "character_name": "Yhral",
        "level_at_death": 128,
        "killed_by": "a giant crayfish",
        "died_at": timezone.now(),
    }
    event = record_watched_death(item)
    assert event is not None
    assert event.character.name == "Yhral"
    assert event.level_at_death == 128


@pytest.mark.django_db
def test_record_watched_death_drops_when_died_before_watch_created_at():
    from django.utils import timezone
    from datetime import timedelta

    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")

    item = {
        "character_name": "Yhral",
        "level_at_death": 128,
        "killed_by": "a dragon",
        "died_at": timezone.now() - timedelta(hours=1),  # before watch.created_at
    }
    event = record_watched_death(item)
    assert event is None
    assert not WatchedDeathEvent.objects.exists()


@pytest.mark.django_db
def test_record_watched_death_drops_when_no_active_watch():
    from django.utils import timezone

    Character.objects.create(name="Yhral")  # exists but no watch
    item = {
        "character_name": "Yhral",
        "level_at_death": 128,
        "killed_by": "a dragon",
        "died_at": timezone.now(),
    }
    assert record_watched_death(item) is None
    assert not WatchedDeathEvent.objects.exists()


@pytest.mark.django_db
def test_record_watched_death_deduplicates_via_unique_constraint():
    from django.utils import timezone
    from datetime import timedelta

    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")
    DeathWatch.objects.filter(user=user).update(
        created_at=timezone.now() - timedelta(hours=1)
    )

    t = timezone.now()
    item = {"character_name": "Yhral", "level_at_death": 128,
            "killed_by": "x", "died_at": t}
    e1 = record_watched_death(item)
    e2 = record_watched_death(item)  # same died_at → dedup
    assert e1 is not None
    assert e2 is None  # already exists
    assert WatchedDeathEvent.objects.count() == 1


@pytest.mark.django_db
def test_record_watched_death_drops_when_character_missing():
    from django.utils import timezone
    item = {"character_name": "Ghost", "level_at_death": 1,
            "killed_by": "x", "died_at": timezone.now()}
    assert record_watched_death(item) is None
```

Run: expected FAIL (record_watched_death nie istnieje).

- [ ] **Step 8: Implement `record_watched_death`**

W `apps/deathwatch/services.py` dopisz:

```python
def record_watched_death(item: dict) -> WatchedDeathEvent | None:
    """Pipeline-side: persist event if it qualifies for any active watch.

    Drops when:
    - Character doesn't exist (abnormal — spider should not yield items for
      unknown chars in normal flow; defensive).
    - No active DeathWatch with created_at < died_at (history before add or
      no watcher).
    - Event already exists (unique constraint hit).
    """
    character_name = _canonicalize_name(item["character_name"])
    try:
        character = Character.objects.get(name=character_name)
    except Character.DoesNotExist:
        logger.warning(
            "record_watched_death: Character %r missing, dropping item",
            character_name,
        )
        return None

    died_at = item["died_at"]
    qualifies = DeathWatch.objects.filter(
        character=character, active=True, created_at__lt=died_at
    ).exists()
    if not qualifies:
        return None

    event, created = WatchedDeathEvent.objects.get_or_create(
        character=character,
        died_at=died_at,
        defaults={
            "level_at_death": item["level_at_death"],
            "killed_by": item.get("killed_by", ""),
        },
    )
    return event if created else None


def notify_watched_deaths_for_character(character: Character) -> int:
    """Iterate channels × pending events, dispatch via handler.

    DW-2 stub: returns 0. DW-6 will plug in DeathWatchAnnouncementHandler.
    """
    # TODO(DW-6): wire up handler.announce() with multi-channel flag-set logic
    return 0
```

- [ ] **Step 9: Run all service tests**

```bash
poetry run pytest tests/unit/deathwatch/test_services.py -v
```

Expected: **PASS** (all 11 tests).

- [ ] **Step 10: Mypy + ruff**

```bash
poetry run mypy apps/deathwatch
poetry run ruff check apps/deathwatch tests/unit/deathwatch
poetry run ruff format apps/deathwatch tests/unit/deathwatch
```

- [ ] **Step 11: Commit + PR**

```bash
git add apps/deathwatch/services.py apps/deathwatch/types.py config/settings/base.py .env.example tests/unit/deathwatch/test_services.py
git commit -m "feat(deathwatch): add services + types + cap setting (DW-2, #<issue>)"
git push -u origin feat/<#>-deathwatch-services
gh pr create --title "feat(deathwatch): services + types (DW-2)" --body "Closes #<issue>. See spec §2, §3.6, §3.7, §3.8."
```

### ⚠️ Pułapki

- **A — `_canonicalize_name` jest źródłem prawdy** — memory `feedback_canonicalization_downstream_audit`. Każda service func która przyjmuje `character_name` musi go zawołać. Discord cog / GraphQL nie wołają go bezpośrednio — przechodzą przez services.
- **B — Cap counts unique characters, not watches** — 2 userów obserwujących Yhral'a + Bubble = 2 unikalne characters, nie 4 watche. Spec §3.2.
- **C — `auto_now_add` bypass w testach** — `DeathWatch.objects.filter(pk=...).update(created_at=...)` jedyna droga do force timestamp w przeszłość.
- **D — `notify_watched_deaths_for_character` jest stubem w DW-2** — DW-6 wymieni implementację. Pozostaw `TODO(DW-6)` comment + return 0.

### 🧪 Testing plan

11 unit testów (Step 4 + Step 7) — covers happy paths + 6 edge cases.

### 📦 Definition of Done

- [ ] 6 service functions implemented (5 real + 1 stub).
- [ ] 11 unit tests PASS.
- [ ] `DEATHWATCH_MAX_WATCHED_CHARACTERS=20` w base.py + .env.example.
- [ ] Mypy + ruff clean.
- [ ] PR zmergowany.

---

## Task #3 — [DW-3] Spider + fixture HTML + management command + date utils refactor

### 🎯 Cel

`CharacterDeathsSpider` parsujący sekcję "Latest Deaths" + fixture HTML zwalidowany na ręcznie zgranej stronie + management command `scrape_character_deaths <name>` + refactor `_parse_last_login` z `character_spider.py` do `scrapers/.../utils/dates.py`. Spider sam w sobie nie pisze do DB — emituje `CharacterDeathItem`, pipeline route w DW-4.

### 🧠 Czego się nauczysz

- **Scrapy spider testing without live HTTP** — `scrapy.http.HtmlResponse(url=..., body=fixture_bytes)` + spider.parse(response) zwraca generator items. Standard pattern, CLAUDE.md §15.6 wymaga.
- **`zoneinfo` dla `Europe/Berlin` parsing** — Tibiantis pokazuje "CEST"/"CET" suffix, ale `datetime.strptime` ich nie rozumie. Wzorzec z `character_spider._parse_last_login`: split string, ZoneInfo("Europe/Berlin") handles DST automatycznie.
- **`CrawlerRunner + crochet` w management command** — wzorzec z `apps/characters/management/commands/scrape_character.py`. `CrawlerProcess` blokuje Twisted reactor przy 2nd użyciu, `CrawlerRunner` z crochet jest reactor-friendly.

### ✅ Acceptance criteria

- `scrapers/tibiantis_scrapers/utils/__init__.py` + `utils/dates.py` z `parse_tibiantis_timestamp(raw: str) -> datetime | None` (signature kompatybilny z istniejącym `_parse_last_login`).
- `scrapers/tibiantis_scrapers/spiders/character_spider.py` zrefactorowany — `_parse_last_login` deleguje do `utils.dates.parse_tibiantis_timestamp`. Stara funkcja zostaje jako thin wrapper LUB jest deletowana i call sites updated.
- `scrapers/tibiantis_scrapers/items.py` — dodać `CharacterDeathItem` z polami: `character_name`, `level_at_death`, `killed_by`, `died_at`.
- `scrapers/tibiantis_scrapers/spiders/character_deaths_spider.py` — `name="character_deaths"`, accepts `-a name=...`, parsuje "Latest Deaths" section, yields `CharacterDeathItem[]`.
- `tests/fixtures/tibiantis_online/character_with_deaths.html` — ręcznie zgrany snapshot strony postaci z **przynajmniej 2 deaths** w tabeli + jeden case z `unknown` killer.
- `apps/deathwatch/management/commands/scrape_character_deaths.py` — mirror `apps/characters/management/commands/scrape_character.py`.
- Unit testy spidera na fixturce HTML (3+ asercje).

### 📋 TDD steps

- [ ] **Step 1: Branch + zgrać fixture**

```bash
git checkout master && git pull
git checkout -b feat/<#>-deathwatch-spider
mkdir -p tests/fixtures/tibiantis_online
```

Ręcznie:
1. Otwórz `https://tibiantis.online/?page=character&name=Yhral` (lub inna postać z deaths).
2. View source → save jako `tests/fixtures/tibiantis_online/character_with_deaths.html`.
3. Sprawdź że sekcja "Latest Deaths" zawiera ≥2 wiersze.
4. Optional: wytnij script/style tagi żeby zmniejszyć rozmiar fixturce.

- [ ] **Step 2: Write failing test dla date utility**

`tests/unit/scrapers/test_dates.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from scrapers.tibiantis_scrapers.utils.dates import parse_tibiantis_timestamp


def test_parse_tibiantis_timestamp_cest():
    raw = "07 May 2026 16:15:46 CEST"
    result = parse_tibiantis_timestamp(raw)
    expected = datetime(2026, 5, 7, 16, 15, 46, tzinfo=ZoneInfo("Europe/Berlin"))
    assert result == expected


def test_parse_tibiantis_timestamp_cet():
    raw = "10 Dec 2025 22:00:00 CET"
    result = parse_tibiantis_timestamp(raw)
    expected = datetime(2025, 12, 10, 22, 0, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    assert result == expected


def test_parse_tibiantis_timestamp_never_returns_none():
    assert parse_tibiantis_timestamp("never") is None
    assert parse_tibiantis_timestamp("") is None
```

Expected: FAIL (utils/dates.py nie istnieje).

- [ ] **Step 3: Implement `scrapers/tibiantis_scrapers/utils/dates.py`**

```python
from datetime import datetime
from zoneinfo import ZoneInfo


def parse_tibiantis_timestamp(raw: str) -> datetime | None:
    """Parse Tibiantis "DD MMM YYYY HH:MM:SS CEST/CET" timestamp to TZ-aware datetime.

    Tibiantis displays Europe/Berlin time. ZoneInfo handles DST.
    Returns None for "never" / empty input.
    """
    if not raw or "never" in raw.lower():
        return None
    naive_part, _tz = raw.rsplit(" ", 1)  # drop "CEST"/"CET" suffix
    dt = datetime.strptime(naive_part, "%d %b %Y %H:%M:%S")
    return dt.replace(tzinfo=ZoneInfo("Europe/Berlin"))
```

- [ ] **Step 4: Refactor `character_spider.py` do reuse**

Edit `scrapers/tibiantis_scrapers/spiders/character_spider.py`:

```python
import scrapy
from datetime import datetime  # noqa: F401  # may stay if still used elsewhere
from scrapers.tibiantis_scrapers.items import CharacterItem
from scrapers.tibiantis_scrapers.utils.dates import parse_tibiantis_timestamp


class CharacterSpider(scrapy.Spider):
    name = "character"

    def __init__(self, name=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not name:
            raise ValueError("CharacterSpider requires -a name=<character>")
        self.character_name = name
        self.start_urls = [f"https://tibiantis.online/?page=character&name={name}"]

    def _parse_last_login(self, raw: str) -> datetime | None:
        return parse_tibiantis_timestamp(raw)

    def parse(self, response):
        # ... unchanged
```

Run test for utility:

```bash
poetry run pytest tests/unit/scrapers/test_dates.py -v
```

Expected: PASS.

- [ ] **Step 5: Existing character_spider tests still pass**

```bash
poetry run pytest tests/unit/scrapers/ -v
```

Expected: PASS (no regression).

- [ ] **Step 6: Add `CharacterDeathItem` do items.py**

`scrapers/tibiantis_scrapers/items.py` — dopisz:

```python
class CharacterDeathItem(scrapy.Item):
    character_name = scrapy.Field()
    level_at_death = scrapy.Field()
    killed_by = scrapy.Field()
    died_at = scrapy.Field()
```

- [ ] **Step 7: Write failing test dla CharacterDeathsSpider**

`tests/unit/deathwatch/test_spider.py`:

```python
from pathlib import Path
from scrapy.http import HtmlResponse, Request
from scrapers.tibiantis_scrapers.spiders.character_deaths_spider import (
    CharacterDeathsSpider,
)


def _load_fixture(name: str) -> bytes:
    path = Path(__file__).parent.parent.parent / "fixtures" / "tibiantis_online" / name
    return path.read_bytes()


def test_spider_yields_items_for_each_death_row():
    body = _load_fixture("character_with_deaths.html")
    spider = CharacterDeathsSpider(name="Yhral")
    request = Request(url="https://tibiantis.online/?page=character&name=Yhral")
    response = HtmlResponse(url=request.url, body=body, encoding="utf-8",
                            request=request)
    items = list(spider.parse(response))
    assert len(items) >= 2  # fixture has 2+ deaths
    for item in items:
        assert item["character_name"] == "Yhral"
        assert isinstance(item["level_at_death"], int)
        assert item["level_at_death"] > 0
        assert item["died_at"] is not None
        # killed_by may be empty string but must exist
        assert "killed_by" in item


def test_spider_parses_died_at_as_europe_berlin_tz():
    from zoneinfo import ZoneInfo
    body = _load_fixture("character_with_deaths.html")
    spider = CharacterDeathsSpider(name="Yhral")
    response = HtmlResponse(url="https://x/", body=body, encoding="utf-8")
    items = list(spider.parse(response))
    assert items[0]["died_at"].tzinfo == ZoneInfo("Europe/Berlin")


def test_spider_requires_name_arg():
    import pytest
    with pytest.raises(ValueError):
        CharacterDeathsSpider()
```

Expected: FAIL (spider nie istnieje).

- [ ] **Step 8: Implement `character_deaths_spider.py`**

`scrapers/tibiantis_scrapers/spiders/character_deaths_spider.py`:

```python
import re
import scrapy

from scrapers.tibiantis_scrapers.items import CharacterDeathItem
from scrapers.tibiantis_scrapers.utils.dates import parse_tibiantis_timestamp


class CharacterDeathsSpider(scrapy.Spider):
    name = "character_deaths"

    def __init__(self, name=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not name:
            raise ValueError(
                "CharacterDeathsSpider requires -a name=<character>"
            )
        self.character_name = name
        self.start_urls = [
            f"https://tibiantis.online/?page=character&name={name}"
        ]

    def parse(self, response):
        # Selektor zwalidowany na fixture HTML:
        # tabela pod nagłówkiem "Latest Deaths" w divie .box.
        rows = response.xpath(
            '//table[preceding::*[contains(text(),"Latest Deaths")][1]]'
            '//tr[position()>1]'
        )
        if not rows:
            self.logger.warning(
                "No Latest Deaths rows for %s", self.character_name
            )
            return

        for row in rows:
            timestamp_raw = row.css("td:nth-child(1)::text").get("").strip()
            death_text = " ".join(
                row.css("td:nth-child(2) ::text").getall()
            ).strip()

            died_at = parse_tibiantis_timestamp(timestamp_raw)
            if died_at is None:
                continue

            level, killer = self._parse_death_text(death_text)

            item = CharacterDeathItem()
            item["character_name"] = self.character_name
            item["died_at"] = died_at
            item["level_at_death"] = level
            item["killed_by"] = killer
            yield item

    @staticmethod
    def _parse_death_text(text: str) -> tuple[int, str]:
        """Parse "Killed at Level 128 by a giant crayfish." into (128, 'a giant crayfish').

        Returns (0, '') if pattern doesn't match — defensive, logged upstream.
        """
        match = re.match(
            r"Killed at Level (\d+)(?: by (.+?))?\.?$",
            text.strip(),
        )
        if not match:
            return 0, ""
        level = int(match.group(1))
        killer = (match.group(2) or "").strip()
        return level, killer
```

- [ ] **Step 9: Run spider tests**

```bash
poetry run pytest tests/unit/deathwatch/test_spider.py -v
```

Expected: PASS (3 tests).

**Jeśli FAIL** — selektor XPath nie matchuje fixturce. Otwórz fixture, sprawdź gdzie żyje "Latest Deaths" heading, dostosuj XPath. To naturalna iteracja, NIE bug planu.

- [ ] **Step 10: Management command**

`apps/deathwatch/management/commands/scrape_character_deaths.py`:

```python
from django.core.management.base import BaseCommand, CommandError
from scrapy.crawler import CrawlerRunner
from scrapy.utils.project import get_project_settings
from crochet import setup as crochet_setup, wait_for

crochet_setup()


class Command(BaseCommand):
    help = "Scrape Latest Deaths section for a character (tibiantis.online)."

    def add_arguments(self, parser):
        parser.add_argument("name", type=str, help="Character name")

    def handle(self, *args, **options):
        name = options["name"]
        try:
            self._run_crawler(name)
        except Exception as exc:
            raise CommandError(f"scrape_character_deaths failed: {exc}") from exc

    @wait_for(timeout=60.0)
    def _run_crawler(self, name: str):
        settings = get_project_settings()
        runner = CrawlerRunner(settings)
        return runner.crawl("character_deaths", name=name)
```

- [ ] **Step 11: Smoke management command (jeśli network dostępny)**

```bash
poetry run python manage.py scrape_character_deaths Yhral
```

Expected: 0 exit code, log z liczbą items. NIE blokuje testów CI jeśli sieć offline — skip ten step w CI environment.

- [ ] **Step 12: Pre-commit + commit + PR**

```bash
poetry run pre-commit run --all-files
git add scrapers/tibiantis_scrapers/utils scrapers/tibiantis_scrapers/items.py scrapers/tibiantis_scrapers/spiders apps/deathwatch/management tests/fixtures/tibiantis_online tests/unit/deathwatch/test_spider.py tests/unit/scrapers/test_dates.py
git commit -m "feat(deathwatch): add CharacterDeathsSpider + date utils refactor (DW-3, #<issue>)"
git push -u origin feat/<#>-deathwatch-spider
gh pr create --title "feat(deathwatch): spider + date utils (DW-3)" --body "Closes #<issue>. See spec §2, §3.6."
```

### ⚠️ Pułapki

- **A — XPath selektor jest fragile** — Tibiantis może zmienić HTML. Fixture musi być dokładny snapshot rzeczywistej strony, nie wyobrażony markup. Test musi failować, nie passować "by accident".
- **B — `Europe/Berlin` vs `UTC` w DB** — Spider emituje tz-aware datetime z `Europe/Berlin`. Django automatycznie konwertuje do UTC przy save (USE_TZ=True). Display w embed w DW-6 konwertuje obratnie do Europe/Warsaw.
- **C — Reactor restart w testach** — testy spidera używają `HtmlResponse` (in-memory), NIE `CrawlerProcess`. Nie ma reactor issue.
- **D — `re.match` regex levelu/killera** — fixture może mieć formaty inne niż "Killed at Level X by Y." np. "Died at Level X" lub bez "by". Sprawdź fixture i dostosuj regex. Defensywne `(0, '')` przy non-match + log warning na pipeline-side.

### 🧪 Testing plan

- 3 testy date utils (test_dates.py).
- 3 testy spider (test_spider.py).
- Smoke management command (manual, nie CI).

### 📦 Definition of Done

- [ ] Date utils + refactor + 3 testy.
- [ ] Fixture HTML committed.
- [ ] Spider + 3 testy.
- [ ] Management command + smoke (manual).
- [ ] Pre-commit zielony.
- [ ] PR zmergowany.

---

## Task #4 — [DW-4] Pipeline route + `record_watched_death` integration

### 🎯 Cel

Pipeline `scrapers/.../pipelines.py` rozpoznaje `CharacterDeathItem` i wywołuje `apps.deathwatch.services.record_watched_death(dict(item))`. Pipeline NIE pisze do ORM bezpośrednio (CLAUDE.md §6). E2E integration test: fixture HTML → spider → pipeline → DB.

### 🧠 Czego się nauczysz

- **`isinstance(item, CharacterDeathItem)` dispatch** — pipelines.py ma już branch dla `CharacterItem`. Dodajemy drugi branch, NIE zastępujemy.
- **`dict(item)` conversion** — Scrapy Item wspiera dict-like access, ale services przyjmują `dict`, nie Item. Konwersja explicit dla type clarity.
- **E2E test bez Twisted reactora** — `scrapy.crawler.CrawlerProcess` ma reactor restart issue. Test pipeline E2E: instancja pipeline'a + manualne wywołanie `process_item()` z fixture-derived items.

### ✅ Acceptance criteria

- `scrapers/tibiantis_scrapers/pipelines.py` ma nowy branch:
  ```python
  if isinstance(item, CharacterDeathItem):
      from apps.deathwatch.services import record_watched_death
      record_watched_death(dict(item))
      return item
  ```
- Integration test `tests/integration/deathwatch/test_pipeline.py` — full flow: fixture → spider yields items → pipeline.process_item() → DB has events / drops correctly.

### 📋 TDD steps

- [ ] **Step 1: Branch**

```bash
git checkout master && git pull
git checkout -b feat/<#>-deathwatch-pipeline
```

- [ ] **Step 2: Write failing integration test**

`tests/integration/deathwatch/test_pipeline.py`:

```python
import pytest
from pathlib import Path
from datetime import timedelta
from django.utils import timezone
from scrapy.http import HtmlResponse

from scrapers.tibiantis_scrapers.spiders.character_deaths_spider import (
    CharacterDeathsSpider,
)
from scrapers.tibiantis_scrapers.pipelines import TibiantisScrapersPipeline
from apps.deathwatch.models import DeathWatch, WatchedDeathEvent
from apps.deathwatch.services import add_death_watch
from apps.characters.models import Character
from apps.accounts.models import User


def _load_fixture() -> bytes:
    return (
        Path(__file__).parent.parent.parent
        / "fixtures" / "tibiantis_online" / "character_with_deaths.html"
    ).read_bytes()


@pytest.mark.django_db
def test_pipeline_persists_event_for_active_watch_with_past_created_at():
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")
    # Force watch's created_at far back so all fixture deaths qualify
    DeathWatch.objects.filter(user=user).update(
        created_at=timezone.now() - timedelta(days=365)
    )

    spider = CharacterDeathsSpider(name="Yhral")
    response = HtmlResponse(url="https://x/", body=_load_fixture(), encoding="utf-8")
    pipeline = TibiantisScrapersPipeline()

    items = list(spider.parse(response))
    assert len(items) >= 2
    for item in items:
        pipeline.process_item(item, spider)

    assert WatchedDeathEvent.objects.filter(character__name="Yhral").count() >= 2


@pytest.mark.django_db
def test_pipeline_drops_when_no_watch():
    Character.objects.create(name="Yhral")  # exists, no watch
    spider = CharacterDeathsSpider(name="Yhral")
    response = HtmlResponse(url="https://x/", body=_load_fixture(), encoding="utf-8")
    pipeline = TibiantisScrapersPipeline()

    for item in spider.parse(response):
        pipeline.process_item(item, spider)

    assert not WatchedDeathEvent.objects.exists()
```

Expected: FAIL (pipeline still routes only CharacterItem).

**Note on pipeline class name:** sprawdź `scrapers/tibiantis_scrapers/pipelines.py` — może być inna nazwa klasy. Adjust import.

- [ ] **Step 3: Edit pipeline**

`scrapers/tibiantis_scrapers/pipelines.py`:

```python
# Existing CharacterItem branch...

from scrapers.tibiantis_scrapers.items import CharacterItem, CharacterDeathItem


class TibiantisScrapersPipeline:
    def process_item(self, item, spider):
        if isinstance(item, CharacterDeathItem):
            from apps.deathwatch.services import record_watched_death
            record_watched_death(dict(item))
            return item

        # Existing CharacterItem branch — unchanged
        if isinstance(item, CharacterItem):
            # ... existing logic
            return item

        return item
```

**Note:** `from apps...` import jest lazy (wewnątrz metody), żeby uniknąć Django import-at-load-time issues w Scrapy proces.

- [ ] **Step 4: Run integration tests**

```bash
poetry run pytest tests/integration/deathwatch/test_pipeline.py -v
```

Expected: PASS.

- [ ] **Step 5: Run cały test suite, sprawdź brak regression**

```bash
poetry run pytest -v
```

Expected: cały suite PASS.

- [ ] **Step 6: Pre-commit + commit + PR**

```bash
poetry run pre-commit run --all-files
git add scrapers/tibiantis_scrapers/pipelines.py tests/integration/deathwatch/
git commit -m "feat(deathwatch): pipeline route for CharacterDeathItem (DW-4, #<issue>)"
git push -u origin feat/<#>-deathwatch-pipeline
gh pr create --title "feat(deathwatch): pipeline route (DW-4)" --body "Closes #<issue>. See spec §2 pipeline section, CLAUDE.md §6."
```

### ⚠️ Pułapki

- **A — Lazy `from apps...` import** w pipeline branch — Scrapy może załadować pipeline poza Django setup w niektórych invocation paths. Lazy import safe.
- **B — `dict(item)` vs `item.copy()`** — Item ma `.copy()` ale zwraca Item, nie dict. Service expects plain dict.
- **C — Pipeline class name** — dokładnie taka jak istniejąca. Sprawdź `scrapers/.../settings.py:ITEM_PIPELINES` listę.

### 🧪 Testing plan

2 integration testy (Step 2) — happy path + drop case.

### 📦 Definition of Done

- [ ] Pipeline branch dla CharacterDeathItem.
- [ ] 2 integration testy PASS.
- [ ] Full suite PASS (no regression).
- [ ] PR zmergowany.

---

## Task #5 — [DW-5] Celery task + Redis lock + freshness gate + seed migration

### 🎯 Cel

`apps.deathwatch.tasks.scrape_for_watched_deaths` Celery task: cap check, freshness gate (`last_deaths_scraped_at`), Redis lock (`cache.add`), subprocess per-character, post-success update `last_deaths_scraped_at` + call `notify_watched_deaths_for_character` (na razie stub z DW-2). Seed migration włącza PeriodicTask "deathwatch.scrape_for_watched_deaths" co 1 min z `enabled=False`.

### 🧠 Czego się nauczysz

- **`django.core.cache.cache.add(key, val, timeout)`** — atomic, returns False jeśli klucz istnieje. Działa atomic na Redis backend. LocMem **nie jest** cross-process atomic — dla dev OK, dla CI integration test mocked.
- **`acks_late=True`** — zadanie zniknie z kolejki dopiero po ACK od workera. Crash workera = redelivery. Bezpieczne dla idempotent tasks.
- **`PeriodicTask.enabled=False`** w seed migration — admin świadomie włącza komendą `python manage.py` lub w admin UI. Domyślne włączenie = stresować staging zaraz po deploy.
- **Subprocess timeout** — `subprocess.run(..., timeout=30)` zwraca `TimeoutExpired` exception, NIE `returncode != 0`. Try/except wokół.

### ✅ Acceptance criteria

- `apps/deathwatch/tasks.py` z `scrape_for_watched_deaths`:
  - `bind=True, max_retries=2, acks_late=True`.
  - Redis lock pierwszą rzeczą: `if not cache.add("deathwatch_scrape_lock", "1", timeout=55): return {"locked": True}`.
  - Cap defense check: jeśli `unique_count > settings.DEATHWATCH_MAX_WATCHED_CHARACTERS` — log error + return.
  - Freshness gate per Character: `last_deaths_scraped_at > now - DEATHWATCH_FRESHNESS_SECONDS` → skip.
  - Subprocess `manage.py scrape_character_deaths <name>` z `timeout=30`, try/except `TimeoutExpired`.
  - Po `returncode == 0`: `Character.objects.filter(name=name).update(last_deaths_scraped_at=timezone.now())` + call `notify_watched_deaths_for_character(character)`.
  - Return summary `{"checked", "skipped", "scraped", "failed", "events_announced", "locked": False}`.
- `apps/deathwatch/migrations/0002_seed_periodic_task.py` — PeriodicTask "deathwatch.scrape_for_watched_deaths" co 1 min, `enabled=False`.
- `DEATHWATCH_FRESHNESS_SECONDS=50` w `base.py` + `.env.example`.
- Integration testy: lock contention, cap defense, freshness gate, subprocess success/failure paths.

### 📋 TDD steps

- [ ] **Step 1: Branch + settings**

```bash
git checkout master && git pull
git checkout -b feat/<#>-deathwatch-task
```

W `config/settings/base.py`:

```python
DEATHWATCH_FRESHNESS_SECONDS = env.int("DEATHWATCH_FRESHNESS_SECONDS", default=50)
```

W `.env.example`:

```
DEATHWATCH_FRESHNESS_SECONDS=50
```

- [ ] **Step 2: Write failing test dla locka**

`tests/integration/deathwatch/test_celery_task.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from datetime import timedelta
from django.utils import timezone
from django.core.cache import cache

from apps.deathwatch.tasks import scrape_for_watched_deaths
from apps.deathwatch.services import add_death_watch
from apps.deathwatch.models import DeathWatch
from apps.characters.models import Character
from apps.accounts.models import User


@pytest.fixture(autouse=True)
def clear_cache():
    cache.delete("deathwatch_scrape_lock")
    yield
    cache.delete("deathwatch_scrape_lock")


@pytest.mark.django_db
def test_task_locked_returns_locked_summary():
    cache.set("deathwatch_scrape_lock", "1", timeout=55)
    result = scrape_for_watched_deaths()
    assert result["locked"] is True


@pytest.mark.django_db
@patch("apps.deathwatch.tasks.subprocess.run")
def test_task_skips_freshly_scraped_character(mock_subprocess):
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")
    Character.objects.filter(name="Yhral").update(
        last_deaths_scraped_at=timezone.now()  # very fresh
    )

    result = scrape_for_watched_deaths()

    assert result["skipped"] == 1
    assert result["scraped"] == 0
    mock_subprocess.assert_not_called()


@pytest.mark.django_db
@patch("apps.deathwatch.tasks.notify_watched_deaths_for_character", return_value=0)
@patch("apps.deathwatch.tasks.subprocess.run")
def test_task_updates_last_deaths_scraped_at_on_success(mock_subprocess, mock_notify):
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")
    mock_subprocess.return_value = MagicMock(returncode=0)

    before = timezone.now()
    result = scrape_for_watched_deaths()
    after = timezone.now()

    assert result["scraped"] == 1
    character = Character.objects.get(name="Yhral")
    assert character.last_deaths_scraped_at is not None
    assert before <= character.last_deaths_scraped_at <= after


@pytest.mark.django_db
@patch("apps.deathwatch.tasks.subprocess.run")
def test_task_does_not_update_last_deaths_on_subprocess_failure(mock_subprocess):
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")
    mock_subprocess.return_value = MagicMock(returncode=1)

    result = scrape_for_watched_deaths()
    assert result["failed"] == 1
    character = Character.objects.get(name="Yhral")
    assert character.last_deaths_scraped_at is None
```

Expected: FAIL (task nie istnieje).

- [ ] **Step 3: Implement `apps/deathwatch/tasks.py`**

```python
import logging
import subprocess
import sys
from datetime import timedelta

from celery import shared_task, Task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.deathwatch.models import DeathWatch
from apps.deathwatch.services import notify_watched_deaths_for_character
from apps.characters.models import Character

logger = logging.getLogger(__name__)

LOCK_KEY = "deathwatch_scrape_lock"
LOCK_TIMEOUT_SECONDS = 55  # < 60s Beat interval


@shared_task(bind=True, max_retries=2, acks_late=True)
def scrape_for_watched_deaths(self: Task) -> dict[str, int | bool]:
    """Per-1-min scrape of watched characters' Latest Deaths section.

    Redis lock (cache.add atomic) zapobiega nakładającym się fire'om gdy
    cycle > 60s. Freshness gate (per-Character last_deaths_scraped_at) skipuje
    postacie świeżo zescrapowane. Subprocess per-character izoluje Twisted
    reactor (M3 retro #8).
    """
    if not cache.add(LOCK_KEY, "1", timeout=LOCK_TIMEOUT_SECONDS):
        logger.info("scrape_for_watched_deaths: lock held, skipping fire")
        return {"checked": 0, "skipped": 0, "scraped": 0, "failed": 0,
                "events_announced": 0, "locked": True}

    try:
        return _do_scrape()
    finally:
        cache.delete(LOCK_KEY)


def _do_scrape() -> dict[str, int | bool]:
    cap = settings.DEATHWATCH_MAX_WATCHED_CHARACTERS
    freshness_seconds = settings.DEATHWATCH_FRESHNESS_SECONDS
    cutoff = timezone.now() - timedelta(seconds=freshness_seconds)

    character_names = list(
        DeathWatch.objects.filter(active=True)
        .values_list("character__name", flat=True)
        .distinct()
    )

    if len(character_names) > cap:
        logger.error(
            "scrape_for_watched_deaths: cap exceeded (%s > %s) — "
            "service-layer validation broke; skipping iteration",
            len(character_names), cap,
        )
        return {"checked": 0, "skipped": 0, "scraped": 0, "failed": 0,
                "events_announced": 0, "locked": False}

    checked = skipped = scraped = failed = events_announced = 0

    for name in character_names:
        checked += 1
        try:
            character = Character.objects.get(name=name)
        except Character.DoesNotExist:
            logger.warning("character %r vanished mid-iteration", name)
            failed += 1
            continue

        if (
            character.last_deaths_scraped_at
            and character.last_deaths_scraped_at > cutoff
        ):
            skipped += 1
            continue

        try:
            result = subprocess.run(
                [sys.executable, "manage.py", "scrape_character_deaths", name],
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("scrape_character_deaths %r timed out", name)
            failed += 1
            continue

        if result.returncode != 0:
            failed += 1
            logger.warning(
                "scrape_character_deaths %r failed: rc=%s", name, result.returncode
            )
            continue

        scraped += 1
        Character.objects.filter(name=name).update(
            last_deaths_scraped_at=timezone.now()
        )
        try:
            character.refresh_from_db()
            events_announced += notify_watched_deaths_for_character(character)
        except Exception:
            logger.exception("notify failed for character %r", name)

    summary = {
        "checked": checked,
        "skipped": skipped,
        "scraped": scraped,
        "failed": failed,
        "events_announced": events_announced,
        "locked": False,
    }
    logger.info("scrape_for_watched_deaths: %s", summary)
    return summary
```

- [ ] **Step 4: Run task tests**

```bash
poetry run pytest tests/integration/deathwatch/test_celery_task.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 5: Seed migration**

`apps/deathwatch/migrations/0002_seed_periodic_task.py`:

```python
from django.db import migrations


def seed_periodic_task(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = IntervalSchedule.objects.get_or_create(
        every=1, period=IntervalSchedule.MINUTES
    )
    PeriodicTask.objects.update_or_create(
        name="deathwatch.scrape_for_watched_deaths",
        defaults={
            "task": "apps.deathwatch.tasks.scrape_for_watched_deaths",
            "interval": schedule,
            "enabled": False,
        },
    )


def unseed_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(
        name="deathwatch.scrape_for_watched_deaths"
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("deathwatch", "0001_initial"),
        ("django_celery_beat", "0018_improve_crontab_helptext"),  # any recent rev
    ]
    operations = [
        migrations.RunPython(seed_periodic_task, unseed_periodic_task),
    ]
```

Sprawdź exact `django_celery_beat` migration revision w innych miejscach projektu (`apps/deaths/migrations/0002_seed_periodic_task.py`, `apps/bedmages/migrations/0002_*`). Match the one they use.

- [ ] **Step 6: Run migrations + smoke**

```bash
poetry run python manage.py migrate
poetry run python manage.py shell -c "from django_celery_beat.models import PeriodicTask; pt = PeriodicTask.objects.get(name='deathwatch.scrape_for_watched_deaths'); print(pt.enabled, pt.interval.every, pt.interval.period)"
```

Expected: `False 1 minutes`.

- [ ] **Step 7: Pre-commit + commit + PR**

```bash
poetry run pre-commit run --all-files
git add apps/deathwatch/tasks.py apps/deathwatch/migrations/0002_seed_periodic_task.py config/settings/base.py .env.example tests/integration/deathwatch/test_celery_task.py
git commit -m "feat(deathwatch): celery task with redis lock + freshness gate (DW-5, #<issue>)"
git push -u origin feat/<#>-deathwatch-task
gh pr create --title "feat(deathwatch): celery task (DW-5)" --body "Closes #<issue>. See spec §2 Celery task, §3.10 (lock), §3.12 (last_deaths_scraped_at)."
```

### ⚠️ Pułapki

- **A — `cache.add()` returns True przy success** — przeciwieństwo `cache.set()`. Easy off-by-one.
- **B — Cache backend MUST be Redis na prodzie** — LocalMemCache nie jest atomic cross-process. CI test używa Redis service (CLAUDE.md §13.1 CI ma Redis serwis).
- **C — `subprocess.TimeoutExpired` NIE jest `returncode != 0`** — TimeoutExpired to exception, łap explicit.
- **D — `Character.objects.filter(name=name).update(...)`** — wzorzec `update()` po `filter()` zamiast `obj.save()` żeby ominąć signals i auto_now (jeśli był; tu nie jest, ale ekonomiczniej). Race-safe.
- **E — `notify_watched_deaths_for_character` w DW-5 to nadal stub z DW-2** — return 0. DW-6 podmieni z real handler call.
- **F — `enabled=False` w seed** — admin musi explicit włączyć. Bez tego CI deploy zaczyna bombić Tibiantis natychmiast.

### 🧪 Testing plan

4 integration testy: lock, freshness skip, last_deaths_scraped_at update on success, no-update on failure.

### 📦 Definition of Done

- [ ] Task implementacja + lock + cap defense + freshness gate.
- [ ] Seed migration (enabled=False).
- [ ] 4 integration testy PASS.
- [ ] Settings + .env.example.
- [ ] PR zmergowany.

---

## Task #6 — [DW-6] Notification handler + factory + notify integration

### 🎯 Cel

Trzy klasy w `apps/notifications/handlers.py`: `DeathWatchAnnouncementHandler` Protocol, `DeathWatchChannelHandler` (real Discord dispatch), `DeathWatchLoggingHandler` (test variant). Factory `get_deathwatch_handler()` w `apps/notifications/__init__.py`. Real implementacja `notify_watched_deaths_for_character` (zamiast stub z DW-2): iteruje `DeathWatchChannel × pending events`, atomic flag-set po pełnym sukcesie. Settings switch `DEATHWATCH_NOTIFICATION_HANDLER`.

### 🧠 Czego się nauczysz

- **`Protocol` z `typing`** — duck-typed interface, nie wymaga subclass. Mirror `BedmageNotificationHandler` (`apps/notifications/handlers.py:16`).
- **Dotted-path handler resolution** — `django.utils.module_loading.import_string(settings.X)` → klasa → instance. Mirror M8 `get_bedmage_handler`.
- **Discord embed authoring** — title (clickable via `url`), description (multi-line), `timestamp`, `color`. Spec §3.11 wymaga `0x8B008B`.
- **TZ display convention** — `died_at` w DB jest UTC, display w `Europe/Warsaw` (mirror #180/#181 — `apps/notifications/handlers.py:141`).

### ✅ Acceptance criteria

- `apps/notifications/handlers.py` rozszerzony o:
  - `DeathWatchAnnouncementHandler(Protocol)`: `announce(event, channel) → bool`.
  - `DeathWatchChannelHandler`: real Discord dispatch przez `DiscordRESTClient.send_channel_message(channel.channel_id, embed=...)`.
  - `DeathWatchLoggingHandler`: logger.info only, return True.
- Embed `_render_embed`:
  - `title` = `event.character.name`.
  - `url` = `https://www.tibiantis.online/?page=character&name=<quote_plus(name)>`.
  - `description` = 3 linie: `"Died at level {level}\n{died_at_local:%Y-%m-%d %H:%M:%S}\nKilled by: {killed_by or 'unknown'}"`.
  - `color` = `0x8B008B`.
  - `died_at_local` = `event.died_at.astimezone(ZoneInfo("Europe/Warsaw"))`.
- `apps/notifications/__init__.py` ma `get_deathwatch_handler()`.
- `apps/deathwatch/services.py:notify_watched_deaths_for_character` real implementation (drop the DW-2 stub TODO).
- `DEATHWATCH_NOTIFICATION_HANDLER` w `base.py` + `.env.example`.
- Unit testy handler + integration test notify flow.

### 📋 TDD steps

- [ ] **Step 1: Branch + settings**

```bash
git checkout master && git pull
git checkout -b feat/<#>-deathwatch-handler
```

W `config/settings/base.py`:

```python
DEATHWATCH_NOTIFICATION_HANDLER = env(
    "DEATHWATCH_NOTIFICATION_HANDLER",
    default="apps.notifications.handlers.DeathWatchChannelHandler",
)
```

W `.env.example`:

```
DEATHWATCH_NOTIFICATION_HANDLER=apps.notifications.handlers.DeathWatchChannelHandler
```

- [ ] **Step 2: Failing tests dla handler**

`tests/unit/deathwatch/test_handlers.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from zoneinfo import ZoneInfo

from apps.notifications.handlers import (
    DeathWatchChannelHandler, DeathWatchLoggingHandler,
)
from apps.deathwatch.models import DeathWatchChannel, WatchedDeathEvent
from apps.characters.models import Character


@pytest.mark.django_db
def test_channel_handler_renders_embed_with_purple_color_and_warsaw_tz():
    character = Character.objects.create(name="Yhral")
    event = WatchedDeathEvent.objects.create(
        character=character,
        level_at_death=128,
        killed_by="a giant crayfish",
        died_at=datetime(2026, 5, 7, 14, 15, 46, tzinfo=ZoneInfo("UTC")),
    )
    channel = DeathWatchChannel.objects.create(guild_id=1, channel_id=2)

    handler = DeathWatchChannelHandler()
    embed = handler._render_embed(event)

    assert embed["title"] == "Yhral"
    assert "tibiantis.online" in embed["url"]
    assert embed["color"] == 0x8B008B
    # Europe/Warsaw is UTC+2 (CEST May 2026) → 14:15 UTC = 16:15 local
    assert "16:15:46" in embed["description"]
    assert "Killed by: a giant crayfish" in embed["description"]
    assert "Died at level 128" in embed["description"]


@pytest.mark.django_db
def test_channel_handler_renders_unknown_killer():
    character = Character.objects.create(name="Yhral")
    event = WatchedDeathEvent.objects.create(
        character=character, level_at_death=50, killed_by="",
        died_at=datetime(2026, 5, 7, 12, 0, 0, tzinfo=ZoneInfo("UTC")),
    )
    handler = DeathWatchChannelHandler()
    embed = handler._render_embed(event)
    assert "Killed by: unknown" in embed["description"]


@pytest.mark.django_db
@patch("apps.notifications.discord_client.DiscordRESTClient.send_channel_message")
def test_channel_handler_announce_returns_client_result(mock_send):
    mock_send.return_value = True
    character = Character.objects.create(name="Yhral")
    event = WatchedDeathEvent.objects.create(
        character=character, level_at_death=10, killed_by="x",
        died_at=datetime(2026, 5, 7, 12, 0, 0, tzinfo=ZoneInfo("UTC")),
    )
    channel = DeathWatchChannel.objects.create(guild_id=1, channel_id=42)

    handler = DeathWatchChannelHandler()
    assert handler.announce(event, channel) is True
    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["channel_id"] == 42
    assert "embed" in call_kwargs


@pytest.mark.django_db
def test_logging_handler_always_succeeds():
    character = Character.objects.create(name="Yhral")
    event = WatchedDeathEvent.objects.create(
        character=character, level_at_death=10, killed_by="x",
        died_at=datetime(2026, 5, 7, 12, 0, 0, tzinfo=ZoneInfo("UTC")),
    )
    channel = DeathWatchChannel.objects.create(guild_id=1, channel_id=42)
    handler = DeathWatchLoggingHandler()
    assert handler.announce(event, channel) is True
```

Expected: FAIL.

- [ ] **Step 3: Implement handlery w `apps/notifications/handlers.py`**

Dopisz po istniejących klasach:

```python
from typing import Protocol


class DeathWatchAnnouncementHandler(Protocol):
    def announce(self, event, channel) -> bool: ...


class DeathWatchChannelHandler:
    """Real Discord dispatch via Bot Token + REST API.

    Mirror DiscordChannelHandler (M8) — different embed color (purple
    vs crimson) to visually separate deathwatch from M4 deaths feed.
    """

    def announce(self, event, channel) -> bool:
        from apps.notifications.discord_client import DiscordRESTClient
        client = DiscordRESTClient()
        return client.send_channel_message(
            channel_id=channel.channel_id,
            embed=self._render_embed(event),
        )

    def _render_embed(self, event) -> dict:
        import urllib.parse
        from zoneinfo import ZoneInfo
        died_at_local = event.died_at.astimezone(ZoneInfo("Europe/Warsaw"))
        return {
            "title": event.character.name,
            "url": (
                "https://www.tibiantis.online/?page=character&name="
                + urllib.parse.quote_plus(event.character.name)
            ),
            "description": (
                f"Died at level {event.level_at_death}\n"
                f"{died_at_local:%Y-%m-%d %H:%M:%S}\n"
                f"Killed by: {event.killed_by or 'unknown'}"
            ),
            "color": 0x8B008B,
        }


class DeathWatchLoggingHandler:
    """Test/dev — logs only, returns True."""

    def announce(self, event, channel) -> bool:
        logger.info(
            "DEATHWATCH ANNOUNCE: %s (lvl %s) → guild=%s channel=%s",
            event.character.name, event.level_at_death,
            channel.guild_id, channel.channel_id,
        )
        return True
```

- [ ] **Step 4: Factory w `apps/notifications/__init__.py`**

Dopisz:

```python
def get_deathwatch_handler():
    from django.conf import settings
    from django.utils.module_loading import import_string
    handler_class = import_string(settings.DEATHWATCH_NOTIFICATION_HANDLER)
    return handler_class()
```

- [ ] **Step 5: Run handler tests**

```bash
poetry run pytest tests/unit/deathwatch/test_handlers.py -v
```

Expected: PASS.

- [ ] **Step 6: Failing test dla notify integration**

`tests/integration/deathwatch/test_notify.py`:

```python
import pytest
from unittest.mock import patch
from datetime import datetime, timedelta
from django.utils import timezone
from zoneinfo import ZoneInfo

from apps.deathwatch.services import (
    notify_watched_deaths_for_character, add_death_watch,
    set_deathwatch_channel_for_guild,
)
from apps.deathwatch.models import WatchedDeathEvent, DeathWatch
from apps.characters.models import Character
from apps.accounts.models import User


@pytest.mark.django_db
@patch("apps.notifications.handlers.DeathWatchChannelHandler.announce",
       return_value=True)
def test_notify_marks_announced_on_success_all_channels(mock_announce):
    set_deathwatch_channel_for_guild(guild_id=1, channel_id=11)
    set_deathwatch_channel_for_guild(guild_id=2, channel_id=22)
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")
    DeathWatch.objects.filter(user=user).update(
        created_at=timezone.now() - timedelta(hours=1)
    )
    character = Character.objects.get(name="Yhral")
    event = WatchedDeathEvent.objects.create(
        character=character, level_at_death=128, killed_by="x",
        died_at=timezone.now(),
    )

    fired = notify_watched_deaths_for_character(character)

    assert fired == 1
    event.refresh_from_db()
    assert event.announced_on_discord is True
    assert mock_announce.call_count == 2  # 2 channels


@pytest.mark.django_db
@patch("apps.notifications.handlers.DeathWatchChannelHandler.announce",
       side_effect=[True, False])
def test_notify_does_not_mark_when_one_channel_fails(mock_announce):
    set_deathwatch_channel_for_guild(guild_id=1, channel_id=11)
    set_deathwatch_channel_for_guild(guild_id=2, channel_id=22)
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")
    DeathWatch.objects.filter(user=user).update(
        created_at=timezone.now() - timedelta(hours=1)
    )
    character = Character.objects.get(name="Yhral")
    event = WatchedDeathEvent.objects.create(
        character=character, level_at_death=128, killed_by="x",
        died_at=timezone.now(),
    )

    notify_watched_deaths_for_character(character)

    event.refresh_from_db()
    assert event.announced_on_discord is False


@pytest.mark.django_db
def test_notify_no_channels_returns_zero():
    character = Character.objects.create(name="Yhral")
    fired = notify_watched_deaths_for_character(character)
    assert fired == 0
```

Expected: FAIL (notify nadal stub returning 0).

- [ ] **Step 7: Implement real `notify_watched_deaths_for_character`**

W `apps/deathwatch/services.py` zastąp stub:

```python
def notify_watched_deaths_for_character(character: Character) -> int:
    """Dispatch pending WatchedDeathEvents for character via configured handler.

    Multi-channel: iterates DeathWatchChannel.objects.all(); flag set
    only when ALL channels accepted (success = handler.announce() → True).
    Partial failure leaves flag False → next task fire retries.
    """
    from apps.notifications import get_deathwatch_handler

    channels = list(DeathWatchChannel.objects.all())
    if not channels:
        return 0

    handler = get_deathwatch_handler()
    fired = 0

    events = WatchedDeathEvent.objects.filter(
        character=character, announced_on_discord=False
    )
    for event in events:
        all_ok = True
        for channel in channels:
            try:
                if not handler.announce(event, channel):
                    all_ok = False
            except Exception:
                logger.exception(
                    "deathwatch announce raised for event=%s channel=%s",
                    event.pk, channel.pk,
                )
                all_ok = False

        if all_ok:
            event.announced_on_discord = True
            event.save(update_fields=["announced_on_discord"])
            fired += 1

    return fired
```

- [ ] **Step 8: Run integration tests**

```bash
poetry run pytest tests/integration/deathwatch/test_notify.py -v
```

Expected: PASS (3 tests).

- [ ] **Step 9: Verify full suite still green**

```bash
poetry run pytest -v
```

- [ ] **Step 10: Pre-commit + commit + PR**

```bash
poetry run pre-commit run --all-files
git add apps/notifications/ apps/deathwatch/services.py config/settings/base.py .env.example tests/unit/deathwatch/test_handlers.py tests/integration/deathwatch/test_notify.py
git commit -m "feat(deathwatch): notification handler + multi-channel notify (DW-6, #<issue>)"
git push -u origin feat/<#>-deathwatch-handler
gh pr create --title "feat(deathwatch): notification handler (DW-6)" --body "Closes #<issue>. See spec §3.9, §3.11, §3.13."
```

### ⚠️ Pułapki

- **A — `event.died_at.astimezone(...)` zakłada że datetime jest tz-aware** — z DB Django zwraca tz-aware (USE_TZ=True). Defensywne: jeśli `tzinfo is None` → assume UTC.
- **B — Embed `url` musi mieć `https://`** — Discord nie clickuje plain `tibiantis.online/...`.
- **C — `urllib.parse.quote_plus`** dla character names ze spacjami — Tibiantis URL używa `+` dla spacji, `quote_plus` to robi. M4 (#178) tę samą decyzję podjął.
- **D — Multi-channel exception isolation** — jeden Discord 5xx nie może wywalić iteracji per pozostałe kanały. Try/except per-channel.

### 🧪 Testing plan

- 4 unit testy handler (embed render, color, unknown killer, dispatch wiring).
- 3 integration testy notify (all-success, partial-fail, no-channels).

### 📦 Definition of Done

- [ ] 3 handler classes + factory + setting.
- [ ] Real `notify_watched_deaths_for_character` (no stub).
- [ ] 7 testów total.
- [ ] PR zmergowany.

---

## Task #7 — [DW-7] Discord cog + register w bot.py

### 🎯 Cel

`discord_bot/cogs/deathwatch.py` z 4 slash commands: `/deathwatch add|remove|list|channel`. Auth wzorcem bedmages (discord_id → User auto-create). Admin guard na `/deathwatch channel`. Ephemeral responses dla user-scoped. Registracja w `discord_bot/bot.py`.

### 🧠 Czego się nauczysz

- **`discord.SlashCommandGroup`** — grupuje subcommands pod jedną nazwą. Mirror M4 deaths cog + M7 bedmages cog.
- **`sync_to_async`** — Django ORM call w py-cord async event loop. Bezpośrednie `Model.objects.get(...)` w async coro = `SynchronousOnlyOperation`.
- **`discord.Member.guild_permissions.administrator`** — admin guard. Mirror `deaths.py:38`.
- **`ephemeral=True`** w `ctx.respond` — visible tylko user'owi. UX dla per-user actions; admin actions są public.

### ✅ Acceptance criteria

- `discord_bot/cogs/deathwatch.py`:
  - `DeathWatchCog(commands.Cog)` z `SlashCommandGroup("deathwatch", "...")`.
  - 4 commands: `add(character_name)`, `remove(character_name)`, `list_`, `channel`.
  - User resolve: `_get_or_create_user(discord_id)` (mirror `bedmages.py`).
  - `add` — cap `ValueError` → ephemeral user-friendly message.
  - `remove` — `True/False` → różny komunikat ephemeral.
  - `list_` — embed ephemeral z listą characters + created_at.
  - `channel` — admin only (sprawdź `ctx.author.guild_permissions.administrator`), public ack.
- `discord_bot/bot.py` — dodać `bot.add_cog(DeathWatchCog(bot))`.
- Integration test cog z mocked DiscordRESTClient.

### 📋 TDD steps

- [ ] **Step 1: Branch + Read precedensów**

```bash
git checkout master && git pull
git checkout -b feat/<#>-deathwatch-cog
```

Read `discord_bot/cogs/bedmages.py` (full file) + `discord_bot/cogs/deaths.py` (full file) — copy patterns 1:1 gdzie aplikuje.

- [ ] **Step 2: Failing test cog**

`tests/integration/discord_bot/test_deathwatch_cog.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from discord_bot.cogs.deathwatch import DeathWatchCog
from apps.deathwatch.models import DeathWatch, DeathWatchChannel
from apps.deathwatch.services import add_death_watch
from apps.accounts.models import User


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_add_command_creates_watch_and_responds_ephemerally():
    cog = DeathWatchCog(MagicMock())
    ctx = MagicMock()
    ctx.author.id = 12345
    ctx.respond = AsyncMock()

    await cog.add.callback(cog, ctx, "Yhral")

    assert User.objects.filter(discord_id="12345").exists()
    user = User.objects.get(discord_id="12345")
    assert DeathWatch.objects.filter(user=user, character__name="Yhral").exists()
    ctx.respond.assert_awaited_once()
    args, kwargs = ctx.respond.call_args
    assert kwargs.get("ephemeral") is True


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_add_command_duplicate_responds_with_error_no_stack_trace():
    user = User.objects.create(username="alice_disc", discord_id="12345")
    add_death_watch(user, "Yhral")

    cog = DeathWatchCog(MagicMock())
    ctx = MagicMock()
    ctx.author.id = 12345
    ctx.respond = AsyncMock()

    await cog.add.callback(cog, ctx, "Yhral")

    ctx.respond.assert_awaited_once()
    args, kwargs = ctx.respond.call_args
    msg = args[0] if args else kwargs.get("content", "")
    assert "already" in msg.lower() or "exists" in msg.lower()
    assert "Traceback" not in msg


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_channel_command_admin_only():
    cog = DeathWatchCog(MagicMock())
    ctx = MagicMock()
    ctx.author.guild_permissions.administrator = False
    ctx.guild = MagicMock()
    ctx.guild.id = 1
    ctx.channel_id = 100
    ctx.respond = AsyncMock()

    await cog.channel.callback(cog, ctx)

    args, kwargs = ctx.respond.call_args
    assert kwargs.get("ephemeral") is True
    msg = args[0] if args else kwargs.get("content", "")
    assert "admin" in msg.lower() or "❌" in msg


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_channel_command_admin_creates_channel_config():
    cog = DeathWatchCog(MagicMock())
    ctx = MagicMock()
    ctx.author.guild_permissions.administrator = True
    ctx.guild.id = 99
    ctx.channel_id = 777
    ctx.respond = AsyncMock()

    await cog.channel.callback(cog, ctx)

    assert DeathWatchChannel.objects.filter(guild_id=99, channel_id=777).exists()
```

Expected: FAIL (cog nie istnieje).

- [ ] **Step 3: Implement cog**

`discord_bot/cogs/deathwatch.py`:

```python
# NOTE: NO `from __future__ import annotations` here — py-cord introspects
# parameter annotations at slash command invocation time.
from asgiref.sync import sync_to_async
import discord
from discord.ext import commands

from apps.deathwatch.services import (
    add_death_watch, remove_death_watch, list_death_watches,
    set_deathwatch_channel_for_guild,
)
from apps.accounts.models import User


class DeathWatchCog(commands.Cog):
    deathwatch = discord.SlashCommandGroup(
        "deathwatch", "Per-character death blacklist"
    )

    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot

    async def _get_or_create_user(self, discord_id: int) -> User:
        user, _ = await sync_to_async(User.objects.get_or_create)(
            discord_id=str(discord_id),
            defaults={"username": f"discord_{discord_id}"},
        )
        return user

    @deathwatch.command(name="add", description="Watch a character for new deaths")
    async def add(
        self, ctx: discord.ApplicationContext,
        character_name: discord.Option(str, "Character name"),
    ) -> None:
        user = await self._get_or_create_user(ctx.author.id)
        try:
            await sync_to_async(add_death_watch)(user, character_name)
        except ValueError as exc:
            await ctx.respond(f"❌ {exc}", ephemeral=True)
            return
        await ctx.respond(
            f"👀 Now watching **{character_name}** for new deaths.",
            ephemeral=True,
        )

    @deathwatch.command(name="remove", description="Stop watching a character")
    async def remove(
        self, ctx: discord.ApplicationContext,
        character_name: discord.Option(str, "Character name"),
    ) -> None:
        user = await self._get_or_create_user(ctx.author.id)
        removed = await sync_to_async(remove_death_watch)(user, character_name)
        if removed:
            await ctx.respond(
                f"🗑️ Stopped watching **{character_name}**.", ephemeral=True
            )
        else:
            await ctx.respond(
                f"⚠️ You weren't watching **{character_name}**.", ephemeral=True
            )

    @deathwatch.command(name="list", description="Show your watched characters")
    async def list_(self, ctx: discord.ApplicationContext) -> None:
        user = await self._get_or_create_user(ctx.author.id)
        watches = await sync_to_async(lambda: list(list_death_watches(user)))()
        if not watches:
            await ctx.respond(
                "You're not watching any characters.", ephemeral=True
            )
            return
        lines = "\n".join(
            f"• **{w.character.name}** (since {w.created_at:%Y-%m-%d %H:%M})"
            for w in watches
        )
        await ctx.respond(f"Your death watches:\n{lines}", ephemeral=True)

    @deathwatch.command(
        name="channel", description="Set announcement channel (admin only)"
    )
    async def channel(self, ctx: discord.ApplicationContext) -> None:
        if ctx.guild is None:
            await ctx.respond(
                "❌ This command must be used in a server.", ephemeral=True
            )
            return
        assert isinstance(ctx.author, discord.Member)
        assert ctx.channel_id is not None

        if not ctx.author.guild_permissions.administrator:
            await ctx.respond(
                "❌ Only server admins can set the deathwatch channel.",
                ephemeral=True,
            )
            return

        await sync_to_async(set_deathwatch_channel_for_guild)(
            guild_id=ctx.guild.id, channel_id=ctx.channel_id,
        )
        await ctx.respond(
            "💀👀 DeathWatch announcements will be posted to this channel."
        )
```

- [ ] **Step 4: Register w `discord_bot/bot.py`**

Znajdź `bot.add_cog(BedmagesCog(bot))` lub równoważne i dopisz:

```python
from discord_bot.cogs.deathwatch import DeathWatchCog
bot.add_cog(DeathWatchCog(bot))
```

- [ ] **Step 5: Run cog tests**

```bash
poetry run pytest tests/integration/discord_bot/test_deathwatch_cog.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 6: Manual smoke (optional, lokalny bot)**

```bash
poetry run python manage.py run_discord_bot
```

W Discord:
- `/deathwatch add Yhral` — expect ephemeral ack.
- `/deathwatch list` — expect Yhral w liście.
- `/deathwatch channel` (admin) — public ack.
- `/deathwatch remove Yhral` — expect ephemeral confirmation.

- [ ] **Step 7: Pre-commit + commit + PR**

```bash
poetry run pre-commit run --all-files
git add discord_bot/cogs/deathwatch.py discord_bot/bot.py tests/integration/discord_bot/test_deathwatch_cog.py
git commit -m "feat(deathwatch): discord cog with 4 slash commands (DW-7, #<issue>)"
git push -u origin feat/<#>-deathwatch-cog
gh pr create --title "feat(deathwatch): discord cog (DW-7)" --body "Closes #<issue>. See spec §2 Discord cog section, CLAUDE.md §8."
```

### ⚠️ Pułapki

- **A — `from __future__ import annotations` BREAK py-cord** — py-cord introspects param annotations runtime. M7 `deaths.py:1-3` comment dokumentuje.
- **B — `sync_to_async(list_death_watches)(user)` zwraca QuerySet** — QuerySet lazy, evaluacja w async context może crashować. Wrap w `list(...)` explicit jak w Step 3.
- **C — `discord.Option(...)` jako annotation, nie typing.Annotated** — py-cord 2.x specyfika. Mirror `deaths.py:24`.
- **D — `assert isinstance(ctx.author, discord.Member)`** — py-cord context może mieć `User` (DM) lub `Member` (guild). Post-guild-check narrowing.
- **E — Stack trace leak na Discord** — `except ValueError as exc: ctx.respond(f"❌ {exc}")` exposes `exc` string only, no traceback. CLAUDE.md §8.

### 🧪 Testing plan

4 integration testy: add success, add duplicate handling, channel admin guard, channel admin success.

### 📦 Definition of Done

- [ ] Cog + 4 slash commands + register.
- [ ] 4 testy PASS.
- [ ] Manual smoke (jeśli możliwe).
- [ ] PR zmergowany.

---

## Task #8 — [DW-8] GraphQL schema + scal

### 🎯 Cel

`apps/deathwatch/schema.py` z Strawberry-Django typami, queries (`myDeathWatches`, `watchedDeaths`), mutations (`addDeathWatch`, `removeDeathWatch`, `setDeathWatchChannel`). Scal w `config/schema.py`. JWT auth guard wzorcem M2-D12 / M5-D27.

### 🧠 Czego się nauczysz

- **`@strawberry_django.type` vs `@strawberry.type`** — django version daje `auto` field resolution + `select_related` hints. Mirror `apps/bedmages/schema.py`.
- **`info.context.request.user.is_authenticated`** — auth check w resolverze. Raise `Exception("Authentication required")` jeśli False.
- **`merge_types`** w `config/schema.py` — Strawberry sposób na scalanie Query/Mutation z różnych apek.

### ✅ Acceptance criteria

- `apps/deathwatch/schema.py` z:
  - Typy: `DeathWatchType`, `WatchedDeathEventType`, `DeathWatchChannelType`.
  - Queries: `myDeathWatches`, `watchedDeaths(characterName, limit)`.
  - Mutations: `addDeathWatch(characterName)`, `removeDeathWatch(characterName)`, `setDeathWatchChannel(guildId, channelId)` (superuser only).
- `config/schema.py` scal `DeathWatchQuery` i `DeathWatchMutation`.
- Unit tests: query/mutation happy paths + auth required + superuser-only `setDeathWatchChannel`.

### 📋 TDD steps

- [ ] **Step 1: Branch + Read precedensu**

```bash
git checkout master && git pull
git checkout -b feat/<#>-deathwatch-graphql
```

Read `apps/bedmages/schema.py` (full) + `config/schema.py` (merge pattern).

- [ ] **Step 2: Failing test schema**

`tests/unit/deathwatch/test_schema.py`:

```python
import pytest
from strawberry.types import ExecutionResult
from config.schema import schema
from apps.accounts.models import User
from apps.deathwatch.services import add_death_watch


@pytest.mark.django_db
def test_my_death_watches_query_returns_user_watches():
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")

    query = "{ myDeathWatches { characterName active } }"
    context = type("ctx", (), {"request": type("req", (), {"user": user})()})()
    result: ExecutionResult = schema.execute_sync(query, context_value=context)

    assert result.errors is None
    assert result.data["myDeathWatches"][0]["characterName"] == "Yhral"


@pytest.mark.django_db
def test_my_death_watches_requires_auth():
    from django.contrib.auth.models import AnonymousUser
    query = "{ myDeathWatches { characterName } }"
    context = type("ctx", (), {"request": type("req", (), {"user": AnonymousUser()})()})()
    result = schema.execute_sync(query, context_value=context)
    assert result.errors is not None
    assert "auth" in str(result.errors[0]).lower()


@pytest.mark.django_db
def test_add_death_watch_mutation():
    user = User.objects.create(username="alice", discord_id="1")
    mutation = '''
        mutation { addDeathWatch(characterName: "Yhral") { characterName active } }
    '''
    context = type("ctx", (), {"request": type("req", (), {"user": user})()})()
    result = schema.execute_sync(mutation, context_value=context)

    assert result.errors is None
    assert result.data["addDeathWatch"]["characterName"] == "Yhral"
    assert result.data["addDeathWatch"]["active"] is True


@pytest.mark.django_db
def test_set_death_watch_channel_requires_superuser():
    user = User.objects.create(username="alice", discord_id="1")  # not superuser
    mutation = '''
        mutation { setDeathWatchChannel(guildId: 1, channelId: 2) { guildId } }
    '''
    context = type("ctx", (), {"request": type("req", (), {"user": user})()})()
    result = schema.execute_sync(mutation, context_value=context)
    assert result.errors is not None
```

Expected: FAIL.

- [ ] **Step 3: Implement `apps/deathwatch/schema.py`**

```python
import strawberry
import strawberry_django
from typing import List
from asgiref.sync import sync_to_async

from apps.deathwatch.models import DeathWatch, WatchedDeathEvent, DeathWatchChannel
from apps.deathwatch.services import (
    add_death_watch, remove_death_watch, list_death_watches,
    set_deathwatch_channel_for_guild,
)


def _require_auth(info):
    user = info.context.request.user
    if not user.is_authenticated:
        raise Exception("Authentication required")
    return user


def _require_superuser(info):
    user = _require_auth(info)
    if not user.is_superuser:
        raise Exception("Superuser required")
    return user


@strawberry_django.type(DeathWatch)
class DeathWatchType:
    id: strawberry.ID
    active: bool
    created_at: "datetime.datetime"

    @strawberry.field
    def character_name(self) -> str:
        return self.character.name


@strawberry_django.type(WatchedDeathEvent)
class WatchedDeathEventType:
    id: strawberry.ID
    level_at_death: int
    killed_by: str
    died_at: "datetime.datetime"
    announced_on_discord: bool

    @strawberry.field
    def character_name(self) -> str:
        return self.character.name


@strawberry_django.type(DeathWatchChannel)
class DeathWatchChannelType:
    guild_id: str
    channel_id: str


@strawberry.type
class DeathWatchQuery:
    @strawberry.field
    def my_death_watches(self, info) -> List[DeathWatchType]:
        user = _require_auth(info)
        return list(list_death_watches(user))

    @strawberry.field
    def watched_deaths(
        self, info, character_name: str | None = None, limit: int = 20
    ) -> List[WatchedDeathEventType]:
        _require_auth(info)
        qs = WatchedDeathEvent.objects.select_related("character").order_by("-died_at")
        if character_name:
            qs = qs.filter(character__name=character_name)
        return list(qs[: max(1, min(limit, 100))])


@strawberry.type
class DeathWatchMutation:
    @strawberry.mutation
    def add_death_watch(self, info, character_name: str) -> DeathWatchType:
        user = _require_auth(info)
        return add_death_watch(user, character_name)

    @strawberry.mutation
    def remove_death_watch(self, info, character_name: str) -> bool:
        user = _require_auth(info)
        return remove_death_watch(user, character_name)

    @strawberry.mutation
    def set_death_watch_channel(
        self, info, guild_id: str, channel_id: str
    ) -> DeathWatchChannelType:
        _require_superuser(info)
        return set_deathwatch_channel_for_guild(
            guild_id=int(guild_id), channel_id=int(channel_id)
        )
```

- [ ] **Step 4: Scal w `config/schema.py`**

Otwórz `config/schema.py`, znajdź merge patterns. Dopisz:

```python
from apps.deathwatch.schema import DeathWatchQuery, DeathWatchMutation

# In existing merge_types/Query/Mutation composition:
Query = merge_types("Query", (ExistingQueries..., DeathWatchQuery))
Mutation = merge_types("Mutation", (ExistingMutations..., DeathWatchMutation))
```

**Note:** sprawdź exact composition w `config/schema.py` przed edycją.

- [ ] **Step 5: Run schema tests**

```bash
poetry run pytest tests/unit/deathwatch/test_schema.py -v
```

Expected: PASS.

- [ ] **Step 6: Pre-commit + commit + PR**

```bash
poetry run pre-commit run --all-files
git add apps/deathwatch/schema.py config/schema.py tests/unit/deathwatch/test_schema.py
git commit -m "feat(deathwatch): graphql schema with queries + mutations (DW-8, #<issue>)"
git push -u origin feat/<#>-deathwatch-graphql
gh pr create --title "feat(deathwatch): graphql schema (DW-8)" --body "Closes #<issue>. See spec §2 GraphQL section, CLAUDE.md §9."
```

### ⚠️ Pułapki

- **A — `info.context.request.user`** — Strawberry-Django wzorzec; sprawdź czy projekt używa `request` czy bezpośrednio `user` w context. Read `apps/bedmages/schema.py` jako autorytatywny.
- **B — `strawberry.ID` zwracane jako string** — frontend musi wiedzieć że `id` jest string-encoded, nie int.
- **C — `guild_id` / `channel_id` jako `str` w mutation arg** — Discord snowflakes są 64-bit ints, GraphQL `Int` wspiera 32-bit only. Trzymaj jako string i konwertuj w resolverze.

### 🧪 Testing plan

4 unit testy schema: query + auth + mutation + superuser guard.

### 📦 Definition of Done

- [ ] Schema + 3 typy + 2 queries + 3 mutations.
- [ ] Scal w config/schema.py.
- [ ] 4 testy PASS.
- [ ] PR zmergowany.

---

## Task #9 — [DW-9] Settings stubs.py mirror + PROGRESS.md + closure

### 🎯 Cel

`config/settings/stubs.py` mirror (mypy CI guard — memory `feedback_stubs_py_backend_overrides`). PROGRESS.md retro + DoD checklist + podsumowanie feature. Final smoke checklist.

### 🧠 Czego się nauczysz

- **`config/settings/stubs.py` jest single source of truth dla mypy** (chore PR #92 history). Nowe `LOCAL_APPS` entries + nowe settings widoczne dla mypy tylko gdy są w stubs.py.
- **PROGRESS.md retro format** — sprawdź ostatnie wpisy w `PROGRESS.md`. Każdy milestone ma sekcję: Cel, Co działa, Co się nauczyłem, Tech debt.

### ✅ Acceptance criteria

- `config/settings/stubs.py` ma:
  - `"apps.deathwatch"` w `LOCAL_APPS`.
  - `DEATHWATCH_MAX_WATCHED_CHARACTERS: int`.
  - `DEATHWATCH_FRESHNESS_SECONDS: int`.
  - `DEATHWATCH_NOTIFICATION_HANDLER: str`.
- `PROGRESS.md` dopisany o retro deathwatch feature.
- Final smoke checklist (poniżej) wykonany.

### 📋 TDD steps

- [ ] **Step 1: Branch**

```bash
git checkout master && git pull
git checkout -b docs/<#>-deathwatch-closure
```

- [ ] **Step 2: Update stubs.py**

Edit `config/settings/stubs.py`:

```python
# In LOCAL_APPS:
LOCAL_APPS: list[str] = [
    # ... existing,
    "apps.deathwatch",
]

# After existing DEATH_* settings:
DEATHWATCH_MAX_WATCHED_CHARACTERS: int
DEATHWATCH_FRESHNESS_SECONDS: int
DEATHWATCH_NOTIFICATION_HANDLER: str
```

- [ ] **Step 3: Verify mypy clean**

```bash
poetry run pre-commit clean  # memory: cache trap po edycji stubs.py
poetry run mypy apps/
```

Expected: zero errors.

- [ ] **Step 4: Update PROGRESS.md**

Dopisz sekcję na końcu z formatem matching previous milestones (sprawdź `PROGRESS.md` ostatnie 50 linii):

```markdown
## DeathWatch — Death Blacklist (2026-05-17 → 2026-05-XX)

### Cel
Per-user blacklist postaci z 1-min monitoringiem śmierci na tibiantis.online,
niezależny od deaths feature (M4).

### Co działa
- 4 Discord slash commands /deathwatch add|remove|list|channel.
- Beat 1-min scrape z Redis lockiem + global cap 20.
- Multi-channel announcements z dedup na poziomie WatchedDeathEvent.
- GraphQL queries + mutations dla domeny.

### Tech debt / follow-ups
(Linki do GitHub Issues jeśli stworzysz)
- Konsolidacja scrape z bedmages (spec §1 Out of scope).
- DeathWatch.guild_id dla multi-guild routing (spec §9.3).
- Per-channel announcement tracking (spec §9.5).
```

- [ ] **Step 5: Final manual smoke checklist**

Przed merge final PR:

- [ ] `python manage.py migrate` świeży DB → wszystko czysto.
- [ ] `python manage.py shell` → `from apps.deathwatch.models import DeathWatch, WatchedDeathEvent, DeathWatchChannel; print('ok')`.
- [ ] `python manage.py run_discord_bot` w dev env → `/deathwatch add` test character → 1-min poczekaj → sprawdź embed.
- [ ] Admin enabled the PeriodicTask manually for the smoke (defaults to `enabled=False`).
- [ ] `python manage.py scrape_character_deaths Yhral` (manual, online) → 0 exit code, log z liczbą items.
- [ ] Coverage report `apps/deathwatch/` ≥ 85%.
- [ ] CI lint + test zielone.

- [ ] **Step 6: Pre-commit + commit + final PR**

```bash
poetry run pre-commit run --all-files
git add config/settings/stubs.py PROGRESS.md
git commit -m "docs(deathwatch): closure + stubs mirror + PROGRESS retro (DW-9, #<issue>)"
git push -u origin docs/<#>-deathwatch-closure
gh pr create --title "docs(deathwatch): closure (DW-9)" --body "Closes #<issue>. Final smoke + PROGRESS retro."
```

### ⚠️ Pułapki

- **A — `pre-commit clean`** po edycji stubs.py jest critical — memory `feedback_pre_commit_mypy_cache`. Inaczej mypy keeps phantom errors lub phantom successes.
- **B — `PROGRESS.md` format** — match exact heading style i sekcje z ostatnich milestone'ów. Niespójność = retro grep'i będą trudniejsze.
- **C — Smoke checklist on prod-like env** — local docker-compose przed claim "done", nie tylko CI.

### 🧪 Testing plan

Smoke checklist (Step 5) zamiast unit testów.

### 📦 Definition of Done

- [ ] stubs.py mirror.
- [ ] PROGRESS retro.
- [ ] Smoke checklist 100% green.
- [ ] PR zmergowany.
- [ ] Wszystkie DW-1..DW-9 PR-y zmergowane.
- [ ] PeriodicTask "deathwatch.scrape_for_watched_deaths" jest w DB z `enabled=False` (admin decyduje kiedy włączyć).

---

## Self-review checklist

Po zakończeniu wszystkich Task #1-#9:

- [ ] Spec §1-§10 coverage — każda sekcja ma odpowiadający task.
- [ ] Wszystkie 13 decyzji §3 zaimplementowane (canonicalize, cap atomicity, lazy fetch, hard delete, filter "po dodaniu", Redis lock, embed color, last_deaths_scraped_at update logic, success-on-all-channels flag).
- [ ] Wszystkie 9 wierszy Risk+mitigation table mają test/mechanizm.
- [ ] Pre-commit + CI zielone na ostatnim PR.
- [ ] Coverage `apps/deathwatch/` ≥ 85%.
- [ ] Manual smoke przeprowadzony.
- [ ] Zero stack-trace leaks na Discord (CLAUDE.md §8).
- [ ] Zero direct ORM access w pipeline (CLAUDE.md §6) / spider / bot — wszystko przez services.
- [ ] Wszystkie 9 PR-ów zmergowane squash z conventional commit format.
