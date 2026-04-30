# M4 — Deaths monitor (backend) — Design

**Data:** 2026-04-30
**Milestone:** M4 (GitHub milestone TBD)
**Budżet:** 5 dni roboczych (~16-20h, mirror M3 budgetu po lekcji "świadomie wąski scope" zadziałała w 2 dni real time).
**Poprzedni milestone:** M3 — Celery infrastructure (zamknięty 2026-04-29, retro w `PROGRESS.md`).

---

## 1. Cel

Dodać drugą domenę monitorowaną przez aplikację — **śmierci postaci** scrapowane z `https://tibiantis.info/stats/deaths` — do warstwy persistence + GraphQL. Po M4 wszystkie deaths z 5-min interwałem siedzą w Postgres, są filtrowalne po levelu przez `recentDeaths` GraphQL query, z ustawionym threshold'em z env var.

**Świadomie wąski scope:** zero Discord, zero notyfikacji, zero nowego procesu, zero nowej infry message-broker. Jeden nowy Celery task (reuse M3 infra), jeden nowy spider (reuse M1 Scrapy), jeden nowy model + GraphQL type (reuse M2 Strawberry stack). M4 to "drugi spider dochodzi do projektu".

**Świadomie odroczone:**
- Discord bot + announcer (M5+) — wymaga osobnego procesu, OAuth/discord_id mapowania, własnego pre-flight (`py-cord` vs `discord.py`?).
- `BedmageWatch` + tracker 100-min (M5/M6) — domena per-user, idempotencja powiadomień, FK do User; znaczenie szersze niż deaths.
- `DiscordChannel` + `setDeathThreshold` mutation (M5) — bez Discord modeli "kanały" nie istnieją; M4 threshold jako env var jest right level.
- `announced_on_discord` field (M5) — forward-looking pole bez konsumenta w M4 = YAGNI.

---

## 2. Scope

**W scope:**
- Nowa aplikacja `apps/deaths/` zarejestrowana w `INSTALLED_APPS` jako `apps.deaths.apps.DeathsConfig`.
- Model `DeathEvent` (`character_name`, `level_at_death`, `killed_by`, `died_at`, `scraped_at`) + migracja initial + Django admin.
- `unique_together = ("character_name", "died_at")` jako mechanizm dedup.
- `DeathItem` w `scrapers/tibiantis_scrapers/items.py`.
- Spider `scrapers/tibiantis_scrapers/spiders/deaths_spider.py` parsujący `table.mytab.long` na `https://tibiantis.info/stats/deaths` — page 1 only, "All" tab.
- Pipeline dispatch w `scrapers/tibiantis_scrapers/pipelines.py` rozszerzony o `isinstance(item, DeathItem)` ścieżkę.
- Service `apps/deaths/services.py::save_death_event(payload) -> DeathEvent | None` (skip-on-duplicate przez `IntegrityError` catch).
- Management command `apps/deaths/management/commands/scrape_deaths.py` — bez argumentów, wypluwa JSON `{"yielded": N, "duplicates": M}` na stdout po crawlu.
- Celery task `apps/deaths/tasks.py::scrape_deaths` — subprocess wrapper na `manage.py scrape_deaths`, parsuje JSON ze stdout, zwraca structured dict.
- Settings `DEATH_LEVEL_THRESHOLD` (env-based, default 30) — read-only z `config/settings/base.py`.
- PeriodicTask seed migration (`apps/deaths/migrations/0002_seed_periodic_task.py`) — `IntervalSchedule(every=5, period=MINUTES)`, `enabled=False` domyślnie.
- GraphQL `recentDeaths(minLevel: Int, limit: Int = 50): [DeathEventType!]!` w `apps/deaths/schema.py`, scalone w `config/schema.py` przez `merge_types`.
- JWT auth wymagany dla `recentDeaths` (resolver-level guard, spójnie z M2).
- Fixturka `tests/fixtures/deaths_sample.html` (zapisana 2026-04-30 podczas brainstormu, 33KB, 50 deaths, full HTML).
- Testy: unit spider, unit service, unit pipeline, unit task, unit GraphQL, integration e2e (eager Celery + mocked subprocess + fixture-based parse).

**Poza scope (post-M4):**
- Discord bot, slash commands, webhook publisher, channel mapping (M5/M6).
- `BedmageWatch` model + tracker (M5/M6).
- `DiscordChannel` model + `setDeathThreshold` GraphQL mutation (M5).
- `announced_on_discord` boolean na `DeathEvent` (M5, dorobimy migrację razem z announcerem).
- Multi-page scrape / historical backfill (potencjalnie M-future, jeśli okaże się że page 1 nie wystarcza).
- "From players" tab (PvP-only feed) — nie ma w roadmap'ie biznesowym, M4 śledzi wszystkie deaths.
- Real Celery worker + real Redis integration tests w CI (nadal post-M3, M4 dziedziczy decyzję).
- Mongo logging integration (`scrape_logs` collection z CLAUDE.md §4) — M5+, M4 standardowy Python logging do stdout.
- Watchdog "deaths feed lag" (alarm gdy najnowszy `died_at` >1h temu) — może w M5 razem z announcerem.

---

## 3. Decyzje technologiczne

