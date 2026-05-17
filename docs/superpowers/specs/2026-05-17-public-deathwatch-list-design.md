# Public DeathWatch list — Design

**Data:** 2026-05-17
**Feature:** M12 follow-up — `/deathwatch list` widoczne dla wszystkich (Discord cog + GraphQL query change).
**Skala:** mała (~5 plików, brak migracji, brak nowych modeli).

---

## 1. Cel

Po M12 lista deathwatches była per-user — każdy widział tylko swoje wpisy. User-feedback: lista ma być **shared** — `/deathwatch list` pokazuje wszystkie aktywne watches w systemie (kto dodał, na kogo).

**Cap pozostaje globalny** (już taki był od spec §3.2): 20 unikalnych postaci across all users — widoczny w outputie `/list` jako `count/cap` reminder.

## 2. Scope

**W scope:**
- Refactor service `apps.deathwatch.services.list_death_watches(user)` → `list_all_death_watches()` (drop param, return all active watches).
- Update Discord cog `/deathwatch list` — wszystkie watches, format z `(added by <@discord_id>)`, `allowed_mentions=AllowedMentions.none()` (no ping spam), ephemeral pozostaje.
- Update bot service wrapper `discord_bot.services.list_deathwatches_for_discord_user(discord_id)` → `list_all_deathwatches()` (drop param).
- Rename GraphQL query `myDeathWatches` → `deathwatches`. Add resolved field `addedByDiscordId` na `DeathWatchType`.
- Update tests we wszystkich trzech warstwach.

**Poza scope:**
- Cap value change (zostaje 20).
- GraphQL backwards-compat — projekt nie ma external GraphQL consumers, breaking rename OK.
- Per-channel filtering, search, pagination — YAGNI, lista max ~20 chars.
- `who-removed` audit history — soft delete poza scope.

---

## 3. Decisions

### 3.1. Nazewnictwo service: `list_all_death_watches` zamiast reuse `list_death_watches`
Explicit `all_` prefix usuwa ambiguity ze starą signaturą `(user)`. Reader natychmiast widzi że to globalny query. Wszystkie callery aktualizowane atomically.

### 3.2. Discord mention syntax `<@discord_id>` zamiast `user.username`
Auto-create User pattern z M7 zapisuje `username = f"discord_{discord_id}"` — raw "discord_12345" wygląda nieprzyjaźnie w embedzie. Discord renderuje `<@id>` jako "@alice" natywnie (faktyczny username z Discord profile, nie z DB). Pole `User.discord_id` istnieje od M2-D9, używane w cogach.

### 3.3. `allowed_mentions=discord.AllowedMentions.none()`
Bez tego `<@id>` w response pinguje każdego usera listed → potencjalny spam (jeden `/list` = 20 notifikacji). `AllowedMentions.none()` renderuje mentions wizualnie bez pingowania. **Critical UX**, test pilnuje.

### 3.4. GraphQL rename `myDeathWatches` → `deathwatches`
Breaking change ALE projekt nie ma external GraphQL consumers (single internal client = aktualnie nieużywany). Zmiana semantyki przy zachowaniu `myDeathWatches` byłaby źródłem przyszłej confusion ("dlaczego `my` zwraca cudze?"). Auth nadal required — nieautoryzowani klienci nie widzą.

### 3.5. Visible cap w `/list` outputie (`count/20`)
Bonus UX nad pure list. User natychmiast widzi że zostało N slotów w systemie. Reminder że cap jest shared. Tani — `settings.DEATHWATCH_MAX_WATCHED_CHARACTERS` access + format string.

### 3.6. Ephemeral zachowany
User explicit chciał ephemeral mimo public list. Trade-off: tylko caller widzi, więc kanał nie spamowany, ale każdy user musi sam zawołać. Akceptowalne — `/list` w deathwatch nie jest częsty, nie ma value w kanał-wide audit trail.

### 3.7. Auth nadal required na GraphQL
Lista jest shared, ale tylko między authenticated clients. Anonymous webhook nie widzi czyje postacie są obserwowane (mild privacy guard mimo że bot expose to przez `/list`).

---

## 4. Implementation outline

### 4.1. Files to modify

| Plik | Zmiana |
|---|---|
| `apps/deathwatch/services.py` | `list_death_watches(user)` → `list_all_death_watches()`. `select_related("user", "character")` (N+1 guard dla username rendering). Order by `-created_at` zachowany. |
| `discord_bot/services.py` | `list_deathwatches_for_discord_user(discord_id)` → `list_all_deathwatches()`. Drop `discord_id` param. |
| `discord_bot/cogs/deathwatch.py` | `/list` resolver: drop `ctx.author.id` arg, fetch all, render z `<@discord_id>`, `count/cap`, `allowed_mentions=AllowedMentions.none()`. |
| `apps/deathwatch/schema.py` | `my_death_watches` resolver → `deathwatches`. Drop user filter. Add `added_by_discord_id` resolved field na `DeathWatchType`. |
| `config/schema.py` | No change (merge_types accepts renamed Query field automatycznie). |

### 4.2. Files to test

