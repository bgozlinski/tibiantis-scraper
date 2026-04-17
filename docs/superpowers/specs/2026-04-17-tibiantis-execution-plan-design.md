# Tibiantis Monitor — Execution Plan (Design)

**Data:** 2026-04-17
**Status:** approved (2026-04-17)
**Autorzy:** bgozlinski (developer), Claude (mentor)

---

## 0. Kontekst

Projekt `tibiantis-scraper` (nazwa robocza: **Tibiantis Monitor**) opisany szczegółowo w `CLAUDE.md`. Ten dokument definiuje **proces wykonania** projektu — nie co zostanie zbudowane (to już jest), tylko **jak** zostanie zbudowane: kto pisze co, w jakiej kolejności, jak trackujemy postęp, jak review'ujemy zmiany.

Dokument jest wynikiem brainstormingu z 2026-04-17 (skill `superpowers:brainstorming`).

---

## 1. Założenia kluczowe

1. **Developer:** bgozlinski. Pisze cały kod implementacji samodzielnie.
2. **Claude:** pełni rolę senior-mentora. Tworzy dzienne taski (GitHub Issues), robi code review na PR, pisze testy po zaakceptowanej implementacji, prowadzi retro po milestones.
3. **Tempo:** ~4h dziennie, 5 dni w tygodniu (zmienne).
4. **Poziom:** developer uczy się Django/Celery/Scrapy/Docker — taski muszą być szczegółowe, z celami edukacyjnymi i pułapkami. Review ma formę edukacyjną, nie tylko "popraw X".
5. **Git workflow:** każdy task = osobny branch `<type>/<issue-nr>-<slug>` → PR do `master` → code review → squash merge → następny task.
6. **Tracking:** GitHub Issues (backlog + daily tasks) + `PROGRESS.md` w repo (ludzkie źródło prawdy o stanie) + GitHub Milestones (grupowanie).

---

## 2. Role i odpowiedzialności

### Developer (bgozlinski)
- Pisze kod implementacji (models, services, views, spiders, bot, Docker).
- Tworzy branch per task, commituje małymi krokami, używa Conventional Commits.
- Otwiera PR z linkiem `Closes #<nr>` do Issue.
- Odpowiada na review — albo poprawia, albo broni decyzji argumentami.
- Mergeuje po approve + green CI.
- Korzysta z `superpowers:receiving-code-review` przy przetwarzaniu review oraz `superpowers:systematic-debugging` przy dłuższych blokerach.

### Claude (mentor)
- Tworzy GitHub Issue dla każdego daily taska (template w §4).
- Prowadzi roadmapę i wybiera następny task na starcie każdej sesji.
- Robi code review na PR przez `code-review:code-review` skill.
- Dopisuje unit/integration testy po zaakceptowanej implementacji.
- Weryfikuje gotowość do merge przez `superpowers:verification-before-completion`.
- Updatuje `PROGRESS.md` po każdym merge.
- Prowadzi retro po każdym milestone.

### Zasada nadrzędna
Claude **nie pisze kodu implementacji**. Jedyne wyjątki:
- Dopisywanie testów (faza review).
- Update `PROGRESS.md` / dokumentów w `docs/`.
- Drobne poprawki w konfiguracji CI/pre-commit po dyskusji.

Gdy developer utknie — Claude pomaga pytaniami sokratejskimi, linkami do dokumentacji, mini-przykładami w komentarzu review (nie w samym kodzie brancha).

---

## 3. Workflow pojedynczego taska