| Obszar | Wybór | Dlaczego |
|---|---|---|
| Source URL | `https://tibiantis.info/stats/deaths` (page 1, "All" tab) | CLAUDE.md §6 Cel 2. Page 1 ma 50 deaths × ~7 deaths/h = ~7h bufora — wystarczające przy 5-min interwale, bez paginacji. |
| Schedule interval | 5 min (default w PeriodicTask seed) | Polite scraping (Tibiantis.info to fansite jednoosobowy: footer "© Gubihe 2020-2026"). 12 GET-ów/h vs 240 dla full-paginate. |
| Source TZ | `Europe/Berlin` (CET/CEST) — hardcoded w spiderze | Mirror M1 `character_spider._parse_last_login`. Tibia/OT serwer time = Europe/Berlin de facto. Django USE_TZ=True robi auto-konwersję do UTC przy save. |
| Dedup constraint | `unique_together = ("character_name", "died_at")` | CLAUDE.md §5 explicit. Timestamp na stronie do sekundy → kolizje fałszywe ekstremalnie rzadkie (DST overlap raz/rok, akceptowalne ryzyko). |
| Dedup strategy | Skip-on-IntegrityError, return None | Deaths są immutable — raz zarejestrowane, nie zmieniają się. Asymetrycznie do M1 `upsert_character` (Character mutable: level/last_login się zmieniają). |
| `character_name` w DeathEvent | `CharField`, **nie** FK do `Character` | Tibiantis.info pokazuje deaths postaci których w ogóle nie scrapujemy (`Character` table = ręczny seed). FK byłby restrykcyjny + cascade delete = utrata historii deaths. |
| `killed_by` typ | `TextField` | Widziałem `<nick>X</nick> (17)` (krótkie) ale przyszłościowo może być długie ("by A, B, C and others"). `CharField(max_length=...)` nie ma sensu dla unbounded source. |
| Pipeline dispatch | Single `DjangoPipeline` z `isinstance(item, ...)` branchami | Dla 2 item types nie ma sensu osobny plik per pipeline. Refactor do osobnych klas = trywialny chore PR jeśli kiedyś dojdzie 3-ci type. |
| Spider invocation z task'a | `subprocess.run([sys.executable, "manage.py", "scrape_deaths"], timeout=120)` | Mirror M3 `scrape_watched_characters` — Twisted reactor w subprocess, izolacja od Celery worker pool (M1 retro #8). Brak per-name argumentu (różnica vs M3). |
| Task return shape | Parsed JSON ze stdout: `{"yielded": int, "duplicates": int, "returncode": int}` | Observability — testy D22 mogą asercjować "po pierwszym scrapie yielded=50 duplicates=0, po drugim yielded=50 duplicates=50". Tylko returncode = ślepe. |
| Threshold semantyka | `settings.DEATH_LEVEL_THRESHOLD` (env var, default 30) jako **default** dla `minLevel` argumentu w `recentDeaths`, nie hard floor | Klient (admin) może nadpisać dowolnie. Naturalna semantyka "co M5 announcer będzie używał" jako default. |
| GraphQL type fields | All DB columns (`id`, `character_name`, `level_at_death`, `killed_by`, `died_at`, `scraped_at`) | Symmetry z `CharacterType` (M2-D12). Admin debug — `now() - scraped_at` daje feed lag bez extra query. |
| GraphQL limit cap | `min(max(limit, 1), 200)` | Sanity — prevent runaway query (np. `limit: 999999`). Default 50. |
| Auth dla `recentDeaths` | JWT required (per-resolver guard) | Spójnie z `me`, `character` z M2-D12. Pytanie 4A z brainstormu. |
| `enabled=False` w PeriodicTask seed | Default off, admin enable'uje świadomie po smoke testach | Mirror M3 — pre-prod sanity, bez self-firing migracji. |
| Async resolver | `async def recent_deaths` z `[e async for e in qs]` | Mirror M2-D12 `character`. Strawberry async dispatch. |

---

## 4. Strategia dekompozycji

**Bottom-up, 5 Issues, strict chain D18 → D19 → D20 → D21 → D22.** Spójne z M2 (D9-D12) i M3 (D13-D17). Zero paralelizmu — każdy Issue czeka na merge poprzedniego.

Alternatywy rozważone i odrzucone:
- **4 Issues (zlanie D20+D21 — services + management command + Celery task w jednym)** — odrzucone: 3 obszary, 3 testy, naturalny split. M3 retro pokazało że "zlewanie" rozszerza review surface.
- **6 Issues (split D19 na "items + spider" + "fixture testy")** — odrzucone, wszystko w jednym pliku spider'a + fixturka jest już zapisana. Sztuczny split.
- **Vertical slice** (jeden PR z całością) — niezgodny z workflow M0-M3, nie da się reviewować odcinkami.

---

## 5. Breakdown — 5 Issues

### D18 — [M4-D18] `apps/deaths/` + `DeathEvent` model + admin + migracja initial (~3h)
**Branch:** `feat/<N>-deaths-app-model`
**Zależy od:** M3 closure merged (de63644)

