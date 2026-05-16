# M10 — Hardening — Implementation plan

> **For agentic workers:** This plan is **NOT** for autonomous agent execution. Per project workflow ([`memory/project_workflow.md`](../../../memory/project_workflow.md)), the developer writes implementation code by hand; Claude scaffolds RED tests, reviews PRs, and writes the close-out retro. Each task below carries an explicit owner tag (`[Claude]` or `[Dev]`). Steps use checkbox (`- [ ]`) syntax so the dev can mark them off as work progresses.

**Goal:** Close 3 post-deploy bugs (#162, #163, #164) surfaced during M9.5-D47 Hetzner first prod deploy, re-deploy to VM, verify, and close M10.

**Architecture:** 1 day = 1 GitHub issue = 1 PR. Order: 164 → 162 → 163 → close. Each PR is independently reviewable and revertible. Single re-deploy on D52 after all three PRs land on master.

**Tech Stack:** Django 6.0, PostgreSQL 16, whitenoise (new dep in D50), Poetry 2.x, pytest-django, pre-commit, GitHub Actions CI, Docker compose (dev + prod), Hetzner CX22 VM.

**Data:** 2026-05-16
**Spec:** [`docs/superpowers/specs/2026-05-16-m10-hardening-design.md`](../specs/2026-05-16-m10-hardening-design.md)
**Status:** READY (spec accepted by developer 2026-05-16 in M10 brainstorm session)

---

## Źródła

- **CLAUDE.md** §3 (struktura katalogów — tests live in top-level `tests/unit/<app>/`, not `apps/<app>/tests/`), §11 (Conventional Commits, ruff format, mypy strict on `apps/`, coverage ≥ 70%), §12 (pre-commit hooks must pass, no `--no-verify`), §15 (Claude reguły: not changing tech stack, services not models, no live-site hits in tests, secrets via .env).
- **Design spec M10** §3.1 (data migration ordering for #164), §3.3 (RED-tests-first pattern), §3.4 (locked design decisions per issue), §4 (DoD), §5 (risks).
- **Precedensy z M0-M9.5:**
  - **M5 (bedmage tracker)** — pattern for `apps/bedmages/services.py` tests (fixtures `user`, `character`, `@pytest.mark.django_db`). M10-D49 extends `test_services.py` in this style.
  - **M8-D40 (notifications PR)** — pattern for data migrations: `RunPython` with `reverse_code=migrations.RunPython.noop`, idempotent via `if Character.objects.filter(...).exists()` guard. M10-D49 data migration follows.
  - **M9-D43 (Dockerfile multi-stage)** — collectstatic step lands between source COPY and final stage. M10-D50 inserts the new RUN line per that pattern.
  - **M9-D41 (`/health/` endpoint)** — Django test client patterns for status-code + content assertions. M10-D50 reuses for `/static/admin/css/base.css` 200 test.
  - **M9.5-D48 (carry-over consolidation pattern)** — close PR adds retro section to `PROGRESS.md`, then `gh api -X PATCH` to close milestone. M10-D52 repeats.
  - **Conventional commit scope underscore** — `docs(m9_5):` NOT `docs(m9.5):`. M10 uses `m10` (no dot, no underscore issue).
  - **`fix/164-bedmage-case-insensitive` RED scaffold** — commit `1b5b7b2` already on branch. D49 picks up from this commit.

---

## Pre-flight checklist (przed startem D49 GREEN phase)

- [ ] **Dev postgres up locally** — `docker compose -f docker-compose.dev.yml up -d postgres` (port 5435). Used for migration dry-runs and pytest.
- [ ] **Local `.env` has working DB connection** — either `DATABASE_URL=postgres://tibiantis:tibiantis@localhost:5435/tibiantis` for the duration of M10 work (current `.env` points at `host=postgres` which is docker-internal). After D51 lands, `.env` shape changes to individual `POSTGRES_*` vars per #163 fix.
- [ ] **Branch `fix/164-bedmage-case-insensitive` checked out + up to date with origin** — `git switch fix/164-bedmage-case-insensitive && git pull`. RED test commit `1b5b7b2` already pushed.
- [ ] **`pre-commit install` done** — `poetry run pre-commit install && poetry run pre-commit install --hook-type commit-msg`. New devs may need this.
- [ ] **`pre-commit clean` if any cache weirdness** — per CLAUDE.md §11/15 mypy cache trap.
- [ ] **`gh` CLI authenticated** — `gh auth status` confirms. Needed for D52 milestone close (`gh api -X PATCH …`).
- [ ] **Hetzner SSH access works** — `ssh deploy@<vm-ip>` reaches VM. Needed for D52 re-deploy.
- [ ] **M10 milestone exists on GitHub** — already confirmed in spec.

---

## Otwarte pytania (rozstrzygnięte 2026-05-16 w spec §7)

All 8 decisions accepted per spec §7. No open design questions enter D49.

1. ✅ Scope = 3 issues only
2. ✅ Order 164 → 162 → 163
3. ✅ 1 PR per issue + 1 close PR (D49-D52)
4. ✅ DoD = 4 criteria (PRs+CI, re-deploy+smoke, prod dedupe, retro+close)
5. ✅ Single re-deploy on D52
6. ✅ #163 dev parity = Option A (unify dev/prod env shape)
7. ✅ #164 canonicalization = explicit `_canonicalize_name`, NOT `.capitalize()`
8. ✅ #164 unique constraint = DB-level functional index on `LOWER(name)`

---

## Risk + mitigation (mirror spec §5, expanded with per-task triggers)

| Ryzyko | Where it bites | Mitigation |
|---|---|---|
| Data migration for #164 corrupts prod data | D49 migration push, D52 re-deploy | Local dry-run on dev DB with fixture rows mirroring prod (D49 task 4). Pre-deploy `pg_dump` backup (D52 task 1). |
| #163 settings refactor breaks Celery worker DB connection | D51 implementation | Pre-merge grep checklist (D51 task 3). CI exercises full stack. Local `docker compose up celery_worker` smoke (D51 task 7). |
| whitenoise breaks `runserver` in DEBUG=True | D50 implementation | Local `runserver` dev parity check (D50 task 6) before PR. Fallback: `WHITENOISE_USE_FINDERS = True`. |
| Re-deploy on D52 surfaces unknown regression | D52 smoke verify | Per-PR local smoke checklist (D49/D50/D51 each include local `docker compose up` verification). D52 = verification not discovery. |
| Pre-commit autoupdate intervention during M10 | Any day | Keep autoupdate in separate post-M10 PR. If a hook breaks mid-M10, fix inline. |
| Scope creep | Any day | Section §6 of spec is explicit. If a new bug surfaces, file new issue with `M10.5-candidate` label, NOT into current PR. |

---

## Phase D49 — Issue #164: Character.name case-insensitive canonicalization

**Issue:** [#164](https://github.com/bgozlinski/tibiantis-scraper/issues/164)
**Branch:** `fix/164-bedmage-case-insensitive` ✅ already open, RED scaffold at `1b5b7b2`
**Spec ref:** §1 (issue scope), §3.1 (data migration ordering), §3.4 (canonicalization primitive)

### Task D49.1 — [Claude — ✅ DONE] Open branch + scaffold RED tests

Already complete. Branch opened off master, 10 failing tests committed at `1b5b7b2`, pushed to origin.

Files touched:
- `tests/unit/characters/test_character_model.py` — 6 new tests (canonicalization on save, whitespace strip, case-insensitive unique, bulk_create bypass)
- `tests/unit/characters/test_character_service.py` — 1 new test (upsert idempotency across casings)
- `tests/unit/bedmages/test_services.py` — 3 new tests (add canonicalizes, dupe casing raises, remove case-insensitive)

Verified locally: `10 failed, 23 passed in 8.39s` against dev postgres.

### Task D49.2 — [Dev] Implement `_canonicalize_name` + `Character.save()` override

**Files:**
- Modify: `apps/characters/models.py`

- [ ] **Step 1: Add the canonicalization helper at module top.**

Reference shape (dev writes actual code):
```python
def _canonicalize_name(name: str) -> str:
    s = name.strip()
    if not s:
        return s
    return s[0].upper() + s[1:].lower()
```

Explicit per spec §3.4 — NOT `str.capitalize()` (would silently lowercase internal caps).

- [ ] **Step 2: Override `Character.save()` to apply canonicalization on every save.**

The override must run on both `create` and `update` paths (not just `_state.adding`) — test `test_name_canonicalized_on_update_via_save` exercises rename via existing instance.

- [ ] **Step 3: Run the model tests, expect canonicalization-on-save tests to GREEN.**

```bash
$env:DATABASE_URL = "postgres://tibiantis:tibiantis@localhost:5435/tibiantis"
poetry run pytest tests/unit/characters/test_character_model.py -k "canonicalized" -v --no-cov
```

Expected: 4 tests pass (`lowercase_input`, `mixed_case_input`, `strips_surrounding_whitespace`, `on_update_via_save`).

Still failing after this step: `case_insensitive_via_save` (needs canonicalization in place — should now also pass), `bulk_create_bypass` (needs DB constraint, comes in next task).

### Task D49.3 — [Dev] Add `UniqueConstraint(Lower("name"))` + run `makemigrations`

**Files:**
- Modify: `apps/characters/models.py` (add `Meta.constraints`)
- Create: `apps/characters/migrations/000X_character_name_lower_unique.py` (auto-generated by makemigrations)

- [ ] **Step 1: Add `Meta.constraints` to `Character`.**

Reference shape:
```python
from django.db.models.functions import Lower

class Character(models.Model):
    # ... existing fields ...

    class Meta:
        ordering = ["-level"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="character_name_lower_unique",
            ),
        ]
```

- [ ] **Step 2: Generate the schema migration.**

```bash
poetry run python manage.py makemigrations characters
```

Expected output: creates `apps/characters/migrations/000X_*.py` (replace X with the next available number, likely `0005_*` based on existing migrations).

**IMPORTANT:** Do NOT apply this migration yet (`migrate` will fail because prod data has duplicates). The data migration in D49.4 runs first.

- [ ] **Step 3: Sanity-check the generated migration file.**

Open the generated file, verify it contains `AddConstraint` operation with `Lower("name")` — not a bare unique index on the column.

### Task D49.4 — [Dev] Write data migration to dedupe + relink

**Files:**
- Create: `apps/characters/migrations/000Y_dedupe_character_names.py` — manually written, numbered LOWER than the schema migration from D49.3

Order trick: if `makemigrations` generated `0005_character_name_lower_unique.py`, rename it to `0006_character_name_lower_unique.py` and create your data migration as `0005_dedupe_character_names.py`. Or set explicit `dependencies = [...]` in the data migration and update the schema migration's dependencies to include the data migration. The CLI command to verify order:

```bash
poetry run python manage.py showmigrations characters
```

Should show data migration `0005` before schema `0006` (or whatever numbers you settle on).

- [ ] **Step 1: Write the `RunPython` body.**

Reference shape (dev writes actual code; this is design clarity not deliverable):
```python
from django.db import migrations


def dedupe_character_names(apps, schema_editor):
    Character = apps.get_model("characters", "Character")
    BedmageWatch = apps.get_model("bedmages", "BedmageWatch")

    # Group by LOWER(name), find collisions
    from collections import defaultdict
    groups = defaultdict(list)
    for c in Character.objects.all():
        groups[c.name.lower()].append(c)

    for canonical_key, rows in groups.items():
        if len(rows) <= 1:
            continue

        # Winner heuristic: highest level (more info), tie-break lowest id
        rows.sort(key=lambda r: (-(r.level or 0), r.id))
        winner = rows[0]
        losers = rows[1:]

        loser_ids = [r.id for r in losers]
        BedmageWatch.objects.filter(character_id__in=loser_ids).update(
            character_id=winner.id
        )
        Character.objects.filter(id__in=loser_ids).delete()

        # Canonical-form rename (UPDATE, not save() — historical model)
        canonical_name = canonical_key[0].upper() + canonical_key[1:].lower() if canonical_key else canonical_key
        Character.objects.filter(id=winner.id).update(name=canonical_name)


class Migration(migrations.Migration):
    dependencies = [
        ("characters", "0004_<previous_migration_name>"),  # whatever the last one was
        ("bedmages", "0001_initial"),  # needed to use BedmageWatch
    ]

    operations = [
        migrations.RunPython(
            dedupe_character_names,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
```

Idempotency note: re-running on dedupe'd data is a no-op because `len(rows) <= 1` short-circuits every group. Safe to run twice.

- [ ] **Step 2: Verify dependencies match real predecessor migration name.**

```bash
ls apps/characters/migrations/
```

Replace `0004_<previous_migration_name>` with the actual file name (likely `0004_alter_character_house_alter_character_guild_membership.py` per M8-D40 retro — verify locally).

- [ ] **Step 3: Adjust schema migration to depend on data migration.**

Edit `0006_character_name_lower_unique.py` (the one from D49.3) — change its `dependencies` to include the data migration:

```python
dependencies = [
    ("characters", "0005_dedupe_character_names"),
]
```

- [ ] **Step 4: Verify migration plan ordering.**

```bash
poetry run python manage.py sqlmigrate characters 0005
poetry run python manage.py sqlmigrate characters 0006
```

`0005` shows raw Python (RunPython block — actually shows no SQL since RunPython is Python-side). `0006` shows `CREATE UNIQUE INDEX … ON characters_character (LOWER(name))`.

```bash
poetry run python manage.py showmigrations characters
```

Confirm order: 0001 → 0002 → 0003 → 0004 → 0005 (dedupe) → 0006 (unique).

### Task D49.5 — [Dev] Apply migrations on local dev DB (dry-run)

**Files:** none (DB state change only)

- [ ] **Step 1: Seed local DB with collision-producing fixture data.**

Start a shell:
```bash
poetry run python manage.py shell
```

```python
from apps.characters.models import Character
# Bypass save() canonicalization to reproduce prod-style collision
Character.objects.bulk_create([
    Character(name="Akrutki", level=12, vocation="Sorcerer"),
    Character(name="akrutki", level=10, vocation="Sorcerer"),
])
Character.objects.all().values_list("name", "level")
# Expect: [('Akrutki', 12), ('akrutki', 10)]
```

Note: `bulk_create` already bypasses `save()`. If your D49.3 unique constraint is already applied, this seed will fail — in that case `migrate` had already run. Reset:
```bash
poetry run python manage.py migrate characters 0004
```
…then re-seed.

- [ ] **Step 2: Run the migration.**

```bash
poetry run python manage.py migrate
```

Expected: `0005_dedupe_character_names` runs (Python code, no SQL), then `0006_character_name_lower_unique` adds the index. Both green.

- [ ] **Step 3: Verify dedupe result.**

```python
from apps.characters.models import Character
list(Character.objects.values_list("name", "level"))
# Expect: [('Akrutki', 12)]  (winner kept, loser deleted, canonical-form)
```

Verify the case-insensitive constraint is enforced:
```python
Character.objects.bulk_create([Character(name="akrutki", level=5)])
# Expect: IntegrityError — LOWER(name) collides with existing 'Akrutki'
```

### Task D49.6 — [Dev] Add `__iexact` belt-and-suspenders to services

**Files:**
- Modify: `apps/characters/services.py` (line ~16, in `upsert_character`)
- Modify: `apps/bedmages/services.py` (line ~24, `add_bedmage_watch`; line ~55, `remove_bedmage_watch`)

The `Character.save()` canonicalization in D49.2 means stored names are always canonical. Services should canonicalize the input lookup key to avoid relying on save() being called on a pre-existing row. Two ways:

1. **Use `__iexact` filter in services** — `Character.objects.filter(name__iexact=name)` matches any casing
2. **Canonicalize at service entry** — `name = _canonicalize_name(name)` before lookup

Pick one consistently. Recommendation: option 2 (canonicalize at entry). It keeps the SQL simple (`name=...` exact match works once both sides are canonical) and surfaces the canonicalization closer to the user input.

- [ ] **Step 1: Import `_canonicalize_name` in services.**

If the helper lives in `apps.characters.models`, import it:
```python
from apps.characters.models import Character, _canonicalize_name
```

(Or move it to `apps.characters.utils` if model-level imports feel wrong; either is fine.)

- [ ] **Step 2: Canonicalize at service entry.**

In `upsert_character`: after the `name` is pulled from payload, canonicalize before the `update_or_create` call.

In `add_bedmage_watch`: canonicalize `character_name` before `get_or_create`.

In `remove_bedmage_watch`: canonicalize `character_name` before the `filter(character__name=...).delete()` call.

- [ ] **Step 3: Run service tests, expect them GREEN.**

```bash
poetry run pytest tests/unit/characters/test_character_service.py tests/unit/bedmages/test_services.py -k "canonicaliz or different_casing or treats_different_casings or with_different_casing" -v --no-cov
```

Expected: 4 tests pass (`test_upsert_with_different_casing_returns_same_row`, `test_add_bedmage_watch_canonicalizes_character_name`, `test_add_bedmage_watch_treats_different_casings_as_same_character`, `test_remove_bedmage_watch_works_with_different_casing`).

### Task D49.7 — [Dev] Update 5 affected assertions in existing tests

**Files:**
- Modify: `tests/unit/bedmages/test_services.py:42` and `:49`
- Modify: `tests/unit/bedmages/test_graphql_bedmages.py:165`, `:179`, `:181`

The `"NewChar"` literals canonicalize to `"Newchar"`. The 5 assertion sites that compare against the stored name need updating.

- [ ] **Step 1: `tests/unit/bedmages/test_services.py` lines 42 + 49.**

Change both `filter(name="NewChar")` to `filter(name="Newchar")`. Document the change is intentional (post-#164 canonicalization).

- [ ] **Step 2: `tests/unit/bedmages/test_graphql_bedmages.py` lines 165, 179, 181.**

Three assertions: two `filter(name="NewChar").count()`, one `payload[...]["character"]["name"] == "NewChar"`. All become `"Newchar"`.

- [ ] **Step 3: Run the full affected test files.**

```bash
poetry run pytest tests/unit/characters/test_character_model.py tests/unit/characters/test_character_service.py tests/unit/bedmages/test_services.py tests/unit/bedmages/test_graphql_bedmages.py -v --no-cov
```

Expected: all GREEN. 33 tests passing total (23 pre-#164 + 10 new RED-now-GREEN).

### Task D49.8 — [Dev] Local smoke + open PR

- [ ] **Step 1: Run full test suite locally.**

```bash
poetry run pytest --no-cov
```

Expected: all tests pass. If anything else broke (likely none — #164 changes are well-contained), investigate before pushing.

- [ ] **Step 2: Verify pre-commit hooks pass.**

```bash
poetry run pre-commit run --all-files
```

Expected: all hooks pass. Fix any complaint inline.

- [ ] **Step 3: Commit + push.**

Suggested commit message (Conventional Commits, no Co-Authored-By per project memory):
```
fix(characters): canonicalize Character.name + DB-level case-insensitive unique (#164)

- _canonicalize_name(name) helper: strip + first-upper, rest-lower
- Character.save() override applies canonicalization on every save
- Meta.constraints adds UniqueConstraint(Lower("name")) — belt-and-suspenders
  against bulk_create / RunPython / raw SQL bypass paths
- Data migration 0005_dedupe_character_names: groups rows by LOWER(name),
  picks winner (highest level, tie-break lowest id), relinks BedmageWatch
  FKs onto winner, deletes losers, renames winner to canonical form
- Schema migration 0006_character_name_lower_unique: adds the functional
  unique index, depends on dedupe migration
- Services canonicalize at entry (upsert_character, add_bedmage_watch,
  remove_bedmage_watch) so any casing typed by the user resolves to the
  canonical row
- Updated 5 existing assertions in test_services.py and
  test_graphql_bedmages.py to match new canonical form ("NewChar" -> "Newchar")

Closes #164
```

```bash
git push -u origin fix/164-bedmage-case-insensitive
gh pr create --title "fix(characters): canonicalize Character.name + DB-level case-insensitive unique (#164)" --body "..."
```

Use the body from the issue body + your commit message. Include a "## Smoke checklist" section with:
- [ ] Local pytest green
- [ ] Local migrate runs cleanly on dev DB with duplicate rows seeded
- [ ] `/bedmage add Akrutki` then `/bedmage add akrutki` (in dev guild) raises "already exists"

### Task D49.9 — [Claude] PR review

When PR is open:
- Verify migration ordering (0005 before 0006 in `showmigrations`)
- Verify migration dependencies are correct
- Verify `_canonicalize_name` matches the locked design (`s[0].upper() + s[1:].lower()`, NOT `.capitalize()`)
- Verify the data migration's reverse_code is `noop` (no auto-undo)
- Verify services canonicalize at entry, not just rely on save()
- Check the 5 test assertion updates are correct
- Spot-check for hardcoded names that survived from "NewChar"-era

Use the `code-review:code-review` skill if useful.

### Task D49.10 — [Dev] Address review + squash merge

- [ ] Address any review comments
- [ ] Wait for CI green (lint + test jobs)
- [ ] Squash merge with PR title as commit message
- [ ] Branch auto-deletes (per repo settings)
- [ ] Local cleanup:
  ```bash
  git switch master && git pull && git branch -D fix/164-bedmage-case-insensitive
  ```

---

## Phase D50 — Issue #162: Django admin static files (whitenoise)

**Issue:** [#162](https://github.com/bgozlinski/tibiantis-scraper/issues/162)
**Branch:** `fix/162-admin-static-files`
**Spec ref:** §1 (issue scope), §3.3 (test scaffolding pattern), §3.4 (dev parity decision)

### Task D50.1 — [Dev] Create branch off latest master

```bash
git switch master && git pull
git switch -c fix/162-admin-static-files
```

### Task D50.2 — [Claude] Scaffold RED tests

**Files:**
- Modify: `tests/unit/core/test_health.py` OR create `tests/unit/web/test_static_files.py` — Claude decides during scaffold

The test must run with `DEBUG=False` to exercise the production path (Django's dev staticfiles app doesn't fire when DEBUG=False). pytest-django provides the `settings` fixture for this.

- [ ] **Step 1 [Claude]: Write the failing test for `/static/admin/css/base.css` returning 200.**

Reference test shape:
```python
import pytest
from django.test import Client, override_settings


@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_static_admin_css_served_under_debug_false() -> None:
    """In prod (DEBUG=False), gunicorn-equivalent serving of /static/admin/css/base.css
    must return 200 with non-empty body. Pre-fix: 404 because nothing serves /static/
    when DEBUG=False (Django's staticfiles app only fires in DEBUG=True). Post-fix:
    whitenoise middleware serves the collected tree.
    """
    client = Client()
    response = client.get("/static/admin/css/base.css")
    assert response.status_code == 200
    assert b"body" in response.content  # base.css contains body{} style
```

- [ ] **Step 2 [Claude]: Verify RED locally.**

```bash
$env:DATABASE_URL = "postgres://tibiantis:tibiantis@localhost:5435/tibiantis"
poetry run pytest tests/unit/web/test_static_files.py -v --no-cov
```

Expected: `404 != 200` failure (or `staticfiles` not present in `INSTALLED_APPS` warning followed by 404).

- [ ] **Step 3 [Claude]: Commit + push.**

```
test(web): scaffold failing test for admin static serving in DEBUG=False (#162)
```

### Task D50.3 — [Dev] Add whitenoise dependency

**Files:**
- Modify: `pyproject.toml` (`[tool.poetry.dependencies]`)
- Modify: `poetry.lock` (auto-regenerated)

- [ ] **Step 1: Add whitenoise as a runtime dep.**

```bash
poetry add "whitenoise@^6.7.0"
```

This updates both `pyproject.toml` and `poetry.lock`. Commit both files.

- [ ] **Step 2: Verify the addition lands in the `[tool.poetry.dependencies]` table** (not dev group).

```bash
grep -A 1 "whitenoise" pyproject.toml
```

Expected: `whitenoise = "^6.7.0"` in the runtime dependencies section.

### Task D50.4 — [Dev] Settings changes — STATIC_ROOT + middleware + storage

**Files:**
- Modify: `config/settings/base.py`

- [ ] **Step 1: Add `STATIC_ROOT` next to existing `STATIC_URL`.**

Reference shape:
```python
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
```

- [ ] **Step 2: Insert `WhiteNoiseMiddleware` immediately after `SecurityMiddleware`.**

Per whitenoise docs the placement is strict — must be the second middleware in the list (after Security, before anything else). Pre-fix MIDDLEWARE starts with `django.middleware.security.SecurityMiddleware`; insert whitenoise right after.

- [ ] **Step 3: Set `STATICFILES_STORAGE` to whitenoise's compressed manifest storage.**

Reference shape:
```python
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
```

Note: in Django 5.0+, `STATICFILES_STORAGE` is deprecated in favor of `STORAGES["staticfiles"]`. Project is Django 6.0 — use the new shape:

```python
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
```

Verify current settings to see if `STORAGES` is already declared; if so, only override `staticfiles` key.

### Task D50.5 — [Dev] Dockerfile collectstatic step

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 1: Locate the right insertion point.**

In the final stage (where source is COPYed and the runtime user is set), add a `RUN python manage.py collectstatic --noinput` line **after** the source COPY but **before** the final `USER app` switch. Static files are output to `STATIC_ROOT` (per D50.4 = `/app/staticfiles`).

Reference shape (Dockerfile fragment):
```dockerfile
COPY . /app
RUN python manage.py collectstatic --noinput
USER app
```

Verify by checking the existing Dockerfile structure — M9-D42 spec describes the multi-stage layout.

- [ ] **Step 2: Verify build works locally.**

```bash
docker build -t tibiantis:m10-d50 .
```

Expected: build succeeds, `collectstatic` step shows "N static files copied to '/app/staticfiles'."

### Task D50.6 — [Dev] `.dockerignore` + `.gitignore` exclusion

**Files:**
- Modify: `.dockerignore`
- Modify: `.gitignore`

Add `staticfiles/` to both so dev-local `collectstatic` runs don't leak into the image build context or git.

- [ ] **Step 1: Edit `.dockerignore`.**

Add `staticfiles/` to the list (alphabetical position).

- [ ] **Step 2: Edit `.gitignore`.**

Add `staticfiles/`.

### Task D50.7 — [Dev] Dev parity verification

- [ ] **Step 1: Verify `runserver` in DEBUG=True still serves admin.**

```bash
poetry run python manage.py runserver
```

Open `http://localhost:8000/admin/` in browser. Expected: full Django admin theme renders (Django's `staticfiles` app serves dev assets when DEBUG=True, whitenoise stays out of the way per the design decision in spec §3.4).

If the admin renders unstyled in DEBUG=True, the fallback is `WHITENOISE_USE_FINDERS = True` in `config/settings/dev.py`. Add it only if needed.

### Task D50.8 — [Dev] Run RED tests, expect GREEN

```bash
$env:DATABASE_URL = "postgres://tibiantis:tibiantis@localhost:5435/tibiantis"
poetry run python manage.py collectstatic --noinput
poetry run pytest tests/unit/web/test_static_files.py -v --no-cov
```

Expected: previously-RED test now GREEN. (collectstatic must run first so the file exists in `STATIC_ROOT` for whitenoise to serve in tests.)

### Task D50.9 — [Dev] Full test suite + smoke + PR

- [ ] **Step 1: Full pytest.**

```bash
poetry run pytest --no-cov
```

- [ ] **Step 2: Pre-commit.**

```bash
poetry run pre-commit run --all-files
```

- [ ] **Step 3: Docker compose smoke (optional but recommended).**

```bash
docker compose build web
docker compose up -d
# Open SSH-tunnel-style locally: just hit http://localhost:8000/admin/
docker compose down
```

Expected: admin renders fully styled in the locally-built prod image.

- [ ] **Step 4: Commit + push + open PR.**

Suggested commit:
```
fix(web): serve Django admin static via whitenoise + collectstatic in image (#162)

- Add whitenoise ^6.7.0 runtime dep
- STATIC_ROOT, WhiteNoiseMiddleware (after SecurityMiddleware),
  STORAGES["staticfiles"] = CompressedManifestStaticFilesStorage in base.py
- Dockerfile: RUN python manage.py collectstatic --noinput in final
  stage between source COPY and USER switch
- .dockerignore + .gitignore: exclude staticfiles/ build artifact
- Dev parity verified: runserver in DEBUG=True still serves admin
  via Django staticfiles app (whitenoise stays out of the way)

Closes #162
```

### Task D50.10 — [Claude] PR review

- Verify middleware placement (whitenoise immediately after SecurityMiddleware, not later)
- Verify `STORAGES` shape (Django 6 style) used, not legacy `STATICFILES_STORAGE`
- Verify Dockerfile collectstatic step lands in the right stage
- Spot-check `.dockerignore` exclusion is present
- Confirm dev parity smoke ran (browser screenshot or written confirmation in PR body)

### Task D50.11 — [Dev] Address review + squash merge

- [ ] Address review comments
- [ ] CI green
- [ ] Squash merge
- [ ] Local cleanup: `git switch master && git pull && git branch -D fix/162-admin-static-files`

---

## Phase D51 — Issue #163: DATABASE_URL DRY refactor

**Issue:** [#163](https://github.com/bgozlinski/tibiantis-scraper/issues/163)
**Branch:** `fix/163-database-url-dry`
**Spec ref:** §1 (issue scope), §3.4 (dev parity = Option A unify)

### Task D51.1 — [Dev] Create branch off latest master

```bash
git switch master && git pull
git switch -c fix/163-database-url-dry
```

### Task D51.2 — [Claude] Audit + scaffold RED tests

**Files:**
- Modify: `tests/unit/core/test_settings.py` OR create — Claude decides during scaffold

- [ ] **Step 1 [Claude]: Run the audit grep checklist** (from #163 triage comment):

```bash
grep -rn "DATABASE_URL\|env.db()" config/ apps/ scrapers/ discord_bot/ .github/
```

Report findings as a comment on PR or as a `# AUDIT` block in the test file. Expected sites: `config/settings/base.py` (or dev/prod), `.github/workflows/ci.yml`, possibly `config/celery.py`.

- [ ] **Step 2 [Claude]: Write RED test for DATABASES["default"] shape.**

Reference shape:
```python
import pytest
from django.conf import settings


def test_databases_constructed_from_postgres_env_vars(monkeypatch) -> None:
    """After #163, prod settings construct DATABASES from individual POSTGRES_*
    env vars (USER, PASSWORD, DB, HOST, PORT) — no DATABASE_URL import path
    remains in config/settings/prod.py. This test reads the constructed config
    and verifies the shape (engine + named env vars present).
    """
    db = settings.DATABASES["default"]
    assert db["ENGINE"] == "django.db.backends.postgresql"
    assert db["NAME"] == "tibiantis"  # or whatever default is in env
    assert db["USER"] == "tibiantis"
    assert db["HOST"] in ("postgres", "localhost", "127.0.0.1")  # depends on env
    assert "PASSWORD" in db
    assert int(db["PORT"]) == 5432 or int(db["PORT"]) == 5435  # dev or prod
```

Note: this test depends on what env you run it in. May need `monkeypatch.setenv(...)` to control. Claude refines during scaffold.

- [ ] **Step 3 [Claude]: Verify RED.**

Run pytest, expect failure (current prod.py likely uses `env.db()` parsing `DATABASE_URL`, not constructing from individual vars).

### Task D51.3 — [Dev] Refactor `config/settings/prod.py` to construct DATABASES

**Files:**
- Modify: `config/settings/prod.py`
- (possibly) Modify: `config/settings/base.py` if DATABASES is declared there

- [ ] **Step 1: Determine where DATABASES is currently declared.**

```bash
grep -n "DATABASES" config/settings/*.py
```

- [ ] **Step 2: Refactor.**

Reference shape (per #163 issue body):
```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST", default="postgres"),
        "PORT": env.int("POSTGRES_PORT", default=5432),
    }
}
```

Per spec §3.4 decision (Option A): apply this to BOTH `base.py` (default) and let `dev.py`/`prod.py` inherit. Single shape across environments.

- [ ] **Step 3: Remove any `env.db()` or `env("DATABASE_URL")` references.**

### Task D51.4 — [Dev] Update `.env.example`

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Remove the `DATABASE_URL=` line.**

- [ ] **Step 2: Add `POSTGRES_HOST=postgres` and `POSTGRES_PORT=5432` lines.**

Reference shape:
```
POSTGRES_USER=tibiantis
POSTGRES_PASSWORD=tibiantis
POSTGRES_DB=tibiantis
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
# DATABASE_URL removed — DATABASES constructed in settings from POSTGRES_* vars
```

The comment explains the removal so a future operator doesn't look for the missing line.

### Task D51.5 — [Dev] Update local `.env`

**Files:**
- Modify: `.env` (NOT committed, dev-local)

- [ ] **Step 1: Mirror the `.env.example` shape.**

For local dev (postgres in `docker-compose.dev.yml` on port 5435):
```
POSTGRES_USER=tibiantis
POSTGRES_PASSWORD=tibiantis
POSTGRES_DB=tibiantis
POSTGRES_HOST=localhost
POSTGRES_PORT=5435
```

Note: `POSTGRES_HOST=localhost` and `POSTGRES_PORT=5435` for laptop pytest. The same `.env` shape (with different values) is used on the Hetzner VM where `HOST=postgres` and `PORT=5432`.

### Task D51.6 — [Dev] Update CI `.github/workflows/ci.yml`

**Files:**
- Modify: `.github/workflows/ci.yml`

Pre-fix the workflow sets `DATABASE_URL: postgres://postgres:postgres@localhost:5432/tibiantis_test`. After #163 this won't be read — but the workflow needs the new env shape.

- [ ] **Step 1: Replace the env block in the `test:` job.**

Reference shape:
```yaml
env:
  POSTGRES_USER: postgres
  POSTGRES_PASSWORD: postgres
  POSTGRES_DB: tibiantis_test
  POSTGRES_HOST: localhost
  POSTGRES_PORT: 5432
  # ... other vars unchanged ...
```

Verify the `services.postgres` block uses the same `POSTGRES_USER/PASSWORD/DB` (yes, it does, per existing workflow).

### Task D51.7 — [Dev] Update `docs/deploy-runbook.md`

**Files:**
- Modify: `docs/deploy-runbook.md` §4.3 + §9.12

- [ ] **Step 1: Remove the "passwords must match" warning in §4.3.**

Pre-fix, §4.3 tells operators to update `POSTGRES_PASSWORD` AND `DATABASE_URL`. Post-fix, only one place to update. Update the wording.

- [ ] **Step 2: Update §9.12 (likely the troubleshooting section about psycopg.OperationalError).**

Remove the "did you update DATABASE_URL too?" recovery step since the duplication no longer exists.

### Task D51.8 — [Dev] Full smoke

- [ ] **Step 1: Local pytest.**

```bash
poetry run pytest --no-cov
```

Expected: all green. The RED test from D51.2 should now PASS.

- [ ] **Step 2: docker compose dev smoke.**

```bash
docker compose -f docker-compose.dev.yml up -d
poetry run python manage.py migrate
poetry run python manage.py runserver
# hit /health/ in browser, verify DB ping returns OK
```

- [ ] **Step 3: Pre-commit.**

```bash
poetry run pre-commit run --all-files
```

### Task D51.9 — [Dev] Commit + PR

Suggested commit:
```
refactor(settings): construct DATABASES from POSTGRES_* env vars, drop DATABASE_URL (#163)

- config/settings/base.py: DATABASES["default"] built from individual
  POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB / POSTGRES_HOST / POSTGRES_PORT
  env vars (Option A — unified shape across dev/prod per M10 spec §3.4)
- .env.example: remove DATABASE_URL line, add POSTGRES_HOST + POSTGRES_PORT
- .github/workflows/ci.yml: replace DATABASE_URL env with POSTGRES_* vars
  (service block already used POSTGRES_USER/PASSWORD/DB)
- docs/deploy-runbook.md §4.3 + §9.12: remove "passwords must match"
  operator warning (no more duplication to keep in sync)

Closes #163
```

### Task D51.10 — [Claude] PR review

- Verify no `DATABASE_URL` or `env.db()` references remain anywhere in `config/`, `apps/`, `scrapers/`, `discord_bot/`, `.github/`, `docs/`
- Verify CI workflow's `services.postgres` block matches the new env shape
- Verify runbook updates remove the warning, don't leave half-edits
- Verify all 4 docker-compose services that depend on DB (web, celery_worker, celery_beat, migrate) still connect — local smoke confirmation in PR body

### Task D51.11 — [Dev] Address review + squash merge

- [ ] CI green
- [ ] Squash merge
- [ ] Local cleanup: `git switch master && git pull && git branch -D fix/163-database-url-dry`

---

## Phase D52 — Milestone close: re-deploy, smoke, retro

**Branch:** `docs/m10-close` (off master, after all 3 PRs merged)
**Spec ref:** §3.2 (re-deploy timing), §4 (DoD checklist), §4.4 (retro section)

### Task D52.1 — [Dev] Pre-deploy backup

- [ ] **Step 1: SSH to VM.**

```bash
ssh deploy@<vm-ip>
cd /opt/tibiantis
```

- [ ] **Step 2: Backup postgres data volume to a SQL dump.**

```bash
docker compose exec postgres pg_dump -U tibiantis tibiantis > ~/pre-m10-$(date +%Y%m%d).sql
ls -lh ~/pre-m10-*.sql
```

Expected: file size ~MB-scale, NOT 0 bytes. Keep this file on the VM for 7 days minimum (rollback window).

### Task D52.2 — [Dev] Update `.env` per #163 changes

- [ ] **Step 1: Edit `.env` on VM.**

Remove `DATABASE_URL=...` line. Add `POSTGRES_HOST=postgres` and `POSTGRES_PORT=5432` (prod values).

```bash
nano /opt/tibiantis/.env
```

- [ ] **Step 2: Verify file mode 600.**

```bash
ls -l /opt/tibiantis/.env
```

Expected: `-rw------- 1 deploy deploy ... .env`.

### Task D52.3 — [Dev] Deploy

- [ ] **Step 1: Pull new image.**

```bash
docker compose pull
```

Expected: web/celery_worker/celery_beat/discord_bot/migrate all pull the new image (same image, multiple service refs).

- [ ] **Step 2: Apply migrations + start services.**

```bash
docker compose up -d
```

Expected: migrate exits 0 (data + schema migrations from D49 run cleanly), all services come up healthy.

- [ ] **Step 3: Watch logs for errors during startup.**

```bash
docker compose logs -f --tail=100 web celery_worker celery_beat discord_bot
```

Watch for ~30s. Expected: no `OperationalError`, no `IntegrityError`, no `psycopg.OperationalError: password authentication failed`. Discord bot logs "Connected to gateway" or similar.

### Task D52.4 — [Dev] Smoke verify 4 DoD criteria

- [ ] **Step 1: `/admin/` fully styled (DoD §4.2 first check).**

```bash
# from laptop
ssh -L 8000:localhost:8000 deploy@<vm-ip>
```

In browser: `http://localhost:8000/admin/`. Expected: full Django admin theme renders (background colors, sidebar, fonts, etc.).

- [ ] **Step 2: `.env` hygiene (DoD §4.2 second check).**

On VM:
```bash
grep DATABASE_URL /opt/tibiantis/.env
```

Expected: no output (line removed).

- [ ] **Step 3: Discord bedmage case-insensitive (DoD §4.2 third check).**

In dev guild:
- `/bedmage add Akrutki` → success ("Added to bedmage list")
- `/bedmage add akrutki` → error ("Akrutki is already on your bedmage list" or similar)
- `/bedmage list` → 1 entry only

- [ ] **Step 4: Prod data dedupe (DoD §4.3).**

On VM:
```bash
docker compose exec postgres psql -U tibiantis -d tibiantis -c "
  SELECT LOWER(name), COUNT(*) AS dupes
  FROM characters_character
  GROUP BY LOWER(name)
  HAVING COUNT(*) > 1;
"
```

Expected: 0 rows.

```bash
docker compose exec postgres psql -U tibiantis -d tibiantis -c "
  SELECT bw.id, bw.character_id, c.name
  FROM bedmages_bedmagewatch bw
  LEFT JOIN characters_character c ON bw.character_id = c.id
  WHERE c.id IS NULL;
"
```

Expected: 0 rows (no orphan FKs).

### Task D52.5 — [Claude] Write `PROGRESS.md` M10 retro section

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: Read the PR sequence + commit logs to gather retro material.**

```bash
git log master --since="2026-05-16" --pretty=format:"%h %s" | head -20
gh pr list --state merged --search "milestone:M10" --json number,title,mergedAt
```

- [ ] **Step 2: Mirror the M9 + M9.5 retro section structure.**

Section header: `## M10 — Hardening (D49-D52)` with `### Status: ✅ COMPLETED` subsection.

Required subsections (per past pattern):
- Per-day retro entries (D49/D50/D51/D52)
- "Niespodzianki / lessons learned" — what surprised during execution
- "Tech debt zidentyfikowany" — anything new found mid-M10
- "Carry-over do M10.5/M11" — items deferred (image scanning, backups, fail2ban, compose pull cron, ALLOWED_HOSTS hygiene) — copy from spec §6
- "Definition of Done M10 — ✅ wszystkie domknięte" — per-criterion checkmark with PR/commit reference

### Task D52.6 — [Dev] Commit retro + open close PR

- [ ] **Step 1: Switch to fresh master, create branch.**

```bash
git switch master && git pull
git switch -c docs/m10-close
```

- [ ] **Step 2: Commit retro changes.**

Suggested commit:
```
docs(progress): close M10 — Hardening COMPLETED + retro D49-D52

PR #<164-PR-num> — Character.name canonicalization + dedupe migration
PR #<162-PR-num> — Django admin static via whitenoise
PR #<163-PR-num> — DATABASE_URL DRY refactor

DoD criteria all green:
- 3 PRs merged, CI green
- Re-deployed to Hetzner VM, smoke verified (admin styled,
  .env clean, case-insensitive bedmage)
- Prod data deduped (psql verification, 0 LOWER(name) collisions,
  0 orphan BedmageWatch FKs)
- Retro section added

Carry-over (per spec §6): image scanning, postgres backups, fail2ban,
compose pull cron, ALLOWED_HOSTS hygiene — to M10.5 / M11.

Refs #162 #163 #164
```

- [ ] **Step 3: Push + PR.**

```bash
git push -u origin docs/m10-close
gh pr create --title "docs(progress): close M10 — Hardening COMPLETED + retro D49-D52" --body "..."
```

PR body includes the retro section preview.

### Task D52.7 — [Claude] Close PR review

Verify retro section accurately reflects what happened (vs idealized spec). If real D49/D50/D51 had any surprises, those must be captured for future-self.

### Task D52.8 — [Dev] Merge + close milestone

- [ ] **Step 1: Squash merge close PR.**

- [ ] **Step 2: Close M10 milestone on GitHub.**

```bash
gh api -X PATCH /repos/bgozlinski/tibiantis-scraper/milestones/<id> -f state=closed
```

Get the milestone ID with: `gh api /repos/bgozlinski/tibiantis-scraper/milestones --jq '.[] | select(.title=="M10 — Hardening") | .number'`.

- [ ] **Step 3: Local cleanup.**

```bash
git switch master && git pull && git branch -D docs/m10-close
```

---

## Definition of Done (per spec §4) — final checklist

- [ ] **§4.1** All 3 issue PRs merged + CI green on master
- [ ] **§4.2** Re-deploy to Hetzner VM + 4 smoke checks passed (admin styled / .env clean / case-insensitive bedmage / —)
- [ ] **§4.3** Prod data dedupe verified via psql (0 LOWER(name) collisions, 0 orphan FKs)
- [ ] **§4.4** Retro + PROGRESS close PR merged, M10 milestone closed on GitHub

Any one unchecked = milestone stays open.

---

## Self-review (writing-plans skill mandate)

**Spec coverage check:**
- Spec §1 (3 issues scope) → covered by D49/D50/D51 phases ✓
- Spec §2 (D49-D52 work breakdown) → expanded into individual tasks per phase ✓
- Spec §3.1 (data migration ordering) → D49.3 + D49.4 explicit dependencies ✓
- Spec §3.2 (re-deploy timing) → D52.1-D52.4 single-deploy sequence ✓
- Spec §3.3 (test scaffolding pattern) → D49.1 already done, D50.2 + D51.2 explicit Claude-owned tasks ✓
- Spec §3.4 (locked design decisions) → cited at point of use in each phase ✓
- Spec §4 (DoD 4 criteria) → final checklist + per-criterion verification in D52 ✓
- Spec §5 (5 risks) → risk + mitigation table in plan header ✓
- Spec §6 (out of scope) → referenced in D52.5 retro carry-over ✓
- Spec §7 (audit trail of 8 decisions) → mirrored in "Otwarte pytania" section ✓

**Placeholder scan:**
- `<vm-ip>` — operator-filled value, standard runbook style, matches M9.5 pattern ✓
- `<id>` in `gh api /milestones/<id>` — explicit retrieval command provided in D52.8 ✓
- `<164-PR-num>` etc. in close commit — operator-filled after merges, acceptable ✓
- "Reference shape (dev writes actual code)" labels — intentional, per project workflow ✓
- No "TBD" / "TODO" / "fill in details" anywhere ✓

**Type consistency check:**
- `_canonicalize_name` referenced consistently across D49.2, D49.6, D49.9 ✓
- `UniqueConstraint(Lower("name"))` consistent name `character_name_lower_unique` ✓
- Migration numbers 0005 (data) before 0006 (schema) used consistently ✓
- `STORAGES["staticfiles"]` Django-6 shape used in D50.4, NOT legacy `STATICFILES_STORAGE` ✓
- `POSTGRES_HOST` / `POSTGRES_PORT` env var names consistent across D51.3-D51.6 ✓

No gaps found.
