# Tibiantis Monitor — M0 + M1 Implementation Plan

> **For agentic workers:** This plan is NOT executed by Claude. Wykonawcą jest developer (bgozlinski). Claude używa tego dokumentu jako źródła treści dla GitHub Issues — tworzy Issue per task gdy repo powstanie na GitHubie (Task #1). Format kroków (`- [ ]`) służy jako acceptance criteria w Issue, nie jako checkboxy dla Claude.

**Goal:** Dostarczyć pierwszy end-to-end działający slice projektu Tibiantis Monitor: scrapowanie pojedynczej postaci z `tibiantis.online` i zapisanie jej do lokalnego Postgresa przez Django management command.

**Architecture:** Vertical slice. Warstwa po warstwie — najpierw minimalna infra (git + GitHub + Django + Postgres lokalnie + ruff/mypy/CI lint), potem pierwszy model + service + spider + pipeline + management command. Bez Dockera, bez Celery, bez Mongo, bez Discorda — wszystkie te warstwy wchodzą w M5+.

**Tech Stack (dla M0-M1):** Python 3.13, Poetry, Django 6.0, psycopg3, django-environ, Postgres 16 (lokalnie), Scrapy, pytest + pytest-django, ruff, mypy (strict dla `apps/`), pre-commit, GitHub Actions.

---

## Źródła

- **Spec procesu:** `docs/superpowers/specs/2026-04-17-tibiantis-execution-plan-design.md` (approved 2026-04-17)
- **Spec techniczny:** `CLAUDE.md` (stos, struktura, konwencje, pre-commit, CI)

## Otwarte pytania do developera (do ustalenia w D3)

1. **Python 3.12 vs 3.13:** `CLAUDE.md §12` pokazuje `default_language_version: python: python3.12` w `.pre-commit-config.yaml`, ale `pyproject.toml` ma `python = "^3.13"`. Sprzeczność. **Sugestia:** ujednolić do **3.13** w obu miejscach. Rozstrzygamy w D3 Step 2 — patrz pytanie w Pułapkach D3.
2. **Coverage threshold w CI:** `CLAUDE.md §13.1` ma `--cov-fail-under=70`. W D5 ledwie zaczynamy pisać kod — 70% może być nieosiągalne. **Sugestia:** threshold = 0 do końca M1, 70 od startu M2. Flagujemy w D3 Step 5.
3. **Hosting Postgres lokalnie:** dev na Windows — Postgres jako natywny instalator czy WSL? **Sugestia:** instalator Windows (prostsze), `DATABASE_URL=postgres://localhost:5432/...`. Rozstrzygamy w D2 Step 1.

---

## Task #1 — [M0-D1] Inicjalizacja repo + GitHub + branch protection

**Milestone:** M0 — Bootstrap
**Czas:** 3-4h
**Branch:** `chore/1-repo-setup` → PR → merge do `master`
**Type:** `chore`

### 🎯 Cel
Projekt ma repo na GitHubie z branchem `master`, włączoną ochroną brancha (1 approve + green CI), labelami i milestones, a plik `CLAUDE.md` + spec + plan są w historii git'a.

### 🧠 Czego się nauczysz
- Różnica między `git init` + `gh repo create` a `gh repo create --source=.`
- Jak działa **branch protection** w GitHubie (required approvals, required status checks, force-push block)
- `gh` CLI auth flow i zakresy tokena (`repo`, `workflow`, `admin:org` — tylko `repo` jest tu potrzebne)
- Tworzenie labels i milestones przez `gh` CLI (zamiast klikania w UI)
- Dlaczego `master` vs `main` — w CLAUDE.md jest `master`, trzymamy się tego

### ✅ Acceptance criteria
- [ ] Repozytorium utworzone na GitHubie jako `bgozlinski/tibiantis-scraper` (private lub public — wybór developera)
- [ ] Domyślny branch to `master` (nie `main`)
- [ ] Branch protection na `master`:
  - [ ] Require a pull request before merging
  - [ ] Require approvals: 1
  - [ ] Dismiss stale approvals when new commits are pushed
  - [ ] Require status checks to pass before merging — na razie pusta lista (dodamy `lint` w D3)
  - [ ] Do not allow bypassing the above settings
  - [ ] Block force pushes
  - [ ] Automatically delete head branches po merge
- [ ] `.gitignore` zawiera: `__pycache__/`, `*.pyc`, `.env`, `.venv/`, `venv/`, `*.sqlite3`, `/staticfiles/`, `/media/`, `.idea/`, `.vscode/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`, `htmlcov/`, `.coverage`, `coverage.xml`
- [ ] Labels utworzone (przez `gh label create`):
  - [ ] `phase-M0`, `phase-M1`, `phase-M2`, ..., `phase-M9` (różne kolory)
  - [ ] `app:characters`, `app:accounts`, `app:bedmages`, `app:deaths`, `app:notifications`, `app:infra`
  - [ ] `type:feat`, `type:fix`, `type:chore`, `type:refactor`, `type:test`, `type:docs`
  - [ ] `status:ready`, `status:in-progress`, `status:blocked`, `status:needs-review`
- [ ] Milestones utworzone: `M0 — Bootstrap`, `M1 — First character scrape`, ..., `M9 — Hardening` (10 sztuk)
- [ ] Pierwszy commit na `master` zawiera: `CLAUDE.md`, `docs/superpowers/specs/2026-04-17-tibiantis-execution-plan-design.md`, `docs/superpowers/plans/2026-04-17-m0-m1-implementation-plan.md`, `.gitignore`, `README.md` (minimalne, 1 akapit opisu + link do `CLAUDE.md`), `PROGRESS.md` (pusty template)
- [ ] Ten task (#1) zamknięty przez PR, który wykona też resztę inicjalizacji (branch→PR→merge). Commit/PR zgodny z Conventional Commits: `chore: initialize repo with specs and plans`

### 📋 Sugerowane kroki
1. Zweryfikuj `gh auth status` — jeśli niezalogowany: `gh auth login` (scope `repo`)
2. `cd C:/Users/barte/PycharmProjects/tibantis-scraper`
3. `git init -b master` (od razu `master`, nie `main`)
4. Utwórz `.gitignore` — możesz ściągnąć z `gh gitignore list` / [toptal gitignore](https://www.toptal.com/developers/gitignore/api/python,django,pycharm) i dodać sekcje powyżej
5. Utwórz minimalny `README.md` (2-3 linijki) i pusty `PROGRESS.md` z sekcjami z §9 speca
6. `git add -A && git commit -m "chore: initial commit with specs and plans"`
7. `gh repo create bgozlinski/tibiantis-scraper --source=. --push --private` (lub `--public`)
8. **Workaround dla branch protection tej samej sesji:** GitHub nie pozwala wykonać PR-merge gdy nie ma drugiego użytkownika (nikt nie może approve'ować Twojego PR-a na prywatnym repo jednoosobowym). **Rozwiązanie:** w branch protection odznacz „Do not allow bypassing" — dzięki temu jako admin repo możesz merge'ować własne PR-y. To **nie** jest bezpieczne w zespołowym repo, ale w solo-projekcie jest jedyny sensowny setup.
9. Włącz branch protection: `gh api --method PUT /repos/bgozlinski/tibiantis-scraper/branches/master/protection ...` (szczegółowa komenda — patrz Dokumentacja) **albo** przez UI: Settings → Branches → Add rule
10. Utwórz labels: `gh label create "phase-M0" --color "0E8A16"` itd. (18+ labels — napisz sobie skrypt bash lub Python)
11. Utwórz milestones: `gh api --method POST /repos/bgozlinski/tibiantis-scraper/milestones -f title="M0 — Bootstrap" -f description="..." -f state=open`
12. Stwórz branch `chore/1-repo-setup` **tylko wtedy gdy dodajesz cokolwiek poza samym ustawieniem repo**. Jeśli task #1 to tylko setup — pierwszy commit może być bezpośrednio na master. **Dyskusja z Claude w komentarzu Issue:** w praktyce D1 to „commit 0" — workflow branch/PR/merge wprowadzamy dopiero od D2. D1 jest setup-em infrastruktury samego workflow.

### ⚠️ Pułapki do uwagi
- **`main` vs `master`:** GitHub domyślnie tworzy `main`. Musisz w kroku 3 użyć `git init -b master`, a w kroku 7 dodać `--default-branch master` lub ręcznie zmienić po utworzeniu. Inaczej będziesz miał rozjazd z CLAUDE.md.
- **Branch protection na solo-repo:** patrz krok 8. Zostaw sobie możliwość merge jako admin (odznacz „Do not allow bypassing settings") — inaczej żaden Twój PR się nie zmerge, bo nikogo nie ma żeby approve'ował. Pamiętaj o tym i zaakceptuj ten kompromis.
- **Token `gh` CLI:** jeśli kiedykolwiek dostaniesz `HTTP 403 — Resource not accessible by personal access token` przy ustawianiu branch protection, token nie ma scope'u `repo`. `gh auth refresh -s repo`.
- **Commit messages:** już w tym tasku musisz trzymać Conventional Commits (nawet jeśli hook `conventional-pre-commit` nie jest jeszcze zainstalowany — będzie w D3). Wyrabiaj nawyk od pierwszego commita.
- **Pliki `docs/superpowers/`:** **upewnij się że są w commitcie**. Łatwo przeoczyć bo `docs/` bywa w `.gitignore` niektórych templates Django. Nie ignoruj `docs/`.

### 🧪 Testing plan (nic do testowania kodowo)
Na tym etapie nie ma kodu. **Claude zweryfikuje po PR:**
- Repo istnieje pod oczekiwanym URL
- Branch protection aktywna (`gh api /repos/.../branches/master/protection` zwraca poprawny JSON)
- Wszystkie labels i milestones istnieją
- Pierwszy commit ma oczekiwane pliki

### 🔗 Dokumentacja pomocnicza
- `gh` CLI manual: https://cli.github.com/manual/
- `gh repo create`: https://cli.github.com/manual/gh_repo_create
- `gh label create`: https://cli.github.com/manual/gh_label_create
- Branch protection API: https://docs.github.com/en/rest/branches/branch-protection
- `.gitignore` templates (Python): https://github.com/github/gitignore/blob/main/Python.gitignore
- Conventional Commits: https://www.conventionalcommits.org/en/v1.0.0/

### 📦 Definition of Done
- [ ] Acceptance criteria spełnione
- [ ] URL repo podany w komentarzu do Issue #1
- [ ] Branch protection zweryfikowana przez Claude (komenda `gh api` w komentarzu)
- [ ] Issue zamknięty

---

## Task #2 — [M0-D2] Django 6 project + Postgres lokalnie + pierwszy runserver

**Milestone:** M0 — Bootstrap
**Czas:** 3-4h
**Branch:** `feat/2-django-bootstrap`
**Type:** `feat`

### 🎯 Cel
`poetry run python manage.py runserver` działa, `http://localhost:8000/admin/` zwraca stronę logowania Django (200 OK), konfiguracja settings jest podzielona na `base/dev/prod`, a wszystkie sekrety idą przez `.env`.

### 🧠 Czego się nauczysz
- Różnica między `poetry add` a `poetry add --group dev`
- Dlaczego settings jest split (base/dev/prod): DRY + bezpieczeństwo (dev-only debug, prod-only strict)
- Jak `django-environ` czyta `.env` (nie myl z `python-dotenv` — to inne biblioteki)
- Psycopg3 vs psycopg2: psycopg3 to natywne wsparcie Django 5.1+, nie potrzeba `psycopg2-binary`
- Po co `DJANGO_SETTINGS_MODULE` i jak go ustawia się w `manage.py` + `wsgi.py` + `asgi.py`

### ✅ Acceptance criteria
- [ ] `pyproject.toml` ma zależności: `django = "^6.0"`, `psycopg = {extras = ["binary"], version = "^3.2"}`, `django-environ = "^0.12"` w grupie głównej
- [ ] `pyproject.toml` ma w grupie `dev`: `pytest = "^8"`, `pytest-django = "^4"`, `ipython = "^8"` (do `./manage.py shell`)
- [ ] Projekt Django utworzony jako `django-admin startproject config .` — katalog `config/` na tym samym poziomie co `manage.py`
- [ ] Settings rozbite na:
  - [ ] `config/settings/__init__.py` (pusty)
  - [ ] `config/settings/base.py` — wszystko wspólne
  - [ ] `config/settings/dev.py` — `from .base import *`, `DEBUG = True`, allowed hosts `["*"]`
  - [ ] `config/settings/prod.py` — `from .base import *`, `DEBUG = False`, strict allowed hosts
- [ ] `manage.py` ustawia `DJANGO_SETTINGS_MODULE=config.settings.dev` jako default
- [ ] `.env.example` istnieje z kluczami: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`
- [ ] `.env` (lokalny, **nie commitowany** — sprawdź `.gitignore`) zawiera **wygenerowany** `DJANGO_SECRET_KEY` (nie „to-be-filled"!) i poprawny `DATABASE_URL=postgres://USER:PASS@localhost:5432/tibiantis_dev`
- [ ] Baza `tibiantis_dev` utworzona lokalnie w Postgresie (użytkownik/hasło wg uznania)
- [ ] `poetry run python manage.py migrate` przechodzi bez błędów (tworzy domyślne tabele Django)
- [ ] `poetry run python manage.py createsuperuser` działa
- [ ] `poetry run python manage.py runserver` uruchamia się, `curl -I http://localhost:8000/admin/` zwraca `HTTP/1.1 200 OK`
- [ ] Commit: `feat: bootstrap django project with split settings and postgres`

### 📋 Sugerowane kroki
1. **Postgres:** zainstaluj lokalnie. **Windows:** https://www.postgresql.org/download/windows/ (instalator EDB). Ustaw użytkownika i hasło, zapisz. Albo przez `choco install postgresql`.
2. Utwórz bazę: `createdb -U postgres tibiantis_dev` (po dodaniu Postgres `bin/` do PATH) — lub przez `psql`: `CREATE DATABASE tibiantis_dev;`
3. `poetry init` — odpowiedz na pytania (name: `tibiantis-scraper`, description: `Tibiantis Monitor — backend scraper + Discord bot`, author: Twój, license: MIT lub inna, Python: `^3.13`)
4. `poetry add "django@^6.0" "psycopg[binary]@^3.2" django-environ`
5. `poetry add --group dev pytest pytest-django ipython`
6. `poetry run django-admin startproject config .` (kropka na końcu — generuje w bieżącym katalogu)
7. Przenieś `config/settings.py` → `config/settings/base.py`, stwórz `__init__.py`, `dev.py`, `prod.py`
8. Popraw `manage.py`, `config/wsgi.py`, `config/asgi.py` — zmień import na `config.settings.dev` (default) i dodaj obsługę env var
9. W `base.py` dodaj `import environ`, `env = environ.Env()`, `environ.Env.read_env(BASE_DIR / ".env")`, odczyt `SECRET_KEY`, `DATABASES = {"default": env.db()}` (django-environ parsuje `DATABASE_URL`)
10. Wygeneruj `SECRET_KEY`: `poetry run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` → wrzuć do `.env`
11. `poetry run python manage.py migrate`
12. `poetry run python manage.py createsuperuser` (zapamiętaj hasło)
13. `poetry run python manage.py runserver` → `curl -I http://localhost:8000/admin/`
14. `git add -A && git commit -m "feat: bootstrap django project with split settings and postgres"`
15. `git push -u origin feat/2-django-bootstrap` → `gh pr create --base master --fill`

### ⚠️ Pułapki do uwagi
- **Kolejność argumentów w `poetry add`:** cytaty `"django@^6.0"` są ważne w PowerShell/cmd — znak `^` to escape character. W bash są zbędne. Jeśli jesteś na Windowsie w CMD, użyj PowerShell albo Git Bash.
- **`environ.Env.read_env()` vs `django_environ`:** wygląda jak nazwa paczki, ale import to `import environ` (bez `django_`). Sprawdź paczkę: `django-environ` (myślnik) — import: `environ` (bez myślnika). Standardowa pułapka nazewnicza Pythona.
- **`DATABASES = {"default": env.db()}`:** `env.db()` woła parser URL-a z env var `DATABASE_URL`. Jeśli nie ustawisz `DATABASE_URL` lokalnie, dostaniesz `ImproperlyConfigured`. Komunikat błędu jest wyraźny, ale pierwszy raz bywa mylący.
- **Psycopg 3 connection strings:** działają tak samo jak dla psycopg 2 (`postgres://...`). Nie potrzebujesz `postgresql+psycopg://` jak w SQLAlchemy — to Django.
- **`runserver` na Windows:** jeśli dostaniesz `OSError: [WinError 10013]`, port jest zajęty. `runserver 8001` albo znajdź co trzyma 8000.
- **Absolutny import `from config.settings.dev import *`** w `prod.py` jest zły — powinno być `from .base import *`. Używamy relatywnych importów **wewnątrz** settings package (wyjątek od reguły §11 CLAUDE.md, bo settings to pakiet Django, nie aplikacja).
- **Nie commituj `.env`:** już w D1 dodaliśmy do `.gitignore`. Ale sprawdź jeszcze raz `git status` przed commitem — jeśli widzisz `.env` w trackowanych plikach, `.gitignore` ma bug (np. literówka).

### 🧪 Testing plan (Claude dopisze po PR)
- Brak testów kodu — nie ma jeszcze nic do przetestowania prócz konfiguracji, a konfigurację lepiej weryfikować integracyjnie (kolejny task)
- Claude zweryfikuje strukturę settings (czy `prod.py` importuje z `base`, czy `dev.py` ma `DEBUG=True`, czy `SECRET_KEY` jest czytany z env)
- **Mini-check:** `poetry run python -c "from config.settings.dev import DATABASES; print(DATABASES)"` powinno zwrócić poprawny słownik (bez hitu do bazy)

### 🔗 Dokumentacja pomocnicza
- Poetry basic usage: https://python-poetry.org/docs/basic-usage/
- Django startproject: https://docs.djangoproject.com/en/stable/ref/django-admin/#startproject (TODO: jeśli Django 6.0 docs pod `/en/6.0/` dostępne — użyj)
- django-environ: https://django-environ.readthedocs.io/en/latest/quickstart.html
- Psycopg3 in Django: https://docs.djangoproject.com/en/stable/releases/4.2/#psycopg-3-support (TODO: 6.0 release notes)
- Splitting settings pattern: https://docs.djangoproject.com/en/stable/topics/settings/

### 📦 Definition of Done
- [ ] Acceptance criteria spełnione
- [ ] Claude code-review na PR (na tym etapie CI jeszcze nie istnieje, więc manualny review)
- [ ] PR approved → squash merge → branch usunięty
- [ ] Issue zamknięty

---

## Task #3 — [M0-D3] pre-commit + ruff + mypy + CI lint

**Milestone:** M0 — Bootstrap
**Czas:** 3-4h
**Branch:** `chore/3-quality-tooling`
**Type:** `chore`

### 🎯 Cel
`poetry run pre-commit run --all-files` przechodzi w 100%, `ruff check .` i `ruff format .` zgodne, `mypy` (strict dla `apps/`, ale na tym etapie `apps/` pusty) czyste, i `.github/workflows/ci.yml` z jobem `lint` zwraca green na PR.

### 🧠 Czego się nauczysz
- Co robi każdy hook z `CLAUDE.md §12` i dlaczego
- Jak pinować wersje hooków (dlaczego nigdy `rev: main`)
- Konfiguracja `ruff` w `pyproject.toml` ([tool.ruff.lint] vs [tool.ruff.format])
- Mypy strict vs liberal — jak skonfigurować `[[tool.mypy.overrides]]` żeby `scrapers/` i `discord_bot/` były permisywne, a `apps/` strict
- Jak GitHub Actions cache'uje Poetry przez `actions/setup-python` z `cache: pip`
- `concurrency` group w workflow — jak jeden parametr oszczędza minuty CI

### ✅ Acceptance criteria
- [ ] `.pre-commit-config.yaml` istnieje w formacie z `CLAUDE.md §12` (pinowane wersje, 8 repos)
- [ ] **Uwaga** `default_language_version.python`: ustawiony na `python3.13` (nie 3.12 — patrz Pułapka A poniżej i „Otwarte pytania" we wstępie)
- [ ] `poetry add --group dev pre-commit ruff mypy django-stubs djangorestframework-stubs` (strawberry-graphql doda się w M2 gdy będzie potrzebny)
- [ ] `poetry run pre-commit install`
- [ ] `poetry run pre-commit install --hook-type commit-msg`
- [ ] `pyproject.toml` zawiera sekcje:
  - [ ] `[tool.ruff]` — `line-length = 100`, `target-version = "py313"`
  - [ ] `[tool.ruff.lint]` — `select = ["E", "F", "W", "I", "N", "UP", "DJ", "B", "A", "C4", "SIM"]` (I=isort, DJ=django, UP=pyupgrade, B=bugbear)
  - [ ] `[tool.ruff.lint.per-file-ignores]` — `"**/migrations/*.py" = ["E501", "N806"]` (migracje bywają długie i mają auto-generated nazwy)
  - [ ] `[tool.mypy]` — `python_version = "3.13"`, `strict = true`, `plugins = ["mypy_django_plugin.main"]`
  - [ ] `[[tool.mypy.overrides]]` — `module = "scrapers.*"` → `ignore_errors = true` (na razie); `module = "discord_bot.*"` → `ignore_errors = true`
  - [ ] `[tool.django-stubs]` — `django_settings_module = "config.settings.dev"`
  - [ ] `[tool.pytest.ini_options]` — `DJANGO_SETTINGS_MODULE = "config.settings.dev"`, `python_files = "test_*.py"`
- [ ] `.github/workflows/ci.yml` istnieje, zawiera **tylko job `lint`** (test job dodamy w D5):
  - [ ] Triggery: `pull_request` + `push` na `master`
  - [ ] `concurrency` group z `cancel-in-progress: true`
  - [ ] Python 3.13 setup
  - [ ] Poetry install (wersja pinowana, np. `1.8.4` albo `^2.2` zgodnie z `poetry.lock`)
  - [ ] `poetry install --no-interaction --no-root`
  - [ ] `poetry run pre-commit run --all-files --show-diff-on-failure`
- [ ] PR z D3 przechodzi job `lint` na green
- [ ] Branch protection na `master` zaktualizowane: required status check = `lint / Pre-commit`
- [ ] `gitleaks` hook skonfigurowany (nawet jeśli nic nie łapie — chcemy ochronę od dnia 1)
- [ ] Pierwszy trywialny test istnienia: `tests/__init__.py` (pusty), `tests/test_smoke.py` z `def test_imports_django(): import django; assert django.VERSION[0] >= 6` — **nie** uruchamiamy testów w CI w D3 (tylko lint), ale plik istnieje żeby D5 miał co rozbudować
- [ ] Commit: `chore: add pre-commit, ruff, mypy, and ci lint job`

### 📋 Sugerowane kroki
1. `poetry add --group dev pre-commit ruff mypy django-stubs djangorestframework-stubs`
2. Skopiuj `.pre-commit-config.yaml` z `CLAUDE.md §12`, **zmień `python3.12` na `python3.13`** — flaguj w PR komentarz do Claude: „CLAUDE.md §12 ma `python3.12`, zmieniłem na `3.13` dla spójności z Poetry. OK?"
3. Dodaj sekcje `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.mypy]`, `[tool.django-stubs]`, `[tool.pytest.ini_options]` do `pyproject.toml` — przykłady w Dokumentacji
4. `poetry run pre-commit install`
5. `poetry run pre-commit install --hook-type commit-msg`
6. `poetry run pre-commit run --all-files` — na początku prawdopodobnie znajdzie drobne błędy (trailing whitespace w CLAUDE.md, mixed line endings). **Napraw**, nie ignoruj. Commit `chore: fix whitespace issues found by pre-commit`
7. Utwórz `.github/workflows/ci.yml` — zawartość zgodna z `CLAUDE.md §13.1`, ale **tylko job `lint`** (usuń job `test`)
8. Utwórz `tests/__init__.py` i `tests/test_smoke.py` (nie uruchamiamy w CI, ale infrastruktura gotowa)
9. `git add -A && git commit -m "chore: add pre-commit, ruff, mypy, and ci lint job"`
10. `git push` → PR → poczekaj aż `lint / Pre-commit` job przejdzie green
11. Po merge: w Settings → Branches → edytuj rule dla `master` → Required status checks → dodaj `lint / Pre-commit`

### ⚠️ Pułapki do uwagi
- **Pułapka A: Python 3.12 vs 3.13.** `CLAUDE.md §12` ma `python3.12`. Twoje `pyproject.toml` z D2 ma `^3.13`. **Jeśli zostawisz `python3.12` w pre-commit i nie masz zainstalowanego 3.12 lokalnie — hooki pythonowe (mypy, ruff — nie, ruff to binarka, ale mypy tak) padną z `Cannot find python3.12`.** Zmień na `python3.13` i w `pyproject.toml` target-version na `py313`. Ta sprzeczność w CLAUDE.md jest błędem do zgłoszenia w PR jako „CLAUDE.md cleanup" (osobny task, nie rozszerzaj scope'u tego PR).
- **Pułapka B: `mypy` strict na pustych `apps/`.** Hook mypy ma `files: ^apps/`. Jeśli `apps/` nie istnieje lub jest pusty (bez `.py`) — mypy wypisze `Success: no issues found` i hook przejdzie. Dobrze. Ale gdy w D4 pojawi się pierwszy plik, wybuchnie na brakujących stubs. Przygotuj się w D4.
- **Pułapka C: `check-added-large-files` próg.** W CLAUDE.md 500KB. Jeśli w przyszłości dodasz fixturę HTML >500KB, hook zablokuje commit. Wtedy decyzja: podzielić fixturę albo podnieść próg (odradzam — lepiej zminimalizować fixturę przez usunięcie niepotrzebnych tagów).
- **Pułapka D: `gitleaks` false-positives.** Jeśli gitleaks wykryje regex który nie jest tokenem (np. hash w migracji), dodaj do `.gitleaksignore` z komentarzem **co** i **dlaczego**. Nie obniżaj restrictive config.
- **Pułapka E: `django-upgrade` args.** CLAUDE.md ma `--target-version 6.0`. Jeśli `django-upgrade` nie zna jeszcze 6.0 (bo pakiet stary), dostaniesz `unrecognized arguments`. `pre-commit autoupdate` albo ustaw tymczasowo `5.1`.
- **Pułapka F: `conventional-pre-commit` blokuje pierwszy commit.** Hook działa **tylko na `commit-msg` stage**, więc zadziała dopiero po `pre-commit install --hook-type commit-msg`. Pamiętaj o kroku 5.
- **Pułapka G: `poetry-lock` hook.** `args: [--no-update]` — sprawdza czy `poetry.lock` jest spójny z `pyproject.toml`. Jeśli ktoś edytuje `pyproject.toml` ręcznie bez `poetry lock` — hook zatrzymuje commit. To **feature**, nie bug.

### 🧪 Testing plan (Claude dopisze po PR)
- **Meta-test setup:** w tej fazie testów kodu nie piszemy, ale Claude zweryfikuje:
  - [ ] `poetry run pre-commit run --all-files` na każdym kroku zielone
  - [ ] Workflow `.github/workflows/ci.yml` ma poprawny YAML (przez `actionlint` lokalnie albo `gh workflow view`)
  - [ ] Status check `lint / Pre-commit` jest required na `master`

### 🔗 Dokumentacja pomocnicza
- pre-commit: https://pre-commit.com/
- ruff config: https://docs.astral.sh/ruff/configuration/
- ruff rules: https://docs.astral.sh/ruff/rules/
- mypy strict: https://mypy.readthedocs.io/en/stable/existing_code.html#introduce-stricter-options
- django-stubs: https://github.com/typeddjango/django-stubs
- GitHub Actions Python: https://github.com/actions/setup-python
- Concurrency groups: https://docs.github.com/en/actions/using-jobs/using-concurrency

### 📦 Definition of Done
- [ ] Acceptance criteria spełnione
- [ ] Job `lint / Pre-commit` zielony na PR
- [ ] Branch protection na `master` wymaga `lint / Pre-commit`
- [ ] Claude approve → squash merge → branch usunięty
- [ ] Issue zamknięty
- [ ] **🎉 M0 — Bootstrap COMPLETED.** Claude updatuje `PROGRESS.md` z sekcją M0 ✅

---

## Task #4 — [M1-D4] apps/ struktura + app "characters" zarejestrowana

**Milestone:** M1 — First character scrape
**Czas:** 2-3h
**Branch:** `feat/4-apps-structure`
**Type:** `feat`

### 🎯 Cel
Katalog `apps/` istnieje i jest na `sys.path` Django, `apps/characters/` to poprawnie zarejestrowana Django app w `INSTALLED_APPS`, i `./manage.py check` nie zgłasza błędów.

### 🧠 Czego się nauczysz
- Dlaczego `apps/` nie jest domyślnie top-level (Django nie rozpoznaje zagnieżdżonych apps „z automatu")
- Jak działa `AppConfig.name` vs label — dlaczego `name = "apps.characters"` a nie `"characters"`
- Co robi `default_auto_field = "django.db.models.BigAutoField"` w AppConfig (Django 6 default, ale explicit wins implicit)
- Po co `__init__.py` w `apps/` (namespace package vs regular package)

### ✅ Acceptance criteria
- [ ] Katalog `apps/` istnieje w repo root, zawiera `__init__.py` (pusty plik)
- [ ] `poetry run python manage.py startapp characters apps/characters` wykonane (albo ręcznie stworzona struktura)
- [ ] `apps/characters/apps.py` zawiera:
  ```python
  from django.apps import AppConfig

  class CharactersConfig(AppConfig):
      default_auto_field = "django.db.models.BigAutoField"
      name = "apps.characters"
      label = "characters"
  ```
- [ ] `apps/characters/__init__.py` pusty (nie ustawiamy `default_app_config` — to Django 3.2+ deprecated)
- [ ] `config/settings/base.py` → `INSTALLED_APPS` zawiera `"apps.characters"` (nie `"characters"`!) w sekcji `LOCAL_APPS`. Podziel `INSTALLED_APPS` na sekcje: `DJANGO_APPS`, `THIRD_PARTY_APPS`, `LOCAL_APPS`, i w finalnej liście `INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS`
- [ ] `apps/characters/models.py` zawiera pusty placeholder:
  ```python
  from django.db import models
  # Character model — będzie dodany w Task #5
  ```
- [ ] `apps/characters/migrations/__init__.py` istnieje
- [ ] `poetry run python manage.py check` — zero błędów
- [ ] `poetry run python manage.py migrate` przechodzi (nic nowego do migracji — tylko sanity check)
- [ ] Commit: `feat: add apps/ directory structure with characters app`

### 📋 Sugerowane kroki
1. Utwórz `apps/` + `apps/__init__.py`
2. `poetry run python manage.py startapp characters apps/characters`
3. Otwórz `apps/characters/apps.py`, zmień `name = "characters"` na `name = "apps.characters"`, dodaj `label = "characters"`, dodaj `default_auto_field`
4. Zmodyfikuj `config/settings/base.py`:
   - Rozbij `INSTALLED_APPS` na sekcje `DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS`
   - Dodaj `"apps.characters"` do `LOCAL_APPS`
5. Sprawdź `apps/characters/models.py` — usuń auto-generowane komentarze, zostaw tylko import i placeholder comment
6. `poetry run python manage.py check`
7. `poetry run pre-commit run --all-files` — weryfikacja lint
8. Commit, push, PR

### ⚠️ Pułapki do uwagi
- **Pułapka A: `AppConfig.name` vs `label`.** `name` to **python import path** — musi być `apps.characters` bo tam fizycznie żyje kod. `label` to **unikalny identyfikator Django** w runtime (używany w `migrations`, `AppConfig.get_model()`). Jeśli `label` się pokrywa z innymi appami — błąd `ImproperlyConfigured`. Tu ustawiamy `label = "characters"` żeby migracje miały sensowny prefiks (`characters_0001_initial`, nie `apps_characters_0001_initial`).
- **Pułapka B: uruchomienie `startapp` bez folderu docelowego.** Jeśli zrobisz `manage.py startapp characters` bez drugiego argumentu, Django stworzy `characters/` w repo root, nie w `apps/`. Musisz drugim argumentem wskazać **istniejący** folder (dlatego krok 1 przed 2).
- **Pułapka C: `default_auto_field` w Django 6.** W Django 6 `BigAutoField` jest domyślny, ale lepiej wpisać explicite — jeśli kiedyś dowalą zmianę default, projekt nie explodes. Konwencja.
- **Pułapka D: `INSTALLED_APPS` kolejność.** Django apps (`django.contrib.*`) zawsze **przed** third-party i local. Inaczej dostaniesz nieoczywiste błędy przy `migrate`.

### 🧪 Testing plan (Claude dopisze po PR)
- Nic do testowania kodowo — na tym etapie sam `manage.py check` jest testem. Claude zweryfikuje strukturę pliku i poprawność konfiguracji.

### 🔗 Dokumentacja pomocnicza
- Django AppConfig: https://docs.djangoproject.com/en/stable/ref/applications/
- `startapp` command: https://docs.djangoproject.com/en/stable/ref/django-admin/#startapp
- Package vs namespace package: https://docs.python.org/3/tutorial/modules.html#packages

### 📦 Definition of Done
- [ ] Acceptance criteria spełnione
- [ ] Lint job zielony
- [ ] Claude approve → squash merge → branch usunięty

---

## Task #5 — [M1-D5] Model Character + migracja + admin + test job w CI + pierwszy test

**Milestone:** M1 — First character scrape
**Czas:** 4h
**Branch:** `feat/5-character-model`
**Type:** `feat`

### 🎯 Cel
Model `Character` z wszystkimi polami z `CLAUDE.md §5` jest w bazie, zarejestrowany w Django admin, pokrywa go pierwszy unit test, a CI uruchamia test job z Postgres jako service.

### 🧠 Czego się nauczysz
- Różnica między `CharField(blank=True)` a `CharField(null=True)` — dla stringów **nie używamy** `null=True`
- Kiedy `db_index=True` jest warte kosztu zapisu (tu: `last_login` — będziemy filtrować po dacie)
- Jak `Meta.ordering` wpływa na domyślne query (i dlaczego ordering po polu bez indeksu to przepis na wolny dashboard)
- `auto_now` vs `auto_now_add` — pierwsze update'uje przy każdym save, drugie tylko przy insert
- Jak GitHub Actions service container (Postgres) działa i dlaczego host jest `localhost`, nie nazwa serwisu

### ✅ Acceptance criteria
- [ ] `apps/characters/models.py` zawiera model `Character` ze **wszystkimi** polami z `CLAUDE.md §5`:
  - [ ] `name` — CharField(max_length=64, unique=True)
  - [ ] `sex` — CharField(max_length=16, blank=True, default="")
  - [ ] `vocation` — CharField(max_length=32, blank=True, default="")
  - [ ] `level` — PositiveIntegerField(null=True, blank=True)
  - [ ] `world` — CharField(max_length=32, blank=True, default="")
  - [ ] `residence` — CharField(max_length=64, blank=True, default="")
  - [ ] `house` — CharField(max_length=128, blank=True, default="")
  - [ ] `guild_membership` — CharField(max_length=128, blank=True, default="")
  - [ ] `last_login` — DateTimeField(null=True, blank=True, db_index=True)
  - [ ] `account_status` — CharField(max_length=32, blank=True, default="")
  - [ ] `last_scraped_at` — DateTimeField(auto_now=True)
- [ ] Model ma `Meta.ordering = ["-level"]` i `Meta.indexes = [models.Index(fields=["name"])]` (nawet mimo `unique=True` — explicit dla czytelności)
- [ ] `__str__` zwraca `f"{self.name} (level {self.level})"`
- [ ] Migracja utworzona przez `makemigrations` i commitowana: `apps/characters/migrations/0001_initial.py`
- [ ] `apps/characters/admin.py` rejestruje model:
  - [ ] `list_display = ("name", "level", "vocation", "world", "last_login")`
  - [ ] `list_filter = ("vocation", "world")`
  - [ ] `search_fields = ("name",)`
  - [ ] `readonly_fields = ("last_scraped_at",)`
- [ ] Pierwszy test `tests/unit/characters/test_character_model.py`:
  - [ ] `test_create_character_with_minimum_fields` — zapisz `Character(name="Yhral")`, sprawdź że `pk` istnieje po save
  - [ ] `test_name_uniqueness_enforced` — dwa `Character(name="Same")` → drugi rzuca `IntegrityError`
  - [ ] `test_last_scraped_at_updates_on_save` — zapisz, zapisz ponownie, sprawdź że `last_scraped_at` się zmienił
- [ ] `.github/workflows/ci.yml` rozszerzony o job `test`:
  - [ ] Postgres service (image `postgres:16`, healthcheck)
  - [ ] env vars: `DATABASE_URL=postgres://postgres:postgres@localhost:5432/tibiantis_test`, `DJANGO_SECRET_KEY=test-only-not-a-real-secret`, `DJANGO_SETTINGS_MODULE=config.settings.dev`
  - [ ] `poetry run python manage.py migrate --noinput`
  - [ ] `poetry run pytest`
  - [ ] `--cov=apps --cov-report=xml --cov-fail-under=0` (threshold 0 do M1 zamknięcia, **flaga dla Claude do dyskusji w PR: podnosimy do 70 na start M2?**)
- [ ] Test job zielony na PR
- [ ] Branch protection: required status check = `lint / Pre-commit` + `test / Pytest`
- [ ] Commit: `feat(characters): add Character model with admin and first tests`

### 📋 Sugerowane kroki
1. Napisz model w `apps/characters/models.py` (patrz acceptance criteria)
2. `poetry run python manage.py makemigrations characters` — **przeczytaj wygenerowaną migrację** zanim przejdziesz dalej. Jeśli coś dziwnego (np. `AddField` zamiast `CreateModel`) — wywal `migrations/0001_*.py` i spróbuj ponownie
3. `poetry run python manage.py migrate`
4. Napisz `apps/characters/admin.py`, zarejestruj model przez `@admin.register(Character)`
5. Uruchom `runserver`, zaloguj się do `/admin/`, ręcznie utwórz `Character(name="Test", level=100)` → sprawdź czy widać
6. **Zainstaluj `pytest-cov`:** `poetry add --group dev pytest-cov`
7. Utwórz strukturę `tests/unit/__init__.py`, `tests/unit/characters/__init__.py`, `tests/unit/characters/test_character_model.py`
8. Napisz 3 testy (AC mówi które). **Decorator:** `@pytest.mark.django_db` (pytest-django wymaga explicit opt-in do DB)
9. `poetry run pytest` lokalnie — wszystko green
10. Rozszerz `.github/workflows/ci.yml` o job `test` (patrz `CLAUDE.md §13.1`, ale **bez `fail_ci_if_error` w codecov step — pomijamy codecov do M9**)
11. Push, PR. Śledź CI — oba joby muszą być green.
12. Po merge: Settings → Branches → dodaj required status check `test / Pytest`

### ⚠️ Pułapki do uwagi
- **Pułapka A: `CharField` i `null=True`.** Django convention: stringi nigdy `null=True`, tylko `blank=True, default=""`. Powód: w bazie dwa reprezentacje „brak" (`NULL` i `""`) to ból przy query. Jeśli widzisz `CharField(null=True)` — to code smell.
- **Pułapka B: `pytest-django` i baza.** Pierwszy raz jak uruchomisz `pytest`, zobaczysz `django.db.utils.OperationalError`. Powód: pytest próbuje utworzyć test DB, a Twój user Postgres nie ma uprawnień `CREATEDB`. Rozwiązanie: `ALTER ROLE tibiantis_user CREATEDB;` albo uruchom `pytest` jako user z uprawnieniami.
- **Pułapka C: `@pytest.mark.django_db`.** Zapomnisz → test dostanie `DatabaseAccessDenied`. Każdy test który tyka bazy musi mieć ten marker (albo `django_db` fixture).
- **Pułapka D: `last_scraped_at` z `auto_now=True` w testach.** Jeśli zrobisz `c.save()` dwa razy w jednej milisekundzie, timestamp może się **nie** zmienić (zależy od rozdzielczości `datetime.now`). W teście użyj `time.sleep(0.01)` albo mock `django.utils.timezone.now`.
- **Pułapka E: Postgres service w CI nie dostępny od razu.** Healthcheck trwa. Nie pomijaj `--health-*` flag z `CLAUDE.md §13.1`. Jeśli pomijasz, dostaniesz `connection refused` na migrate.
- **Pułapka F: coverage threshold.** Zaczynamy od 0 bo kodu mało. Ale **po M1 zamknięciu** podnosimy do 70. Nie zapomnij zrobić osobnego PR-a podnoszącego threshold jako część D8 retro.

### 🧪 Testing plan (Claude dopisze po PR — rozszerzenie Twoich 3 testów)
Claude dopisze:
- [ ] `test_character_default_ordering_by_level_desc` — zapisz 3, query, sprawdź kolejność
- [ ] `test_character_str_representation` — `str(c) == "Yhral (level 100)"`
- [ ] `test_last_login_nullable` — `Character(name="X", last_login=None).full_clean()` nie rzuca
- [ ] Integration test: `test_admin_list_page_renders` — Django test client hit `/admin/characters/character/` jako superuser, sprawdź 200

### 🔗 Dokumentacja pomocnicza
- Django Model fields: https://docs.djangoproject.com/en/stable/ref/models/fields/
- Django Meta options: https://docs.djangoproject.com/en/stable/ref/models/options/
- Django admin: https://docs.djangoproject.com/en/stable/ref/contrib/admin/
- pytest-django: https://pytest-django.readthedocs.io/en/latest/
- pytest-django db access: https://pytest-django.readthedocs.io/en/latest/database.html
- GitHub Actions services: https://docs.github.com/en/actions/using-containerized-services/about-service-containers

### 📦 Definition of Done
- [ ] Acceptance criteria spełnione
- [ ] Lint + test joby zielone
- [ ] Coverage raport dostępny w artefaktach CI (nawet jeśli threshold=0)
- [ ] Claude approve → squash merge

---

## Task #6 — [M1-D6] Service layer: upsert_character()

**Milestone:** M1 — First character scrape
**Czas:** 3h
**Branch:** `feat/6-character-service`
**Type:** `feat`

### 🎯 Cel
`apps/characters/services.py` zawiera funkcję `upsert_character(payload: dict) -> Character` — idempotentną, ze ścisłymi type hints, dostępną do wywołania z dowolnego miejsca (w tym z pipeline Scrapy w D8).

### 🧠 Czego się nauczysz
- Dlaczego logika biznesowa w `services.py`, nie w `models.py` czy views (reguła z `CLAUDE.md §15.2`)
- Różnica między `Model.objects.update_or_create()` a ręcznym `get_or_create()` + save — kiedy która
- Jak typować Django ORM przez `django-stubs` (zwłaszcza `QuerySet` i `Manager`)
- Dlaczego service przyjmuje `dict` (nie `Character`) — boundary oddzielający "skąd przyszły dane" (scraper/HTTP/CLI) od "jak zapisujemy"
- Jak pisać czyste docstringi (nie za długie, „co" zamiast „jak")

### ✅ Acceptance criteria
- [ ] `apps/characters/services.py` istnieje, zawiera:
  - [ ] Funkcję `upsert_character(payload: CharacterPayload) -> Character` gdzie `CharacterPayload` to `TypedDict` zadeklarowany w tym samym module (albo w `apps/characters/types.py` — decyzja developera)
  - [ ] Pełne type hints dla wszystkich pól payloadu (name: str, sex: str, level: int | None, itd.)
  - [ ] Walidacja: `name` jest wymagany i nie-pusty (raise `ValueError` gdy brak)
  - [ ] Logika: jeśli `Character` o tym `name` istnieje → update pól które są w payload (nie dotykaj pól nie-wymienionych); jeśli nie istnieje → create. **Używamy `Model.objects.update_or_create()`.**
  - [ ] Funkcja jest idempotentna: wywołana 2x z tym samym payload — tylko jeden `Character` w bazie
  - [ ] Funkcja zwraca zapisany obiekt (`Character`)
  - [ ] Docstring: 3 linijki max, co robi + co zwraca + exceptions
- [ ] `apps/characters/types.py` (opcjonalne — jeśli decyzja to wynieść TypedDict) z `CharacterPayload`
- [ ] Testy w `tests/unit/characters/test_character_service.py`:
  - [ ] `test_upsert_creates_new_character_when_not_exists`
  - [ ] `test_upsert_updates_existing_character_in_place` — tworzysz Character, wołasz upsert z nowym level, sprawdzasz że ten sam pk i nowy level
  - [ ] `test_upsert_without_name_raises_valueerror`
  - [ ] `test_upsert_preserves_unspecified_fields` — update tylko level, sprawdź że `vocation` zostaje z pierwszego wywołania
- [ ] `mypy apps/characters` przechodzi bez błędów (strict)
- [ ] Commit: `feat(characters): add upsert_character service`

### 📋 Sugerowane kroki
1. Zdecyduj gdzie `CharacterPayload` — `services.py` czy `types.py`. W tym tasku lean — w `services.py`. Jeśli kiedyś payload urośnie i będzie używany w wielu miejscach, wtedy wyciągamy.
2. Napisz `TypedDict`:
   ```python
   class CharacterPayload(TypedDict, total=False):
       name: str  # Required w logic, ale TypedDict total=False dla elastyczności
       sex: str
       vocation: str
       level: int | None
       world: str
       residence: str
       house: str
       guild_membership: str
       last_login: datetime | None
       account_status: str
   ```
3. Napisz funkcję `upsert_character(payload)`. Szkic:
   - Wyciągnij `name = payload.get("name")`, walidacja
   - `defaults = {k: v for k, v in payload.items() if k != "name"}`
   - `character, created = Character.objects.update_or_create(name=name, defaults=defaults)`
   - Return `character`
4. Napisz testy. Pamiętaj o `@pytest.mark.django_db`.
5. `poetry run pytest tests/unit/characters/test_character_service.py -v`
6. `poetry run mypy apps/characters` — musi przejść strict
7. Commit, push, PR

### ⚠️ Pułapki do uwagi
- **Pułapka A: `update_or_create` vs `get_or_create` + `save`.** `update_or_create` jest atomic w jednej transakcji — to co chcemy. `get_or_create` + save to 2 zapytania i race condition okno. Nie mieszaj.
- **Pułapka B: `TypedDict(total=False)`.** Sprawia że **wszystkie** pola są opcjonalne. Ale `name` jest wymagany logicznie. Walidacja runtime zamiast type system — OK, ale kompilator Ci o tym nie powie. Rozważ `Required[...]` z `typing_extensions` w przyszłości.
- **Pułapka C: `datetime` parse z Scrapy.** W D7/D8 payload z scrapera będzie miał `last_login` jako string. Service nie konwertuje — scraper/pipeline konwertuje. Boundary clear.
- **Pułapka D: Silent field drop.** Jeśli payload zawiera `race_condition_field` której nie ma w modelu, `update_or_create` rzuci `TypeError: 'race_condition_field' is an invalid keyword argument`. **Nie filtruj silnie** — niech błąd wyleci, żeby scrapery nie ukrywały bugów.
- **Pułapka E: `Model.objects` w stubs.** django-stubs typuje `objects` jako `Manager[Model]`. Jeśli `mypy` krzyczy — sprawdź `django_settings_module` w `[tool.django-stubs]` (ustawione w D3).

### 🧪 Testing plan (Claude dopisze po PR — oprócz Twoich 4 testów)
Claude dopisze:
- [ ] `test_upsert_with_empty_payload_uses_name_only` — defaults wszystkie puste
- [ ] `test_upsert_is_idempotent` — 3x to samo → 1 obiekt, ostatni save zwycięża
- [ ] Parametryzowany test: `test_upsert_accepts_all_field_combinations` — produkt różnych pól

### 🔗 Dokumentacja pomocnicza
- Django update_or_create: https://docs.djangoproject.com/en/stable/ref/models/querysets/#update-or-create
- Python TypedDict: https://docs.python.org/3/library/typing.html#typing.TypedDict
- django-stubs: https://github.com/typeddjango/django-stubs

### 📦 Definition of Done
- [ ] Acceptance criteria spełnione
- [ ] Lint + test + mypy zielone
- [ ] Claude approve → squash merge

---

## Task #7 — [M1-D7] Scrapy: minimalny spider character_spider

**Milestone:** M1 — First character scrape
**Czas:** 4h
**Branch:** `feat/7-character-spider`
**Type:** `feat`

### 🎯 Cel
Struktura `scrapers/` istnieje, `character_spider.py` potrafi sparsować zapisaną fixturę HTML z `tibiantis.online/?page=character&name=Yhral` na `CharacterItem` z wszystkimi polami. Spider **nie** pisze do bazy (to robi pipeline w D8).

### 🧠 Czego się nauczysz
- Różnica między `scrapy.Spider` a `CrawlSpider` — tu wystarczy `Spider`
- Jak parsować HTML przez CSS selectors i XPath (Scrapy wspiera obydwa)
- Dlaczego `Item` klasa zamiast `dict` — walidacja, autocomplete, consistent boundary
- Jak testować spider **offline** przez `scrapy.http.HtmlResponse` z zapisaną fixturą
- Co to jest `response.follow()` i dlaczego tutaj nie potrzebujemy (1 strona per call)

### ✅ Acceptance criteria
- [ ] `poetry add scrapy` — w głównej grupie (nie dev — będzie runtime dependency)
- [ ] Struktura:
  ```
  scrapers/
  ├── __init__.py
  ├── scrapy.cfg
  └── tibiantis_scrapers/
      ├── __init__.py
      ├── settings.py
      ├── items.py
      ├── pipelines.py           # pusty na ten task, treść w D8
      └── spiders/
          ├── __init__.py
          └── character_spider.py
  ```
- [ ] `scrapy.cfg` wskazuje `settings = tibiantis_scrapers.settings`
- [ ] `scrapers/tibiantis_scrapers/settings.py` zawiera:
  - [ ] `BOT_NAME = "tibiantis_scrapers"`
  - [ ] `USER_AGENT = "TibiantisMonitor/1.0 (contact: <twój email>)"` — realny, z kontaktem (zgodnie z `CLAUDE.md §6`)
  - [ ] `ROBOTSTXT_OBEY = True`
  - [ ] `DOWNLOAD_DELAY = 2.5`
  - [ ] `CONCURRENT_REQUESTS_PER_DOMAIN = 1`
  - [ ] `ITEM_PIPELINES = {}` (puste do D8)
- [ ] `items.py` zawiera `CharacterItem` z polami lustrzanymi do modelu (name, sex, vocation, level, world, residence, house, guild_membership, last_login, account_status)
- [ ] `character_spider.py`:
  - [ ] Klasa `CharacterSpider(scrapy.Spider)`, `name = "character"`
  - [ ] Przyjmuje arg `name` z linii komend: `scrapy crawl character -a name=Yhral`
  - [ ] `start_requests()` builds URL z `name`
  - [ ] `parse(response)` wyciąga wszystkie pola z CharacterItem, yielduje Item
  - [ ] Obsługa „character not found" — jeśli strona nie ma oczekiwanej sekcji, log warning + yield nothing
- [ ] `tests/fixtures/character_yhral.html` — **realny snapshot** pobrany ręcznie przez `curl` z `tibiantis.online/?page=character&name=Yhral` (zapisany lokalnie, commitowany; ostrożnie z `check-added-large-files` — HTML powinien być <500KB)
- [ ] Testy `tests/unit/scrapers/test_character_spider.py`:
  - [ ] Fixture `html_response` — tworzy `HtmlResponse` z zapisanej fixtury
  - [ ] `test_parse_yields_character_item`
  - [ ] `test_parsed_name_matches_yhral`
  - [ ] `test_parsed_level_is_integer` (parsowanie z string → int)
  - [ ] `test_parsed_last_login_is_datetime` (parsowanie daty w strefie czasowej Tibiantis)
  - [ ] `test_parse_missing_section_yields_nothing` — fixtura z „character not found"
- [ ] `scrapy crawl character -a name=Yhral` wykonane ręcznie (jednokrotnie, dla weryfikacji) — potwierdź że się udaje i **loguje output**. To nie musi być w CI (zero live scraping w CI — `CLAUDE.md §15.6`).
- [ ] Commit: `feat(scrapers): add character spider with offline tests`

### 📋 Sugerowane kroki
1. `poetry add scrapy`
2. Utwórz strukturę katalogów ręcznie (albo `cd scrapers && scrapy startproject tibiantis_scrapers .` i posprzątaj)
3. Pobierz fixturę: `curl "https://tibiantis.online/?page=character&name=Yhral" -o tests/fixtures/character_yhral.html`
4. **Ręcznie** otwórz fixturę w przeglądarce + narzędzia dev (F12), zidentyfikuj CSS selectors dla każdego pola. **Strona może używać tabel HTML z lat 90.** — XPath może być lepszy niż CSS.
5. Napisz `CharacterItem` (items.py)
6. Napisz `CharacterSpider.parse()` — iteracyjnie, testuj przez `scrapy shell` (`poetry run scrapy shell file:///path/to/fixture.html`)
7. Napisz testy offline używając `HtmlResponse`:
   ```python
   from scrapy.http import HtmlResponse

   def test_parse_yields_character_item():
       with open("tests/fixtures/character_yhral.html") as f:
           body = f.read()
       response = HtmlResponse(url="http://test", body=body, encoding="utf-8")
       spider = CharacterSpider(name="Yhral")
       items = list(spider.parse(response))
       assert len(items) == 1
   ```
8. `poetry run pytest tests/unit/scrapers -v`
9. Ręczny test live: `poetry run scrapy crawl character -a name=Yhral -s LOG_LEVEL=INFO` (z katalogu `scrapers/`)
10. Commit, push, PR

### ⚠️ Pułapki do uwagi
- **Pułapka A: `scrapy.cfg` ścieżka.** Musi wskazywać na **moduł Pythona** (`tibiantis_scrapers.settings`), nie ścieżkę pliku. Pomyłka = `ImportError` przy crawl.
- **Pułapka B: `PYTHONPATH` w Scrapy.** Jeśli `scrapy crawl` wywołujesz z root'a repo, `scrapers/` musi być na ścieżce. Najprościej: zawsze `cd scrapers && scrapy crawl ...`. Alternatywnie edytuj `scrapy.cfg` i ustaw `[settings] default = tibiantis_scrapers.settings` + wskaż inne ścieżki.
- **Pułapka C: HTML z lat 90.** Tibiantis to klon Tibii retro — strony mogą nie mieć klas CSS, tylko tabele. Nie polegaj na `response.css(".char-name")` — użyj XPath typu `response.xpath('//td[contains(text(), "Name:")]/following-sibling::td/text()').get()`.
- **Pułapka D: Encoding.** Jeśli tibiantis.online zwraca Windows-1252 a Ty zakładasz UTF-8, znaki akcentowane (polskie guildy!) się połamią. `HtmlResponse(encoding=response.encoding)` w testach, w real scraping Scrapy auto-detectuje.
- **Pułapka E: `check-added-large-files` i fixtura.** Jeśli fixtura >500KB (raczej nie dla Tibii, ale sprawdź), hook zablokuje. Zminimalizuj usuwając `<script>`, `<style>`, niepotrzebne `<td>` — ale uważaj żeby nie usuwać tego co parsujesz.
- **Pułapka F: `ROBOTSTXT_OBEY = True`.** Jeśli tibiantis.online zabrania w robots.txt strony character — Scrapy **odmówi** crawla. Sprawdź `https://tibiantis.online/robots.txt` w razie błędu. Jeśli tak — skontaktuj się z adminami strony, nie obchodzimy ograniczenia.
- **Pułapka G: `DOWNLOAD_DELAY = 2.5`.** Minimum 2s to dobry ton. Nie obniżaj. Gdy będziemy scrapować listę 100 postaci, trwa to 4+ minut — to ma być wolne.

### 🧪 Testing plan (Claude dopisze po PR — oprócz Twoich 5 testów)
Claude dopisze:
- [ ] Fixture z postacią z wysokim leveli + gildią (edge case duże liczby)
- [ ] Fixture z postacią offline przez >30 dni (edge case `last_login`)
- [ ] `test_spider_respects_user_agent_setting`
- [ ] Integration smoke test: czy `CharacterItem.fields` pokrywa się z `Character._meta.fields` (parity check)

### 🔗 Dokumentacja pomocnicza
- Scrapy Spider: https://docs.scrapy.org/en/latest/topics/spiders.html
- Scrapy Items: https://docs.scrapy.org/en/latest/topics/items.html
- Scrapy Selectors: https://docs.scrapy.org/en/latest/topics/selectors.html
- HtmlResponse for testing: https://docs.scrapy.org/en/latest/topics/request-response.html#scrapy.http.HtmlResponse
- scrapy shell debugging: https://docs.scrapy.org/en/latest/topics/shell.html

### 📦 Definition of Done
- [ ] Acceptance criteria spełnione
- [ ] Lint + test zielone (test job skipuje live scraping — weryfikujemy offline)
- [ ] Fixture HTML commitowana i <500KB
- [ ] Claude approve → squash merge

---

## Task #8 — [M1-D8] Pipeline Scrapy → service + management command

**Milestone:** M1 — First character scrape
**Czas:** 3-4h
**Branch:** `feat/8-scrape-pipeline`
**Type:** `feat`

### 🎯 Cel
`poetry run python manage.py scrape_character Yhral` uruchamia spider programowo, pipeline woła `upsert_character()`, i postać jest widoczna w Django admin pod `/admin/characters/character/Yhral/`. **M1 done.**

### 🧠 Czego się nauczysz
- Dlaczego pipeline Scrapy nie woła `Model.objects.create()` bezpośrednio (separation of concerns — scraper nie wie co to ORM)
- Jak uruchomić Scrapy z poziomu Django (CrawlerRunner + Twisted reactor)
- Dlaczego `CrawlerProcess` nie zadziała drugiej gdy wywołamy go 2x w tym samym procesie Pythona — Twisted reactor jest non-restartable
- Jak konwertować ScrapyItem → dict (payload dla service)
- Jak pisać Django management command (`BaseCommand.add_arguments` + `handle`)

### ✅ Acceptance criteria
- [ ] `scrapers/tibiantis_scrapers/pipelines.py` zawiera `DjangoPipeline`:
  - [ ] `process_item(item, spider)` konwertuje `CharacterItem` na `CharacterPayload` (dict)
  - [ ] Woła `from apps.characters.services import upsert_character; upsert_character(payload)`
  - [ ] Zwraca `item` (Scrapy convention)
  - [ ] Error handling: jeśli `upsert_character` rzuci → log błąd, **nie** połknij. Spider kontynuuje, pipeline nie.
- [ ] Pipeline zarejestrowany w `settings.py`:
  ```python
  ITEM_PIPELINES = {
      "tibiantis_scrapers.pipelines.DjangoPipeline": 300,
  }
  ```
- [ ] Django **nie** jest importowane w `settings.py` Scrapy — jest importowane **tylko** w `pipelines.py`, i tam przez `django.setup()` gdy potrzebne (albo przez management command który setup już zrobił)
- [ ] `apps/characters/management/commands/scrape_character.py`:
  - [ ] `BaseCommand` z argumentem `name` (positional, required)
  - [ ] `handle()` uruchamia `CrawlerRunner` (nie `CrawlerProcess`)
  - [ ] Konfiguracja Scrapy czytana przez `get_project_settings()` — trzeba dodać `SCRAPY_SETTINGS_MODULE=tibiantis_scrapers.settings` do env
  - [ ] Używa `crochet` (lub `reactor.run()`) do blokującego czekania na zakończenie crawl'a
- [ ] `poetry add crochet` (albo bez crochet — decyzja developera, ale crochet prosty)
- [ ] `pyproject.toml` ma `[tool.pytest.ini_options] pythonpath = ["scrapers"]` (żeby pytest widział spidery)
- [ ] Test integracyjny `tests/integration/test_scrape_pipeline.py`:
  - [ ] `test_pipeline_calls_upsert_character` — mockuj `upsert_character`, przekaż `CharacterItem`, sprawdź że funkcja wywołana z oczekiwanym payload
  - [ ] `test_pipeline_does_not_swallow_service_errors` — `upsert_character` rzuca → pipeline loguje i nie połyka
- [ ] **End-to-end manual test:**
  - [ ] `poetry run python manage.py scrape_character Yhral` → exit code 0
  - [ ] `poetry run python manage.py shell -c "from apps.characters.models import Character; print(Character.objects.get(name='Yhral').__dict__)"` → pokazuje zapisaną postać
  - [ ] `runserver` → `/admin/characters/character/` → widać Yhrala na liście
- [ ] **PROGRESS.md updatowany przez Claude** po merge — sekcja M1 ✅
- [ ] Commit: `feat(scrapers): wire pipeline to character service via management command`

### 📋 Sugerowane kroki
1. `poetry add crochet` (i `twisted` auto-install przez Scrapy)
2. Napisz `DjangoPipeline` w `pipelines.py`:
   - Import lokalny w metodzie (`def process_item`): `from apps.characters.services import upsert_character`
   - Konwertuj `CharacterItem` → dict (np. `dict(item)`)
   - Wywołaj service, obsłuż wyjątek
3. Zarejestruj pipeline w `settings.py`
4. Utwórz `apps/characters/management/__init__.py`, `apps/characters/management/commands/__init__.py`, `apps/characters/management/commands/scrape_character.py`
5. Napisz command:
   ```python
   from django.core.management.base import BaseCommand
   from scrapy.crawler import CrawlerRunner
   from scrapy.utils.project import get_project_settings
   from crochet import setup, wait_for

   setup()

   class Command(BaseCommand):
       def add_arguments(self, parser):
           parser.add_argument("name", type=str)

       @wait_for(timeout=60.0)
       def _run_crawl(self, name):
           settings = get_project_settings()
           runner = CrawlerRunner(settings)
           from tibiantis_scrapers.spiders.character_spider import CharacterSpider
           return runner.crawl(CharacterSpider, name=name)

       def handle(self, *args, **options):
           self._run_crawl(options["name"])
           self.stdout.write(self.style.SUCCESS(f"Scraped {options['name']}"))
   ```
6. Ustaw `SCRAPY_SETTINGS_MODULE` — najlepiej w `config/settings/base.py` jako `os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "tibiantis_scrapers.settings")`
7. Dodaj `scrapers/` do `sys.path` w `manage.py` (lub do `pythonpath` w pytest — AC wymaga obojga)
8. Test manualny: `poetry run python manage.py scrape_character Yhral`
9. Napisz testy integracyjne pipeline'u (mock service)
10. `poetry run pytest` — wszystko green
11. `poetry run pre-commit run --all-files` — wszystko green
12. Commit, push, PR

### ⚠️ Pułapki do uwagi
- **Pułapka A: `CrawlerProcess` vs `CrawlerRunner`.** Nie używaj `CrawlerProcess` w management command. Pierwszy raz zadziała. Drugi raz dostaniesz `ReactorNotRestartable`. Użyj `CrawlerRunner` + `crochet` (`CLAUDE.md §6`).
- **Pułapka B: Twisted reactor + Django ORM.** Twisted lubi swoje threadpools, Django ORM lubi własne connections. Jeśli `upsert_character()` odpala `save()` wewnątrz Twisted thread, **poza** głównym Django context — dostaniesz `SynchronousOnlyOperation` albo `AppRegistryNotReady`. Rozwiązanie: command musi zrobić `django.setup()` **przed** `CrawlerRunner`. Management commands robią to same z siebie (bo startują przez Django manage).
- **Pułapka C: Import w pipelines.py.** Jeśli zaimportujesz `from apps.characters.services` **na poziomie modułu** (top-level), Scrapy może próbować załadować pipeline zanim Django jest ready. Import **wewnątrz metody** `process_item` działa zawsze.
- **Pułapka D: `SCRAPY_SETTINGS_MODULE` env.** Jeśli command nie znajdzie settings Scrapy, dostaniesz nieoczywisty komunikat. Ustaw env w settings Django + sanity check w command.
- **Pułapka E: `dict(item)` vs `item.to_dict()`.** Item to `ItemAdapter`-friendly, `dict(item)` działa w Scrapy 2.10+. Jeśli masz starszą, użyj `ItemAdapter(item).asdict()`.
- **Pułapka F: Live scraping w CI.** Test integracyjny **mockuje service**. Nie odpala spidera na żywo. Jeśli ulegniesz pokusie „zrobię e2e test który scrapuje naprawdę" — NIE. `CLAUDE.md §15.6`.
- **Pułapka G: Timeout `crochet.wait_for`.** 60s default może nie starczyć przy wolnym DOWNLOAD_DELAY i retry. Jeśli widzisz `TimeoutError`, zwiększ na 120s lub 180s.

### 🧪 Testing plan (Claude dopisze po PR — oprócz Twoich 2 testów)
Claude dopisze:
- [ ] `test_management_command_with_invalid_character_name_exits_nonzero`
- [ ] `test_pipeline_skips_item_with_empty_name` (graceful degradation)
- [ ] Integration: `test_command_creates_character_in_db` — z zamockowanym Scrapy (nie hitujemy sieci), sprawdzamy że chain command→spider→pipeline→service→db działa
- [ ] Sprawdzenie czy coverage dla `apps/characters/` > 60% (mimo że globalny threshold 0)

### 🔗 Dokumentacja pomocnicza
- Django Management Commands: https://docs.djangoproject.com/en/stable/howto/custom-management-commands/
- Scrapy CrawlerRunner: https://docs.scrapy.org/en/latest/topics/api.html#scrapy.crawler.CrawlerRunner
- Scrapy Item Pipeline: https://docs.scrapy.org/en/latest/topics/item-pipeline.html
- crochet: https://crochet.readthedocs.io/

### 📦 Definition of Done
- [ ] Acceptance criteria spełnione
- [ ] Lint + test zielone
- [ ] E2E test manualny udokumentowany w PR description (screenshot/log)
- [ ] Claude approve → squash merge
- [ ] **🎉 M1 — First character scrape COMPLETED.**
- [ ] Claude updatuje `PROGRESS.md` oraz zamyka Milestone M1 w GitHubie (`gh api --method PATCH /repos/.../milestones/1 -f state=closed`)

---

## Next steps — co dzieje się po M1

Po merge PR #8 i zaznaczeniu M1 jako completed:

### 1. Retrospektywa M1 (Claude ↔ developer)
Claude otwiera w kolejnej sesji rozmowę podsumowującą:
- **Co zadziałało:** wzorce warte powtórzenia (np. „ścisłe TypedDict w service sprawiło że pipeline się pisał sam")
- **Gdzie utknęliśmy:** taski które przekroczyły 4h, gdzie developer wracał drugiego dnia — ile razy i dlaczego (→ lepsze szacowanie M2)
- **Pułapki CLAUDE.md:** czego się dowiedzieliśmy o specyfice projektu (np. sprzeczność python3.12/3.13 — czy naprawiliśmy w CLAUDE.md?)
- **Wzorce do utrwalenia:** dodać do pliku `docs/conventions.md` albo do `CLAUDE.md §11`

### 2. Zmiana coverage threshold
Osobny micro-task (Issue #9): `chore: raise coverage threshold from 0 to 70 for post-M1`.
- Ten task to 15-minutowa zmiana `.github/workflows/ci.yml` (zmiana jednego numeru) + weryfikacja że nadal green
- Jeśli coverage <70 — **nie** obniżamy progu, dopisujemy testy (zasada z `CLAUDE.md §15.13`)

### 3. Generacja planu dla M2
Claude uruchamia `superpowers:writing-plans` z argumentami:
- Spec źródłowy: istniejący `docs/superpowers/specs/2026-04-17-tibiantis-execution-plan-design.md` (sekcja 6 — M2)
- Zakres: 4 taski M2 (auth REST + GraphQL fundament)
- Plik output: `docs/superpowers/plans/<YYYY-MM-DD>-m2-implementation-plan.md`

### 4. Decyzje architektoniczne do rozstrzygnięcia przed M2
M2 wprowadza GraphQL. CLAUDE.md wybiera **Strawberry-Django**. Przed rozpoczęciem M2:
- Mini-brainstorm (`superpowers:brainstorming`) o authz w GraphQL: JWT z DRF middleware vs Strawberry extension vs dekorator resolver?
- Decyzja o location JWT w requeście: header `Authorization: Bearer` (standard) czy cookie?
- CSRF w GraphQL: włączamy czy wyłączamy dla `/graphql/`? (Strawberry zwykle wyłącza, ale flag dla świadomej decyzji)

---

## Self-review (wykonany przez Claude 2026-04-17)

### Spec coverage
- Section 3 speca (role) → pokryte w strukturze planu: developer wykonuje, Claude tworzy Issues + review + testy
- Section 4 (workflow) → każdy task dziedziczy strukturę: branch → PR → CI → review → approve → merge
- Section 4 template → każdy task z tego planu używa identycznej struktury
- Section 5 (code review checklist) → nie duplikowany w planie (jest w specu, Claude używa); blockers/architecture/quality/learning referencowane w Acceptance Criteria i Pułapkach
- Section 6 roadmapa M0+M1 → 8 tasków pokrywają 3 dni M0 i 5 dni M1
- Section 7 daily tasks → 1:1 mapping ze szkicami z §7 speca
- Section 8 superpowers skills → referenced w Next steps (writing-plans, brainstorming)

### Placeholder scan — czyste (usunięto TODO)
- D2 i D3: URL-e do Django 6.0 docs oznaczone jako TODO bo niepewne czy `/en/6.0/` istnieje (pisać w wiedzy cutoff Aug 2025 — Django 6.0 może nie być wydany). Użyłem `/en/stable/` jako fallback. To nie jest placeholder w planie, tylko świadoma niepewność. Developer zweryfikuje podczas czytania.

### Type consistency
- `CharacterPayload` TypedDict — zdefiniowany w Task #6, używany w Task #8 (pipeline). Nazwa spójna.
- `upsert_character(payload: CharacterPayload) -> Character` — ta sama sygnatura w Task #6 Acceptance, Task #8 Pulapki, Task #8 pipelines.py
- `CharacterItem` vs `Character` vs `CharacterPayload` — trzy różne typy z jasnymi granicami:
  - `CharacterItem`: Scrapy item (boundary spider ↔ pipeline)
  - `CharacterPayload`: TypedDict (boundary pipeline ↔ service)
  - `Character`: Django model (boundary service ↔ DB)

### Internal consistency
- M0 = 3 taski (Task #1, #2, #3) ✓
- M1 = 5 tasków (Task #4-#8) ✓
- Branch naming: zgodny z §3 speca (`<type>/<nr>-<slug>`)
- Conventional Commits: każdy task ma przykładowy commit message zgodny
- Sprzeczność python3.12/3.13 flagowana w Task #3 pułapka A + Open Questions top

Plan gotowy do użycia jako źródło treści GitHub Issues po utworzeniu repo w Task #1.
