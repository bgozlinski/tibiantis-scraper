# Tibiantis Monitor — Progress

## 🎉 Milestone M0 — Bootstrap COMPLETED (2026-04-17)
Wszystkie 3 zadania ukończone, milestone zamknięty.

## Następny milestone: M1 — First character scrape
**Status:** 3/5 dni

### Ukończone (M0)
- ✅ #1 [M0-D1] Inicjalizacja repo + GitHub + branch protection (2026-04-17) — PR [#9](https://github.com/bgozlinski/tibiantis-scraper/pull/9) — squash `d611e2a`
- ✅ #2 [M0-D2] Django 6 project + Postgres lokalnie + pierwszy runserver (2026-04-17) — PR [#10](https://github.com/bgozlinski/tibiantis-scraper/pull/10) — squash `cc89de3`
- ✅ #3 [M0-D3] pre-commit + ruff + mypy + CI lint (2026-04-17) — PR [#11](https://github.com/bgozlinski/tibiantis-scraper/pull/11) — squash `1f9b072`

### Ukończone (M1)
- ✅ #4 [M1-D4] apps/ struktura + app `characters` zarejestrowana (2026-04-17) — PR [#12](https://github.com/bgozlinski/tibiantis-scraper/pull/12) — squash `10bbf44`
- ✅ #5 [M1-D5] Model `Character` + migracja + admin + test job w CI + pierwszy test (2026-04-18) — PR [#14](https://github.com/bgozlinski/tibiantis-scraper/pull/14) — squash `831344c`
- ✅ #6 [M1-D6] Service layer: `upsert_character()` (2026-04-18) — PR [#16](https://github.com/bgozlinski/tibiantis-scraper/pull/16) — squash `04d1b88`

### W trakcie
_(pusto)_

### Następne (M1)
- 🔜 #7 [M1-D7] Scrapy: minimalny spider `character_spider`
- 🔜 #8 [M1-D8] Pipeline Scrapy → service + management command (**M1 done**)

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
  - Brak docstringa na `upsert_character()` — funkcja self-explanatory, ale AC #6 sugerowało docstring (max 3 linie). Dopisać przy najbliższej okazji (np. razem z #7 jak spider zacznie wywoływać service).
  - Race condition w `update_or_create`: dwa Celery workery scrapeujące tę samą postać równocześnie mogą trafić w `IntegrityError` na unique `name`. Do ogarnięcia w #8 (pipeline) — albo retry, albo `select_for_update` w transakcji, albo dedup po stronie schedulera.

### Notatki z retro M1
- **#6 (merge 2026-04-18):** PyCharm auto-import wrzucił `from IPython.core.magic_arguments import defaults` do `types.py` bo zmienna lokalna nazywała się `defaults`. Wniosek: po napisaniu service przelecieć wzrokiem top-of-file imports, PyCharm czasem halucynuje. Drugi wniosek: mieszanie `services.py` i `types.py` w jednym pliku (pierwotnie wszystko w `types.py`) złapane w review — zgodnie z CLAUDE.md §3 logika do `services.py`, typy osobno. Trzeci: funkcja deklarowała `-> Character` ale nie miała `return` — mypy strict by to złapał, ale warto przed pushem odpalić `poetry run mypy apps/` lokalnie zamiast liczyć na CI.
