# Tibiantis Monitor — M4 Implementation Plan

> **For agentic workers:** Ten plan **NIE** jest wykonywany przez Claude. Wykonawcą jest developer (bgozlinski). Claude używa tego dokumentu jako źródła treści dla GitHub Issues — tworzy 1 Issue per task po utworzeniu milestone'u "M4 — Deaths monitor (backend)". Format kroków (`- [ ]`) służy jako acceptance criteria w Issue, nie jako checkboxy dla Claude. Po implementacji każdego Issue Claude wchodzi na PR jako reviewer + dopisuje testy follow-up po accept.

**Goal:** Dostarczyć drugą domenę monitorowaną przez aplikację — śmierci postaci scrapowane z `tibiantis.info/stats/deaths` — do warstwy persistence + GraphQL. Po M4 wszystkie deaths z 5-min interwałem siedzą w Postgres, są filtrowalne po levelu przez `recentDeaths` GraphQL query.

**Architecture:** Reuse M1 (Scrapy spider + DjangoPipeline) + M2 (Strawberry GraphQL + JWT auth dispatch) + M3 (Celery shared_task + subprocess + PeriodicTask seed migration). Nowa aplikacja `apps/deaths/` z czterema warstwami (model, service, task, schema). Pipeline Scrapy rozszerzony o `isinstance(item, ...)` dispatch. Zero Discord, zero notyfikacji, zero nowego procesu — to M5+.

**Tech Stack (dla M4):** Python 3.13, Django 6.0, psycopg3, django-environ, Postgres 16 (Docker), Scrapy + Twisted asyncio reactor, Celery 5.6 + django-celery-beat, Strawberry-Django, simplejwt, pytest + pytest-django.

---

## Źródła

