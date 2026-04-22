# Tibiantis Monitor — Progress

## 🎉 Milestone M0 — Bootstrap COMPLETED (2026-04-17)
Wszystkie 3 zadania ukończone, milestone zamknięty.

## 🎉 Milestone M1 — First character scrape COMPLETED (2026-04-22)
Wszystkie 5 zadań ukończone, milestone zamknięty.

## 🚀 Milestone M2 — Auth + GraphQL fundament IN PROGRESS (start 2026-04-22)
Design spec: [`docs/superpowers/specs/2026-04-22-m2-auth-graphql-fundament-design.md`](docs/superpowers/specs/2026-04-22-m2-auth-graphql-fundament-design.md). Budżet 4 dni, 4 Issues (strict chain D9→D10→D11→D12).

### Ukończone (M0)
- ✅ #1 [M0-D1] Inicjalizacja repo + GitHub + branch protection (2026-04-17) — PR [#9](https://github.com/bgozlinski/tibiantis-scraper/pull/9) — squash `d611e2a`
- ✅ #2 [M0-D2] Django 6 project + Postgres lokalnie + pierwszy runserver (2026-04-17) — PR [#10](https://github.com/bgozlinski/tibiantis-scraper/pull/10) — squash `cc89de3`
- ✅ #3 [M0-D3] pre-commit + ruff + mypy + CI lint (2026-04-17) — PR [#11](https://github.com/bgozlinski/tibiantis-scraper/pull/11) — squash `1f9b072`

### Ukończone (M1)
- ✅ #4 [M1-D4] apps/ struktura + app `characters` zarejestrowana (2026-04-17) — PR [#12](https://github.com/bgozlinski/tibiantis-scraper/pull/12) — squash `10bbf44`
- ✅ #5 [M1-D5] Model `Character` + migracja + admin + test job w CI + pierwszy test (2026-04-18) — PR [#14](https://github.com/bgozlinski/tibiantis-scraper/pull/14) — squash `831344c`
- ✅ #6 [M1-D6] Service layer: `upsert_character()` (2026-04-18) — PR [#16](https://github.com/bgozlinski/tibiantis-scraper/pull/16) — squash `04d1b88`
- ✅ #7 [M1-D7] Scrapy: minimalny spider `character_spider` (2026-04-18) — PR [#18](https://github.com/bgozlinski/tibiantis-scraper/pull/18) — squash `114ff86`
- ✅ #8 [M1-D8] Pipeline Scrapy → service + management command (2026-04-22) — PR [#25](https://github.com/bgozlinski/tibiantis-scraper/pull/25) — squash `75e516c`

### Ukończone (M2)
- ✅ #28 [M2-D9] accounts app + custom User + AUTH_USER_MODEL (2026-04-22) — PR [#33](https://github.com/bgozlinski/tibiantis-scraper/pull/33) — squash `56961b3`

### W trakcie
_(pusto)_

### Następne (M2)
- #29 [M2-D10] REST auth endpoints (register/login/refresh/logout) — `feat/29-rest-auth-jwt`, zależy od #28 ✅
- #30 [M2-D11] Strawberry schema + `/graphql/` + `me` query — `feat/30-graphql-bootstrap`, zależy od #29
- #31 [M2-D12] JWT w GraphQL + `character(name)` + e2e test — `feat/31-graphql-jwt-character`, zależy od #30

