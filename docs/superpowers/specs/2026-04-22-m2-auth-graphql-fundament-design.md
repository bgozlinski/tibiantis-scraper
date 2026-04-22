# M2 — Auth + GraphQL fundament — Design

**Data:** 2026-04-22
**Milestone:** M2 (GitHub milestone #3)
**Budżet:** 4 dni roboczych (~14-16h)
**Poprzedni milestone:** M1 — First character scrape (zamknięty 2026-04-22)

---

## 1. Cel

Położyć fundament API projektu: użytkownicy, autentykacja JWT przez REST, oraz działający endpoint GraphQL z pierwszym query chronionym przez JWT. Po M2 kolejne milestones dokładają tylko domenę (Bedmage, Deaths) — warstwa transportu (REST auth + GraphQL) jest gotowa.

---

## 2. Scope

**W scope:**
- `apps/accounts/` — nowa aplikacja Django
- Custom `User` model (`AbstractUser` + `discord_id`)
- REST auth: `/api/auth/{register,login,refresh,logout}/` oparte o `djangorestframework-simplejwt`
- Strawberry-Django schema w `/graphql/`
- Query `me` (chronione JWT) i `character(name)` (public)
- Testy jednostkowe per warstwa + jeden e2e test (login → JWT → GraphQL)

**Poza scope (post-M2):**
- Password reset, email verification, social auth
- Rate limiting
- GraphQL mutations (`addBedmageWatch`, `setDeathThreshold` — M3/M4)
- Query `myBedmages`, `recentDeaths` — M3/M4
- Raising `coverage threshold` → 70 (tech debt z #5, osobne Issue post-M2)

---

## 3. Decyzje technologiczne

| Obszar | Wybór | Dlaczego |
|---|---|---|
| User model | `AbstractUser` + `discord_id = CharField(max_length=32, null=True, blank=True, unique=True, db_index=True)` od D9 | Django explicite zaleca custom User od dnia 1. `discord_id` wiadomo że będzie potrzebny (M6 bot). Dokładając custom później = data migration + FK churn. |
| Auth lib | `djangorestframework-simplejwt` + manualny register | Wartość edukacyjna (nauka DRF ViewSets, serializer validation). `djoser` abstrahuje zbyt dużo. Custom register pozwoli później wpiąć walidację `discord_id`. |
| GraphQL lib | `strawberry-graphql-django` | CLAUDE.md §2 preferowane. Pre-flight compat check z Django 6 obowiązkowy przed D11. |
| Schema scaling | Per-app `schema.py`, scalanie w `config/schema.py` | CLAUDE.md §3. Matches convention. |
| JWT w GraphQL | `strawberry_django.auth.extensions` jeśli działa, fallback: DRF `JWTAuthentication` na `AsyncGraphQLView` | Decyzja w D12 po pre-flight. |

---

## 4. Strategia dekompozycji

**Bottom-up, 4 Issues, strict chain D9 → D10 → D11 → D12.** Zgodne z konwencją M1 (model → service → spider → pipeline). Każdy Issue ma zamknięty zakres, żadnego paralelizmu.

Alternatywy rozważone i odrzucone:
- **Vertical slice** — rozmywa granice Issues (D9 register potem przerabiany w D11 dla `discord_id`), ryzyko przepisywania.
- **Parallel tracks (5 Issues)** — D11 GraphQL bez auth = praca do częściowego wyrzucenia w D12, nie mieści się w 4-dniowym budżecie.

---

## 5. Breakdown — 4 Issues

### D9 — [M2-D9] accounts app + custom User + AUTH_USER_MODEL (~3h)
**Branch:** `feat/<N>-accounts-user-model`

Acceptance criteria:
- `apps/accounts/` utworzone przez `manage.py startapp accounts`
- Dopisane do `LOCAL_APPS` w `config/settings/base.py`
- `apps/accounts/models.py` definiuje `class User(AbstractUser)` z:
  - `discord_id = CharField(max_length=32, null=True, blank=True, unique=True, db_index=True)`
- `AUTH_USER_MODEL = "accounts.User"` w `config/settings/base.py`
- Migracja `0001_initial` wygenerowana, zacommitowana
- `apps/accounts/admin.py` — `UserAdmin` subclass z `discord_id` w obu `fieldsets` i `add_fieldsets`
- Testy: create user z `discord_id`, `IntegrityError` przy duplikacie `discord_id`, manualny smoke "create user przez /admin/ działa"

**Pułapka:** Kolejność migracji. `AUTH_USER_MODEL` MUSI wyjść zanim ktokolwiek utworzy FK na User. Sanity check: `BedmageWatch.user` dopiero w M3, safe.

### D10 — [M2-D10] REST auth endpoints (~4h)
**Branch:** `feat/<N>-rest-auth-jwt`
**Zależy od:** D9 merged

Acceptance criteria:
- `poetry add djangorestframework djangorestframework-simplejwt`
- `INSTALLED_APPS += ["rest_framework", "rest_framework_simplejwt.token_blacklist"]`
- `python manage.py migrate` — migracja `token_blacklist` zaaplikowana (bez custom migration artifact w repo)
- `apps/accounts/api/serializers.py` — `RegisterSerializer` z `validate_password` przez Django `AUTH_PASSWORD_VALIDATORS`
- `apps/accounts/api/views.py` — `RegisterView (CreateAPIView)` + re-export `TokenObtainPairView` / `TokenRefreshView` / `TokenBlacklistView`
- `config/urls.py` → `path("api/auth/", include(...))` z `register/`, `login/`, `refresh/`, `logout/`
- `SIMPLE_JWT` w settings: `ROTATE_REFRESH_TOKENS=True`, `BLACKLIST_AFTER_ROTATION=True`, `ACCESS_TOKEN_LIFETIME=timedelta(minutes=5)`, `REFRESH_TOKEN_LIFETIME=timedelta(days=1)`
- Testy:
  - POST register: 201 tworzy usera, 400 przy duplikacie username, 400 przy słabym haśle
  - POST login: 200 zwraca access+refresh, 401 przy złych creds
  - POST refresh: 200 z valid refresh, 401 z expired/invalid
  - POST logout: 200 blacklistuje refresh, kolejne użycie tego refresha = 401

### D11 — [M2-D11] Strawberry schema + /graphql/ + me query (~3-4h)
**Branch:** `feat/<N>-graphql-bootstrap`
**Zależy od:** D10 merged

**Pre-flight (przed startem Issue):** `poetry add strawberry-graphql-django --dry-run`. Jeśli konflikt `django<6` — **STOP**, redesign. Nie downgradujemy Django (CLAUDE.md §15.10). Alternatywa: `strawberry-graphql` (bez `-django`) + manualny mapping types. Wynik pre-flight zapisać w body Issue D11 jako "zweryfikowane YYYY-MM-DD".

Acceptance criteria:
- `poetry add strawberry-graphql-django` (wariant z `-django` jeśli kompatybilny)
- `INSTALLED_APPS += ["strawberry_django"]`
- `apps/accounts/schema.py`:
  - `UserType` mapped z modelu
  - Explicit field list (bez `password`, `is_superuser`, `is_staff`, `user_permissions`, `groups`)
  - Include `username`, `email`, `date_joined`, `discord_id`
  - Query class z resolver `me: UserType | None` — zwraca `info.context.request.user` jeśli `is_authenticated`, None wpp
- `config/schema.py` — scala `Query` z apps, `schema = strawberry.Schema(query=Query)`
- `config/urls.py` → `/graphql/` przez `AsyncGraphQLView.as_view(schema=schema)` (async bo Django 6 + spójnie z M1 pipeline, który już używa `sync_to_async`)
- Testy:
  - Schema introspection smoke (`query { __schema { types { name } } }` zwraca ok)
  - `query { me { username } }` bez auth → `me: null`
  - `query { me { username } }` z `force_login` w TestClient → zwraca usera
  - Min. jeden test na async resolver z realnym ORM query (canary na `SynchronousOnlyOperation`)

### D12 — [M2-D12] JWT w GraphQL + character(name) + e2e (~4h)
**Branch:** `feat/<N>-graphql-jwt-character`
**Zależy od:** D11 merged

Acceptance criteria:
- JWT authentication działa na `/graphql/` — wybór: `strawberry_django.auth.extensions` jeśli wspiera simplejwt out-of-the-box, fallback custom middleware / DRF `JWTAuthentication` w `AsyncGraphQLView`
- `apps/characters/schema.py`:
  - `CharacterType` — all public Character fields
  - Query resolver `character(name: str) -> CharacterType | None` zwraca `Character.objects.filter(name=name).afirst()`
- `config/schema.py` dopina `apps.characters.schema.Query`
- `character(name)` jest **public** (działa bez JWT)
- `me` wymaga JWT (null bez auth, dane z auth)
- e2e integration test:
  1. POST `/api/auth/register/` tworzy usera
  2. POST `/api/auth/login/` zwraca `access`
  3. Seed `Character.objects.create(name="Yhral", level=120, ...)`
  4. POST `/graphql/` z `Authorization: Bearer <access>` i query `{ me { username } character(name: "Yhral") { level } }`
  5. Response: `me.username` = created user, `character.level` = 120
- Wszystkie 4 pre-commit hooks zielone (ruff, ruff-format, mypy, django-upgrade)

---

## 6. Ryzyka i watch-outs

| # | Ryzyko | Mitigacja |
|---|---|---|
| R1 | Zmiana `AUTH_USER_MODEL` po utworzeniu FK na User | Sanity check przy D9: `BedmageWatch` / inne FK jeszcze nie istnieją → safe. |
| R2 | `SynchronousOnlyOperation` w async GraphQL resolver z sync ORM | Test canary w D11 (ORM w resolver). Jeśli wywala się — Strawberry-Django's auto-wrap nie działa → explicit `sync_to_async` (jak w M1 pipeline). |
| R3 | Zapomniana migracja `token_blacklist` | AC D10 explicit. |
| R4 | `UserAdmin.add_fieldsets` vs `fieldsets` — create user przez admin wywala się bo brak password field | AC D9 manual smoke. |
| R5 | `strawberry-graphql-django` niekompatybilny z Django 6 | Pre-flight `--dry-run` przed D11, nie downgradujemy Django, plan B = `strawberry-graphql` bez -django. |

---

## 7. Test strategy

- Każdy Issue — testy jednostkowe odpowiedniej warstwy (serializer / view / resolver).
- Integration e2e test tylko w D12 (login → JWT → GraphQL).
- `coverage threshold` zostaje 0 — tech debt z #5, osobne post-M2 Issue.
- Brak testów hitujących żywe external services (CLAUDE.md §6).

---

## 8. Definition of Done (M2)

- [ ] 4 PR merged, 4 Issues zamknięte
- [ ] `POST /api/auth/login/` → JWT → `Authorization: Bearer` autentykuje `/graphql/`
- [ ] `query { me { username } character(name: "Yhral") { level } }` zwraca dane
- [ ] Wszystkie pre-commit + CI zielone na master
- [ ] PROGRESS.md: "🎉 M2 COMPLETED" + retro per Issue
- [ ] Milestone M2 zamknięty na GitHub

---

## 9. Zamrożony scope

Nowe pomysły poza sekcją 2 (password reset, rate limiting, social auth, ekstra queries/mutations) = osobne Issues post-M2. Nie dorzucamy w trakcie milestone'u.