**Acceptance criteria:**
- `apps/deaths/__init__.py`, `apps/deaths/apps.py` (klasa `DeathsConfig` z `default_auto_field = "django.db.models.BigAutoField"`).
- `INSTALLED_APPS += ["apps.deaths.apps.DeathsConfig"]` w `config/settings/base.py` (sekcja `LOCAL_APPS`).
- `apps/deaths/models.py`:
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
- `apps/deaths/admin.py` — `@admin.register(DeathEvent)` z `list_display = ("character_name", "level_at_death", "died_at", "killed_by")`, `list_filter = ("level_at_death",)`, `search_fields = ("character_name",)`, `ordering = ("-died_at",)`. Read-only model (immutable) — `def has_change_permission(...)` returns False.
- `apps/deaths/migrations/0001_initial.py` — wygenerowana przez `manage.py makemigrations deaths`. Sprawdzić że ma poprawny `unique_together` i indeksy.
- Brak testów w tym Issue — model trywialny, testy services + spider w D19/D20.

**Pułapka A (z post-M2 retro #28):** `db_index=True` + `unique_together` na tych samych polach byłby redundant — Postgres tworzy btree dla unique constraint automatycznie. Tutaj `db_index=True` jest tylko na pojedynczym `character_name` (lookup per name), unique jest na parze. Brak konfliktu, ale warto sprawdzić wygenerowaną migrację że nie ma duplikatów index'ów.

**Pułapka B:** `auto_now_add=True` na `scraped_at` ignoruje passed value przy `create()` (M3 retro #61 lekcja). Test fixtures w D19+ muszą używać `update()` post-create jeśli chcą sterować `scraped_at`.

**Pułapka C (admin):** `has_change_permission = lambda ...: False` na `ModelAdmin` zablokuje także `add` UI? Nie — `has_change_permission` dotyczy edit, `has_add_permission` dotyczy add. Chcemy zablokować oba (deaths są tylko z scraperu) — ale add z admin może się przydać do testów manualnych. **Decyzja:** zablokować tylko change, add zostawić (admin może ręcznie wpisać test row).

### D19 — [M4-D19] Spider `deaths_spider` + `DeathItem` + pipeline dispatch + unit testy spider'a (~4h)
**Branch:** `feat/<N>-deaths-spider`
**Zależy od:** D18 merged

**Acceptance criteria:**
- `scrapers/tibiantis_scrapers/items.py` rozszerzony o `DeathItem(Item)` z polami: `character_name`, `level_at_death`, `killed_by`, `died_at`.
- `scrapers/tibiantis_scrapers/spiders/deaths_spider.py`:
  ```python
  import re
  from datetime import datetime
  from zoneinfo import ZoneInfo

  import scrapy
  from scrapers.tibiantis_scrapers.items import DeathItem


  class DeathsSpider(scrapy.Spider):
      name = "deaths"
      start_urls = ["https://tibiantis.info/stats/deaths"]

      _LEVEL_RE = re.compile(r"\((\d+)\)")
      _SOURCE_TZ = ZoneInfo("Europe/Berlin")

      def parse(self, response):
          rows = response.css("table.mytab.long tr")[1:]  # skip header

          if not rows:
              self.logger.warning(
                  "No death rows found on %s — page layout may have changed",
                  response.url,
              )
              return

          for row in rows:
              try:
                  yield self._parse_row(row)
              except (AttributeError, ValueError) as exc:
                  self.logger.warning("Row parse failed: %s", exc)
                  continue

      def _parse_row(self, row) -> DeathItem:
          name = row.css("td.ld a::text, td.lu a::text").get("").strip()
          level_text = "".join(row.css("td.ld ::text, td.lu ::text").getall())
          level_match = self._LEVEL_RE.search(level_text)
          if not level_match:
              raise ValueError(f"No level in row text: {level_text[:100]}")
          level = int(level_match.group(1))

          tds = row.css("td.m, td.md")
          died_at_str = tds[1].css("::text").get("").strip()  # 3rd td (after name + icon)
          died_at_naive = datetime.strptime(died_at_str, "%Y-%m-%d %H:%M:%S")
          died_at = died_at_naive.replace(tzinfo=self._SOURCE_TZ)

          killed_by_td = row.css("td.m:last-child, td.md:last-child").get()
          killed_by = "".join(row.css("td.m:last-child ::text, td.md:last-child ::text").getall()).strip()

          item = DeathItem()
          item["character_name"] = name
          item["level_at_death"] = level
          item["killed_by"] = killed_by
          item["died_at"] = died_at
          return item
  ```
  (Implementacja przykładowa — selectory mogą wymagać tweaka po pierwszym `pytest` przeciw fixturce. **Powyższe to design, nie kod do skopiowania**.)
- `scrapers/tibiantis_scrapers/pipelines.py` rozszerzony:
  ```python
  from asgiref.sync import sync_to_async
  from scrapers.tibiantis_scrapers.items import CharacterItem, DeathItem


  class DjangoPipeline:
      async def process_item(self, item, spider):
          if isinstance(item, CharacterItem):
              from apps.characters.services import upsert_character
              await sync_to_async(upsert_character)(dict(item))
          elif isinstance(item, DeathItem):
              from apps.deaths.services import save_death_event
              await sync_to_async(save_death_event)(dict(item))
          return item
  ```
  (Service `save_death_event` jeszcze nie istnieje — D20 doda. Ten import w pipeline'ie zostanie nieaktywny do D20. Jeśli pipeline dispatch ląduje w PR-ze D19 (a service w D20), `from apps.deaths.services import save_death_event` w środku `elif` brancha zaimportuje się leniwie — D19 nie wywoła path'a `DeathItem` bo task scheduler jeszcze nie istnieje.)
- Testy spider'a (`tests/unit/scrapers/test_deaths_spider.py`) — wzór 1:1 z `test_character_spider.py`:
  - `test_yields_50_deaths` — `HtmlResponse(body=fixture_path.read_bytes())` → `len(list(spider.parse(response))) == 50`.
  - `test_pvp_killer_parsed` — rząd z `<nick>Beaga</nick> (17)` → `item["killed_by"]` zawiera `"Beaga"` i `"(17)"`.
  - `test_monster_killer_parsed` — rząd z `a slime` → `item["killed_by"] == "a slime"`.
  - `test_level_extracted_from_parens` — pierwszy item ma `level_at_death == 10` (Hakin Ace z fixturki).
  - `test_died_at_converted_to_utc` — `2026-04-30 05:25:12` w Europe/Berlin → `datetime(2026, 4, 30, 3, 25, 12, tzinfo=UTC)` (CEST = UTC+2 na koniec kwietnia).
  - `test_lu_class_row_parsed_same_as_ld` — synthetic helper `_build_deaths_html` z rzędami obu klas.
  - `test_warning_on_empty_table_uses_url` (regression guard z M1 retro #7) — empty `<table>` → log warning zawiera URL, nie hardkodowanego "deaths".
  - `test_row_parse_error_does_not_kill_batch` — synthetic HTML z 1 popsutym rzędem (np. brak `(level)`) i 2 dobrymi → spider yielded 2 items + 1 warning logged.
- Testy pipeline'a (`tests/unit/scrapers/test_pipeline.py` — extend):
  - `test_death_item_dispatched_to_save_death_event` — patch `apps.deaths.services.save_death_event`, feed `DeathItem` → mock called once with `dict(item)`.
  - `test_character_item_still_dispatched_to_upsert_character` — regression guard (M1 path nie zepsuty).

**Pułapka A:** Selectors `td.ld, td.lu` muszą być dwie alternatywy bo różne klasy = rożne td. Jeśli spider pomyłkowo bierze tylko `td.ld`, pominie ~8% rzędów (`lu` w sample fixturce = 4/50). Test `test_lu_class_row_parsed_same_as_ld` to złapie.

**Pułapka B:** `<nick>` to **niestandardowy HTML tag**. Scrapy parser (lxml/parsel) tolerancyjnie wyciągnie text przez `::text`, ale jeśli kiedyś strona zmieni na `<span class="nick">` — selectory się złamią. **Decyzja:** używać generic `td:last-child ::text` (cały td text), nie celować w `<nick>` specifically. Defensywny parsing.

**Pułapka C:** `tibiantis.info` na fixturce ma `<td class="m">` ORAZ `<td class="md">` jako alternatywne. Selector musi obejmować obie (`td.m, td.md`). Bez tego ~30% rzędów ma `td.md` jako last col i jest pomijane.

**Pułapka D (z post-M2 tech debt, niezamknięte w M3):** `Path(__file__).resolve().parents[3]` w testach jest fragile. **Decyzja M4:** zostawić ten sam pattern dla spójności z M1, ALE rozważyć refactor do `tests/conftest.py` jako fixture path provider w **post-M4 chore PR**. Nie blokuje M4.

### D20 — [M4-D20] Service `save_death_event` + management command `scrape_deaths` + JSON output (~3h)
**Branch:** `feat/<N>-deaths-service-cmd`
**Zależy od:** D19 merged

**Acceptance criteria:**
- `apps/deaths/services.py`:
  ```python
  from typing import TypedDict
  from datetime import datetime
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
      return value, but tests assert on it for dedup verification.
      """
      try:
          with transaction.atomic():
              return DeathEvent.objects.create(**payload)
      except IntegrityError:
          return None
  ```
- `apps/deaths/management/commands/scrape_deaths.py`:
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
          # `duplicates` counter dochodzi z pipeline'a — rozszerzyć pipeline o stats.inc_value()
          duplicates = stats.get("custom/death_duplicates", 0)

          self.stdout.write(json.dumps({"yielded": yielded, "duplicates": duplicates}))
  ```
- `scrapers/tibiantis_scrapers/pipelines.py` rozszerzony o counter w `DeathItem` ścieżce:
  ```python
  elif isinstance(item, DeathItem):
      from apps.deaths.services import save_death_event
      result = await sync_to_async(save_death_event)(dict(item))
      if result is None:
          spider.crawler.stats.inc_value("custom/death_duplicates")
  ```
- Testy service'u (`tests/unit/deaths/test_save_death_event.py`):
  - `test_create_returns_event` — payload → DeathEvent w DB, return non-None.
  - `test_duplicate_returns_none` — drugi save z identycznym `(character_name, died_at)` → return None, `DeathEvent.objects.count() == 1`.
  - `test_different_died_at_creates_two_events` — same name, różne timestamp → 2 rzędy.
  - `test_integrity_error_caught_silently` — assert no log.error emitted (capture log).
- Testy management commanda (`tests/unit/deaths/test_scrape_deaths_command.py`):
  - `test_command_outputs_json_summary` — call_command z mocked `CrawlerProcess` → stdout zawiera valid JSON z `yielded` i `duplicates`.
  - `test_command_uses_deaths_spider` — assert `process.crawl(...)` called with `DeathsSpider`.

**Pułapka A:** `CrawlerProcess.start()` może być wywołane **tylko raz** w lifetime procesu (Twisted reactor). Drugie wywołanie → `ReactorAlreadyRunning`. Każdy `manage.py scrape_deaths` to fresh subprocess więc OK, ale w testach unit nie wolno wywoływać prawdziwego `CrawlerProcess` — mock cały klass.

**Pułapka B:** `crawler.stats.inc_value("custom/death_duplicates")` — namespace `custom/` to konwencja Scrapy dla user-defined stats. Bez prefiksu mogą kolidować z built-in (`item_scraped_count`, `downloader/request_count`).

**Pułapka C:** `install_root_handler=False` w `CrawlerProcess` — bez tego Scrapy doinstalowuje swój logging handler i mieszanie z Django logging robi szum. Z mgmt commanda chcemy clean stdout (parseable JSON), Scrapy log idzie na stderr.

### D21 — [M4-D21] Celery task `scrape_deaths` + PeriodicTask seed migration (~3h)
**Branch:** `feat/<N>-scheduled-deaths-scrape`
**Zależy od:** D20 merged

**Acceptance criteria:**
- `apps/deaths/tasks.py`:
  ```python
  import json
  import logging
  import subprocess
  import sys
  from typing import Any

  from celery import shared_task, Task

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
          raise self.retry(exc=exc, countdown=60)

      if result.returncode != 0:
          logger.warning("scrape_deaths subprocess returned %s: %s", result.returncode, result.stderr[:500])

      try:
          summary = json.loads(result.stdout)
      except json.JSONDecodeError:
          logger.error("scrape_deaths stdout not JSON: %s", result.stdout[:500])
          return {"yielded": -1, "duplicates": -1, "returncode": result.returncode}

      summary["returncode"] = result.returncode
      logger.info("scrape_deaths: %s", summary)
      return summary
  ```
- `apps/deaths/migrations/0002_seed_periodic_task.py` — data migration, mirror `apps/characters/migrations/0003_seed_default_periodic_task.py`:
  - Tworzy `IntervalSchedule(every=5, period=IntervalSchedule.MINUTES)` jeśli nie istnieje (`get_or_create`).
  - Tworzy `PeriodicTask(name="scrape_deaths", task="apps.deaths.tasks.scrape_deaths", interval=<above>, enabled=False)` jeśli nie istnieje.
  - `dependencies = [("deaths", "0001_initial"), ("django_celery_beat", "0019_alter_periodictasks_options")]` (lub aktualna nazwa migracji `django_celery_beat` na master).
- `config/settings/base.py` — `DEATH_LEVEL_THRESHOLD = env.int("DEATH_LEVEL_THRESHOLD", default=30)` (jeśli nie ma już z M3 — sprawdzić; jeśli `.env.example` ma wpis ale `base.py` go nie czyta, dodać).
- `.env.example` — sprawdzić że `DEATH_LEVEL_THRESHOLD=30` jest (CLAUDE.md §10 mówi że jest, weryfikować).
- Smoke (manual): admin Django enable PeriodicTask, Beat fires task co 5 min, worker odpala subprocess, `DeathEvent.objects.count()` rośnie.

**Pułapka A:** `subprocess.run(timeout=120)` — Scrapy crawl 1 strony (z DOWNLOAD_DELAY=2s, jedno GET) trwa ~3-5s. 120s daje 24x margines. Jeśli kiedyś dodamy paginację, podnieść do 600s.

**Pułapka B:** `self.retry(exc=exc, countdown=60)` — Celery retry domyślnie liczy się w `max_retries`. Po 2 retry'ach (3 fires total) Celery `Task.MaxRetriesExceededError`. Acceptable — następny Beat fire za 5 min i tak weźmie nowe zlecenie.

**Pułapka C:** `result.stdout` to `str` (z `text=True`), nie `bytes`. `json.loads(str)` działa, ale `json.loads(b'...')` w Pythonie 3.9+ też działa. Ten sam pattern co M3, tam też było `text=True` w `scrape_watched_characters` (sprawdzić — jeśli nie, ujednolicić).

**Pułapka D (M3 lekcja "triple-source-of-truth dla deps"):** task używa tylko stdlib (`subprocess`, `json`, `logging`) + `celery` (już w deps). Brak nowych dep'ów = brak triple-source ceremonii. ALE — **management command z D20 importuje `scrapy`** w pipeline tasku (przez `manage.py scrape_deaths`), co zadziała bo `scrapy` jest w `pyproject.toml` i `pre-commit-config.yaml mypy additional_dependencies` (z M1). Sanity check: `poetry run pre-commit run mypy --files apps/deaths/tasks.py apps/deaths/management/commands/scrape_deaths.py` ZIELONY przed pushem.

**Pułapka E (M3 retro #61 lekcja):** settings name match 1:1. `DEATH_LEVEL_THRESHOLD` w `base.py` = `DEATH_LEVEL_THRESHOLD` w `.env.example` = `settings.DEATH_LEVEL_THRESHOLD` w resolverze. Jedna literówka i `getattr(settings, ...)` cicho fallbackuje do default. **Mitigation:** `settings.DEATH_LEVEL_THRESHOLD` (atrybut, nie `getattr`) — `AttributeError` przy złej nazwie zamiast cichego default.

### D22 — [M4-D22] GraphQL `recentDeaths` + e2e test + M4 closure (~4h)
**Branch:** `feat/<N>-deaths-graphql` + osobny `docs/close-m4-tracker`
**Zależy od:** D21 merged

**Acceptance criteria (kod):**
- `apps/deaths/schema.py`:
  ```python
  from typing import cast
  import strawberry
  import strawberry_django
  from strawberry import auto
  from django.conf import settings

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

          effective_min_level = min_level if min_level is not None else settings.DEATH_LEVEL_THRESHOLD
          effective_limit = min(max(limit, 1), 200)

          qs = (
              DeathEvent.objects
              .filter(level_at_death__gte=effective_min_level)
              .order_by("-died_at")[:effective_limit]
          )
          return cast("list[DeathEventType]", [e async for e in qs])
  ```
- `config/schema.py` rozszerzony:
  ```python
  from apps.deaths.schema import Query as DeathsQuery
  Query = merge_types("Query", (AccountsQuery, CharactersQuery, DeathsQuery))
  ```
- Testy GraphQL (`tests/unit/deaths/test_graphql_recent_deaths.py`):
  - `test_recent_deaths_default_uses_settings_threshold` — DB z 3 deaths (level 20/30/40), `settings.DEATH_LEVEL_THRESHOLD=30` (override przez `@override_settings`) → query bez `minLevel` zwraca 2.
  - `test_recent_deaths_explicit_min_level_overrides_default` — query `recentDeaths(minLevel: 1)` zwraca 3.
  - `test_recent_deaths_limit_capped_at_200` — DB z 250 deaths, query `limit: 1000` → 200 elementów.
  - `test_recent_deaths_ordered_by_died_at_desc` — DB z mieszanymi timestampami → response order DESC.
  - `test_recent_deaths_requires_authentication` — query bez JWT (lub z `AnonymousUser`) → error response.

**Acceptance criteria (e2e):**
- `tests/integration/test_m4_deaths_e2e.py` — pokrycie pełnego flow task → spider → service → DB w jednym teście, **bez** real subprocess i **bez** real HTTP:
  - Mock `apps.deaths.tasks.subprocess.run` z `side_effect`-em który: (a) instancjuje `DeathsSpider`, (b) buduje `HtmlResponse(body=fixture.read_bytes())`, (c) iteruje `spider.parse(response)`, (d) per yielded item woła `save_death_event(dict(item))` directly (bypass async pipeline w teście — pipeline async path pokryty w unit testach D19), (e) zlicza `yielded`/`duplicates` z return value `save_death_event`, (f) zwraca `CompletedProcess(returncode=0, stdout=json.dumps({"yielded": Y, "duplicates": D}))`.
  - **Round 1:** `scrape_deaths.apply().get()` → `{"yielded": 50, "duplicates": 0, "returncode": 0}`, `DeathEvent.objects.count() == 50`.
  - **Round 2 (re-run bez clear DB):** `scrape_deaths.apply().get()` → `{"yielded": 50, "duplicates": 50, "returncode": 0}`, `DeathEvent.objects.count() == 50` (no growth, dedup zadziałał).
  - Wzór `apply()` z M3 D17. Real subprocess + real HTTP = manual smoke (3-terminalowy test poza CI), nie automated.

**Acceptance criteria (closure):**
- `PROGRESS.md` rozszerzony o sekcję `🎉 Milestone M4 — Deaths monitor (backend) COMPLETED (YYYY-MM-DD)` z retro per Issue.
- Milestone M4 zamknięty na GitHub (`gh api -X PATCH repos/:owner/:repo/milestones/<N> -f state=closed`).

**Pułapka A (M2-D12 lekcja, znana z `character` query):** Strawberry async + Django ORM async iteration — `[e async for e in qs]` jest correct. `await qs.afirst()` działa dla single object. `list(qs)` w async resolver da `SynchronousOnlyOperation`.

**Pułapka B (M2-D12 lekcja):** auth guard powinien być explicit `if not request.user.is_authenticated` zamiast assumption "dispatch already gated". Dispatch zapewnia `request.user` istnieje (anonymous lub authenticated), ale resolver per-pole musi zdecydować czy anonymous to OK. Tu — nie OK (Pytanie 4A z brainstormu).

**Pułapka C (z post-M2 tech debt):** `min_level: int | None = None` jako default = `None`. Strawberry generuje GraphQL nullable: `minLevel: Int = null`. Klient może pominąć argument (`recentDeaths { ... }`) — wtedy resolver dostaje `min_level=None` i fallbackuje do settings. Klient może też explicit wysłać `null` — to samo zachowanie. **OK.**

**Pułapka D:** `merge_types` (M2-D12 lekcja) — flat merge fields, hard fail przy nazwie konfliktowej. `recent_deaths` jest unique (nie ma w `AccountsQuery` ani `CharactersQuery`), bezpieczne. Jeśli kiedyś dodamy `Query.deaths` w innym schema'cie — kolizja.

**Pułapka E (M3 lekcja "branch dla docs-close"):** `docs/close-m4-tracker` branch utworzyć **OD świeżego master po merge'u D22 feature'a**, nie OD test brancha (M1 retro #8).

---

## 6. Ryzyka i watch-outs

| # | Ryzyko | Mitigacja |
|---|---|---|
| R1 | tibiantis.info layout drift (klasa `mytab long` zmieni się na coś innego, albo struktura `td.ld/lu` zniknie) | **Cichy degrade** — spider yielded 0 items, task return `{"yielded": 0, "duplicates": 0}`. Watchdog (post-M4) wykryje przez `DeathEvent.objects.latest().scraped_at`. M4 ma log warning na empty table, integration test zauważy regresję jeśli fixturka się rozjedzie z prod HTML. |
| R2 | Per-row parse error psuje cały batch | Per-row try/except w spider'ze (Pułapka A w D19) + `test_row_parse_error_does_not_kill_batch`. Jeden popsuty rząd → log warning, 49 dobrych yielded. |
| R3 | TZ ambiguity (DST switch — 2026-10-25 02:30 CEST/CET overlap) | Akceptowalne ryzyko — fals dedup raz/rok w skrajnie wąskim oknie (2h). Nie naprawiamy w M4, dokumentujemy. |
| R4 | `subprocess.run` na Windows vs Linux różnice w SIGTERM | M3 retro: `timeout=` na Windows używa `TerminateProcess`, mniej graceful ale działa. Akceptowalne. M3 D16 Pułapka B precedens. |
| R5 | Beat race (drugi fire startuje gdy pierwszy wciąż działa) | Subprocess timeout 120s vs interval 5min = mało prawdopodobne. Unlike M3, deaths task nie ma freshness threshold (deaths są immutable, nie ma "last scraped"). Jeśli dwa fires nakładają się — drugi parsuje tę samą stronę, dedup w DB skip'uje. Idempotent. |
| R6 | `IntegrityError` w pipeline'ie zamiast w service'ie | Pipeline wywołuje service, service łapie IntegrityError. Jeśli pipeline złapie samo (np. concurrent kontekst Twisted) — service nigdy nie wywołany. **Mitigation:** zostawić atomic block w service, nie w pipeline. Test `test_duplicate_returns_none` pokrywa. |
| R7 | `merge_types` collision z innym Query | Niezerowy ale niski risk — `recent_deaths` nazwa unique. |
| R8 | Spider robi `process.crawl()` w teście unit i się wywala (Pułapka A w D20) | Mock `CrawlerProcess` w unit testach mgmt commanda. Test `test_command_outputs_json_summary` używa `unittest.mock.patch`. |
| R9 | Pipeline counter nie zliczy duplicates (pipeline `result is None` check z service'u — service zwraca None na IntegrityError — pipeline `inc_value`) — co jeśli service rzuci inny exception (np. ValueError z ValueError w `create`)? | Service łapie tylko `IntegrityError`. Inne wyjątki propagują, pipeline nie złapie, Twisted error handler je log'uje, item nie ląduje w DB ani w `duplicates` counter. **Akceptowalne** — anomalia, dobrze że nie cicho. |
| R10 | Task return shape change w D21 łamie integration test w D22 | Strict chain D21 → D22, integration test pisany po implementacji task'a. Mock subprocess zwraca expected stdout shape, asercje na `result["yielded"]`/`result["duplicates"]`. |

---

## 7. Pre-flight checklist (przed startem D18)

- [x] **Fixturka `tests/fixtures/deaths_sample.html`** zapisana (33KB, 50 deaths, 2026-04-30 fetch). **Zweryfikowane podczas brainstormu**.
- [ ] **Milestone "M4 — Deaths monitor (backend)"** utworzony na GitHub.
- [ ] **5 Issues (#<N>-#<N+4>)** z linkami do tego spec'a + AC z odpowiednich D-section.
- [ ] **`gh issue list --milestone "M4 — Deaths monitor (backend)"`** zwraca 5 Issues po creation.
- [ ] **Sprawdzić aktualną nazwę najświeższej migracji `django_celery_beat`** (D21 dependency): `python manage.py showmigrations django_celery_beat | tail -5`. Wstawić do `0002_seed_periodic_task.py`.
- [ ] **`.env.example` ma `DEATH_LEVEL_THRESHOLD=30`** — sprawdzić, dodać jeśli nie ma.
- [ ] **`config/settings/base.py` czyta `DEATH_LEVEL_THRESHOLD`** — sprawdzić, dodać jeśli nie ma. Spójność z M3 retro #59 lekcja "triple-source-of-truth".

---

## 8. Definition of Done (M4)

- [ ] **5 PR merged, 5 Issues zamknięte** (D18-D22).
- [ ] **`apps.deaths` zarejestrowane w `INSTALLED_APPS`**, migracje aplikują się czysto na świeżej bazie (`manage.py migrate`).
- [ ] **`DeathEvent` widoczne w Django admin** z list_display i search.
- [ ] **`scrapy crawl deaths`** (manualnie z roota repo) parsuje fixturkę lokalną OR live page (manual smoke), yieldsy ≥1 item.
- [ ] **`python manage.py scrape_deaths`** wypluwa valid JSON `{"yielded": N, "duplicates": M}` na stdout, returncode 0.
- [ ] **`scrape_deaths.delay().get()`** (z eager mode lub real worker) zwraca dict z polami `yielded`, `duplicates`, `returncode`.
- [ ] **PeriodicTask `scrape_deaths` enable'uje się w admin**, Beat fires task co 5 min, deaths zaczynają lądować w DB.
- [ ] **GraphQL `recentDeaths(minLevel: 1, limit: 10)`** zwraca 10 najnowszych deaths (po manual smoke z włączonym Beat'em + populated DB).
- [ ] **GraphQL `recentDeaths` bez JWT** → error response (auth required).
- [ ] **Wszystkie pre-commit + CI zielone na master** dla każdego PR-a.
- [ ] **`coverage threshold = 70` zachowane** (lokalnie cel 100% dla `apps/deaths/*.py`).
- [ ] **PROGRESS.md** rozszerzony o sekcję M4 z retro per Issue.
- [ ] **Milestone M4 zamknięty** na GitHub.

---

## 9. Open questions / future

**Otwarte (nie blokujące M4, do decyzji w M5+):**
- Czy `DeathEvent.character_name` powinno mieć FK do `Character` w przyszłości? Decyzja: nie w M4 (różny domain — deaths obejmują postacie nie-watched). Może w M5 jako optional FK z `null=True` + indeksowanie przez `character_name` zachowane jako fallback.
- Watchdog "deaths feed lag" — alarm gdy najnowszy `died_at` >1h temu (sygnał że strona padła lub spider się zepsuł). M5 razem z Discord announcerem (tam jest infra na alarmy).
- Mongo `scrape_logs` (CLAUDE.md §4) — strukturalne logi scrape'a (URL, czas, liczba items, errors). M5+ razem z `apps/notifications/`.
- "From players" tab (PvP-only feed) — jeśli okaże się że biznes chce osobnego threshold dla PvP vs mob deaths. M5+.
- Multi-page scrape — backfill po incident lub jeśli interwał scrape urośnie do >>5 min. Niska wartość, M-future.
- `announced_on_discord` field — dorobimy w M5 razem z announcerem.

**Tech debt z M3 do adresowania razem z M4 (jeśli się składa):**
- `celery-types` package — pierwszy kandydat na chore PR M4 pre-flight (M3 retro lekcja 1). **Decyzja:** odłożyć na osobny standalone PR, nie blokować M4 startu. Workaround `self: Any` z M3 D16 nadal działa.
- Branch protection master required check `test / Pytest` — niezamknięte z post-M2. Dodać w GitHub Settings → Branches **przed startem M4 D18**, żeby M4 PR-y miały full coverage check.
- Spider defensive parsing (`int(level_raw)` na "118 (deleted)" w `character_spider.py:49`, hardcoded `Europe/Berlin` TZ) — niezamknięte z post-M2/M3. **M4 spider używa `re.search` na `\d+` regex** więc nowy hardening — explicit. Stary `character_spider` zostaje, naprawimy w osobnym chore PR (kandydat na M4 pre-flight lub side PR).
- Fragile fixture path `parents[3]` (z post-M2 tech debt) — spec D19 Pułapka D mówi zostawić dla spójności. Refactor osobno.

---

## 10. References

- **CLAUDE.md** §1 (cel biznesowy: Monitoring śmierci), §3 (struktura katalogów), §5 (model `DeathEvent` szkic), §6 (Cel 2 scraping), §7 (Deaths monitor logika), §9 (GraphQL surface), §10 (`DEATH_LEVEL_THRESHOLD` env var).
- **PROGRESS.md** — retro M3 lekcje (1-5), tech debt M2/M3.
- **Spec M3** `docs/superpowers/specs/2026-04-28-m3-celery-fundament-design.md` — wzór dekompozycji + PeriodicTask migration pattern.
- **Spec M2** `docs/superpowers/specs/2026-04-22-m2-auth-graphql-fundament-design.md` — wzór GraphQL Query + auth dispatch (M2-D12).
- **M1 fixturka** `tests/fixtures/character_yhral.html` + `tests/unit/scrapers/test_character_spider.py` — wzór fixture-based spider testu.
- **M3 task** `apps/characters/tasks.py::scrape_watched_characters` — wzór subprocess + JSON return + `@shared_task(bind=True, max_retries=2)`.
- **M3 PeriodicTask migration** `apps/characters/migrations/0003_seed_default_periodic_task.py` — wzór data migration dla seed'u.
- **Fixturka deaths** `tests/fixtures/deaths_sample.html` — zapisana podczas brainstormu 2026-04-30, 33KB, 50 deaths, full HTML z paginacją + tabami.
