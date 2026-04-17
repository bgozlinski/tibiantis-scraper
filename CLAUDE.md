# CLAUDE.md

Ten plik dostarcza kontekst dla Claude Code (claude.ai/code) podczas pracy nad tym repozytorium.

---

## 1. Przegląd projektu

**Nazwa robocza:** Tibiantis Monitor

Aplikacja backendowa, która w harmonogramie scrapuje dwa serwisy z gry Tibiantis, przechowuje dane postaci i wydarzenia w bazie danych oraz komunikuje się z użytkownikami przez bota Discord. Kluczowe funkcje biznesowe:

1. **Monitoring postaci** — scraper profili z `tibiantis.online`.
2. **Monitoring śmierci** — scraper listy śmierci z `tibiantis.info`.
3. **Bedmage tracker** — przypominanie użytkownikom, że minęło 100 min od zalogowania się postaci (koniec regeneracji many w łóżku).
4. **Discord Bot** — interfejs użytkownika: powiadomienia o śmierciach wysokopoziomowych postaci oraz komendy do zarządzania listą bedmages.

Aplikacja jest modułowa — planowane są kolejne funkcje, więc architektura musi być rozszerzalna.

---

## 2. Stos technologiczny (ściśle obowiązujący)

| Warstwa | Technologia |
|---|---|
| Framework | **Django 6.0** |
| Zarządzanie zależnościami | **Poetry** (żadnego `pip install` ani `requirements.txt` bez uzasadnienia) |
| Scraping | **Scrapy** |
| REST API | **Django REST Framework** — **tylko** autentykacja (login / rejestracja / refresh tokenu) |
| GraphQL API | **Strawberry-Django** (preferowane) lub Graphene-Django — **cała reszta domeny** |
| Baza relacyjna | **PostgreSQL** — dane domenowe |
| Baza dokumentowa | **MongoDB** — logi aplikacyjne i logi scrapowania |
| Scheduler | **Celery + Celery Beat** (broker: Redis) |
| Discord bot | **discord.py** (py-cord) jako osobny proces |
| Konteneryzacja | **Docker + docker-compose** (produkcja) |

**Zasady dotyczące stosu:**
- Nie dodawaj nowych bibliotek bez uprzedniego uzasadnienia. Jeśli coś dubluje istniejącą funkcjonalność — odmów.
- Django 6.0 jest wymagane — nie downgraduj do 5.x nawet jeśli jakaś biblioteka nie ma jeszcze wsparcia. Zamiast tego zaproponuj alternatywę.
- REST służy **wyłącznie** do auth. Jeśli ktoś prosi o endpoint CRUD w REST — zaproponuj GraphQL.

---

## 3. Struktura katalogów

```
.
├── CLAUDE.md
├── pyproject.toml              # Poetry
├── poetry.lock
├── docker-compose.yml          # produkcja
├── docker-compose.dev.yml      # lokalna praca
├── Dockerfile
├── .env.example
├── manage.py
├── config/                     # Projekt Django
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   └── prod.py
│   ├── urls.py
│   ├── schema.py               # Główny schemat GraphQL (scalony)
│   ├── celery.py
│   └── wsgi.py / asgi.py
├── apps/
│   ├── accounts/               # Użytkownicy + REST auth
│   │   ├── api/                # DRF views, serializers
│   │   └── schema.py           # (opcjonalnie: profile w GraphQL)
│   ├── characters/             # Model Character + logika domenowa
│   │   ├── models.py
│   │   ├── schema.py           # GraphQL (queries + mutations)
│   │   └── services.py
│   ├── bedmages/               # Tracker 100-minutowy
│   │   ├── models.py
│   │   ├── schema.py
│   │   ├── services.py         # logika wykrywania końca regeneracji
│   │   └── tasks.py            # Celery tasks
│   ├── deaths/                 # Monitor śmierci
│   │   ├── models.py
│   │   ├── schema.py
│   │   └── tasks.py
│   └── notifications/          # Warstwa powiadomień (Discord, przyszłość: email itp.)
├── scrapers/                   # Projekt Scrapy (osobny od apps/)
│   ├── scrapy.cfg
│   └── tibiantis_scrapers/
│       ├── settings.py
│       ├── items.py
│       ├── pipelines.py        # Pipeline zapisujący do Django ORM
│       └── spiders/
│           ├── character_spider.py     # tibiantis.online
│           └── deaths_spider.py        # tibiantis.info
├── discord_bot/                # Osobny proces, współdzieli modele Django
│   ├── bot.py
│   ├── cogs/
│   │   ├── bedmages.py
│   │   └── deaths.py
│   └── management/
│       └── commands/
│           └── run_discord_bot.py
├── logs_backend/               # Integracja z MongoDB (handler loggingu)
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/
```

