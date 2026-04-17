# Tibiantis Monitor — Progress

## Aktualny milestone: M0 — Bootstrap
**Status:** 1/3 dni ukończone

### Ukończone
- ✅ #1 [M0-D1] Inicjalizacja repo + GitHub + branch protection (2026-04-17) — PR [#9](https://github.com/bgozlinski/tibiantis-scraper/pull/9) — squash `d611e2a`

### W trakcie
_(pusto)_

### Następne
- 🔜 #2 [M0-D2] Django 6 project + Postgres lokalnie + pierwszy runserver
- 🔜 #3 [M0-D3] pre-commit + ruff + mypy + CI lint

### Notatki z retro
- **#1 (merge 2026-04-17):** Issue #1 wymagał drobnego fixup commita — w pierwotnym commitcie brakowało 8 wzorców z AC (`*.pyc`, `*.sqlite3`, `/staticfiles/`, `/media/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`, `.vscode/`). Wszystkie dopisane w drugim commicie. Wniosek: warto przed push przeklikać AC checklist linia po linii, żeby review nie wracał z drobnostkami.
- **Solo-repo paradox:** GitHub blokuje self-approval własnego PR, dlatego Claude nie może wciskać `--approve`, tylko zostawia komentarz LGTM. Branch protection ma `enforce_admins=false`, więc Ty mergeujesz jako admin.