```
1. Start sesji Claude
   → git pull master
   → Read PROGRESS.md
   → gh issue list --milestone <aktualny> --state open
   → gh pr list (otwarty PR do review?)

2. Claude: gh issue create (template z §4)
   Labels: phase-M<N>, app:<nazwa>, type:<feat|chore|fix|refactor|test|docs>
   Milestone: M<N>
   Assignee: developer

3. Developer:
   git checkout master && git pull
   git checkout -b <type>/<issue-nr>-<slug>
   [implementacja, ~4h, małe commity]
   poetry run pre-commit run --all-files
   poetry run pytest
   git push -u origin <branch>
   gh pr create --base master --fill --body "Closes #<nr>"

4. CI (.github/workflows/ci.yml):
   - lint job (ruff + mypy + pre-commit all-files)
   - test job (pytest + coverage, Postgres service)

5. Claude: code review (checklist w §5)
   - inline comments (suggestion / nit / question / issue / praise)
   - top-level: ogólna ocena + learning notes
   - status: REQUEST_CHANGES | APPROVE | COMMENT

6. Developer: iteracje na review aż APPROVE.

7. Claude: dopisuje testy → commit "test: add tests for #<nr>"
   → verification-before-completion sprawdza zielone CI
   → APPROVE PR

8. Developer: gh pr merge --squash --delete-branch
   Issue auto-closuje się.

9. Claude: update PROGRESS.md (commit bezpośrednio na master, `docs:`).
```

### Branch protection (master)
- 1 approve wymagany.
- CI `lint` + `test` muszą być green.
- Force-push zablokowany.
- Branch automatycznie usuwany po merge.

### Merge strategy
- **Squash merge** (nie merge commit, nie rebase). Historia na master = jeden commit per task.
- Squashed message dziedziczy z tytułu PR (który dziedziczy z tytułu Issue).

---

## 4. Template GitHub Issue (daily task)

Każde Issue stworzone przez Claude ma tę strukturę (copy-paste-modify, nie kreatywność):

```markdown
# [M<N>-D<n>] <krótki tytuł taska>

**Milestone:** M<N> — <nazwa milestone>
**Czas:** ~3-4h
**Branch:** `<type>/<nr>-<slug>`

## 🎯 Cel
Jedno zdanie: co działa po zakończeniu.

## 🧠 Czego się nauczysz
- punkt 1 (konkretny koncept, nie "Django")
- punkt 2
- punkt 3

## ✅ Acceptance criteria
- [ ] checklistowe, weryfikowalne (nie "kod jest dobry")
- [ ] ...

## 📋 Sugerowane kroki
1. ...
2. ...

## ⚠️ Pułapki do uwagi
- specyficzne gotcha z doświadczenia

## 🧪 Testing plan
Lista scenariuszy które ja dopiszę po PR review.

## 🔗 Dokumentacja pomocnicza
- linki do docs

## 📦 Definition of Done
- [ ] Acceptance criteria spełnione
- [ ] CI zielony
- [ ] pre-commit czysto
- [ ] PR otwarty, linkuje Closes #<nr>
- [ ] Moje approve po code-review
```

---

## 5. Code review checklist

W kolejności (`code-review:code-review` skill):

### 🔴 Blockers (automatyczny REQUEST_CHANGES)
- CI green (lint + test)
- Acceptance criteria spełnione
- Conventional Commit message
- Brak sekretów/tokenów
- Migracje commitowane z modelem
- Scrapery nie piszą do ORM bezpośrednio (CLAUDE.md §6, §15.4)

### 🟡 Architecture (dyskusja)
- Logika biznesowa w `services.py`, nie w views/resolvers/spiders
- Absolutne importy
- `settings` nie importowane w `models.py`
- GraphQL per-app, scalenie w `config/schema.py`
- Podział Postgres (dane) vs MongoDB (logi)
- Single responsibility — gdy test jest trudny, unit jest za duży

### 🟢 Quality (sugestie)
- Type hints
- Czytelne nazwy
- Brak niepotrzebnej duplikacji
- Error handling tylko tam gdzie konieczny
- Komentarze "dlaczego", nie "co"

### 🎓 Learning (edukacyjny feedback)
- Chwalenie tego co dobre (żeby powtarzać)
- Alternatywne wzorce
- Linki do dalszej nauki