### Notatki z retro M0
- **#1 (merge 2026-04-17):** Issue #1 wymagał drobnego fixup commita — w pierwotnym commicie brakowało 8 wzorców z AC. Wniosek: warto przed push przeklikać AC checklist linia po linii.
- **#2 (merge 2026-04-17):** dwa drobne bugi złapane w lokalnym review przed pushem (`env("DJANGO_SECRET_KEY,")` z przecinkiem i `BASE_DIR = parent.parent` zamiast `parent.parent.parent` w subpackage settings). Wniosek: przy rozbijaniu plików sprawdzaj wszystkie ścieżki względne.
- **#3 (merge 2026-04-17):** długa walka z CI (11 commitów fixów). Kluczowe odkrycia:
  - Poetry 2.x + PEP 621 `[project]` wymaga spójności: pusta sekcja `[tool.poetry]` wymusza legacy mode i blokuje PEP 621.
  - `requires-python` w `[project]` musi być PEP 440 (`>=3.13,<4.0`), nie Poetry caret (`^3.13`).
  - `[dependency-groups]` (PEP 735) w Poetry 2.0.x nie jest instalowane przez `--with dev` ani `--all-groups`. **Uzupełnione po #5 (2026-04-18):** nawet w Poetry 2.1.4 `--all-groups` nie obejmuje PEP 735 groups — dopiero `[tool.poetry.group.dev.dependencies]` (Poetry-native) działa przewidywalnie. Wniosek: używaj Poetry-native groups dla CI-heavy projektów, PEP 735 w Poetry nie jest jeszcze battle-tested.
  - Ostateczne rozwiązanie dla lint joba: **pre-commit bez Poetry** — `pip install pre-commit` + `pre-commit run --all-files`. Pre-commit ma własne isolated envs per hook, Poetry niczego tu nie daje. Ten wzorzec przetrwa dla `lint` joba, test job dostanie Poetry w swoim czasie.
  - **Wniosek:** zapisywać w CLAUDE.md aktualne wersje tylko jak się potwierdzą w CI, nie z głowy. Sesja #3 zjadła sporo czasu bo rev hooków (Poetry 1.8.4) i python-version ("3.12") w CLAUDE.md nie odpowiadały rzeczywistej instalacji (Poetry 2.x, Python 3.13) — przenosiliśmy CLAUDE.md "wyprzedająco", ale rzeczywistość trafiała dopiero po wielu iteracjach.
- **Solo-repo paradox:** GitHub blokuje self-approval własnego PR, dlatego Claude nie może `--approve` — zostawia komentarz LGTM. Branch protection ma `enforce_admins=false`, więc Ty mergeujesz jako admin.
- **Squash-only enforced (2026-04-17):** repo skonfigurowane tak, że UI GitHuba pokazuje tylko „Squash and merge" (`allow_merge_commit=false`, `allow_rebase_merge=false`).

### Obserwacje techniczne do adresowania w kolejnych issues
- ~~W `config/settings/base.py` brakuje `DEFAULT_AUTO_FIELD`~~ — rozwiązane w #4.
- ~~`CharactersConfig` ma redundantny `default_auto_field`~~ — rozwiązane w #5.
- ~~`INSTALLED_APPS` 2-way split~~ — rozwiązane w #5 (3-way z `DJANGO_APPS`/`THIRD_PARTY_APPS`/`LOCAL_APPS`).
- ~~Test job w CI~~ — rozwiązane w #5 (Postgres 16 service + pytest + coverage).
- `dev.py` hardcoduje `DEBUG = True` i `ALLOWED_HOSTS = ['*']`, override'ując wartości z env. Do przemyślenia czy `DJANGO_DEBUG`/`DJANGO_ALLOWED_HOSTS` z `.env.example` mają sens dla dev.
- `django-upgrade` target pinowany na `5.1` (maks. który narzędzie zna w rev `1.22.1`). Przy `pre-commit autoupdate` w przyszłości sprawdzić czy nowa rev wspiera `6.0`.
- **Tech debt z #5 (do adresowania post-M1):**
  - `Meta.indexes = [models.Index(fields=["name"])]` — redundant z `unique=True` na `name` (już tworzy unique btree). Usunąć w chore PR, zregenerować migrację.
  - `admin.ModelAdmin` bez generic parameter (`# type: ignore[type-arg]` zamiast `ModelAdmin[Character]`). Alternatywa — `django-stubs-ext.monkeypatch()` w `base.py`. Decyzja na później.
  - `coverage threshold = 0` — AC #5 Pułapka F mówi podnosić do 70 w osobnym PR post-M1. Kandydat na Issue #9.
  - Branch protection master: dodać required status check `test / Pytest` (obecnie tylko `lint`).
  - CLAUDE.md §12 pokazuje `[dependency-groups]` (PEP 735) jako pattern — w praktyce okazało się że Poetry 2.1.4 nie instaluje takich groups przez `--all-groups`. Teraz używamy `[tool.poetry.group.dev.dependencies]` (Poetry-native). CLAUDE.md wymaga update żeby odzwierciedlał rzeczywistość.