| Plik | Zmiana |
|---|---|
| `tests/unit/deathwatch/test_services.py` | Drop `test_list_death_watches_filters_by_user_and_orders_newest_first`. Add `test_list_all_death_watches_returns_all_users_newest_first`. |
| `tests/unit/discord_bot/test_deathwatch_cog.py` | Update `test_list_command_renders_character_names` (multi-user seed, assert both watches visible). Add `test_list_command_shows_added_by_discord_mention` (assert `<@id>` w outputie). Add `test_list_command_uses_allowed_mentions_none` (assert kwarg passed). Add `test_list_command_includes_cap_indicator` (`/20` w outputie). |
| `tests/unit/deathwatch/test_graphql_deathwatch.py` | Rename 3 tests `test_my_death_watches_*` → `test_deathwatches_*`. Drop "filters by user" (anti-feature). Add `test_deathwatches_returns_watches_from_all_users`. Add `test_deathwatches_exposes_added_by_discord_id`. |

### 4.3. Discord output sample

```
Active deathwatches (3/20):
• `Yhral` (added by <@123456789012345678>)
• `Bubble` (added by <@987654321098765432>)
• `Eternal oblivion` (added by <@123456789012345678>)
```

Empty state (no watches w systemie):
```
No active deathwatches. Add one with `/deathwatch add <name>`.
```

### 4.4. GraphQL schema delta

```graphql
type DeathWatchType {
  id: ID!
  createdAt: DateTime!
  active: Boolean!
  character: CharacterType!
  addedByDiscordId: String!  # NEW — resolved from user.discord_id
}

type Query {
  # OLD: myDeathWatches: [DeathWatchType!]!
  deathwatches: [DeathWatchType!]!  # all active, auth-gated
  watchedDeaths(characterName: String, limit: Int = 20): [WatchedDeathEventType!]!
}
```

---

## 5. Edge cases

| Sytuacja | Zachowanie |
|---|---|
| User nie ma `discord_id` (manual Django admin user) | Render `<@unknown>` w outputie. Field `discord_id` jest CharField bez null, default `""`. Test pilnuje. |
| Lista pusta (no watches w systemie) | Empty state ze wskazówką `/deathwatch add`. Nie pokazuje cap counter (`0/20` mylące). |
| User dodał inactive watch (`active=False`) | Filter `active=True` w service — inactive watches nie liczą się do cap ani nie renderowane w `/list`. Konsystencja z istniejącym cap check (services.py:59). |
| Same character watched przez wielu userów | Każdy watch jako osobna linia (`Yhral (added by alice)` + `Yhral (added by bob)`). Cap liczy jako 1 unique char. To **expected** — user widzi że Yhral jest watched przez wielu. |

---

## 6. Test plan

### 6.1. Unit (`tests/unit/deathwatch/test_services.py`)
- `test_list_all_death_watches_returns_all_users_newest_first` — seed 2 users × 2 watches, assert order desc.
- `test_list_all_death_watches_excludes_inactive` — soft-deactivated watch nie w wyniku.

### 6.2. Discord cog (`tests/unit/discord_bot/test_deathwatch_cog.py`)
- `test_list_command_renders_character_names` (updated) — multi-user seed, assert both watches w outputie.
- `test_list_command_shows_added_by_discord_mention` — assert `<@discord_id>` literal w response string.
- `test_list_command_uses_allowed_mentions_none` — `respond.call_args.kwargs["allowed_mentions"]` matches `discord.AllowedMentions.none()`.
- `test_list_command_includes_cap_indicator` — assert `(N/20)` w response.
- `test_list_command_empty_state` (existing, no change) — assert "No active deathwatches" gdy pusta.

### 6.3. GraphQL (`tests/unit/deathwatch/test_graphql_deathwatch.py`)
- Rename 3 testy `test_my_death_watches_*` → `test_deathwatches_*`.
- **Drop** `test_my_death_watches_filters_by_request_user` (anti-feature now).
- Add `test_deathwatches_returns_watches_from_all_users` — 2 users seed, assert oba watches w results.
- Add `test_deathwatches_exposes_added_by_discord_id` — query `{ deathwatches { addedByDiscordId } }`, assert non-empty.
- Keep `test_deathwatches_requires_authentication` (renamed).

---

## 7. Definition of Done

- [ ] `list_all_death_watches()` service + drop `list_death_watches(user)`.
- [ ] `list_all_deathwatches()` bot service wrapper + drop `list_deathwatches_for_discord_user(discord_id)`.
- [ ] Discord cog `/list` updated: all watches, `<@id>` mention, `allowed_mentions=none`, `count/cap` indicator.
- [ ] GraphQL: `myDeathWatches` → `deathwatches` rename, `DeathWatchType.addedByDiscordId` added.
- [ ] Tests updated we wszystkich 3 warstwach (services + cog + GraphQL).
- [ ] Pre-commit + CI zielone.
- [ ] Manual smoke (`docs/dev-runbook.md §7`) re-run dla updated `/list` behavior.

---

## 8. Risks & follow-ups

### 8.1. Ryzyko: jeden `/list` = 20 user mentions w response, mimo `allowed_mentions=none`
Discord embed/message z 20 `<@id>` mentions może wyglądać przeładowane. Jeśli prod feedback to potwierdzi — switch na `**username**` (markdown bold derived z Discord User cache) zamiast mention syntax. Trigger: user complaint po smoke. Memory note dla follow-up.

### 8.2. Follow-up: `removed_by` audit
Aktualnie hard delete — kto usunął watch nie jest tracked. Jeśli kiedyś będzie potrzeba audit log (np. "ktoś removed Yhral bez powodu"), zmiana modelu na soft delete + `removed_by_user_id` field. Spec §1 odroczone.

### 8.3. Follow-up: pagination
20 watches × ~80 char per line = ~1600 chars per response — pod Discord 2000 char limit, ale tight. Jeśli cap kiedyś rośnie >25, pagination wymagana. YAGNI dla MVP.