**Reguły strukturalne:**
- Każda aplikacja Django trzyma GraphQL w `schema.py` wewnątrz aplikacji. `config/schema.py` tylko scala.
- Scrapery żyją poza `apps/` — są uruchamiane z Celery tasków, a wyniki zapisują przez pipeline Scrapy wywołujący `services.py` odpowiedniej aplikacji (nigdy bezpośrednio `Model.objects.create` w spiderze).
- Logika biznesowa w `services.py`, nie w widokach ani nie w resolverach GraphQL ani nie w spiderach.

---

## 4. Bazy danych — podział odpowiedzialności

### PostgreSQL (domyślna baza Django)
Trzyma **wszystkie** dane domenowe:
- `User` (model Django + rozszerzenia)
- `Character` — zescrapowane profile
- `BedmageWatch` — kto, jaką postać, od kiedy monitoruje
- `DeathEvent` — zarejestrowane śmierci
- `DiscordChannel` — gdzie bot publikuje powiadomienia

### MongoDB
**Tylko** logi — nigdy dane domenowe. Dwie kolekcje:
- `app_logs` — standardowy logging Pythona (poziomy INFO+)
- `scrape_logs` — historia prób scrapowania: timestamp, URL, status HTTP, czas odpowiedzi, liczba pozyskanych rekordów, błędy

Do Mongo używaj `pymongo` bezpośrednio (przez prosty handler loggingu w `logs_backend/`). **Nie używaj** Djongo ani MongoEngine jako ORM — to nie jest baza domenowa.

---

## 5. Kluczowe modele danych (szkice)

```python
# apps/characters/models.py
class Character(models.Model):
    name = models.CharField(max_length=64, unique=True)
    sex = models.CharField(max_length=16, blank=True)
    vocation = models.CharField(max_length=32, blank=True)
    level = models.PositiveIntegerField(null=True)
    world = models.CharField(max_length=32, blank=True)
    residence = models.CharField(max_length=64, blank=True)
    house = models.CharField(max_length=128, blank=True)
    guild_membership = models.CharField(max_length=128, blank=True)
    last_login = models.DateTimeField(null=True)
    account_status = models.CharField(max_length=32, blank=True)
    last_scraped_at = models.DateTimeField(auto_now=True)

# apps/bedmages/models.py
class BedmageWatch(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    character = models.ForeignKey(Character, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    last_notified_login = models.DateTimeField(null=True)  # żeby nie spamować
    active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("user", "character")

# apps/deaths/models.py
class DeathEvent(models.Model):
    character_name = models.CharField(max_length=64, db_index=True)
    level_at_death = models.PositiveIntegerField()
    killed_by = models.TextField(blank=True)
    died_at = models.DateTimeField(db_index=True)
    scraped_at = models.DateTimeField(auto_now_add=True)
    announced_on_discord = models.BooleanField(default=False)

    class Meta:
        unique_together = ("character_name", "died_at")  # deduplikacja
```

---

## 6. Scraping — wymagania

### Cel 1: `https://tibiantis.online/?page=character&name=<n>`
- Parametr `name` dynamiczny, przekazywany do spidera z taska Celery.
- Wyciągane pola: **Name, Sex, Vocation, Level, World, Residence, House, Guild Membership, Last Login, Account Status**.
- Spider iteruje po liście postaci pochodzącej z:
  - wszystkich aktywnych `BedmageWatch`,
  - (opcjonalnie) ręcznie dodanej listy „obserwowane postacie".

### Cel 2: `https://tibiantis.info/stats/deaths`
- Scraper tabeli śmierci. Wyciąga: imię, poziom, opis śmierci, timestamp.
- Odpowiada za deduplikację — rekord `(character_name, died_at)` musi być unikalny.