- **Tech debt z #6 (do adresowania post-M1):**
  - ~~Brak docstringa na `upsert_character()`~~ — rozwiązane w #8 (docstring opisuje kontrakt + race window).
  - ~~Race condition w `update_or_create`~~ — rozwiązane w #8 (retry na `IntegrityError` w osobnym `transaction.atomic()` savepoincie).
- **Tech debt z #7 (do adresowania post-M1):**
  - **Bug `self.name` vs `self.character_name` w `character_spider.py:30`** — log warning dla postaci "not found" pokazuje nazwę spidera (`"character"`), nie imię postaci. `Spider.name` to class-level attr Scrapy, instance var nazywa się `self.character_name`. Wyłapie test z log capture (follow-up).
  - **Bug `_parse_last_login` crashuje na "Never logged in"** — `rsplit(" ", 1)` na takim stringu da `("Never logged", "in")` i `strptime` rzuci `ValueError`. Potrzebny early return + fixtura edge case.
  - **Brak defensywnego parsowania `level`** — `int(level_raw)` pada gdy layout strony się zmieni lub pojawi się np. `"118 (deleted)"`. Rozważyć regex `^\d+` albo try/except.
  - **`_parse_last_login` hardcoduje `Europe/Berlin`** zamiast walidować odczytaną TZ (`_tz` jest odrzucona). Nit, ale gdyby serwer kiedyś wysłał inny TZ, cichy bug. Minimum: assert `_tz in {"CEST","CET"}` albo warning.
  - **Fragile fixture path `parents[3]`** w `tests/unit/scrapers/test_character_spider.py` — przy przeniesieniu katalogu cicho zwróci złą ścieżkę. Refactor do `conftest.py` w `tests/`.
  - **Deviation od AC#7** (świadoma, nie bug): `scrapy.cfg` w rootcie repo zamiast `scrapers/`, wszystkie importy z prefiksem `scrapers.tibiantis_scrapers...`. Konsekwencja dla #8: management command musi ustawić `SCRAPY_SETTINGS_MODULE=scrapers.tibiantis_scrapers.settings` (z prefiksem) i uruchomić crawl z roota repo.