### 📝 Testy (dopisuje Claude po approve implementacji)
- Unit test na każdy service (happy path + 2 edge cases)
- Integration test gdy dotyka bazy/zewnętrznego systemu
- Scrapery testowane na zapisanych fixturach HTML (zero live scraping w CI — CLAUDE.md §15.6)
- Coverage po merge nie spada (`--cov-fail-under=70`)

### Konwencje komentarzy (Conventional Comments)
- `nit:` drobiazg, opcjonalny
- `suggestion:` propozycja do rozważenia
- `question:` wyjaśnij
- `issue:` wymaga poprawki
- `praise:` dobrze zrobione

---

## 6. Roadmapa — fazy i milestones

**Podejście:** vertical slice. Pierwszy działający efekt (scraping pojedynczej postaci widoczny w Django admin) w M1, po ~1 tygodniu pracy. Potem dorzucamy warstwy.

| # | Milestone | Czas (4h/dzień) | Efekt |
|---|---|---|---|
| M0 | Bootstrap projektu | 3 dni | Repo + GitHub + branch protection + Django 6 runserver + Postgres lokalnie + pre-commit + CI lint |
| M1 | First character scrape (e2e) | 5 dni | Model `Character`, service, Scrapy spider, management command. `./manage.py scrape_character Yhral` → admin pokazuje postać |
| M2 | Auth + GraphQL fundament | 4 dni | REST auth (register/login/refresh JWT), `/graphql/` z `me` + `character(name)`, testy auth |
| M3 | Bedmage tracker (bez Discorda) | 4 dni | `BedmageWatch`, mutations, logika 100-min, management command drukuje powiadomienia do stdout |
| M4 | Deaths monitor (bez Discorda) | 3 dni | `DeathEvent`, spider `tibiantis.info`, deduplikacja, query `recentDeaths`, próg konfigurowalny |
| M5 | Celery + Beat + Redis + Mongo | 3 dni | Redis + Mongo lokalnie, Celery worker/beat, spidery z harmonogramu, `scrape_logs` → Mongo |
| M6 | Discord bot — commands | 4 dni | Osobny proces, slash commands `/bedmage {add,remove,list}`, `/deaths threshold`, mapping `discord_id` ↔ `User` |
| M7 | Discord powiadomienia | 2 dni | Celery task pushuje powiadomienia przez webhook. End-to-end działa |
| M8 | Dockeryzacja + prod-ready | 4 dni | `Dockerfile` multi-stage, `docker-compose.yml` z 7 serwisami, healthchecki |
| M9 | Hardening | 3 dni | Coverage ≥ 70%, mypy strict zielone, security workflow, Dependabot, README |

**Suma:** ~35 dni × 4h = ~140h → ~7 tygodni przy 5 dniach pracy/tydzień.

### Odstępstwa od ścisłego CLAUDE.md
- **Docker dopiero w M8** — na starcie Postgres/Redis/Mongo lokalnie. Uzasadnienie: dla uczącej się osoby pełna infra od dnia 1 to bariera wejścia. Zmiana na Docker na końcu dotyczy kilku zmiennych w `.env`, nie kodu.
- **Celery dopiero w M5** — do M4 spidery uruchamiane przez management commands. Izoluje naukę Django od nauki Celery.
- **MongoDB dopiero w M5** — do tego momentu logi do plików/stdout (domyślny Django logging).

Odstępstwa są świadome i zatwierdzone przez developera.

### YAGNI (po M9, osobne projekty)
- Dashboard webowy
- Powiadomienia mailowe
- Nginx + TLS (tylko przy realnym deploy)
- Historia poziomów / wykresy

---

## 7. Daily tasks — M0 + M1 (pierwszy sprint)

Szczegółowy breakdown na następnych 7-8 dni. Kolejne milestones dostają breakdown przed startem milestone'u (nie generujemy 35 dni naraz — szczegóły się dezaktualizują).

### M0 — Bootstrap (3 dni)