### Reguły scrapera:
- Każdy spider ma **osobny task Celery** i **osobny harmonogram** w Celery Beat. Można zmieniać interwały niezależnie (konfiguracja w bazie przez `django-celery-beat`, żeby zmieniać bez deployu).
- Przestrzegaj `robots.txt` i dodaj rozsądny `DOWNLOAD_DELAY` (≥ 2 s) oraz realny `USER_AGENT` z linkiem kontaktowym.
- Każde uruchomienie spidera loguje do MongoDB (`scrape_logs`): url, czas trwania, liczba itemów, błędy.
- Pipeline Scrapy woła funkcje z `apps/*/services.py` — nie pisze bezpośrednio do ORM.
- Uruchamianie Scrapy w Celery: `CrawlerRunner` + `crochet` albo subprocess na `scrapy crawl`. Nigdy `CrawlerProcess` (blokuje event loop Twisted przy drugim użyciu).

---

## 7. Logika biznesowa — szczegóły

### Bedmage tracker (100 minut)
- Po każdym scrapowaniu postaci z aktywnym `BedmageWatch`:
  - oblicz `delta = now() - character.last_login`,
  - jeśli `delta >= 100 minut` **oraz** `last_notified_login != character.last_login` — wyślij powiadomienie Discord do `watch.user`, ustaw `last_notified_login = character.last_login`.
- Dzięki `last_notified_login` użytkownik dostaje powiadomienie **raz na sesję spania**, a nie przy każdym scrapie.
- Jeśli postać znów się zaloguje (`last_login` się zmieni) — cykl startuje od nowa.

### Deaths monitor
- Po każdym scrapie `tibiantis.info/stats/deaths`:
  - znajdź `DeathEvent` z `announced_on_discord=False` **i** `level_at_death >= THRESHOLD` (domyślnie 30, ale **konfigurowalny** — trzymać w ustawieniach lub w modelu `DiscordChannel`),
  - wyślij zbiorczą wiadomość na skonfigurowany kanał Discord,
  - oznacz jako `announced_on_discord=True`.
- Próg poziomu ma być edytowalny przez admina (GraphQL mutation lub Django admin).

---

## 8. Discord Bot — wymagania

Bot to **osobny proces** (osobny kontener w docker-compose), który dzieli modele z Django. Uruchamiany przez management command:

```bash
python manage.py run_discord_bot
```

### Wymagane komendy (slash commands):
| Komenda | Działanie |
|---|---|
| `/bedmage add <character_name>` | Dodaje postać do listy bedmages wywołującego |
| `/bedmage remove <character_name>` | Usuwa postać z listy |
| `/bedmage list` | Pokazuje postacie monitorowane przez użytkownika |
| `/deaths threshold <level>` | (tylko admin kanału) Ustawia próg powiadomień o śmierciach |

### Zasady bota:
- Użytkownik Discord musi być powiązany z kontem Django (`User`) — mapowanie przez `discord_id`. Przy pierwszej komendzie bot tworzy `User` automatycznie albo prosi o link przez OAuth (do ustalenia — **domyślnie** auto-tworzenie).
- Bot nie wysyła powiadomień sam z siebie — robi to Celery task, który pisze do kanału przez webhook / API Discord. Bot słucha tylko komend. (**Alternatywnie** — bot nasłuchuje na kolejkę Redis i wysyła. Pierwsza opcja prostsza, wybieramy ją.)
- Obsługa błędów: każda komenda łapie wyjątki i odpowiada czytelnie użytkownikowi. Nigdy nie pokazuj stack trace na Discordzie.

---

## 9. API — podział REST / GraphQL

### REST (DRF) — tylko auth:
- `POST /api/auth/register/`
- `POST /api/auth/login/` (zwraca JWT access + refresh)
- `POST /api/auth/refresh/`
- `POST /api/auth/logout/` (blacklistuje refresh token)

Użyj `djangorestframework-simplejwt` albo `djoser`. **Nie** twórz endpointów CRUD w REST.

### GraphQL — reszta:
- Single endpoint: `/graphql/`.
- Autoryzacja: dekorator sprawdzający JWT w kontekście (albo middleware Strawberry).
- Operacje:
  - **Query:** `characters`, `character(name)`, `myBedmages`, `recentDeaths(level: Int)`, `me`
  - **Mutation:** `addBedmageWatch`, `removeBedmageWatch`, `setDeathThreshold`
- Trzymaj typy GraphQL blisko modelu (`schema.py` per aplikacja), scalaj w `config/schema.py`.

---

## 10. Docker / docker-compose

### Serwisy w `docker-compose.yml` (produkcja):
1. `web` — Django + Gunicorn (ASGI: `uvicorn` jeśli potrzebujemy async)
2. `celery_worker`
3. `celery_beat`
4. `discord_bot`
5. `postgres`
6. `mongodb`
7. `redis` (broker Celery)
8. `nginx` (reverse proxy, TLS)