### Notatki z retro M1
- **#6 (merge 2026-04-18):** PyCharm auto-import wrzucił `from IPython.core.magic_arguments import defaults` do `types.py` bo zmienna lokalna nazywała się `defaults`. Wniosek: po napisaniu service przelecieć wzrokiem top-of-file imports, PyCharm czasem halucynuje. Drugi wniosek: mieszanie `services.py` i `types.py` w jednym pliku (pierwotnie wszystko w `types.py`) złapane w review — zgodnie z CLAUDE.md §3 logika do `services.py`, typy osobno. Trzeci: funkcja deklarowała `-> Character` ale nie miała `return` — mypy strict by to złapał, ale warto przed pushem odpalić `poetry run mypy apps/` lokalnie zamiast liczyć na CI.
- **#7 (merge 2026-04-18):** Spider parsuje fixture HTML poprawnie (6 testów green), wszystkie pola modelu pokryte. W retro-review wyszły 2 bugi niewyłapane przez testy (`self.name` w logu = nazwa spidera, nie postaci; `_parse_last_login` crashuje na "Never logged in") → follow-up PR dopisze fixturki edge-case i pokryje te ścieżki, bugi do naprawy w osobnym issue. **"Dependency conflicts" w PR title** sugeruje walkę z Poetry przy `poetry add scrapy` — warto spisać co się wydarzyło (bg: Scrapy pociąga Twisted + cryptography + lxml, potencjał kolizji z django-stubs). Świadoma deviation od AC: `scrapy.cfg` w root repo + prefiks `scrapers.` w importach → uprości #8 (brak `cd scrapers/`), ale w management command będzie `SCRAPY_SETTINGS_MODULE=scrapers.tibiantis_scrapers.settings` zamiast `tibiantis_scrapers.settings`.
- **#8 (merge 2026-04-22):** Cztery AC, pięć commitów (`build(deps)`, AC1 pipeline, AC2 command, AC3 tests, AC4 race retry). Wyzwania:
  - **Scrapy 2.x async pipelines** — `process_item` musi być `async def` i ORM-y owinąć `sync_to_async`; pierwsze podejście (sync) dało `SynchronousOnlyOperation` przy pierwszym scrapie.
  - **Twisted reactor + crochet + Windows** — trzy gotchas w jednej linii: (1) `asyncioreactor.install()` MUSI być przed `from crochet import ...`, (2) na win32 `WindowsSelectorEventLoopPolicy` zamiast ProactorEventLoop (niekompatybilny z `asyncioreactor`), (3) w `scrapers/settings.py` trzeba dodać `django.setup()` żeby direct `scrapy crawl` też działał.
  - **Pre-commit mypy w isolated env** — bez `scrapy`/`crochet`/`twisted` w `additional_dependencies` hook nie widział base classes → landed jako osobny PR #24 zgodnie z CLAUDE.md §12 (infrastruktura odseparowana od kodu funkcjonalnego).
  - **AC4 race condition** — rozwiązanie: jeden retry w `except IntegrityError`, każda próba w swoim `transaction.atomic()` savepoint (bez tego aborted transaction po pierwszym `IntegrityError` blokuje retry). Sygnał z retro #6 zadziałał — był flagowany jako tech debt do #8.
  - **Ops blunder — accidental duplicate PR #26:** po PR #25 (zmergowany) otworzyłem docs/close-m1-tracker z zamiarem aktualizacji PROGRESS.md, ale branch był utworzony OD feat/8 (nie od master) i nigdy nie dopisał się commit z PROGRESS.md. Pushed + zmergowany jako PR #26 = no-op squash `fe805eb` na master duplikujący treść PR #25. Wniosek: **zawsze twórz docs-close branch OD świeżego master po merge'u feature'a**, nie od feature-brancha. `git checkout master && git pull && git checkout -b docs/...` jako stały procedurę.
  - **Wniosek:** Scrapy + Django + Celery-ready = 3 event loopy (Twisted, asyncio, Django sync). Kluczowe było trzymać integrację w jednym miejscu (management command + pipeline) i trzymać pipeline po stronie async.

### Notatki z retro M2
- **#28 (merge 2026-04-22):** Implementacja minimalistyczna zgodnie ze spec §5/D9 — 5 linii `models.py`, 10 linii `admin.py`. R1 (kolejność migracji) zweryfikowane pre-flightem (żadnego FK na User jeszcze nie ma), R4 (`UserAdmin.add_fieldsets` vs password fields) zaadresowane przez spread `*(BaseUserAdmin.add_fieldsets or ())` który zachowuje `password1`/`password2` z base + doklejenie sekcji Discord. PR zmerge'owany bez code review (solo-repo paradox z retro M0 — self-approval zablokowany przez GitHub, mergujemy jako admin). Testy jednostkowe dopisywane follow-upem zgodnie z workflow.
- **Tech debt z #28 (do adresowania post-M2):**
  - **`db_index=True` + `unique=True` na `discord_id`** — redundant (Postgres `UNIQUE` tworzy btree automatycznie). Ten sam pattern co `Character.name` flagowany w retro M1 (#5 tech debt). Kandydat na chore PR razem z Character cleanup + regeneracja migracji.
  - **Escaped markdown w body PR #33** (`\##`, `&#x20;`, `\\\`) — `gh pr create --body` na Windows zjada heredoc/quoting inaczej niż na Linux. Rozwiązanie na przyszłość: pisać body do pliku tymczasowego i używać `--body-file`, albo PR-y z UI GitHuba gdy treść ma markdown formatting.