| D | Issue | Tytuł | Branch | Czas |
|---|---|---|---|---|
| D1 | #1 | `[M0] Inicjalizacja repo + GitHub + branch protection` | `chore/1-repo-setup` | 3-4h |
| D2 | #2 | `[M0] Django 6 project + Postgres lokalnie + pierwszy runserver` | `feat/2-django-bootstrap` | 3-4h |
| D3 | #3 | `[M0] pre-commit + ruff + mypy + CI lint` | `chore/3-quality-tooling` | 3-4h |

**Uwaga D3:** test job w CI pojawi się dopiero w D5, kiedy jest pierwszy realny test. Lint job wcześniej wystarczy.

### M1 — First character scrape (5 dni)

| D | Issue | Tytuł | Branch | Czas |
|---|---|---|---|---|
| D4 | #4 | `[M1] apps/ struktura + app "characters" zarejestrowana` | `feat/4-apps-structure` | 2-3h |
| D5 | #5 | `[M1] Model Character + migracja + admin + pierwszy test` | `feat/5-character-model` | 4h |
| D6 | #6 | `[M1] Service layer: upsert_character()` | `feat/6-character-service` | 3h |
| D7 | #7 | `[M1] Scrapy: minimalny spider character_spider` | `feat/7-character-spider` | 4h |
| D8 | #8 | `[M1] Pipeline Scrapy → service + management command` | `feat/8-scrape-pipeline` | 3-4h |

Po D8: retrospekcja M1 + update PROGRESS.md + breakdown dzienny dla M2.

### Zasady sprintu

1. **Scope nie rośnie w trakcie.** Nowe pomysły = nowe Issues, nie doklejki.
2. **Escape hatch:** jeśli po 4h nie ma PR → push WIP, kontynuujemy jutro z mniejszym follow-up tasku. Brak wstydu w niedokończeniu.
3. **Dni puste są OK.** PROGRESS.md działa jako zakładka.

---

## 8. Superpowers skills — kiedy i kto

### Aktywnie używane
| Skill | Kto | Kiedy |
|---|---|---|
| `code-review:code-review` | Claude | Każdy PR |
| `superpowers:verification-before-completion` | Claude | Przed każdym approve |
| `superpowers:systematic-debugging` | Developer | Blokery > 30 min |
| `superpowers:receiving-code-review` | Developer | Przy każdym review |
| `superpowers:test-driven-development` | Claude | Przy pisaniu testów |

### Okazjonalnie
| Skill | Kiedy |
|---|---|
| `superpowers:brainstorming` | Przed większymi decyzjami architektonicznymi (np. start M5 — architektura Celery) |
| `superpowers:writing-plans` | Po każdym milestone, przed następnym |
| `superpowers:requesting-code-review` | Developer, gdy chce review poza normalnym PR flow |
| `superpowers:finishing-a-development-branch` | Claude, na końcu każdego milestone |

### Nie używamy
- `superpowers:using-git-worktrees` — overkill dla sekwencyjnego workflow
- `superpowers:dispatching-parallel-agents` — Claude pracuje sekwencyjnie
- `superpowers:subagent-driven-development` — Claude nie implementuje
- `superpowers:executing-plans` — wykonawcą planu jest developer

---

## 9. Persistent memory — handoff między sesjami

### Warstwa 1: `PROGRESS.md` (repo, master)
Ludzkie źródło prawdy. Struktura:
```markdown
# Tibiantis Monitor — Progress

## Aktualny milestone: M<N> — <nazwa>
**Status:** <x>/<y> dni ukończone

### Ukończone
- ✅ #<nr> <tytuł> (YYYY-MM-DD) — PR #<nr>

### W trakcie
- 🔨 #<nr> <tytuł> — branch `<branch>`

### Notatki z retro
- krótkie uwagi per task
```

Update: commit `docs: update progress after #<nr>` bezpośrednio na master przez Claude po każdym merge.

### Warstwa 2: GitHub Issues + Milestones
- Backlog = Issues z labelką `status:ready`
- `status:blocked` + komentarz = powód
- Milestones = grupowanie M0-M9

