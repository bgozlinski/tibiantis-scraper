# Tibiantis Monitor — Progress

## 🎉 Milestone M0 — Bootstrap COMPLETED (2026-04-17)
Wszystkie 3 zadania ukończone, milestone zamknięty.

## Następny milestone: M1 — First character scrape
**Status:** 0/5 dni — start kiedy gotowy

### Ukończone (M0)
- ✅ #1 [M0-D1] Inicjalizacja repo + GitHub + branch protection (2026-04-17) — PR [#9](https://github.com/bgozlinski/tibiantis-scraper/pull/9) — squash `d611e2a`
- ✅ #2 [M0-D2] Django 6 project + Postgres lokalnie + pierwszy runserver (2026-04-17) — PR [#10](https://github.com/bgozlinski/tibiantis-scraper/pull/10) — squash `cc89de3`
- ✅ #3 [M0-D3] pre-commit + ruff + mypy + CI lint (2026-04-17) — PR [#11](https://github.com/bgozlinski/tibiantis-scraper/pull/11) — squash `1f9b072`

### W trakcie
_(pusto)_

### Następne (M1)
- 🔜 #4 [M1-D4] apps/ struktura + app `characters` zarejestrowana
- 🔜 #5 [M1-D5] Model `Character` + migracja + admin + test job w CI + pierwszy test
- 🔜 #6 [M1-D6] Service layer: `upsert_character()`
- 🔜 #7 [M1-D7] Scrapy: minimalny spider `character_spider`
- 🔜 #8 [M1-D8] Pipeline Scrapy → service + management command (**M1 done**)

### Notatki z retro M0
- **#1 (merge 2026-04-17):** Issue #1 wymagał drobnego fixup commita — w pierwotnym commicie brakowało 8 wzorców z AC. Wniosek: warto przed push przeklikać AC checklist linia po linii.
- **#2 (merge 2026-04-17):** dwa drobne bugi złapane w lokalnym review przed pushem (`env("DJANGO_SECRET_KEY,")` z przecinkiem i `BASE_DIR = parent.parent` zamiast `parent.parent.parent` w subpackage settings). Wniosek: przy rozbijaniu plików sprawdzaj wszystkie ścieżki względne.
- **#3 (merge 2026-04-17):** długa walka z CI (11 commitów fixów). Kluczowe odkrycia:
  - Poetry 2.x + PEP 621 `[project]` wymaga spójności: pusta sekcja `[tool.poetry]` wymusza legacy mode i blokuje PEP 621.
  - `requires-python` w `[project]` musi być PEP 440 (`>=3.13,<4.0`), nie Poetry caret (`^3.13`).
  - `[dependency-groups]` (PEP 735) w Poetry 2.0.x nie jest instalowane przez `--with dev` ani `--all-groups` — dopiero od 2.1.
  - Ostateczne rozwiązanie dla lint joba: **pre-commit bez Poetry** — `pip install pre-commit` + `pre-commit run --all-files`. Pre-commit ma własne isolated envs per hook, Poetry niczego tu nie daje. Ten wzorzec przetrwa dla `lint` joba, test job dostanie Poetry w swoim czasie.
  - **Wniosek:** zapisywać w CLAUDE.md aktualne wersje tylko jak się potwierdzą w CI, nie z głowy. Sesja #3 zjadła sporo czasu bo rev hooków (Poetry 1.8.4) i python-version ("3.12") w CLAUDE.md nie odpowiadały rzeczywistej instalacji (Poetry 2.x, Python 3.13) — przenosiliśmy CLAUDE.md "wyprzedająco", ale rzeczywistość trafiała dopiero po wielu iteracjach.
- **Solo-repo paradox:** GitHub blokuje self-approval własnego PR, dlatego Claude nie może `--approve` — zostawia komentarz LGTM. Branch protection ma `enforce_admins=false`, więc Ty mergeujesz jako admin.
- **Squash-only enforced (2026-04-17):** repo skonfigurowane tak, że UI GitHuba pokazuje tylko „Squash and merge" (`allow_merge_commit=false`, `allow_rebase_merge=false`).

### Obserwacje techniczne do adresowania w kolejnych issues
- W `config/settings/base.py` brakuje `DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'` — Django rzuci `W042` przy pierwszym modelu (#4).
- `dev.py` hardcoduje `DEBUG = True` i `ALLOWED_HOSTS = ['*']`, override'ując wartości z env. Do przemyślenia czy `DJANGO_DEBUG`/`DJANGO_ALLOWED_HOSTS` z `.env.example` mają sens dla dev.
- CLAUDE.md §13 pokazuje rozbudowany `ci.yml` z Postgresem/Redisem/Mongo dla test joba — obecnie mamy tylko lint job. Test job wejdzie gdy pojawią się testy (Issue #4+).
- `django-upgrade` target pinowany na `5.1` (maks. który narzędzie zna w rev `1.22.1`). Przy `pre-commit autoupdate` w przyszłości sprawdzić czy nowa rev wspiera `6.0`.
