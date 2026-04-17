# Tibiantis Monitor — Progress

## Aktualny milestone: M0 — Bootstrap
**Status:** 2/3 dni ukończone

### Ukończone
- ✅ #1 [M0-D1] Inicjalizacja repo + GitHub + branch protection (2026-04-17) — PR [#9](https://github.com/bgozlinski/tibiantis-scraper/pull/9) — squash `d611e2a`
- ✅ #2 [M0-D2] Django 6 project + Postgres lokalnie + pierwszy runserver (2026-04-17) — PR [#10](https://github.com/bgozlinski/tibiantis-scraper/pull/10) — squash `cc89de3`

### W trakcie
_(pusto)_

### Następne
- 🔜 #3 [M0-D3] pre-commit + ruff + mypy + CI lint

### Notatki z retro
- **#1 (merge 2026-04-17):** Issue #1 wymagał drobnego fixup commita — w pierwotnym commitcie brakowało 8 wzorców z AC (`*.pyc`, `*.sqlite3`, `/staticfiles/`, `/media/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`, `.vscode/`). Wszystkie dopisane w drugim commicie. Wniosek: warto przed push przeklikać AC checklist linia po linii, żeby review nie wracał z drobnostkami.
- **#2 (merge 2026-04-17):** dwa drobne bugi złapane w lokalnym review przed pushem (`env("DJANGO_SECRET_KEY,")` z przecinkiem i `BASE_DIR = parent.parent` zamiast `parent.parent.parent` w subpackage settings). Pierwszy to literówka copy-paste, drugi — klasyczna pułapka przy rozbijaniu `settings.py` na pakiet. Wniosek: przy rozbijaniu plików sprawdzaj wszystkie ścieżki względne (`BASE_DIR`, importy, `os.environ.setdefault`).
- **Solo-repo paradox:** GitHub blokuje self-approval własnego PR, dlatego Claude nie może wciskać `--approve`, tylko zostawia komentarz LGTM. Branch protection ma `enforce_admins=false`, więc Ty mergeujesz jako admin.
- **Squash-only enforced (2026-04-17):** repo skonfigurowane tak, że UI GitHuba pokazuje tylko przycisk „Squash and merge" (`allow_merge_commit=false`, `allow_rebase_merge=false`). Zgodne ze spec §3.

### Obserwacje techniczne do adresowania w kolejnych issues
- W `config/settings/base.py` brakuje `DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'` — Django rzuci `W042` przy pierwszym modelu (Issue #4).
- `dev.py` hardcoduje `DEBUG = True` i `ALLOWED_HOSTS = ['*']`, override'ując wartości z env. Rozważ czy zmienne `DJANGO_DEBUG`/`DJANGO_ALLOWED_HOSTS` z `.env.example` mają sens dla dev — opcjonalnie usuń override lub usuń z env.example (spójność).