### Warstwa 3: Claude memory
Tylko rzeczy trwałe o developerze:
- poziom techniczny (uczy się Django, chce mentora)
- preferencje feedbacku (edukacyjny, nie "popraw X")
- język komunikacji (polski)

**Nie zapisuję:** aktualny task, ostatni merge, status milestone'u — to w PROGRESS.md / Issues.

### Start każdej sesji Claude (protokół)
1. `git pull master`
2. `Read PROGRESS.md`
3. `gh issue list --milestone "M<N>" --state open`
4. `gh pr list` — czy jest PR do review?
5. Odpowiedź developerowi: "Jesteśmy w M<N>, task #<nr>. Plan na dziś: [...]"

---

## 10. Ryzyka i mitygacje

| Ryzyko | Prawdopodobieństwo | Wpływ | Mitygacja |
|---|---|---|---|
| Developer porzuca projekt po 2 tygodniach (typowe) | Średnie | Wysoki | Vertical slice → efekt widoczny w M1 (~5 dni) jako motywator; taski ≤ 4h; escape hatch |
| Scope creep (nowe ficzery w trakcie) | Wysokie | Średni | Zasada „nowy pomysł = nowe Issue"; YAGNI-lista w §6; retro po milestones |
| Task okazuje się za duży (>4h) | Wysokie na start | Niski | Escape hatch (push WIP, follow-up task); retro uczy mnie lepiej szacować |
| Claude pisze za mało / za dużo w Issue | Średnie | Niski | Template §4 wymusza strukturę; po M1 retro dostosowuje szczegółowość |
| Breaking changes w Django 6 w trakcie | Niskie | Średni | `django-upgrade` w pre-commit; pinowanie wersji w `pyproject.toml` |
| Tibiantis zmienia HTML → spider pada | Średnie | Średni | Testy na fixturach HTML (nie live); fallback: log błąd + alert, nie fail całego systemu |
| Developer rate-limit z żywych stron | Niskie | Niski | `DOWNLOAD_DELAY ≥ 2s`; realny USER_AGENT; live scraping tylko manualnie |

---

## 11. Sukces projektu — kryteria

Projekt uznajemy za **ukończony** (post-M9), gdy wszystkie poniższe są prawdą:
- `docker compose up` startuje 7 serwisów bez błędów
- Scraper `tibiantis.online` działa z harmonogramu Celery Beat
- Scraper `tibiantis.info/stats/deaths` działa z harmonogramu
- Discord bot odpowiada na `/bedmage add`, `/bedmage remove`, `/bedmage list`, `/deaths threshold`
- Powiadomienia o śmierciach postaci level ≥ 30 trafiają na skonfigurowany kanał
- Powiadomienia bedmage 100-min trafiają do DM użytkownika
- `pytest` przechodzi z `coverage ≥ 70%` dla `apps/`
- `mypy apps/` strict zielone
- CI (lint + test) zielone na master
- README dokumentuje lokalny setup + deploy
- Wszystkie M0-M9 mergnięte do master

**Projekt uznajemy za sukces edukacyjny** (ortogonalne do ukończenia), gdy developer umie:
- Stworzyć nową aplikację Django z modelami, migracjami, adminem, GraphQL resolverami, testami (bez pytania Claude)
- Dopisać nowy Celery task + harmonogram w Beat
- Dopisać nowego Scrapy spidera + pipeline
- Przetoczyć PR przez review → approve → merge bez błędów procesu
- Zdebugować typowy błąd Django (migration conflict, circular import, N+1 query) samodzielnie

---

## 12. Kolejny krok

Po akceptacji tego designu przez developera — Claude wywołuje `superpowers:writing-plans` żeby wygenerować **szczegółowy plan implementacyjny dla M0 + M1** (8 tasków × pełny breakdown z acceptance criteria). Kolejne milestones dostają plan przed ich startem, nie teraz.