### Reguły:
- Jeden `Dockerfile` multi-stage dla aplikacji Pythona (web/celery/bot korzystają z tego samego obrazu, różnią się `command`).
- Build obrazu przez Poetry: `poetry install --no-dev --no-root` bezpośrednio w obrazie. Nie eksportuj do `requirements.txt` — to legacy pattern.
- Wszystkie sekrety w `.env` (nigdy w repo). `.env.example` musi być zawsze aktualny.
- Nie instaluj narzędzi deweloperskich w obrazie produkcyjnym.
- Healthchecki dla postgres, redis, web.
- Volumes: `postgres_data`, `mongo_data`, `static_volume`, `media_volume`.

### Zmienne środowiskowe (`.env.example`):
```
DJANGO_SECRET_KEY=
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=
DATABASE_URL=postgres://user:pass@postgres:5432/tibiantis
MONGO_URL=mongodb://mongo:27017
MONGO_DB=tibiantis_logs
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
DISCORD_BOT_TOKEN=
DISCORD_DEFAULT_CHANNEL_ID=
SCRAPE_USER_AGENT=TibiantisMonitor/1.0 (contact@example.com)
DEATH_LEVEL_THRESHOLD=30
```

---

## 11. Konwencje kodu

- **Formatowanie:** `ruff format` (zastępuje Black) + `ruff check --fix`.
- **Typowanie:** używaj type hints wszędzie. `mypy` w strict mode dla `apps/`.
- **Importy:** absolutne (`from apps.characters.models import Character`), nie relatywne między aplikacjami.
- **Settings:** nigdy `from django.conf import settings` w modelach — wyłącznie w widokach/services.
- **Migracje:** każda migracja musi być commitowana razem ze zmianą modelu. Nazwy opisowe: `0003_add_bedmage_last_notified_login.py`.
- **Testy:** `pytest` + `pytest-django`. Każdy service musi mieć testy jednostkowe. Scrapery testujemy na zapisanych fixturach HTML (`tests/fixtures/*.html`), **nie** hitujemy żywych stron w CI.
- **Commit messages:** Conventional Commits (`feat:`, `fix:`, `chore:`, `refactor:`, `test:`, `docs:`).

---

## 12. Pre-commit hooks

Repozytorium używa **`pre-commit`** do egzekwowania konwencji z sekcji 11 jeszcze przed commitem. Każdy deweloper musi zainstalować hooki lokalnie:

```bash
poetry run pre-commit install
poetry run pre-commit install --hook-type commit-msg   # dla Conventional Commits
```

### Plik `.pre-commit-config.yaml`

```yaml
default_language_version:
  python: python3.12

repos:
  # Ogólne pliki / higiena repo
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-json
      - id: check-added-large-files
        args: [--maxkb=500]
      - id: check-merge-conflict
      - id: detect-private-key
      - id: mixed-line-ending
        args: [--fix=lf]

  # Ruff (lint + format) — jedyny linter/formatter Pythona
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.7.4
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]
      - id: ruff-format

  # Mypy — strict na apps/
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.13.0
    hooks:
      - id: mypy
        files: ^apps/
        additional_dependencies:
          - django-stubs[compatible-mypy]
          - djangorestframework-stubs
          - strawberry-graphql

  # Django 6.0 — automatyczna modernizacja składni
  - repo: https://github.com/adamchainz/django-upgrade
    rev: 1.22.1
    hooks:
      - id: django-upgrade
        args: [--target-version, "6.0"]

  # Poetry — spójność pyproject.toml + poetry.lock
  - repo: https://github.com/python-poetry/poetry
    rev: 1.8.4
    hooks:
      - id: poetry-check
      - id: poetry-lock
        args: [--no-update]

  # Sekrety — ostatnia linia obrony przed commitowaniem tokenów
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2
    hooks:
      - id: gitleaks

  # Conventional Commits — sprawdzenie formatu wiadomości
  - repo: https://github.com/compilerla/conventional-pre-commit
    rev: v3.6.0
    hooks:
      - id: conventional-pre-commit
        stages: [commit-msg]
        args: [feat, fix, chore, refactor, test, docs, perf, ci, build]
```

### Reguły dotyczące pre-commit:

