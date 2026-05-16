# M10 — Hardening — Design spec

**Data:** 2026-05-16
**Status:** ACCEPTED (decyzje §1-§5 zaakceptowane przez developera 2026-05-16 w sesji M10 brainstorm)
**Plan:** do utworzenia po akceptacji spec'a (writing-plans next step) — `docs/superpowers/plans/2026-05-16-m10-implementation-plan.md`
**Milestone:** [M10 — Hardening](https://github.com/bgozlinski/tibiantis-scraper/milestones) (już utworzony, 3 issues attached: #162, #163, #164)
**Branch (D49 w trakcie):** `fix/164-bedmage-case-insensitive` — RED test scaffold commit `1b5b7b2`

---

## §1 Cel + scope

Post-deploy fix-up sprint po M9.5. Pierwszy realny prod deploy (M9.5-D47 na Hetzner CX22) wykrył trzy bugi/tech-debt items, które nie były złapane w pre-deploy smoke (M9-D41/D42/D43 weryfikowały tylko `/health/`, nie `/admin/`; brak operatora-na-świeżo testującego `.env` placeholder swap; `/bedmage add` testowane tylko z jedną casing w wcześniejszych milestone'ach).

M10 zamyka te trzy konkretne bugi — **żadnych new features, żadnego scope creep do innych Hardening kandydatów** (image scanning, backups, fail2ban, `compose pull` cron — wszystkie deferred do M10.5/M11/M-future, patrz §6).

### W zakresie M10:

1. **#164 — `Character.name` case-insensitive canonicalization** (data-correctness bug, user-visible)
   - Symptom: `/bedmage add Akrutki` + `/bedmage add akrutki` tworzą 2 separate `Character` + 2 separate `BedmageWatch` rows. Tibiantis treats names case-insensitively, nasz DB nie zgadza się z game layer.
   - Fix: canonicalization w `Character.save()` (first-letter-upper, rest-lower, strip whitespace) + DB-level `UniqueConstraint(Lower("name"))` jako belt-and-suspenders przeciw bypass paths (bulk_create, RunPython, raw SQL).
   - Pre-flight: RED test scaffold już na branchu `fix/164-bedmage-case-insensitive` (10 failing tests, commit `1b5b7b2`).

2. **#162 — Django admin renders bez CSS/JS w prod** (ops UX bug)
   - Symptom: `/admin/` przez SSH tunnel zwraca functional HTML ale unstyled — brak `/static/` serving w gunicorn, brak `STATIC_ROOT`, brak `collectstatic` w obrazie.
   - Fix: `whitenoise` runtime dep + middleware + `STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"` + `RUN python manage.py collectstatic --noinput` w Dockerfile + `.dockerignore`/`.gitignore` exclusion `staticfiles/`.
   - Dev parity guard: weryfikacja że `manage.py runserver` w `DEBUG=True` dalej serwuje admin (Django staticfiles app, nie whitenoise).

3. **#163 — `.env` `DATABASE_URL` password duplication** (operator footgun)
   - Symptom: `.env.example` ma `POSTGRES_PASSWORD=tibiantis` + `DATABASE_URL=postgres://tibiantis:tibiantis@postgres:5432/tibiantis` — operator generuje strong random password ale zapomina updateować DATABASE_URL → postgres init z nowym pwd, Django connect z placeholder pwd → migrate exit 1 → recovery wymaga wipe data volume. Kosztowało ~30 min na M9.5-D47.
   - Fix: konstrukcja `DATABASES["default"]` w `config/settings/prod.py` z individual `POSTGRES_*` env vars (USER, PASSWORD, DB, HOST, PORT), usunięcie `DATABASE_URL` z `.env.example`.
   - Dev parity decyzja: **Option A — unify** (dev też reads individual `POSTGRES_*` vars). Jedna shape env'a across environments. Cost: lokalne `.env` operatorów wymagają update.

### Poza zakresem M10 (deferred):

Patrz §6 dla pełnej listy. Skrót: image scanning, postgres backups, fail2ban + unattended-upgrades, `compose pull` cron, ALLOWED_HOSTS hygiene, TLS/DNS, GHA auto-deploy.

---

## §2 Work breakdown — D49 → D52

Następujemy past milestone pattern: 1 day = 1 GitHub issue = 1 PR. M10 ma 4 dni (3 functional + 1 close).

| Day | Issue | Branch | Type | Scope |
|---|---|---|---|---|
| **D49** | [#164](https://github.com/bgozlinski/tibiantis-scraper/issues/164) | `fix/164-bedmage-case-insensitive` ✅ | `fix(characters)` | Implementacja canonicalization w `Character.save()`, `UniqueConstraint(Lower("name"))` migration, data migration (dedupe + relink `BedmageWatch` FKs), update 5 affected assertions w existing tests, `__iexact` w services jako belt-and-suspenders. Claude robi PR review + scaffolds dodatkowe integration testy gdy widzi gaps. |
| **D50** | [#162](https://github.com/bgozlinski/tibiantis-scraper/issues/162) | `fix/162-admin-static-files` | `fix(web)` | `whitenoise = "^6.7.0"` w pyproject, settings changes (STATIC_ROOT, STATICFILES_STORAGE, middleware order), Dockerfile collectstatic step, `.dockerignore`/`.gitignore` exclusion, dev parity smoke (runserver DEBUG=True dalej działa). Claude scaffolds RED test (e.g. `/static/admin/css/base.css` returns 200 z content przez Django test client) + PR review. |
| **D51** | [#163](https://github.com/bgozlinski/tibiantis-scraper/issues/163) | `fix/163-database-url-dry` | `refactor(settings)` | `config/settings/prod.py` constructs DATABASES z `POSTGRES_*` vars, `.env.example` update (remove DATABASE_URL, add POSTGRES_HOST/PORT), audit per #163 triage checklist (Celery, dev.py, ci.yml, runbook §4.3+§9.12). Claude scaffolds RED test (settings shape) + audit grep validation w PR review. |
| **D52** | (milestone close) | `docs/m10-close` | `docs(progress)` | **Re-deploy na Hetzner VM** (`docker compose pull && up -d`), smoke verify 4 DoD criteria (patrz §4), prod dedupe verification dla #164 (psql query: no LOWER(name) collisions), `PROGRESS.md` M10 retro section, close M10 milestone na GitHub. |

### Branch lifecycle

Każdy fix branch:
1. Open from `master` (D49 already opened off master)
2. Claude scaffolds failing tests, commit pierwszy
3. Dev implementuje GREEN, commit/commits
4. PR open → CI → Claude review → squash merge
5. Branch auto-delete (per repo settings)
6. Local cleanup: `git switch master && git pull && git branch -D fix/...`

---

## §3 Cross-cutting concerns

### 3.1 Data migration dla #164

Prod state na 2026-05-16: M9.5-D47 smoke utworzyło duplicate rows (`Akrutki` i `akrutki`). Migration musi:

1. **Find collisions** — `SELECT LOWER(name), COUNT(*), ARRAY_AGG(id) FROM characters_character GROUP BY LOWER(name) HAVING COUNT(*) > 1`
2. **Pick winner per group** — heuristic: row z highest `level` (more recently scraped, więcej info). Tie-breaker: lowest `id` (created first).
3. **Relink `BedmageWatch.character_id`** loser → winner (UPDATE).
4. **Delete loser rows** (DELETE FROM characters_character WHERE id IN (losers)).
5. **Rename winner do canonical form** — UPDATE z explicit canonical value (`UPDATE … SET name = INITCAP(LOWER(name))` lub Python equivalent w `RunPython`), nie poleganie na `save()` ORM-side (migration code działa na historical model snapshot, save() override może nie być available).

Migration ordering (CRITICAL — dwa pliki w `apps/characters/migrations/`):

- **Krok kod (NIE migration):** dorzucenie `Character.save()` canonicalization override + `Meta.constraints = [UniqueConstraint(Lower("name"))]` w `apps/characters/models.py`. To trigger'uje Django do auto-wygenerowania schema migration przez `makemigrations`.
- **Migration X (`RunPython`, **manually written**):** dedupe (kroki 1-5 powyżej). Musi runnąć **przed** schema migration. Idempotent (kolejne run = no-op).
- **Migration Y (schema, **auto-generated by `makemigrations`**):** dodanie `UniqueConstraint(Lower("name"))` w DB. Failed jeśli X nie odpalił first — duplicates trigger constraint violation podczas CREATE UNIQUE INDEX.

Praktyczna kolejność tworzenia w PR:
1. Edit `models.py` (save() override + Meta.constraints)
2. `makemigrations` → generuje Y
3. Manually create X w numerze niższym niż Y (lub Y depends_on X explicitly)
4. Verify `python manage.py sqlmigrate characters X` + `Y` w correct order
5. Test on local DB z fixturami reflecting prod state

Pre-deploy dry-run: developer testuje migration na local DB z fixturami reflecting prod state (Akrutki + akrutki rows). PR description ma psql snippet do verify w prod post-deploy.

### 3.2 Re-deploy timing

**Single re-deploy w D52**, po wszystkich 3 PR-ach merged. Każdy PR ma własny CI run (lint + test + coverage) jako per-merge gate; prod-state confirmation jest centralized at close.

Ryzyko: jeśli PR #2 łamie observable behavior z PR #1 w prod, nie wykrywamy do D52. Mitygacja: każdy PR ma sekcję "## Smoke checklist" w body — dev odpala lokalnie przeciw `docker-compose.dev.yml` przed merge. D52 re-deploy = verification, nie discovery.

Pre-deploy backup (CRITICAL dla #164 migration):
```bash
ssh deploy@<vm-ip>
cd /opt/tibiantis
docker compose exec postgres pg_dump -U tibiantis tibiantis > ~/pre-m10-$(date +%Y%m%d).sql
```

Recovery jeśli migration psuje data:
```bash
docker compose down
docker volume rm tibantis-scraper_postgres_data
docker compose up -d postgres
cat ~/pre-m10-*.sql | docker compose exec -T postgres psql -U tibiantis tibiantis
docker compose up -d
```

### 3.3 Test scaffolding pattern (Claude role)

Claude kontynuuje RED-tests-first pattern zaczęty dla #164:
1. Open branch off master.
2. Read existing code (models, services, settings, tests).
3. Write failing tests committed first jako standalone commit (`test(scope): scaffold ...`).
4. Run tests locally, verify wszystkie fail dla correct reason (feature missing, nie typo/import error).
5. Push branch, hand off do dev.
6. Po dev's implementation PR — Claude robi review (per `code-review` skill), dorzuca dodatkowe integration testy jeśli widzi gaps.

Per-issue test scaffolds (planowane):

| Issue | RED test highlights |
|---|---|
| #164 ✅ already done | 10 tests across 3 files: canonicalization (lowercase, mixed case, whitespace, update path), case-insensitive unique via save(), DB functional index via bulk_create bypass, upsert idempotency, bedmage add/remove case-insensitivity |
| #162 | `/static/admin/css/base.css` returns 200 z content via Django test client (DEBUG=False, w-staticfiles-collected scenario); whitenoise middleware placement test |
| #163 | Settings shape test — `DATABASES["default"]` constructed z `POSTGRES_*` env vars, no `DATABASE_URL` import path remains w `config/`, `apps/`, `scrapers/`, `discord_bot/` |

### 3.4 Dev parity decisions (locked)

| Issue | Decyzja | Powód |
|---|---|---|
| #162 | Dev i prod oba przez whitenoise; w DEBUG=True Django's `staticfiles` app override'uje (default behavior). Verify `runserver` z DEBUG=True dalej serwuje admin. | Zero env shape drift, jeden codepath |
| #163 | **Option A — unify**: dev `.env` też reads individual `POSTGRES_*` vars (USER, PASSWORD, DB, HOST, PORT). | Jedna env shape across local/CI/prod, no surprises. Cost: jednorazowy update lokalnego `.env`. |
| #164 | `_canonicalize_name(s) = s.strip()[0].upper() + s.strip()[1:].lower()` (explicit, **nie** `.capitalize()`). | `.capitalize()` lowercases internal letters jako side effect — Tibia names dziś ASCII, ale explicit primitive jest łatwiejszy do testowania + future-proof |

---

## §4 Definition of Done

Wszystkie cztery wymagane — milestone NIE zamknięty dopóki każdy spełniony:

### 4.1 All 3 issue PRs merged + CI green

- #164 PR merged do master, milestone link visible w PR body
- #162 PR merged do master
- #163 PR merged do master
- Po każdym merge: `ci.yml` workflow green (lint job + test job)
- Coverage threshold ≥ 70% utrzymany (`pytest --cov-fail-under=70` w `ci.yml`)

### 4.2 Re-deploy na Hetzner VM + smoke verify

Wykonane na D52, dokumentowane w retro section:

```bash
# SSH access
ssh deploy@<vm-ip>
cd /opt/tibiantis

# Pre-deploy backup (3.2)
docker compose exec postgres pg_dump -U tibiantis tibiantis > ~/pre-m10-$(date +%Y%m%d).sql

# Update .env per #163 changes (remove DATABASE_URL, add POSTGRES_HOST=postgres POSTGRES_PORT=5432)
nano .env

# Deploy
docker compose pull
docker compose up -d

# Smoke verify (4 checks, all must pass):
# (a) /admin/ via SSH tunnel — fully styled
ssh -L 8000:localhost:8000 deploy@<vm-ip>
# → przeglądarka: http://localhost:8000/admin/ pokazuje pełen Django admin theme

# (b) .env hygiene
grep DATABASE_URL /opt/tibiantis/.env  # → no output (line removed)

# (c) Discord bedmage case-insensitive (w dev guild)
# /bedmage add Akrutki  → success
# /bedmage add akrutki  → error "already exists"
# /bedmage list         → 1 entry only

# (d) #164 dedupe in DB (per §4.3 below)
```

### 4.3 Prod data dedupe verified dla #164

```sql
-- Powinno zwrócić 0 wierszy (każdy LOWER(name) unikalny):
SELECT LOWER(name) AS canonical, COUNT(*) AS dupes
FROM characters_character
GROUP BY LOWER(name)
HAVING COUNT(*) > 1;

-- Wszystkie BedmageWatch.character_id wskazują na valid canonical row:
SELECT bw.id, bw.character_id, c.name
FROM bedmages_bedmagewatch bw
LEFT JOIN characters_character c ON bw.character_id = c.id
WHERE c.id IS NULL;
-- → 0 rows (no orphan FKs)
```

### 4.4 Retro + PROGRESS close PR merged

D52 PR z message `docs(progress): close M10 — Hardening COMPLETED + retro D49-D52` zawiera:
- Sekcja "M10 — Hardening" w `PROGRESS.md` (mirror M9/M9.5 close pattern)
- Per-day retro entries (D49/D50/D51/D52)
- "Lessons learned" — niespodzianki, traps avoided, tech debt zidentyfikowany
- "Carry-over do M10.5/M11" — lista (patrz §6)
- M10 milestone closed na GitHub (manual `gh api -X PATCH /repos/.../milestones/<id> -f state=closed`)

---

## §5 Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| #164 data migration corrupts prod data | Low | High | Pre-deploy `pg_dump` backup (§3.2). Dry-run migration na local DB z fixturami reflecting prod state. Migration `RunPython` używa `transaction.atomic()` — wszystko-albo-nic. |
| #163 settings refactor breaks Celery worker/beat DB connection | Medium | High | Audit grep checklist z #163 triage comment (Celery, dev.py, ci.yml, runbook). CI `test` job exercises full stack pre-merge. Post-deploy smoke: `docker compose logs celery_worker | grep -i "error\|operationalerror"`. |
| #162 whitenoise breaks `runserver` w DEBUG=True | Low | Medium | Dev parity verify pre-merge: lokalny `runserver` → admin fully styled. Fallback: `WHITENOISE_USE_FINDERS = True` w dev settings (zostawia Django staticfiles dla dev, whitenoise tylko w prod). |
| Re-deploy na D52 odkrywa unknown M10 regression | Medium | Medium | Każdy PR ma "## Smoke checklist" w body — dev odpala przeciw `docker-compose.dev.yml` przed merge. CI exercises postgres + redis + mongo + migrate. D52 deploy = verification, nie discovery. |
| Pre-commit autoupdate intervention podczas M10 | Low | Low | Trzymać autoupdate w osobnym PR (CLAUDE.md §11 + §15 punkt 12). Jeśli któryś hook breaks w trakcie M10, fix inline w danym PR-ze, autoupdate odkładamy do post-M10. |
| Scope creep do innych Hardening candidates | Medium | Medium | Lock'd przez sekcję §6 (Out of scope). Jeśli dev/Claude znajdują dodatkowy bug w trakcie M10, filing nowego issue + label `M10.5-candidate` lub `M11-candidate`, **nie** dorzucenie do current PR. |

---

## §6 Poza zakresem M10 (deferred)

Wszystkie poniższe to legit Hardening candidates ze M9.5 retro / brainstorm, świadomie wyłączone z M10 żeby trzymać scope tight. Każdy będzie addressed w przyszłym milestone.

### M10.5 — kandydaci (lightweight, mogą trafić razem)

- **Image scanning w `docker.yml`** — Trivy / Snyk / Docker Scout step przed push, fail na high/critical CVEs
- **`DJANGO_ALLOWED_HOSTS` hygiene** — CLAUDE.md addendum dla internal-caller hostnames (web, nginx, blackbox-exporter)
- **fail2ban + unattended-upgrades** — VM-level polish (bootstrap.sh extension)
- **Pre-commit autoupdate** — osobny PR per CLAUDE.md §15 punkt 12

### M11 — kandydaci (potrzebne design effort)

- **Postgres backups → S3-compatible** (Backblaze B2 / Hetzner Object Storage / Wasabi) — wymaga decyzji o retention, encryption, restore drill cadence
- **`docker compose pull` cron na VM** — auto-update post master push, paired z observability/alerting (Kuma notification gdy pull fails / image old)
- **Discord bot Mongo heartbeat + Kuma monitor #5** — wymaga app code change (bot pisze heartbeat doc do mongo co N sec, Kuma scrape'uje)
- **`celery_beat` pidfile race** — `celery status` per-worker ping zamiast pidfile

### M-future (osobne milestones, znacząca scope)

- **TLS + DNS subdomain** — Caddy w docker-compose + Let's Encrypt + Hetzner Cloud DNS subdomain. Wymaga DNS provider integration + Cloud Firewall config (80/443 open).
- **GHA auto-deploy job** — SSH na Hetzner po master push, `docker compose pull && up -d`. Wymaga secrets HETZNER_HOST/USER/SSH_KEY.
- **Multi-arch builds** — `linux/amd64,linux/arm64` w build-push-action. YAGNI dopóki single deploy target.
- **VM-level logs aggregation** — Loki + Promtail lub Grafana Cloud. Aktualnie `docker logs` na żądanie wystarcza.
- **Multi-environment** (staging + prod) — wymaga drugiej VM lub namespace strategy

---

## §7 Decyzje zaakceptowane (audit trail)

Zaakceptowane przez developera 2026-05-16 w sesji M10 brainstorm:

1. **Scope** — tylko 3 issues (#162, #163, #164), no broadening do innych Hardening candidates
2. **Order** — 164 → 162 → 163 (rationale: stop data-corruption bleed first, then quick whitenoise win, careful DB refactor last)
3. **PR cadence** — 1 PR per issue (3 PRs + 1 close PR = 4 days D49-D52)
4. **DoD** — 4 criteria (PRs+CI, re-deploy+smoke, prod dedupe, retro+close PR)
5. **Re-deploy timing** — single deploy w D52 po wszystkich 3 merged
6. **#163 dev parity** — Option A (unify dev/prod env shape)
7. **#164 canonicalization primitive** — `_canonicalize_name` explicit (nie `.capitalize()`)
8. **#164 DB-level unique** — `UniqueConstraint(Lower("name"))` jako belt-and-suspenders against bulk_create/RunPython bypass

---

## §8 Linki

- Issue #164: https://github.com/bgozlinski/tibiantis-scraper/issues/164
- Issue #162: https://github.com/bgozlinski/tibiantis-scraper/issues/162
- Issue #163: https://github.com/bgozlinski/tibiantis-scraper/issues/163
- M9.5 close PR (immediate predecessor): #166
- M9.5 retro section in PROGRESS.md — origin of M10 candidates
- D49 RED test scaffold commit: `1b5b7b2` on `fix/164-bedmage-case-insensitive`