- **Spec techniczny M4:** `docs/superpowers/specs/2026-04-30-m4-deaths-monitor-design.md` (zmergowane PR #77, squash `b552201`).
- **Spec procesu (workflow):** `docs/superpowers/specs/2026-04-17-tibiantis-execution-plan-design.md`.
- **CLAUDE.md** §1 (cel biznesowy), §3 (struktura katalogów), §5 (model `DeathEvent` szkic), §6 (Cel 2 scraping), §7 (Deaths monitor logika), §9 (GraphQL surface), §10 (`DEATH_LEVEL_THRESHOLD` env var).
- **Fixturka:** `tests/fixtures/deaths_sample.html` (zfetch'owana 2026-04-30 z `https://tibiantis.info/stats/deaths`, 33KB, 50 deaths).
- **Wzorce z poprzednich milestones:**
  - M1 spider — `scrapers/tibiantis_scrapers/spiders/character_spider.py`, `tests/unit/scrapers/test_character_spider.py`.
  - M3 task — `apps/characters/tasks.py::scrape_watched_characters`, `tests/integration/test_celery_e2e.py`.
  - M3 PeriodicTask migration — `apps/characters/migrations/0003_seed_default_periodic_task.py`.
  - M2 GraphQL resolver — `apps/characters/schema.py::Query.character`, `apps/accounts/schema.py::Query.me`.

---

## Pre-flight checklist (przed startem D18)

Wykonać **przed** stworzeniem Issues — wszystkie kroki sanity, żeby D-taski miały czystą bazę.

- [ ] **Milestone na GitHub:**
  ```bash
  gh api -X POST repos/bgozlinski/tibiantis-scraper/milestones \
    -f title="M4 — Deaths monitor (backend)" \
    -f description="Deaths scraping from tibiantis.info → DB → GraphQL recentDeaths query. Backend only — zero Discord/notifications/new infra. Strict chain D18 → D22. Spec: docs/superpowers/specs/2026-04-30-m4-deaths-monitor-design.md" \
    -f state=open
  ```
  Zapisać zwrócony `number` (np. 12) — będzie potrzebny przy `gh issue create --milestone <number>`.
- [ ] **5 Issues utworzone** przez `gh issue create --body-file <plik>` (per task #1-5 z tego planu — patrz `gh` commendy w sekcji "Tworzenie Issues" na końcu planu).
- [ ] **Sanity: `gh issue list --milestone "M4 — Deaths monitor (backend)"`** zwraca 5 Issues.
- [ ] **CLAUDE.md spójność:** §10 .env.example template wymienia `DEATH_LEVEL_THRESHOLD=30`, ale **realny `.env.example` w repo go nie ma** (zweryfikowane 2026-04-30). To gap — dorobić w D21 razem z `settings/base.py`. **Nie blokuje startu D18.**
- [ ] **Branch protection na `master`:** wciąż brak required check `test / Pytest` (post-M2/M3 tech debt). **Decyzja:** dodać teraz przed startem M4, żeby M4 PR-y miały full coverage check w CI:
  ```bash
  gh api -X PUT repos/bgozlinski/tibiantis-scraper/branches/master/protection \
    -f required_status_checks[strict]=true \
    -f 'required_status_checks[contexts][]=lint' \
    -f 'required_status_checks[contexts][]=test' \
    ... (zostaw resztę protection bez zmian — patrz current config przez gh api -X GET .../protection)
  ```
  Lub przez UI: Settings → Branches → Edit master rule → dodać `test` do required checks.
- [ ] **Pull master** lokalnie: `git checkout master && git pull origin master` (b552201 — spec M4 + fixturka).

---

## Otwarte pytania do developera (do ustalenia w D-tasku, jeśli w ogóle)

1. **Threshold semantyka — `null` vs missing argument:** spec sekcja 5.D22 mówi `min_level: int | None = None` z fallback do `settings.DEATH_LEVEL_THRESHOLD`. Klient Strawberry może wysłać `recentDeaths { ... }` (missing) lub `recentDeaths(minLevel: null) { ... }` (explicit null) — oba traktowane identycznie (fallback). **Zatwierdzone w brainstormie 2026-04-30.** Brak otwartego pytania.
2. **Pipeline counter w `crawler.stats`:** spec sekcja 5.D20 używa `spider.crawler.stats.inc_value("custom/death_duplicates")`. Strawberry-niezwiązane, ale nawiasem — namespace `custom/` to konwencja Scrapy stats user-defined, nie kolizja z `item_scraped_count`. **Zatwierdzone.**

---

## Task #1 — [M4-D18] `apps/deaths/` + `DeathEvent` model + admin + migracja initial

**Milestone:** M4 — Deaths monitor (backend)
**Czas:** 3h
**Branch:** `feat/<N>-deaths-app-model`
**Type:** `feat`
**Zależy od:** master @ b552201 (spec M4 zmergowany)

### 🎯 Cel
Aplikacja `apps/deaths/` zarejestrowana w Django, model `DeathEvent` w bazie, widoczny w admin pod `/admin/deaths/deathevent/`. Admin pokazuje listę z `level_at_death`, `died_at`, `killed_by`, search po `character_name`, sortowanie po `-died_at`. Migracja initial przechodzi czysto na świeżej bazie.

### 🧠 Czego się nauczysz
- **Differencja `unique=True` vs `unique_together`:** pierwszy na pojedynczym polu, drugi na **parze**. Postgres tworzy btree index dla obu. Pułapka: `db_index=True` na polu które już jest w `unique_together` jest **redundant** dla par (post-M2 retro #28 lekcja). Tutaj `db_index=True` jest na pojedynczym `character_name` (lookup per name), unique jest na `(character_name, died_at)` — brak konfliktu.
- **`auto_now_add` semantyka:** ustawia value przy `objects.create()`, **ignoruje** passed value (M3 retro #61 lekcja). W testach (D19+) sterujemy przez `Model.objects.filter(pk=...).update(...)` post-create.
- **`has_change_permission` vs `has_add_permission`:** dwa różne admin permission knobs. Chcemy zablokować edycję (deaths są immutable), ale zostawić add (manual test row). Default `True` dla obu.
- **`apps.py` `default_auto_field`:** Django 6.0 wymaga explicit `BigAutoField` — `INTEGER` (4 bytes) byłby wąskim gardłem dla deaths (akumulują się szybciej niż characters). M2 #28 retro precedens.

### ✅ Acceptance criteria

#### Aplikacja Django
- [ ] `apps/deaths/__init__.py` (pusty plik).
- [ ] `apps/deaths/apps.py`:
  ```python
  from django.apps import AppConfig


  class DeathsConfig(AppConfig):
      default_auto_field = "django.db.models.BigAutoField"
      name = "apps.deaths"
  ```
- [ ] `config/settings/base.py` — `LOCAL_APPS` rozszerzone o `"apps.deaths.apps.DeathsConfig"`. Sprawdzić istniejący split `DJANGO_APPS` / `THIRD_PARTY_APPS` / `LOCAL_APPS` (z M1 #5).

#### Model
- [ ] `apps/deaths/models.py`:
  ```python
  from django.db import models


  class DeathEvent(models.Model):
      character_name = models.CharField(max_length=64, db_index=True)
      level_at_death = models.PositiveIntegerField()
      killed_by = models.TextField(blank=True, default="")
      died_at = models.DateTimeField(db_index=True)
      scraped_at = models.DateTimeField(auto_now_add=True)

      class Meta:
          unique_together = ("character_name", "died_at")
          ordering = ["-died_at"]

      def __str__(self) -> str:
          return f"{self.character_name} (lvl {self.level_at_death}) @ {self.died_at:%Y-%m-%d %H:%M}"
  ```

#### Admin
- [ ] `apps/deaths/admin.py`:
  ```python
  from django.contrib import admin

  from apps.deaths.models import DeathEvent


  @admin.register(DeathEvent)
  class DeathEventAdmin(admin.ModelAdmin):
      list_display = ("character_name", "level_at_death", "died_at", "killed_by")
      list_filter = ("level_at_death",)
      search_fields = ("character_name",)
      ordering = ("-died_at",)
      readonly_fields = ("scraped_at",)

      def has_change_permission(self, request, obj=None):
          return False
  ```

#### Migracja
- [ ] `poetry run python manage.py makemigrations deaths` wygenerowuje `apps/deaths/migrations/0001_initial.py`.
- [ ] Inspekcja migracji — sprawdzić że ma:
  - `models.PositiveIntegerField()` na `level_at_death`
  - `models.TextField(blank=True, default='')` na `killed_by`
  - `models.DateTimeField(db_index=True)` na `died_at`
  - `unique_together={('character_name', 'died_at')}` w `Meta`
  - `ordering=['-died_at']` w `Meta`
- [ ] `poetry run python manage.py migrate` aplikuje migrację bez błędu.

#### Smoke (manual)
- [ ] `runserver` → `/admin/deaths/deathevent/` zwraca pustą listę (200 OK).
- [ ] Add row z UI admin → zapisuje się. Edit → button niewidoczny / przycisk save daje 403 (read-only).
- [ ] Delete row z UI admin → działa (default permission).

### 📋 Sugerowane kroki

1. `git checkout master && git pull origin master` — fresh master.
2. `git checkout -b feat/<N>-deaths-app-model` (gdzie `<N>` = numer Issue #).
3. Utwórz strukturę katalogów: `mkdir -p apps/deaths/migrations && touch apps/deaths/__init__.py apps/deaths/migrations/__init__.py`.
4. Napisz `apps/deaths/apps.py` (skopiuj z AC + dostosuj name).
5. Dodaj `apps.deaths.apps.DeathsConfig` do `LOCAL_APPS` w `base.py`.
6. Sanity: `poetry run python manage.py check` → no errors. Jeśli `default_auto_field` warning — zignoruj, wyciszany przez `apps.py` config.
7. Napisz `apps/deaths/models.py` (skopiuj z AC).
8. `poetry run python manage.py makemigrations deaths` — sprawdź wygenerowaną migrację.
9. Napisz `apps/deaths/admin.py` (skopiuj z AC).
10. `poetry run python manage.py migrate` — apply migration.
11. `poetry run python manage.py runserver` → `/admin/`. Smoke testy z AC #4.
12. `git add apps/deaths config/settings/base.py && git status` — sprawdź że nic ekstra (pre-commit może auto-fix CRLF).
13. `git commit -m "feat(deaths): add DeathEvent model + admin + initial migration (M4-D18, #<N>)"` — pre-commit zielony, hook conventional-commits passes.
14. `git push -u origin feat/<N>-deaths-app-model`.
15. `gh pr create --base master --title "feat(deaths): add DeathEvent model + admin + initial migration (M4-D18, #<N>)" --body-file .github-pr-body.md` (przygotuj body z `Closes #<N>` + AC checklist).
16. Czekaj na Claude code review (komentarz LGTM + uwagi). Po accept: squash merge jako admin.

### ⚠️ Pułapki do uwagi

- **A — `db_index=True` redundancy:** post-M2 retro #28 lekcja. Tu `db_index=True` jest **tylko** na pojedynczym `character_name`, **nie** na parze. Postgres `UNIQUE (character_name, died_at)` constraint tworzy btree na **całej** parze, ale **nie** osobny single-column index na `character_name`. Dlatego `db_index=True` na samym `character_name` jest sensowny (lookup `WHERE character_name = '...'`). Sanity: po `migrate` sprawdź `\d deaths_deathevent` w psql — powinny być 2 indeksy (`unique` na parę + `btree` na single).
- **B — `auto_now_add=True` w testach:** `Character.objects.create(scraped_at=...)` cicho ignoruje passed value (M3 retro #61). D19+ testy korzystające z `scraped_at` muszą być świadome. **W tym Issue (D18) nie ma testów** (model trywialny), więc Pułapka jest tylko forward-looking dla D19.
- **C — `has_change_permission` blokuje też `add`?** **NIE.** `has_change_permission` dotyczy **edit existing**, `has_add_permission` dotyczy **add new**. Default obu = `True`. Tu blokujemy tylko change → admin może `add` (manualny test row), ale nie edit. Sanity z AC #4 weryfikuje.
- **D — Migration ordering:** `makemigrations` wykryje że `apps.deaths` jest świeże (brak prior state). Jeśli `manage.py check` zgłasza `models have changes that are not yet reflected in a migration` — uruchom `makemigrations` ponownie. Jeśli generuje **dwie** migracje — coś się rozjechało, zacznij od `git clean -f apps/deaths/migrations/`.
- **E — Schema drift z `apps.characters`:** post-M2 wykryto że `makemigrations` wygenerował niezamówioną migrację `0002_remove_character_characters__name_6d8b81_idx`. Pre-flight: `poetry run python manage.py makemigrations --dry-run` przed napisaniem `models.py` — jeśli pokazuje cokolwiek, ktoś zostawił schema drift na master (mało prawdopodobne, ale check). M4 nie powinno tego mieć.

### 🧪 Testing plan

**Brak testów w tym Issue.** Model trywialny — testy services + spider w D19/D20. Migracja sprawdzana przez `manage.py migrate` bez błędu.

**Claude weryfikuje po PR:**
- Migracja ma `unique_together` i `db_index` jak spec.
- Brak `db_index=True` redundantnego na polach z `unique_together`.
- `apps.py` ma `default_auto_field = BigAutoField`.
- `admin.py` ma `has_change_permission = False` (read-only edit), `has_add_permission` default (True).

### 🔗 Dokumentacja pomocnicza

- Django `unique_together`: https://docs.djangoproject.com/en/6.0/ref/models/options/#unique-together
- `Meta.ordering` vs explicit `order_by`: https://docs.djangoproject.com/en/6.0/ref/models/options/#ordering
- `ModelAdmin` permissions: https://docs.djangoproject.com/en/6.0/ref/contrib/admin/#django.contrib.admin.ModelAdmin.has_change_permission
- `auto_now_add` gotcha: https://docs.djangoproject.com/en/6.0/ref/models/fields/#datefield (sekcja "auto_now_add")

### 📦 Definition of Done

- [ ] AC spełnione (sekcje Aplikacja, Model, Admin, Migracja, Smoke).
- [ ] PR zmergowany squash (`feat(deaths): add DeathEvent model + admin + initial migration (M4-D18, #<N>)`).
- [ ] Pre-commit + CI lint + CI test zielone.
- [ ] Issue zamknięty (`Closes #<N>` w PR body).

---

## Task #2 — [M4-D19] Spider `deaths_spider` + `DeathItem` + pipeline dispatch + unit testy spider'a

**Milestone:** M4 — Deaths monitor (backend)
**Czas:** 4h
**Branch:** `feat/<N>-deaths-spider`
**Type:** `feat`
**Zależy od:** D18 merged

### 🎯 Cel
Spider `deaths` parsuje `tibiantis.info/stats/deaths` (HTML fixturka albo live), yieldsy `DeathItem` z 4 polami (`character_name`, `level_at_death`, `killed_by`, `died_at` w UTC). Pipeline dispatch przez `isinstance(item, ...)` wywołuje `save_death_event` dla `DeathItem` (service jeszcze nie istnieje — D20, ale import lazy w `elif` brachu jest OK). Unit testy spidera: 50 deaths z fixturki, edge cases na synthetic HTML (PvP killer, monster killer, level extraction, TZ conversion, `td.lu` vs `td.ld`).

### 🧠 Czego się nauczysz
- **Scrapy CSS selectors quirks:** `td.m, td.md` jako combined selector (dwa class names alternatywnie). `td.m:last-child` (pseudo-class na position) różni się od `td.m + td.m` (sibling). M4 spider używa `:last-child` bo killer jest zawsze ostatnim td.
- **`HtmlResponse` w testach:** budujesz lokalne `Response` z body zapisanej fixturki, omijasz network. M1 retro #7 lekcja zaaplikowana — wszystkie spider tests są offline.
- **TZ conversion w Django USE_TZ=True:** Django zapisuje datetimes w UTC. Spider produkuje `datetime` z `tzinfo=ZoneInfo("Europe/Berlin")` — Django ORM przy save automatycznie konwertuje do UTC. Test asercji powinien używać UTC (`datetime(2026, 4, 30, 3, 25, 12, tzinfo=UTC)` dla `2026-04-30 05:25:12` CEST).
- **`isinstance` dispatch w pipeline:** alternatywa do osobnych pipeline classes per item type. Trade-off: prostota (1 plik, 1 klasa) vs idiomaticness (Scrapy zachęca osobne pipelines). Dla 2 item types — `isinstance` wygrywa.
- **`<nick>` as non-standard HTML tag:** lxml/parsel toleruje, ale defensive parsing wymaga generic `td:last-child ::text` zamiast celowania w `<nick>`. Forward-looking robustness.
- **Per-row try/except:** jedna popsuta krotka HTML nie powinna killować całego batcha. Spider `parse` używa generatora — `yield from` z try wewnątrz pętli rzedzi.

### ✅ Acceptance criteria

#### Items
- [ ] `scrapers/tibiantis_scrapers/items.py` rozszerzony o `DeathItem(Item)`:
  ```python
  class DeathItem(Item):
      character_name = Field()
      level_at_death = Field()
      killed_by = Field()
      died_at = Field()
  ```

#### Spider
- [ ] `scrapers/tibiantis_scrapers/spiders/deaths_spider.py` — full implementacja per spec sekcja 5.D19. Kluczowe założenia:
  - `name = "deaths"` (używane przez `scrapy crawl deaths`).
  - `start_urls = ["https://tibiantis.info/stats/deaths"]`.
  - `parse(response)`: `rows = response.css("table.mytab.long tr")[1:]` (skip header). Pusty list → log warning + return.
  - Per-row: try/except `(AttributeError, ValueError)` — log warning, continue.
  - Per-row parsing:
    - **Name:** `row.css("td.ld a::text, td.lu a::text").get("").strip()`.
    - **Level:** regex `r"\((\d+)\)"` na text whole `td.ld` lub `td.lu`. `int(match.group(1))`.
    - **Date:** `tds = row.css("td.m, td.md")` → `tds[1]` (third visible td after td.ld/lu icon-td). `datetime.strptime("%Y-%m-%d %H:%M:%S")` + `tzinfo=ZoneInfo("Europe/Berlin")`.
    - **Killer:** `"".join(row.css("td.m:last-child ::text, td.md:last-child ::text").getall()).strip()` — pickup zarówno `<nick>X</nick> (17)` jak i plain `a slime`.
- [ ] `scrapers/tibiantis_scrapers/spiders/deaths_spider.py` używa `re` module (top-level import + class-level `_LEVEL_RE = re.compile(r"\((\d+)\)")` dla cache).

#### Pipeline dispatch
- [ ] `scrapers/tibiantis_scrapers/pipelines.py` rozszerzony:
  ```python
  from asgiref.sync import sync_to_async
  from scrapers.tibiantis_scrapers.items import CharacterItem, DeathItem


  class DjangoPipeline:
      async def process_item(self, item, spider):
          if isinstance(item, CharacterItem):
              from apps.characters.services import upsert_character
              await sync_to_async(upsert_character)(dict(item))
          elif isinstance(item, DeathItem):
              from apps.deaths.services import save_death_event  # DEFINED IN D20
              await sync_to_async(save_death_event)(dict(item))
          return item
  ```
  **Note:** `apps.deaths.services.save_death_event` **nie istnieje jeszcze w D19** — zostanie dodany w D20. Lazy import w `elif` branchu **nie wybuchnie przy starcie**, tylko gdy pipeline faktycznie dostanie `DeathItem`. W D19 testach pipeline'a — patch `save_death_event` (też nieistniejący jeszcze, użyj `unittest.mock.patch("apps.deaths.services.save_death_event", create=True)` lub patchuj w `sys.modules`).

  **Alternatywa:** dodać w D19 plik `apps/deaths/services.py` z **stubem** `def save_death_event(payload): raise NotImplementedError`. Kosmetycznie czyściej (no `create=True` w mockach), ale tworzy dodatkowy noise. **Wybór:** stub w D19 (1 linia), full impl w D20.

#### Unit testy spider'a
- [ ] `tests/unit/scrapers/test_deaths_spider.py` — wzór 1:1 z `tests/unit/scrapers/test_character_spider.py`:
  - `FIXTURE_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "deaths_sample.html"`.
  - Fixture pytest `deaths_response` budujący `HtmlResponse` z fixturki.
  - Helper `_build_deaths_html(rows: list[dict])` — synthetic HTML dla edge cases:
    ```python
    def _build_deaths_html(rows: list[dict]) -> bytes:
        tr_html = ""
        for row in rows:
            tr_html += f"""
            <tr>
                <td class='{row.get("name_class", "ld")}'>
                    <a href='/stats/player/{row['name']}'>{row['name']}</a>
                    ({row['level']})
                </td>
                <td class='m'><a href='...'><img/></a></td>
                <td class='m'>{row['died_at']}</td>
                <td class='{row.get("killer_class", "m")}'>{row['killer']}</td>
            </tr>
            """
        body = f"<html><body><table class='mytab long'><tr><th></th><th></th><th></th><th></th></tr>{tr_html}</table></body></html>"
        return body.encode("utf-8")
    ```
  - Test cases:
    - `test_yields_50_deaths` — fixturka → `len(list(spider.parse(response))) == 50`.
    - `test_pvp_killer_parsed` — fixture pierwszy rząd `<nick>Beaga</nick> (17)` → `item["killed_by"]` zawiera `"Beaga"` i `"(17)"`.
    - `test_monster_killer_parsed` — synthetic helper z `killer="a slime"` → `item["killed_by"] == "a slime"`.
    - `test_level_extracted_from_parens` — fixture pierwszy rząd Hakin Ace → `item["level_at_death"] == 10`.
    - `test_died_at_converted_to_utc` — fixture pierwszy rząd `2026-04-30 05:25:12` Berlin → after Django ORM save (lub direct check) → `datetime(2026, 4, 30, 3, 25, 12, tzinfo=UTC)`. **Note:** spider zwraca datetime **z** `tzinfo=ZoneInfo("Europe/Berlin")`, konwersja do UTC dzieje się przy save w ORM. W teście spidera asercja na `tzinfo` powinna być `Europe/Berlin`, **nie** UTC.
    - `test_lu_class_row_parsed_same_as_ld` — synthetic helper z `name_class="lu"` → parses OK identycznie jak `ld`.
    - `test_warning_on_empty_table_uses_url` — synthetic empty table → `caplog.records[0].message` zawiera URL, **nie** hardcoded "deaths" (regression guard z M1 retro #7).
    - `test_row_parse_error_does_not_kill_batch` — synthetic z 2 dobrymi + 1 popsuty (np. brak `(level)` w nawiasie) → spider yieldsy 2 items + 1 warning logged.
    - `test_killer_with_special_chars` — synthetic helper z `killer="& monster <name>"` (HTML entities + special chars) → spider robi `.strip()` ale nie escape'uje (Scrapy parse już zdekodowało).

#### Unit testy pipeline'a
- [ ] `tests/unit/scrapers/test_pipeline.py` — extend istniejący plik:
  - `test_death_item_dispatched_to_save_death_event` — patch `apps.deaths.services.save_death_event` (lub `create=True` jeśli stuba jeszcze nie ma), `process_item(DeathItem(...), spider=mock)` → mock called once z `dict(item)`.
  - `test_character_item_still_dispatched_to_upsert_character` — regression guard, M1 path nie zepsuty (test już istnieje? Sprawdzić — jeśli nie, dodać).
- [ ] **Decyzja Pipeline impl:** czy włożyć stub `save_death_event` w D19, czy używać `create=True` w mock?
  - **Rekomendacja: stub** w `apps/deaths/services.py`:
    ```python
    def save_death_event(payload: dict) -> None:
        """STUB — full implementation in D20. Pipeline imports lazily."""
        raise NotImplementedError("save_death_event will be implemented in D20")
    ```
    Pipeline test patch'uje normalnie (`patch("apps.deaths.services.save_death_event")`), bez `create=True`. Plik `services.py` będzie nadpisany w D20.

### 📋 Sugerowane kroki

1. `git checkout master && git pull origin master`.
2. `git checkout -b feat/<N>-deaths-spider`.
3. **Items first** — extend `scrapers/tibiantis_scrapers/items.py` o `DeathItem`. Smoke: `from scrapers.tibiantis_scrapers.items import DeathItem` w `python -c`.
4. **Stub services** — `apps/deaths/services.py` z `def save_death_event(payload): raise NotImplementedError(...)`. (Plik zostanie nadpisany w D20.)
5. **Pipeline** — extend `pipelines.py` o `elif isinstance(item, DeathItem)` branch z lazy import.
6. **Pipeline tests** — `tests/unit/scrapers/test_pipeline.py` extend o 2 testy. Run: `poetry run pytest tests/unit/scrapers/test_pipeline.py -v` → green.
7. **Spider** — `scrapers/tibiantis_scrapers/spiders/deaths_spider.py` per AC.
8. **Spider tests** — `tests/unit/scrapers/test_deaths_spider.py`. Run: `poetry run pytest tests/unit/scrapers/test_deaths_spider.py -v` → 9 testów green (5 fixture-based + 4 synthetic).
9. **Smoke manual:** `poetry run scrapy crawl deaths -s ROBOTSTXT_OBEY=False` (bez ORM, z roota repo). Czytaj log — spider pobiera stronę, parsuje 50 rzędów, ale pipeline rzuca `NotImplementedError`. **Akceptowalne** — to D20 zadanie. **Sanity z perspektywy spider'a:** logging line "Crawled 1 pages" + brak parse warningów = OK.
10. **Pre-commit run** — `poetry run pre-commit run --all-files` lokalnie. Mypy może zgłaszać `[no-untyped-def]` dla `parse(self, response)` — Scrapy spider classes są typowane luźno, użyj `# type: ignore[no-untyped-def]` lub explicit hint `def parse(self, response: scrapy.http.Response) -> Iterator[DeathItem]:`. Wybór: explicit hint, czystsze.
11. `git add ... && git commit -m "feat(deaths): add deaths_spider + DeathItem + pipeline dispatch (M4-D19, #<N>)"`.
12. Push + PR + review.

### ⚠️ Pułapki do uwagi

- **A — `td.lu` rzędy pomijane:** spider ma 2 alternatywne klasy na td name (`ld` lost level, `lu` no loss). Selector `td.ld a::text, td.lu a::text` MUSI mieć przecinek (CSS OR). Zapomnienie `lu` → ~8% rzędów (4/50 w fixturce) pomijane. Test `test_lu_class_row_parsed_same_as_ld` to złapie.
- **B — `<nick>` non-standard tag:** parsel/lxml toleruje, ale specyficzne celowanie selektorem (np. `nick::text`) jest fragile. Spec używa generic `td:last-child ::text` (whole td text content) — defensive. Jeśli kiedyś strona zmieni `<nick>` na `<span class="nick">`, spider nadal zadziała.
- **C — `td.m` vs `td.md` w killer column:** w fixturce zauważone że niektóre killer cells mają `class="md"` (PvP — color highlight), inne `class="m"` (mob). Selector MUSI obejmować obie alternatywy: `td.m:last-child, td.md:last-child`. Bez obu — ~30% rzędów ma killer pomijany.
- **D — `tds[1]` vs `tds[2]`:** indeksowanie listy `tds` po selektorze `td.m, td.md` zwraca 3 elementy (icon, date, killer — pomija `td.ld/lu` które nie matchują selektora). `tds[1]` to **date**, `tds[-1]` to **killer**. Łatwo pomylić — sanity check w teście synthetic.
- **E — TZ conversion timing:** spider zwraca datetime **przed** ORM save. `Europe/Berlin` w spider'ze, **UTC** w bazie. Test spider'a asercjuje TZ-aware datetime z `Europe/Berlin`. Test integration (D22) asercjuje `DeathEvent.died_at.tzinfo == UTC` (Django USE_TZ=True). Don't mix.
- **F — Per-row try/except:** spec mówi `except (AttributeError, ValueError)`. Inne wyjątki (np. `KeyError` na missing CSS class) **propagują**. Decyzja świadoma — error w parsowaniu pojedynczego rzędu = log + skip; error w parsowaniu structure HTML (whole table missing) = let it propagate (Scrapy log handler złapie + spider close error).
- **G — `caplog` w pytest dla logger warning:** pytest fixture `caplog` przechwytuje. Wymaga `caplog.set_level(logging.WARNING, logger="scrapers.tibiantis_scrapers.spiders.deaths_spider")` na początku testu — bez tego `caplog.records` może być puste mimo że warning był wyemitowany.
- **H — Fragile fixture path `parents[3]`:** post-M2 tech debt, niezamknięte. Spec D19 mówi zostawić dla spójności z M1. **Refactor do `tests/conftest.py` w osobnym chore PR post-M4** — nie blokuj M4.

### 🧪 Testing plan

- **Unit testy spider'a:** 9 testów (5 fixture-based + 4 synthetic). Run lokalnie + CI.
- **Unit testy pipeline'a:** 2 testy (death dispatch + character regression).
- **Smoke manual:** `scrapy crawl deaths -s ROBOTSTXT_OBEY=False` z roota repo. Spider pobiera live stronę, pipeline rzuca `NotImplementedError` (akceptowalne — D20 doda impl). **Po D20 manual smoke pełny.**
- **Coverage cel:** `apps/deaths/services.py` skipped (stub), `scrapers/tibiantis_scrapers/spiders/deaths_spider.py` ≥ 90%, `scrapers/tibiantis_scrapers/pipelines.py` 100% (mały plik).

**Claude weryfikuje po PR:**
- Selectors covering both `ld` and `lu`, both `m` and `md`.
- Per-row try/except nie kasuje całego batcha.
- TZ assertions w testach na poziomie spider — `Europe/Berlin`, nie UTC.
- Pipeline dispatch lazy import w branchu (a nie top-level), żeby M1 path nie ładował niepotrzebnie `apps.deaths.services`.

### 🔗 Dokumentacja pomocnicza

- Scrapy CSS selectors: https://docs.scrapy.org/en/latest/topics/selectors.html#using-selectors
- `HtmlResponse` w testach: https://docs.scrapy.org/en/latest/topics/request-response.html#scrapy.http.Response
- `pytest caplog` fixture: https://docs.pytest.org/en/stable/how-to/logging.html
- `unittest.mock.patch` z `create=True`: https://docs.python.org/3/library/unittest.mock.html#patch
- `ZoneInfo` (PEP 615): https://docs.python.org/3/library/zoneinfo.html

### 📦 Definition of Done

- [ ] AC spełnione (Items, Spider, Pipeline dispatch, Unit testy spider'a 9, Unit testy pipeline'a 2).
- [ ] Stub `save_death_event` w `apps/deaths/services.py` (do nadpisania w D20).
- [ ] PR zmergowany squash (`feat(deaths): add deaths_spider + DeathItem + pipeline dispatch (M4-D19, #<N>)`).
- [ ] CI lint + test zielone (`pytest tests/unit/scrapers/ -v`).
- [ ] Issue zamknięty.

---

## Task #3 — [M4-D20] Service `save_death_event` + management command `scrape_deaths` + JSON output

**Milestone:** M4 — Deaths monitor (backend)
**Czas:** 3h
**Branch:** `feat/<N>-deaths-service-cmd`
**Type:** `feat`
**Zależy od:** D19 merged

### 🎯 Cel
Service `save_death_event(payload)` zapisuje `DeathEvent` z dedup przez `IntegrityError` catch (return `None` na duplikat). Management command `python manage.py scrape_deaths` uruchamia spider'a z D19, na końcu wypluwa JSON `{"yielded": N, "duplicates": M}` na stdout (parse'owalne przez Celery task w D21). Pipeline w D19 zostaje rozszerzony o counter — gdy `save_death_event` zwraca `None`, `crawler.stats.inc_value("custom/death_duplicates")`.

### 🧠 Czego się nauczysz
- **Skip-on-duplicate semantyka:** `try ... DeathEvent.objects.create(...) except IntegrityError: return None`. Asymetria do M3 `upsert_character` (Character mutable → retry; DeathEvent immutable → skip). **Decyzja designowa** — zapisz w docstring.
- **Scrapy CrawlerProcess lifetime:** `CrawlerProcess.start()` można wywołać **tylko raz** w lifetime procesu (Twisted reactor jest single-shot). Każde `manage.py scrape_deaths` spawn'uje fresh subprocess (z M3 task'a) — OK. Ale w testach unit **NIE** wolno wywoływać prawdziwego — mock cały klass.
- **`crawler.stats` namespace:** `inc_value("custom/death_duplicates")` używa konwencji prefiksu `custom/` dla user-defined stats. Bez prefiksu → potencjalna kolizja z built-in (`item_scraped_count`, `downloader/request_count`).
- **`install_root_handler=False` w `CrawlerProcess`:** Scrapy domyślnie instaluje swój logging handler — kolidowałby z Django logging. Bez tego flag'a clean stdout dla JSON parse.
- **`call_command` w testach:** `from django.core.management import call_command; call_command("scrape_deaths")` uruchamia mgmt cmd in-process. Mock `CrawlerProcess` żeby nie hitować HTTP.

### ✅ Acceptance criteria

#### Service
- [ ] `apps/deaths/services.py` (nadpisanie stuba z D19):
  ```python
  from datetime import datetime
  from typing import TypedDict

  from django.db import IntegrityError, transaction

  from apps.deaths.models import DeathEvent


  class DeathPayload(TypedDict):
      character_name: str
      level_at_death: int
      killed_by: str
      died_at: datetime


  def save_death_event(payload: DeathPayload) -> DeathEvent | None:
      """Create DeathEvent or skip silently on dedup hit.

      Returns None when (character_name, died_at) already exists in DB.
      Deaths are immutable — no upsert semantics. Caller (pipeline) ignores
      return value, but pipeline's stats counter inc'es on None to track
      duplicates for observability.
      """
      try:
          with transaction.atomic():
              return DeathEvent.objects.create(**payload)
      except IntegrityError:
          return None
  ```
- [ ] **Decyzja `TypedDict` vs alias:** istnieje precedens w `apps/characters/types.py` dla `CharacterPayload`. Dla M4 **skonsoliduj** — `apps/deaths/types.py` z `DeathPayload` (osobny plik dla typu, mirror M1 #6).

#### Management command
- [ ] `apps/deaths/management/commands/scrape_deaths.py`:
  ```python
  import json

  from django.core.management.base import BaseCommand
  from scrapy.crawler import CrawlerProcess
  from scrapy.utils.project import get_project_settings

  from scrapers.tibiantis_scrapers.spiders.deaths_spider import DeathsSpider


  class Command(BaseCommand):
      help = "Scrape latest deaths from tibiantis.info/stats/deaths"

      def handle(self, *args, **options):
          settings = get_project_settings()
          process = CrawlerProcess(settings=settings, install_root_handler=False)
          crawler = process.create_crawler(DeathsSpider)
          process.crawl(crawler)
          process.start()  # blocks until spider closes

          stats = crawler.stats.get_stats()
          yielded = stats.get("item_scraped_count", 0)
          duplicates = stats.get("custom/death_duplicates", 0)

          self.stdout.write(json.dumps({"yielded": yielded, "duplicates": duplicates}))
  ```
- [ ] `apps/deaths/management/__init__.py` + `apps/deaths/management/commands/__init__.py` (puste pliki — Django magic).

#### Pipeline counter
- [ ] `scrapers/tibiantis_scrapers/pipelines.py` rozszerzony — w gałęzi `DeathItem` capture return value + inc `custom/death_duplicates` gdy `None`:
  ```python
  elif isinstance(item, DeathItem):
      from apps.deaths.services import save_death_event
      result = await sync_to_async(save_death_event)(dict(item))
      if result is None:
          spider.crawler.stats.inc_value("custom/death_duplicates")
  ```

#### Unit testy service'u
- [ ] `tests/unit/deaths/__init__.py` (utworzyć katalog).
- [ ] `tests/unit/deaths/test_save_death_event.py`:
  - `test_create_returns_event` — payload → `DeathEvent` w DB, return non-None.
  - `test_duplicate_returns_none` — drugi save z identycznym `(character_name, died_at)` → return `None`, `DeathEvent.objects.count() == 1`.
  - `test_different_died_at_creates_two_events` — same name, różne timestamps → 2 rzędy.
  - `test_integrity_error_caught_silently` — assert no `log.error` emitted (capture log z `caplog`).
  - `test_payload_without_required_field_raises` — payload bez `character_name` → `TypeError` (Django ORM).

#### Unit testy management commanda
- [ ] `tests/unit/deaths/test_scrape_deaths_command.py`:
  - `test_command_outputs_json_summary` — mock `CrawlerProcess`, mock crawler.stats z `{"item_scraped_count": 50, "custom/death_duplicates": 0}` → stdout JSON `{"yielded": 50, "duplicates": 0}`. Użyj `call_command` + `StringIO` capture.
  - `test_command_uses_deaths_spider` — mock `process.crawl`, assert called z `DeathsSpider` (lub `crawler` z `DeathsSpider` jako spider attr).

#### Pipeline counter test (extend D19 testy)
- [ ] `tests/unit/scrapers/test_pipeline.py` extend o `test_death_pipeline_increments_duplicates_counter`:
  - Mock `save_death_event` zwraca `None` (duplikat).
  - Mock `spider.crawler.stats.inc_value`.
  - Process item → assert `inc_value` called once z `"custom/death_duplicates"`.

#### Smoke manual
- [ ] `poetry run python manage.py scrape_deaths` → JSON na stdout, returncode 0. **Wymaga że spider z D19 działa live** (`tibiantis.info` reachable). Akceptowalne odpalenie raz przed PR.
- [ ] Sprawdź `DeathEvent.objects.count()` po pierwszym scrape — powinno być 50 (lub mniej jeśli niektóre rzędy popsute).
- [ ] Drugi `scrape_deaths` → stdout `{"yielded": 50, "duplicates": 50}`, count nadal 50 (dedup zadziałał).

### 📋 Sugerowane kroki

1. `git checkout master && git pull origin master`.
2. `git checkout -b feat/<N>-deaths-service-cmd`.
3. **Service first** — nadpisz `apps/deaths/services.py` (z stuba D19) full impl.
4. **Types module** — `apps/deaths/types.py` z `DeathPayload` (jeśli decyzja "osobny plik").
5. **Service tests** — `tests/unit/deaths/test_save_death_event.py`. Run: `pytest tests/unit/deaths/test_save_death_event.py -v` → 5 green.
6. **Management command** — `apps/deaths/management/commands/scrape_deaths.py`.
7. **Mgmt command tests** — `tests/unit/deaths/test_scrape_deaths_command.py`. Run: 2 green.
8. **Pipeline counter** — extend `pipelines.py` (capture return + inc_value).
9. **Pipeline counter test** — extend `tests/unit/scrapers/test_pipeline.py`. Run: green.
10. **Smoke manual** — z punktu AC #5 (live `scrape_deaths`).
11. **Pre-commit + push + PR.**

### ⚠️ Pułapki do uwagi

- **A — `CrawlerProcess.start()` only-once:** Twisted reactor jest single-shot per process. Drugi `process.start()` w tym samym Pythonie → `ReactorAlreadyRunning`. **W testach unit NIE wywołuj prawdziwego** — mock cały `CrawlerProcess`. Manual smoke OK bo każdy `manage.py` to fresh subprocess.
- **B — `IntegrityError` w `transaction.atomic()`:** bez `atomic()` IntegrityError aborts całej transakcji request/test → potem każdy ORM call rzuca `TransactionManagementError`. `transaction.atomic()` tworzy savepoint — IntegrityError aborts tylko savepoint, outer transaction zostaje czysta. **Krytyczne** w testach Django (każdy test jest w transaction).
- **C — `stats.get_stats()` dict copy:** zwraca **kopię** stats dict. Modyfikacja kopii nie wpływa na live stats. W mgmt command robimy tylko `.get()` — bezpieczne. W testach mock'uj `stats.get_stats` zwracając dict bezpośrednio.
- **D — `install_root_handler=False`:** bez tego CrawlerProcess instaluje globalny logging handler — Django logging traci config, mgmt command stdout ma śmieci ze Scrapy log. JSON parse wybuchnie. **Krytyczne** dla D21 task.
- **E — `service` nie loguje IntegrityError:** spec mówi "no `log.error` emitted on dedup". Łatwo przeoczyć i dodać `logger.warning("duplicate skipped")` które robi szum w prod (5-min interval × 50 deaths × 49 duplicates = 588 warn/h). **Decyzja:** zero log noise w service. Dedup counter w pipeline daje observability.
- **F — Pipeline `result is None` check kolejność:** jeśli zmienisz pipeline na inny pattern (np. `if isinstance(item, DeathItem) and (result := await ...) is None: stats.inc_value(...)`), uważaj na walrus i `await` w tym samym warunku — Python 3.10+ działa, ale czytelność spada. Spec używa explicit `result = await ...; if result is None: ...` — czystsze.
- **G — `apps/deaths/services.py` nadpisanie stuba z D19:** sanity przed commit'em — `git diff apps/deaths/services.py` pokazuje, że stub `raise NotImplementedError` jest zastąpiony pełną impl. Zapomnienie → pipeline nadal rzuca `NotImplementedError` w runtime.

### 🧪 Testing plan

- **Unit testy service:** 5 testów (create, dup return None, different died_at, no log on dup, payload validation).
- **Unit testy mgmt command:** 2 testy (JSON output, spider class).
- **Unit testy pipeline counter:** 1 test (inc_value on None return).
- **Smoke manual:** live `manage.py scrape_deaths` x2 (verify dedup).
- **Coverage cel:** `apps/deaths/services.py` 100% (mały, branche tested), `apps/deaths/management/commands/scrape_deaths.py` 90%+ (CrawlerProcess.start path skipped przez mock).

**Claude weryfikuje po PR:**
- Service używa `transaction.atomic()` przed `create()`.
- IntegrityError catch zwraca `None`, nie raise'uje.
- Brak log.warning/error w service na dedup.
- Pipeline counter zlicza tylko `None` returns (nie inne exceptions — propagują).
- Mgmt command nie loguje na stdout poza JSON (sanity dla D21 parse).

### 🔗 Dokumentacja pomocnicza

- `transaction.atomic()`: https://docs.djangoproject.com/en/6.0/topics/db/transactions/#django.db.transaction.atomic
- Scrapy `CrawlerProcess`: https://docs.scrapy.org/en/latest/topics/practices.html#run-scrapy-from-a-script
- `crawler.stats` API: https://docs.scrapy.org/en/latest/topics/stats.html
- Django `call_command`: https://docs.djangoproject.com/en/6.0/ref/django-admin/#running-management-commands-from-your-code
- `TypedDict`: https://docs.python.org/3/library/typing.html#typing.TypedDict

### 📦 Definition of Done

- [ ] AC spełnione (Service, Mgmt command, Pipeline counter, Unit testy 5+2+1, Smoke manual).
- [ ] PR zmergowany squash (`feat(deaths): add save_death_event service + scrape_deaths command (M4-D20, #<N>)`).
- [ ] CI lint + test zielone.
- [ ] `apps/deaths/services.py` 100% covered, ~5 stmts.
- [ ] Issue zamknięty.

---

## Task #4 — [M4-D21] Celery task `scrape_deaths` + PeriodicTask seed migration

**Milestone:** M4 — Deaths monitor (backend)
**Czas:** 3h
**Branch:** `feat/<N>-scheduled-deaths-scrape`
**Type:** `feat`
**Zależy od:** D20 merged

### 🎯 Cel
Celery task `apps.deaths.tasks.scrape_deaths` uruchamia subprocess `python manage.py scrape_deaths` (timeout 120s), parsuje JSON ze stdout, zwraca `{"yielded": N, "duplicates": M, "returncode": 0}`. PeriodicTask seed migration tworzy `IntervalSchedule(every=5, period=MINUTES)` + `PeriodicTask(name="scrape_deaths", task="apps.deaths.tasks.scrape_deaths", enabled=False)`. `DEATH_LEVEL_THRESHOLD` env var dodany do `.env.example` + `config/settings/base.py` (gap odkryty 2026-04-30 pre-flight).

### 🧠 Czego się nauczysz
- **`@shared_task(bind=True, max_retries=2)`:** `bind=True` daje task'owi self-reference (`self`) potrzebny do `self.retry()`. `max_retries=2` to **task-level errors** (DB unreachable, subprocess timeout) — per-row scrape errors są wewnątrz subprocess, nie eskalują tutaj.
- **`subprocess.run` Windows specifics:** `timeout=` na Windows używa `TerminateProcess` (Linux: SIGTERM). Mniej graceful, ale działa. M3 D16 precedens.
- **`text=True` w subprocess:** zwraca `stdout` jako `str`, nie `bytes`. `json.loads(str)` działa. Bez `text=True` musiałbyś `result.stdout.decode("utf-8")` — niepotrzebny extra krok.
- **PeriodicTask seed migration `dependencies`:** musi mieć `("django_celery_beat", "0001_initial")` — tabele `IntervalSchedule`/`PeriodicTask` muszą istnieć przed seed'em. M3 D16 precedens.
- **`enabled=False` default:** sanity pre-prod — admin enable'uje świadomie po smoke testach. Bez tego self-firing migration mógłby uruchomić task przed konfiguracją worker'a.
- **Triple-source-of-truth dla deps (M3 lekcja):** każdy nowy `env(...)` w `settings/base.py` wymaga 3 miejsc — `.env.example` + `config/settings/base.py` + `.github/workflows/ci.yml`. Tutaj dotyczy `DEATH_LEVEL_THRESHOLD` (resolver D22 czyta) — sprawdzić wszystkie 3 jeszcze w D21 albo D22.

### ✅ Acceptance criteria

#### Settings + env
- [ ] `.env.example` rozszerzone o `DEATH_LEVEL_THRESHOLD=30` (sprawdzić, czy nie ma już z M3 — gap pre-flight 2026-04-30).
- [ ] `config/settings/base.py` rozszerzone o:
  ```python
  DEATH_LEVEL_THRESHOLD = env.int("DEATH_LEVEL_THRESHOLD", default=30)
  ```
  W sekcji już istniejących Celery/scrape settings, np. po `CELERY_SCRAPE_FRESHNESS_MINUTES`.
- [ ] `.github/workflows/ci.yml` `env:` block w `test` job rozszerzone o `DEATH_LEVEL_THRESHOLD: "30"` (jeśli `base.py` wymaga env zamiast default — sprawdzić, default 30 oznacza że env jest **opcjonalny**, więc CI nie wymaga jeśli `default=30` w `env.int`).

#### Celery task
- [ ] `apps/deaths/tasks.py`:
  ```python
  import json
  import logging
  import subprocess
  import sys
  from typing import Any

  from celery import shared_task

  logger = logging.getLogger(__name__)


  @shared_task(bind=True, max_retries=2)
  def scrape_deaths(self: Any) -> dict[str, int]:
      """Scrape deaths from tibiantis.info via subprocess scrape_deaths.

      Subprocess isolates Twisted reactor from Celery worker pool (M1 retro #8).
      Parses JSON summary from stdout for observability.

      Returns: {"yielded": int, "duplicates": int, "returncode": int}
      Sentinel values (-1, -1) if JSON parse fails (subprocess crashed before print).
      """
      try:
          result = subprocess.run(
              [sys.executable, "manage.py", "scrape_deaths"],
              timeout=120,
              check=False,
              capture_output=True,
              text=True,
          )
      except subprocess.TimeoutExpired as exc:
          logger.warning("scrape_deaths subprocess timed out: %s", exc)
          raise self.retry(exc=exc, countdown=60) from exc

      if result.returncode != 0:
          logger.warning(
              "scrape_deaths subprocess returncode=%s stderr=%s",
              result.returncode, result.stderr[:500],
          )

      try:
          summary = json.loads(result.stdout)
      except json.JSONDecodeError:
          logger.error("scrape_deaths stdout not JSON: %s", result.stdout[:500])
          return {"yielded": -1, "duplicates": -1, "returncode": result.returncode}

      summary["returncode"] = result.returncode
      logger.info("scrape_deaths: %s", summary)
      return summary
  ```

#### PeriodicTask seed migration
- [ ] `apps/deaths/migrations/0002_seed_periodic_task.py`:
  ```python
  from django.db import migrations


  def create_periodic_task(apps, schema_editor):
      IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
      PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

      schedule, _ = IntervalSchedule.objects.get_or_create(
          every=5,
          period="minutes",
      )
      PeriodicTask.objects.get_or_create(
          name="scrape_deaths",
          defaults={
              "task": "apps.deaths.tasks.scrape_deaths",
              "interval": schedule,
              "enabled": False,
          },
      )


  def remove_periodic_task(apps, schema_editor):
      PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
      PeriodicTask.objects.filter(name="scrape_deaths").delete()


  class Migration(migrations.Migration):
      dependencies = [
          ("deaths", "0001_initial"),
          ("django_celery_beat", "0001_initial"),
      ]
      operations = [migrations.RunPython(create_periodic_task, remove_periodic_task)]
  ```

#### Pre-commit `mypy` additional_dependencies (jeśli Celery missing)
- [ ] Sprawdzić `.pre-commit-config.yaml` — czy `mypy` hook ma `celery` i `django-celery-beat` w `additional_dependencies`. **Powinno być z M3 #66.** Jeśli brakuje — dodać. W razie wątpliwości: `poetry run pre-commit run mypy --all-files` lokalnie ZIELONY = OK.

#### Smoke manual
- [ ] `poetry run python -c "from apps.deaths.tasks import scrape_deaths; print(scrape_deaths.delay().get(timeout=130))"` (z worker'em uruchomionym + Redis dostępny) → dict z `{"yielded": ..., "duplicates": ..., "returncode": 0}`.
- [ ] W admin Django enable `PeriodicTask("scrape_deaths")`, restart Beat, po 5 min `DeathEvent.objects.count()` rośnie o ~50 (lub 0 jeśli druga iteracja w okresie 7h bufora).
- [ ] Po smoke: **wyłącz PeriodicTask z powrotem** (sanity, żeby nie spamić tibiantis.info w background dev).

### 📋 Sugerowane kroki

1. `git checkout master && git pull origin master`.
2. `git checkout -b feat/<N>-scheduled-deaths-scrape`.
3. **Settings + env** — dodaj `DEATH_LEVEL_THRESHOLD` do `.env.example` (pierwszy) i `base.py` (drugi). Sanity: `poetry run python -c "from django.conf import settings; print(settings.DEATH_LEVEL_THRESHOLD)"` → 30.
4. **Celery task** — `apps/deaths/tasks.py` per AC.
5. **Migracja PeriodicTask** — `apps/deaths/migrations/0002_seed_periodic_task.py`. Zachowaj `enabled=False`.
6. **Migrate** — `poetry run python manage.py migrate` → no errors. Sprawdź `PeriodicTask.objects.get(name="scrape_deaths").enabled == False`.
7. **Pre-commit** — `poetry run pre-commit run --all-files`. Mypy może zgłaszać `[no-untyped-def]` na `scrape_deaths(self: Any)` mimo `Any` — sprawdź w lokalnym mypy config czy tasks/* override jest aktywny (z M3 #67).
8. **Smoke manual** — punkt AC #4. **WYMAGA REDIS + WORKER + BEAT** (M3 setup). Jeśli Memurai/WSL2 nie działa — odpal worker'a w eager mode dla quick test:
   ```python
   # python -c
   from django.conf import settings
   settings.CELERY_TASK_ALWAYS_EAGER = True  # może wymagać import django.setup() first
   from apps.deaths.tasks import scrape_deaths
   print(scrape_deaths.apply().get())
   ```
9. **Push + PR + review.**

### ⚠️ Pułapki do uwagi

- **A — `DEATH_LEVEL_THRESHOLD` nie jest w `base.py` ani `.env.example`** (gap pre-flight 2026-04-30). D21 dodaje **oba**. Zapomnienie którego z 2 → resolver D22 wybuchnie w runtime (`AttributeError: settings has no DEATH_LEVEL_THRESHOLD`).
- **B — `default=30` w `env.int(...)`:** oznacza że `.env` może **nie mieć** `DEATH_LEVEL_THRESHOLD` i settings wciąż działa. Dlatego CI `env:` block **nie musi** mieć tej zmiennej (bezpieczne fallback). M3 retro #59 lekcja: settings strict (no defaults) wymagają CI env match. Tu default jest = OK bez CI env update.
- **C — `mypy` cross-env gymnastics** (M3 lekcja #1): `@shared_task(bind=True)` + `self: Any` workaround. Pre-commit mypy w isolated env może zgłosić `[no-untyped-def]` na `self`. Direct `poetry run mypy apps/deaths/tasks.py` może pokazać `Success`. Sanity: ZIELONY w pre-commit, nie w direct mypy. Jeśli tylko direct OK, hook się wywali w CI.
- **D — `subprocess.run(text=True)` Windows:** `text=True` na Windows decoduje stdout używając `locale.getpreferredencoding()` — w Polsce `cp1250`. Jeśli mgmt command pisze unicode characters (np. Polish names), może wywalić `UnicodeDecodeError`. **Mitigation:** explicit `encoding="utf-8", errors="replace"` w subprocess. Spec sekcja 5.D21 nie ma tego — **dodać** podczas implementacji.
- **E — `self.retry(exc=exc, countdown=60)`:** retry tworzy nowy task, dodaje do `max_retries`. Po 2 retries → `MaxRetriesExceededError`. Beat fires task ponownie za 5 min — wystarczające recovery.
- **F — `migrations/0002` nazwa:** sprawdź że nie ma konfliktu (np. `python manage.py makemigrations deaths` wygenerowało coś innego po D18). Jeśli auto-generated `0002_*.py` istnieje (np. `0002_alter_*`) → twoja seed migration powinna być `0003_seed_periodic_task.py`. Sanity: `ls apps/deaths/migrations/` przed napisaniem seed.
- **G — `enabled=False` w seed jest celowe.** Spec mówi: admin enable'uje świadomie. Uważaj żeby nie zmienić defaultu w testach — testy z `apply()` używają eager mode, nie wymagają Beat enable.
- **H — `subprocess.TimeoutExpired` raising loop:** jeśli każdy retry też timeout'uje, max_retries=2 → 3 fires total → wszystkie fail → Celery wpisuje failure w result backend. **Akceptowalne** — Beat odpali za 5 min, fresh task. Symptom infrastrukturalny (np. tibiantis.info down).

### 🧪 Testing plan

**Unit testy (3-4 testy):**
- [ ] `tests/unit/deaths/test_scrape_deaths_task.py`:
  - `test_returns_parsed_json_summary` — mock `subprocess.run` z `stdout='{"yielded": 50, "duplicates": 0}'`, returncode 0 → task return `{"yielded": 50, "duplicates": 0, "returncode": 0}`.
  - `test_subprocess_timeout_triggers_retry` — `subprocess.run` raises `TimeoutExpired` → assert `self.retry` was called via mock (use `unittest.mock.patch.object(scrape_deaths, "retry")`).
  - `test_json_decode_error_returns_sentinel` — stdout invalid JSON (np. `b'crash'`) → return `{"yielded": -1, "duplicates": -1, "returncode": <whatever>}`.
  - `test_returncode_nonzero_logged_and_returned` — returncode=1 + valid stdout → return JSON normalnie + log warning emitted (capture log).

**Migration test (opcjonalne):**
- [ ] `tests/unit/deaths/test_migration_seed.py` (nie blokuje M4):
  - Sprawdź `PeriodicTask.objects.get(name="scrape_deaths")` po `migrate` — `task=apps.deaths.tasks.scrape_deaths`, `interval.every=5`, `interval.period=minutes`, `enabled=False`.
  - **Optional** — D22 e2e test pokrywa to pośrednio (PeriodicTask musi istnieć żeby task fire'ował, choć w eager mode nie jest sprawdzany).

**Smoke manual:** AC #4 — live `scrape_deaths.delay().get()` z workerem.

**Coverage cel:** `apps/deaths/tasks.py` 100% (mały, ~30 stmts, wszystkie ścieżki happy + error covered).

**Claude weryfikuje po PR:**
- `text=True` + `encoding="utf-8"` w subprocess (Windows safety).
- `dependencies` w migration ma poprawne app names (`("deaths", "0001_initial")`, `("django_celery_beat", "0001_initial")`).
- `DEATH_LEVEL_THRESHOLD` w 3 miejscach (`.env.example`, `base.py`, opcjonalnie CI).
- `enabled=False` w seed.
- Sentinel return shape match — `{"yielded": -1, "duplicates": -1, "returncode": ...}` precyzyjnie.

### 🔗 Dokumentacja pomocnicza

- `@shared_task(bind=True)`: https://docs.celeryq.dev/en/stable/userguide/tasks.html#bind
- `self.retry`: https://docs.celeryq.dev/en/stable/userguide/tasks.html#retrying
- `subprocess.run`: https://docs.python.org/3/library/subprocess.html#subprocess.run
- `django-celery-beat` PeriodicTask API: https://django-celery-beat.readthedocs.io/en/latest/
- Data migration `RunPython`: https://docs.djangoproject.com/en/6.0/topics/migrations/#data-migrations

### 📦 Definition of Done

- [ ] AC spełnione (Settings, Task, Migration, Pre-commit deps, Smoke).
- [ ] PR zmergowany squash (`feat(deaths): scheduled scrape_deaths task + Beat schedule (M4-D21, #<N>)`).
- [ ] CI lint + test zielone.
- [ ] `apps/deaths/tasks.py` 100% coverage (~30 stmts).
- [ ] Issue zamknięty.

---

## Task #5 — [M4-D22] GraphQL `recentDeaths` + e2e test + M4 closure

**Milestone:** M4 — Deaths monitor (backend)
**Czas:** 4h
**Branch:** `feat/<N>-deaths-graphql` + osobny `docs/close-m4-tracker`
**Type:** `feat` (kod) + `docs` (PROGRESS.md)
**Zależy od:** D21 merged

### 🎯 Cel
GraphQL query `recentDeaths(minLevel: Int, limit: Int = 50): [DeathEventType!]!` zwraca posortowane DESC po `died_at` deaths z filtrem `level_at_death >= min_level`. JWT auth required (resolver-level guard, M2 wzór). E2E integration test pokrywa pełny flow task → spider → service → DB → query w jednym teście (eager Celery + mock subprocess + fixture spider). M4 zamyka się PROGRESS.md retro per Issue + milestone closed.

### 🧠 Czego się nauczysz
- **Strawberry async resolver z Django ORM:** `[e async for e in qs]` materializuje QuerySet asynchronicznie. `await qs.afirst()` dla pojedynczego obiektu. `list(qs)` w async resolver da `SynchronousOnlyOperation`.
- **`merge_types("Query", (...))` collision risk:** flat merge fields, hard fail przy konflikcie nazw przy starcie schemy. M2 #30 precedens — preferować `merge_types` nad multiple inheritance (MRO cicho rozwiązuje konflikty = anti-pattern w GraphQL).
- **`info.context["request"]` w Strawberry:** middleware GraphQL view (z M2-D12 dispatch) wstrzykuje `request` do contextu. Dostęp do `request.user` per-resolver. **Auth guard logic:** `if not request.user.is_authenticated: raise ...`.
- **`limit` clamping:** `min(max(limit, 1), 200)` chroni przed `limit: 999999` (runaway query) i `limit: 0` (empty result instead of error). Default 50.
- **E2E test pattern z M3 D17:** `@override_settings(CELERY_TASK_ALWAYS_EAGER=True)` + mock `subprocess.run` z `side_effect`-em który invoke'uje spider w-procesowo. Bez real subprocess + bez real HTTP.
- **`docs/close-m4-tracker` branch z świeżego master** (M1 retro #8 lekcja): `git checkout master && git pull && git checkout -b docs/close-m4-tracker`. NIE od feature brancha.

### ✅ Acceptance criteria

#### GraphQL — schema
- [ ] `apps/deaths/schema.py`:
  ```python
  from typing import cast

  import strawberry
  import strawberry_django
  from django.conf import settings
  from strawberry import auto

  from apps.deaths.models import DeathEvent


  @strawberry_django.type(DeathEvent)
  class DeathEventType:
      id: auto
      character_name: auto
      level_at_death: auto
      killed_by: auto
      died_at: auto
      scraped_at: auto


  @strawberry.type
  class Query:
      @strawberry.field
      async def recent_deaths(
          self,
          info: strawberry.Info,
          min_level: int | None = None,
          limit: int = 50,
      ) -> list[DeathEventType]:
          request = info.context["request"]
          if not request.user.is_authenticated:
              raise PermissionError("Authentication required")

          effective_min_level = (
              min_level if min_level is not None else settings.DEATH_LEVEL_THRESHOLD
          )
          effective_limit = min(max(limit, 1), 200)

          qs = (
              DeathEvent.objects
              .filter(level_at_death__gte=effective_min_level)
              .order_by("-died_at")[:effective_limit]
          )
          return cast("list[DeathEventType]", [e async for e in qs])
  ```

#### GraphQL — merge
- [ ] `config/schema.py` rozszerzony:
  ```python
  import strawberry
  from strawberry.tools import merge_types

  from apps.accounts.schema import Query as AccountsQuery
  from apps.characters.schema import Query as CharactersQuery
  from apps.deaths.schema import Query as DeathsQuery

  Query = merge_types("Query", (AccountsQuery, CharactersQuery, DeathsQuery))
  schema = strawberry.Schema(query=Query)
  ```

#### Unit testy GraphQL
- [ ] `tests/unit/deaths/test_graphql_recent_deaths.py` — pattern z `tests/unit/characters/test_graphql_character.py`:
  - `test_recent_deaths_default_uses_settings_threshold` — DB seed: 3 deaths z levelami 20/30/40. `@override_settings(DEATH_LEVEL_THRESHOLD=30)`. Query `{ recentDeaths { id, levelAtDeath } }` (bez `minLevel`) → response 2 elementy (lvl 30, 40).
  - `test_recent_deaths_explicit_min_level_overrides_default` — query `recentDeaths(minLevel: 1) { ... }` → 3 elementy.
  - `test_recent_deaths_limit_capped_at_200` — DB seed: 250 deaths. Query `recentDeaths(limit: 1000) { id }` → 200 elementów.
  - `test_recent_deaths_limit_min_clamped_at_1` — query `recentDeaths(limit: 0)` → 1 element (clamp).
  - `test_recent_deaths_ordered_by_died_at_desc` — DB seed: 3 deaths z `died_at = now() - 1h`, `now() - 2h`, `now() - 3h`. Response order = -1h, -2h, -3h.
  - `test_recent_deaths_requires_authentication` — query bez JWT (lub z `AnonymousUser`) → response error (Strawberry serializuje `PermissionError` jako `errors` field w response).

#### E2E integration test
- [ ] `tests/integration/test_m4_deaths_e2e.py`:
  ```python
  import json
  from pathlib import Path
  from unittest.mock import patch
  from subprocess import CompletedProcess

  import pytest
  from django.test import override_settings
  from scrapy.http import HtmlResponse, Request

  from apps.deaths.models import DeathEvent
  from apps.deaths.services import save_death_event
  from apps.deaths.tasks import scrape_deaths
  from scrapers.tibiantis_scrapers.spiders.deaths_spider import DeathsSpider

  FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "deaths_sample.html"


  def _spider_fixture_side_effect(*args, **kwargs):
      """Mock subprocess: invoke spider on fixture, save items, return JSON stdout."""
      spider = DeathsSpider()
      request = Request(url="https://tibiantis.info/stats/deaths")
      response = HtmlResponse(
          url=request.url,
          body=FIXTURE.read_bytes(),
          encoding="utf-8",
          request=request,
      )
      yielded = duplicates = 0
      for item in spider.parse(response):
          result = save_death_event(dict(item))
          yielded += 1
          if result is None:
              duplicates += 1
      return CompletedProcess(
          args=args[0],
          returncode=0,
          stdout=json.dumps({"yielded": yielded, "duplicates": duplicates}),
          stderr="",
      )


  @pytest.mark.django_db
  @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
  def test_e2e_first_scrape_creates_50_deaths_second_scrape_dedups():
      with patch("apps.deaths.tasks.subprocess.run", side_effect=_spider_fixture_side_effect):
          # Round 1
          result1 = scrape_deaths.apply().get()
          assert result1["yielded"] == 50
          assert result1["duplicates"] == 0
          assert result1["returncode"] == 0
          assert DeathEvent.objects.count() == 50

          # Round 2 — same fixture, should fully dedup
          result2 = scrape_deaths.apply().get()
          assert result2["yielded"] == 50
          assert result2["duplicates"] == 50
          assert result2["returncode"] == 0
          assert DeathEvent.objects.count() == 50  # no growth
  ```

#### PROGRESS.md (osobny `docs/close-m4-tracker` branch po merge feature PR-a)
- [ ] Sekcja `## 🎉 Milestone M4 — Deaths monitor (backend) COMPLETED (YYYY-MM-DD)`.
- [ ] Lista 5 ukończonych Issues z linkami do PR-ów + squash hashes.
- [ ] Notatki retro per Issue (D18-D22) — wzór z M3 retro w PROGRESS.md.
- [ ] Sekcja "Tech debt z M4 do adresowania post-M4" (jeśli wystąpi).
- [ ] DoD M4 ze spec'a §8 — wszystkie [x].
- [ ] Milestone M4 zamknięty: `gh api -X PATCH repos/:owner/:repo/milestones/<N> -f state=closed`.

#### Smoke manual (po merge feature PR-a, przed close)
- [ ] `runserver` + worker + beat działają.
- [ ] Enable `PeriodicTask("scrape_deaths")` w admin → po 5 min DB ma rows.
- [ ] Login na `/api/auth/login/` → JWT.
- [ ] POST `/graphql/` z header `Authorization: Bearer <jwt>`, body `{"query": "{ recentDeaths(minLevel: 1, limit: 10) { characterName levelAtDeath diedAt } }"}` → 10 najnowszych deaths.
- [ ] Disable PeriodicTask po smoke (sanity).

### 📋 Sugerowane kroki

1. `git checkout master && git pull origin master`.
2. `git checkout -b feat/<N>-deaths-graphql`.
3. **Schema impl** — `apps/deaths/schema.py` per AC.
4. **Schema merge** — `config/schema.py` extend.
5. **Sanity:** `poetry run python manage.py runserver` → `/graphql/` GraphiQL UI → introspection pokazuje `recentDeaths`.
6. **Unit testy GraphQL** — 6 testów w `test_graphql_recent_deaths.py`.
7. **E2E test** — `tests/integration/test_m4_deaths_e2e.py`. Run: `pytest tests/integration/test_m4_deaths_e2e.py -v` → green.
8. **Pre-commit + push + PR.**
9. Po merge feature PR-a: `git checkout master && git pull && git checkout -b docs/close-m4-tracker`.
10. **PROGRESS.md** — extend sekcją M4 retro (mirror M3 retro structure).
11. **Smoke manual** (AC #6).
12. **Push docs branch + PR + merge.**
13. **Close milestone:** `gh api -X PATCH repos/bgozlinski/tibiantis-scraper/milestones/<M4_ID> -f state=closed`.

### ⚠️ Pułapki do uwagi

- **A — Async ORM iteration:** `[e async for e in qs]` to prawidłowy pattern (M2-D12 wzór). `list(qs)` w async resolver = `SynchronousOnlyOperation`. `await qs.afirst()` tylko dla pojedynczego obiektu. **Sanity:** test `test_recent_deaths_ordered_by_died_at_desc` — jeśli wybucha `SynchronousOnlyOperation`, fix iteration.
- **B — `merge_types` collision:** `recent_deaths` jest unique nazwą. Sprawdź `gh search code --owner bgozlinski "async def recent_deaths"` przed pushem (w razie nieoczywistego konfliktu z innym schematem). M2 #30 lekcja.
- **C — `PermissionError` w Strawberry:** Strawberry serializuje wszystkie exceptions jako `errors` field w response. `PermissionError` (built-in `OSError` subclass) działa, ale nie ma "auth-specific" semantyki. **Alternatywy:** `raise Exception("Authentication required")` — generic. Lub Strawberry custom error. Wybór spec'a: `PermissionError` (czytelne intent w kodzie).
- **D — `info.context["request"]`:** klucz `request` jest convention z M2-D12 `AsyncGraphQLView` dispatch. Sprawdź `apps/accounts/schema.py::Query.me` jak czyta context — mirror pattern.
- **E — `auto` typowanie z `strawberry_django`:** `id: auto` daje auto `ID` GraphQL type (`strawberry.ID`). `level_at_death: auto` daje `Int!`. `died_at: auto` daje `DateTime!`. Dla `killed_by: auto` (TextField) — mapowanie do `String!`. Sprawdź `tests/unit/deaths/test_graphql_recent_deaths.py` introspection żeby potwierdzić nazwy.
- **F — Field naming camelCase:** Strawberry domyślnie konwertuje `character_name` (Python snake_case) → `characterName` (GraphQL camelCase) przy schema generation. Test query używa camelCase (`characterName`), Python kod operuje snake_case (`character_name`). **Sanity:** `print(strawberry.Schema(...).as_str())` w teście żeby zobaczyć schema SDL.
- **G — `tests/integration/test_m4_deaths_e2e.py` requires `@pytest.mark.django_db`:** bez tego test ma `DatabaseAccess error` (django_db marker tworzy transakcje per-test).
- **H — `_spider_fixture_side_effect` reusable:** funkcja jako `side_effect` w mock. Po pierwszym call'u Round 1 i drugim call'u Round 2 — **te same items** są yieldowane (stessa fixturka). Dlatego Round 2 ma `duplicates=50` (wszystkie `(name, died_at)` już istnieją).
- **I — Closure `docs/close-m4-tracker` branch from FRESH master:** M1 retro #8 lekcja. `git checkout master && git pull && git checkout -b docs/close-m4-tracker`. **NIE** od feature brancha (M1 wbloodopiero złapało duplicate PR #26).
- **J — `gh issue close` jeśli `Closes #<N>` nie zadziałał:** sanity po merge — sprawdź `gh issue list --milestone "M4 ..." --state open` powinno być puste. Jeśli nie — `gh issue close <N>` ręcznie. M3 #58 precedens.

### 🧪 Testing plan

**Unit testy GraphQL:** 6 testów (default threshold, explicit min_level, limit cap 200, limit min clamp 1, order DESC, auth required).

**E2E integration test:** 1 test (full flow round 1 + round 2 dedup).

**Smoke manual:** AC #6 (live `/graphql/` request z JWT, populated DB).

**Coverage cel:** `apps/deaths/schema.py` 100%. Cały `apps/deaths/*.py` 100% po D22.

**Claude weryfikuje po PR:**
- Auth guard explicit `if not request.user.is_authenticated`.
- `min_level` fallback do settings, **nie** hard-coded 30.
- `limit` clamp `min(max(limit, 1), 200)` — both bounds tested.
- E2E test używa fixture, **nie** real HTTP.
- E2E test asercjuje BOTH counters (yielded AND duplicates), **nie** tylko jeden (M3 retro #61 lekcja).
- `merge_types` w `config/schema.py` ma `DeathsQuery` na końcu listy (consistency).
- PROGRESS.md retro ma sekcję per D18-D22 z PR linkami + squash hashes + lekcje.

### 🔗 Dokumentacja pomocnicza

- Strawberry async resolvers: https://strawberry.rocks/docs/general/async
- `strawberry_django.type`: https://strawberry-graphql.github.io/strawberry-django/types/
- Django ORM async: https://docs.djangoproject.com/en/6.0/topics/async/
- `merge_types`: https://strawberry.rocks/docs/guides/schema-extensions
- `@override_settings`: https://docs.djangoproject.com/en/6.0/topics/testing/tools/#django.test.override_settings

### 📦 Definition of Done

- [ ] AC spełnione (Schema, Merge, Unit testy 6, E2E test, PROGRESS.md, Smoke manual).
- [ ] **Feature PR** zmergowany squash (`feat(deaths): recentDeaths GraphQL + e2e test (M4-D22, #<N>)`).
- [ ] **Closure PR** zmergowany squash (`docs(progress): close M4 — Deaths monitor (backend) COMPLETED + retro D22 (#<close_pr>)`).
- [ ] CI lint + test zielone na obu PR-ach.
- [ ] `apps/deaths/*.py` cumulative coverage ≥ 95%.
- [ ] Issue zamknięty (oba — feature i closure).
- [ ] Milestone M4 zamknięty na GitHub.

---

## Tworzenie Issues — gh commands

Przygotuj 5 plików body — jeden per task. Każdy plik to **trim** odpowiedniego Task #N — sekcje 🎯 Cel, ✅ Acceptance criteria, ⚠️ Pułapki, 📦 DoD wystarczą (📋 Sugerowane kroki + 🔗 Dokumentacja pomocnicza zostają tylko w plan dokumencie, niepotrzebne w Issue body).

```bash
# Po utworzeniu milestone'u (zachowaj <M4_NUMBER> z odpowiedzi):
M4_NUMBER=$(gh api -X POST repos/bgozlinski/tibiantis-scraper/milestones \
  -f title="M4 — Deaths monitor (backend)" \
  -f description="..." \
  -f state=open --jq .number)

# Issue per task (5 razy):
gh issue create \
  --milestone "M4 — Deaths monitor (backend)" \
  --label "phase-M4,app:characters,type:feat" \
  --title "[M4-D18] apps/deaths/ + DeathEvent model + admin + initial migration" \
  --body-file .github/issue-bodies/m4-d18.md

# ... powtórz dla d19, d20, d21, d22 z odpowiednimi labelami:
# D19: type:feat, app:characters
# D20: type:feat, app:characters
# D21: type:feat, app:characters
# D22: type:feat, app:characters

# Sanity:
gh issue list --milestone "M4 — Deaths monitor (backend)"  # == 5
```

**Decyzja `app:` label:** projekt nie ma jeszcze `app:deaths` label (M0 #1 utworzył tylko `app:characters/accounts/bedmages/notifications/infra`). **Pre-flight:** `gh label create "app:deaths" --color "..."` przed `gh issue create`. Lub user `app:characters` jako temporary fallback (deaths są blisko characters domain).

---

## Self-review

**1. Spec coverage** — sprawdziłem każdą sekcję spec'a M4 vs zadania w planie:

| Spec section | Plan task | Status |
|---|---|---|
| §2 Scope: nowa aplikacja `apps/deaths/` | Task #1 D18 | ✅ |
| §2 Scope: `DeathEvent` model + admin | Task #1 D18 | ✅ |
| §2 Scope: `unique_together` | Task #1 D18 | ✅ |
| §2 Scope: `DeathItem` w items.py | Task #2 D19 | ✅ |
| §2 Scope: `deaths_spider` | Task #2 D19 | ✅ |
| §2 Scope: pipeline dispatch | Task #2 D19 (dispatch) + Task #3 D20 (counter) | ✅ |
| §2 Scope: `save_death_event` service | Task #3 D20 | ✅ |
| §2 Scope: `manage.py scrape_deaths` cmd | Task #3 D20 | ✅ |
| §2 Scope: Celery task `scrape_deaths` | Task #4 D21 | ✅ |
| §2 Scope: `DEATH_LEVEL_THRESHOLD` setting | Task #4 D21 | ✅ |
| §2 Scope: PeriodicTask seed migration | Task #4 D21 | ✅ |
| §2 Scope: `recentDeaths` GraphQL query | Task #5 D22 | ✅ |
| §2 Scope: JWT auth (resolver-level guard) | Task #5 D22 | ✅ |
| §2 Scope: testy unit/integration | Tasks #2-#5 (D19-D22) | ✅ |
| §6 Ryzyka R1-R10 | Pułapki w odpowiednich D-tasks | ✅ |
| §7 Pre-flight checklist | Pre-flight section + D21 (env gap) | ✅ |
| §8 DoD M4 | Per-task DoD + closure D22 | ✅ |

**2. Placeholder scan** — zero `TBD`, `TODO` (pustych), `<fill in>`. `<N>` jako placeholder Issue # akceptowalne (nie wiemy numerów do utworzenia Issues). `<M4_NUMBER>` dla milestone — runtime-filled. `YYYY-MM-DD` dla closure date — runtime.

**3. Type consistency** — `DeathEvent.character_name` (snake_case w Pythonie) → `characterName` w GraphQL (Strawberry auto-conversion). Test queries używają camelCase. ✅. Task return shape `{"yielded": int, "duplicates": int, "returncode": int}` consistently across D20 (mgmt cmd output), D21 (task return), D22 (e2e asercje). ✅. `DeathPayload` TypedDict wspomniany w D19 (lazy import w pipeline) i D20 (full impl) — konsystentnie. ✅.

**4. Spec gaps wykryte podczas planowania:**
- **Gap 1:** `DEATH_LEVEL_THRESHOLD` brak w aktualnym `.env.example` i `base.py`. Spec wspominał "sprawdzić, dodać jeśli nie ma" — plan eksplicite przypisuje do D21 AC. ✅ rozwiązane.
- **Gap 2:** `app:deaths` GitHub label nie istnieje. Plan pre-flight ma "create label przed issues". ✅ rozwiązane.
- **Gap 3:** `branch protection` master required check `test / Pytest` — z post-M2 tech debt, niezamknięte. Plan pre-flight ma "dodać teraz". ✅ rozwiązane.

**5. Inne notatki:**
- **D19 Pułapka C** (Windows subprocess `text=True` + locale): nie była w spec'u, ale ważna dla Windows dev. Dorzucone do D21 Pułapka D.
- **D22 unique addition:** test `test_recent_deaths_limit_min_clamped_at_1` (nie był eksplicite w spec'u). Defensive — `limit: 0` daje 1 element, nie crash.
- **Plan jest długi** (~1600 linii) — adekwatne do projektu mentora-junior. Każdy task ma educational sekcję ("🧠 Czego się nauczysz") spójnie z user profile.

---

## Execution Handoff

Plan zapisany. Workflow projektu **NIE** używa subagent-driven ani inline-execution skilli (rola Claude: tworzyć Issues + review, **nie** implementować). Następne kroki:

1. **Pre-flight** — wykonaj sekcję "Pre-flight checklist" z planu (milestone, labele, branch protection).
2. **Tworzenie Issues** — wytrim per Task body do `.github/issue-bodies/m4-d{18..22}.md` plików, użyj `gh issue create --body-file` (sekcja "Tworzenie Issues" w planie).
3. **D18 start** — `git checkout -b feat/<N>-deaths-app-model`, implementuj per Task #1 AC, otwórz PR. **Tylko po D18 merge przechodzimy do D19** (strict chain).
4. **Code review per PR** — Claude robi review + dopisuje testy follow-up po accept (workflow z `project_workflow.md`).
5. **Closure D22** — feature PR + osobny `docs/close-m4-tracker` PR z PROGRESS.md retro (mirror M3 PR #76 #74 pattern).

**Estimated duration:** 5 dni roboczych (~17h work, mirror M3 budgetu po lekcji "świadomie wąski scope" zadziałała w 2 dni real time).