- **Wszystkie hooki muszą przechodzić** przed push. Lokalny `--no-verify` jest dopuszczalny **tylko** w skrajnych wypadkach (np. pilny hotfix) — CI i tak odrzuci nieprawidłowy commit.
- **Pinuj wersje** (`rev`) — nigdy `rev: main`. Aktualizacja przez `pre-commit autoupdate` w osobnym PR-ze, nie razem z zmianą kodu.
- **Jeśli dodajesz nową zależność deweloperską** (linter, checker) — hook idzie do `.pre-commit-config.yaml`, **nie** do `pyproject.toml` jako samodzielne narzędzie. Wyjątek: narzędzia wywoływane z Celery/kodu.
- **`mypy` w strict mode** tylko dla `apps/`. `scrapers/` i `discord_bot/` mogą być bardziej permisywne (ustaw w `pyproject.toml` przez `[[tool.mypy.overrides]]`).
- **Gitleaks** blokuje commit, gdy wykryje token zgodny z regexami (AWS keys, Discord tokens, JWT, Django SECRET_KEY itp.). Jeśli false-positive — dodaj do `.gitleaksignore` z komentarzem, dlaczego to nie jest sekret.

---

## 13. GitHub Actions — CI / CD

Workflowy żyją w `.github/workflows/`. Trzy podstawowe pliki:

### 13.1. `ci.yml` — lint + testy na każdym PR

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    name: Pre-commit (lint + format + mypy)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install Poetry
        run: pipx install poetry==1.8.4
      - name: Install dependencies
        run: poetry install --no-interaction --no-root
      - name: Run pre-commit on all files
        run: poetry run pre-commit run --all-files --show-diff-on-failure

  test:
    name: Pytest
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: tibiantis_test
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7
        ports: ["6379:6379"]
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
      mongo:
        image: mongo:7
        ports: ["27017:27017"]
    env:
      DATABASE_URL: postgres://postgres:postgres@localhost:5432/tibiantis_test
      REDIS_URL: redis://localhost:6379/0
      CELERY_BROKER_URL: redis://localhost:6379/1
      MONGO_URL: mongodb://localhost:27017
      MONGO_DB: tibiantis_logs_test
      DJANGO_SECRET_KEY: test-only-not-a-real-secret
      DJANGO_DEBUG: "False"
      DJANGO_ALLOWED_HOSTS: "*"
      DISCORD_BOT_TOKEN: test-token
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pipx install poetry==1.8.4
      - run: poetry install --no-interaction --no-root
      - name: Migrate
        run: poetry run python manage.py migrate --noinput
      - name: Run tests
        run: poetry run pytest --cov=apps --cov-report=xml --cov-fail-under=70
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          files: ./coverage.xml
          fail_ci_if_error: false
```

### 13.2. `docker.yml` — build i push obrazu na `main`

```yaml
name: Docker build

on:
  push:
    branches: [main]
    tags: ["v*"]

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/metadata-action@v5
        id: meta
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=ref,event=branch
            type=semver,pattern={{version}}
            type=sha,prefix=sha-,format=short
      - uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

### 13.3. `security.yml` — cotygodniowy skan zależności

```yaml
name: Security audit

on:
  schedule:
    - cron: "0 6 * * 1"    # poniedziałek 06:00 UTC
  workflow_dispatch:

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pipx install poetry==1.8.4
      - run: poetry install --no-interaction --no-root
      - name: pip-audit
        run: poetry run pip-audit --strict
      - name: Gitleaks full history
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### Reguły dotyczące CI:

- **Branch protection na `main`**: wymagane passing checks = `lint` + `test`. Brak force-push. Wymagany co najmniej jeden review.
- **Sekrety GitHub Actions**: `DJANGO_SECRET_KEY`, `DISCORD_BOT_TOKEN` itd. **nigdy** w kodzie workflow. Zawsze `${{ secrets.* }}`.
- **Testy nie mogą hitować żywych stron Tibiantis ani żywego Discorda** — używają fixturek HTML i `discord.py` w trybie test/mock.
- **Cache Poetry** przez `actions/setup-python` z `cache: pip` (prostsze niż ręczny cache `~/.cache/pypoetry`).
- **`concurrency` group** zabija stare runy tego samego PR — oszczędność minut CI.
- **Coverage threshold** — minimum 70% dla `apps/`, docelowo 85%+. Nie obniżaj progu, żeby „przeszedł build" — zamiast tego dopisz testy.
- **Dependabot** włączony przez `.github/dependabot.yml` (weekly, grouped updates dla Pythona i Dockera).

### `.github/dependabot.yml`

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
    groups:
      django:
        patterns: ["django*"]
      testing:
        patterns: ["pytest*", "coverage*"]
  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "monthly"
```

---

## 14. Cheatsheet komend

```bash
# Zależności
poetry install
poetry add <package>
poetry add --group dev <package>

# Django
poetry run python manage.py makemigrations
poetry run python manage.py migrate
poetry run python manage.py createsuperuser
poetry run python manage.py runserver

# Scrapy (ręcznie, do debugu)
poetry run scrapy crawl character -a name=Yhral
poetry run scrapy crawl deaths

# Celery
poetry run celery -A config worker -l info
poetry run celery -A config beat -l info

# Discord bot
poetry run python manage.py run_discord_bot

# Testy
poetry run pytest
poetry run pytest apps/bedmages -v

# Linter
poetry run ruff check .
poetry run ruff format .
poetry run mypy apps/

# Pre-commit
poetry run pre-commit install
poetry run pre-commit run --all-files          # lokalny odpowiednik joba `lint` w CI
poetry run pre-commit autoupdate               # aktualizacja wersji hooków (osobny PR!)
poetry run pre-commit run <hook-id> --all-files    # pojedynczy hook, np. `ruff` / `mypy`

# Docker (prod)
docker compose up -d --build
docker compose logs -f web
docker compose exec web python manage.py migrate
```

---

## 15. Zasady dla Claude — ważne

1. **Nie modyfikuj stosu technologicznego** z sekcji 2 bez wyraźnej zgody użytkownika. Jeśli jakaś biblioteka wydaje się nieoptymalna — **zapytaj**, nie zmieniaj samodzielnie.
2. **Logika biznesowa w `services.py`**, nie w widokach / resolverach / spiderach.
3. **Nie mieszaj baz** — żadnych danych domenowych w MongoDB, żadnych logów w PostgreSQL.
4. **Scrapery nie piszą do ORM bezpośrednio** — przechodzą przez services.
5. **Uruchamiając nową funkcję, zawsze dopisz test** (minimum jednostkowy dla service).
6. **Nie hituj żywych stron Tibiantis w testach** — używaj fixturek HTML.
7. **Przy każdej zmianie modelu**: migracja + aktualizacja GraphQL schema + test.
8. **Sekrety i tokeny nigdy nie lądują w repo** — zawsze przez `.env` + `django-environ`. Gitleaks w pre-commit i tak zablokuje commit, ale polegaj na konwencji, nie na narzędziu.
9. **Bot Discord to osobny proces** — nie próbuj go uruchamiać wewnątrz Django request/response cycle.
10. **Django 6.0** — jeśli jakaś biblioteka nie jest jeszcze kompatybilna, zaproponuj alternatywę, a nie downgrade Django.
11. **Przed proponowaniem commita** — upewnij się, że kod przechodzi przez `pre-commit run --all-files`. Jeśli hook zgłasza błąd, popraw kod, nie hook.
12. **Zmiany w `.pre-commit-config.yaml` i `.github/workflows/`** wymagają osobnego PR-a, nie miksuj ich ze zmianami funkcjonalnymi. Claude, jeśli proponujesz zmianę hooka lub workflow, wyraźnie to oznacz i wyjaśnij dlaczego.
13. **Nie obniżaj coverage threshold** w CI, żeby przeszedł build. Zamiast tego dopisz brakujące testy.
14. **Nowe zależności deweloperskie** (lintery, formattery) idą do `pre-commit-config.yaml`, nie do `pyproject.toml`. Odwrotnie — biblioteki używane w kodzie aplikacji idą do Poetry, nie do pre-commit.
15. **Wiadomość commita** musi być zgodna z Conventional Commits (wymusza to hook `conventional-pre-commit`). Format: `type(scope): message`, np. `feat(bedmages): add 100min regen tracker`.

---

## 16. Otwarte kwestie / przyszłe funkcje

Miejsce na notatki dotyczące rozwoju aplikacji. Dopisuj tutaj pomysły, zanim zostaną zaimplementowane:

- [ ] Powiadomienia mailowe jako alternatywa dla Discord
- [ ] Dashboard webowy (frontend do ustalenia)
- [ ] Historia poziomów postaci (wykresy progresji)
- [ ] Integracja z dodatkowymi światami / serwerami