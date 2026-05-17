# Public DeathWatch list — Implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/deathwatch list` (Discord) i GraphQL `deathwatches` zwracają wszystkie aktywne watches w systemie (nie per-user) — share visibility z preserved ephemeral Discord response.

**Architecture:** Refactor `list_*_death_watches` services do drop user param (return all active + `select_related("user", "character")`). Discord cog renders `<@discord_id>` mentions z `allowed_mentions=AllowedMentions.none()` (no ping spam). GraphQL query rename `myDeathWatches` → `deathwatches` + `addedByDiscordId` resolved field. Cap globalny już istnieje od M12 (spec §3.2), bez zmian.

**Tech Stack:** Django 6.0, Strawberry-Django, py-cord, pytest.

**Data:** 2026-05-17
**Spec:** [`docs/superpowers/specs/2026-05-17-public-deathwatch-list-design.md`](../specs/2026-05-17-public-deathwatch-list-design.md)
**Status:** READY (spec accepted 2026-05-17, all 7 decisions §3 approved).

---

## Pre-flight checklist

- [ ] **M12 merged** — patrz #186, #196-#205 (wszystkie zmergowane na master 2026-05-17).
- [ ] **Branch** `feat/deathwatch-public-list` z spec commit `6971415` — already created, build on top.
- [ ] **`User.discord_id`** field istnieje od M2-D9 — `CharField(max_length=64, blank=True, default="")`. Cog rendering polega na tym field.
- [ ] **`DEATHWATCH_MAX_WATCHED_CHARACTERS`** w settings — istnieje od DW-2 (`config/settings/base.py`), value `20`.
- [ ] **`discord.AllowedMentions.none()`** — py-cord API method, no extra deps.

---

## Task overview

| # | Tytuł | Czas |
|---|---|---|
| 1 | Service layer rename (`list_death_watches` → `list_all_death_watches`) + tests | 30 min |
| 2 | Bot wrapper rename + Discord cog rewrite + tests | 1h |
| 3 | GraphQL rename + `addedByDiscordId` field + tests | 30 min |
| 4 | Final pre-commit + PR | 15 min |

**Total:** ~2h. Single PR (`feat/deathwatch-public-list`), wszystkie tasks na tym samym branchu.

---

## Task 1 — Service layer rename + tests

**Files:**
- Modify: `apps/deathwatch/services.py` — drop `list_death_watches(user)`, add `list_all_death_watches()`.
- Modify: `tests/unit/deathwatch/test_services.py` — drop `test_list_death_watches_filters_by_user_and_orders_newest_first`, add 2 new tests.

### TDD steps

- [ ] **Step 1: Drop old test, write new failing tests**

Otwórz `tests/unit/deathwatch/test_services.py`. **Usuń** funkcję `test_list_death_watches_filters_by_user_and_orders_newest_first` (anti-feature now). Zmień import line:

```python
from apps.deathwatch.services import (
    add_death_watch,
    list_all_death_watches,  # was: list_death_watches
    record_watched_death,
    remove_death_watch,
    set_deathwatch_channel_for_guild,
)
```

Dopisz w sekcji `# list_death_watches` (rename komentarz na `# list_all_death_watches`):

```python
@pytest.mark.django_db
def test_list_all_death_watches_returns_all_users_newest_first() -> None:
    """Public list: every active watch, ordered by created_at desc."""
    alice = User.objects.create(username="alice", discord_id="1")
    bob = User.objects.create(username="bob", discord_id="2")
    add_death_watch(alice, "Yhral")
    add_death_watch(bob, "Bubble")
    add_death_watch(alice, "Eternal Oblivion")

    watches = list(list_all_death_watches())

    assert len(watches) == 3
    names = [w.character.name for w in watches]
    # Newest first
    assert names[0] == "Eternal oblivion"
    assert set(names) == {"Yhral", "Bubble", "Eternal oblivion"}


@pytest.mark.django_db
def test_list_all_death_watches_excludes_inactive() -> None:
    """Soft-deactivated watches are excluded — consistent with cap counter."""
    user = User.objects.create(username="alice", discord_id="1")
    add_death_watch(user, "Yhral")
    inactive_watch = add_death_watch(user, "Bubble")
    inactive_watch.active = False
    inactive_watch.save(update_fields=["active"])

    watches = list(list_all_death_watches())

    assert len(watches) == 1
    assert watches[0].character.name == "Yhral"
```

- [ ] **Step 2: Run tests — expected FAIL (ImportError)**

```bash
poetry run pytest tests/unit/deathwatch/test_services.py -v -k "list_all_death_watches"
```

Expected: `ImportError: cannot import name 'list_all_death_watches'`.

- [ ] **Step 3: Implement service rename**

W `apps/deathwatch/services.py`, znajdź `def list_death_watches(user: User) -> QuerySet[DeathWatch]:` i **zastąp** całą funkcję:

```python
def list_all_death_watches() -> QuerySet[DeathWatch]:
    """List all active DeathWatches across all users, newest first.

    `select_related("user", "character")` pre-loads both FK objects so
    callers can render `watch.user.discord_id` + `watch.character.name`
    without N+1 — Discord cog iterates the QuerySet to build a multi-line
    response (~20 entries max, capped by DEATHWATCH_MAX_WATCHED_CHARACTERS).

    Spec §3.1 — public list visibility change (M12 follow-up).
    """
    return (
        DeathWatch.objects.filter(active=True)
        .select_related("user", "character")
        .order_by("-created_at")
    )
```

- [ ] **Step 4: Run tests — expected PASS**

```bash
poetry run pytest tests/unit/deathwatch/test_services.py -v
```

Expected: wszystkie testy PASS (z włączeniem 2 nowych + reszty z M12).

- [ ] **Step 5: Verify nothing else imports old name**

```bash
poetry run python -c "from apps.deathwatch.services import list_death_watches" 2>&1
```

Expected: `ImportError: cannot import name 'list_death_watches'`. Jeśli nie — usuń lingering re-export.

```bash
grep -rn "list_death_watches" --include="*.py" | grep -v "list_all_death_watches"
```

Expected: zero hits (poza tym planem/spec docs). Jeśli są — to T2/T3 callery (sprawdź, naprawimy w następnym tasku).

- [ ] **Step 6: Commit**

```bash
git add apps/deathwatch/services.py tests/unit/deathwatch/test_services.py
git commit -m "refactor(deathwatch): rename list_death_watches to list_all_death_watches"
```

---

## Task 2 — Bot wrapper + Discord cog rewrite + tests

**Files:**
- Modify: `discord_bot/services.py` — `list_deathwatches_for_discord_user(discord_id)` → `list_all_deathwatches()`.
- Modify: `discord_bot/cogs/deathwatch.py` — `/list` rewrite: all watches, mentions, count/cap.
- Modify: `tests/unit/discord_bot/test_deathwatch_cog.py` — update + add 3 tests.

### TDD steps

- [ ] **Step 1: Update bot wrapper service**

W `discord_bot/services.py`, znajdź `def list_deathwatches_for_discord_user(discord_id: int) -> list[DeathWatch]:` i **zastąp** całą funkcję + zmień import:

```python
from apps.deathwatch.services import (
    add_death_watch,
    list_all_death_watches,  # was: list_death_watches
    remove_death_watch,
)
```

```python
def list_all_deathwatches() -> list[DeathWatch]:
    """All active deathwatches across all users (M12 follow-up, public list).

    Wrapper over `apps.deathwatch.services.list_all_death_watches` —
    returns concrete list (cog awaits via `sync_to_async`, py-cord doesn't
    consume QuerySets across sync/async boundary).
    """
    return list(list_all_death_watches())
```

- [ ] **Step 2: Write failing cog tests**

W `tests/unit/discord_bot/test_deathwatch_cog.py`, **zastąp** test `test_list_command_renders_character_names` całością + dopisz 3 nowe testy. Zmień import top-of-file:

```python
import discord  # already imported, just confirm
```

**Usuń** `test_list_command_empty_state` body (zmieniamy semantykę message) — przepisuj:

```python
@pytest.mark.asyncio
async def test_list_command_empty_state_when_no_watches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No watches anywhere in the system → hint to add."""
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.respond = AsyncMock()

    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.list_all_deathwatches",
        MagicMock(return_value=[]),
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.list.callback(cog, mock_ctx)

    args, kwargs = mock_ctx.respond.call_args
    assert "No active deathwatches" in args[0]
    assert "/deathwatch add" in args[0]
    assert kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_list_command_renders_all_users_watches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public list visibility — every user's watches included (M12 follow-up)."""
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.respond = AsyncMock()

    w1 = MagicMock()
    w1.character.name = "Yhral"
    w1.user.discord_id = "111"
    w2 = MagicMock()
    w2.character.name = "Bubble"
    w2.user.discord_id = "222"
    w3 = MagicMock()
    w3.character.name = "Eternal oblivion"
    w3.user.discord_id = "111"  # alice again

    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.list_all_deathwatches",
        MagicMock(return_value=[w1, w2, w3]),
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.list.callback(cog, mock_ctx)

    args, kwargs = mock_ctx.respond.call_args
    text = args[0]
    # All three character names present
    assert "Yhral" in text
    assert "Bubble" in text
    assert "Eternal oblivion" in text
    assert kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_list_command_shows_added_by_discord_mention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each entry includes `<@discord_id>` mention syntax (spec §3.2)."""
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.respond = AsyncMock()

    w = MagicMock()
    w.character.name = "Yhral"
    w.user.discord_id = "99999"

    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.list_all_deathwatches",
        MagicMock(return_value=[w]),
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.list.callback(cog, mock_ctx)

    args, _ = mock_ctx.respond.call_args
    assert "<@99999>" in args[0]


@pytest.mark.asyncio
async def test_list_command_uses_allowed_mentions_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """20 mentions w outputie nie mogą pingować users (spec §3.3)."""
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.respond = AsyncMock()

    w = MagicMock()
    w.character.name = "Yhral"
    w.user.discord_id = "1"
    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.list_all_deathwatches",
        MagicMock(return_value=[w]),
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.list.callback(cog, mock_ctx)

    _, kwargs = mock_ctx.respond.call_args
    am = kwargs["allowed_mentions"]
    # AllowedMentions.none() = no everyone/users/roles pings
    assert am.everyone is False
    assert am.users is False
    assert am.roles is False


@pytest.mark.asyncio
async def test_list_command_shows_count_over_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cap indicator `(N/20)` w outputie (spec §3.5)."""
    mock_ctx = MagicMock(spec=discord.ApplicationContext)
    mock_ctx.respond = AsyncMock()

    # 3 watches in the system
    watches = []
    for i in range(3):
        w = MagicMock()
        w.character.name = f"Char{i}"
        w.user.discord_id = str(i)
        watches.append(w)

    monkeypatch.setattr(
        "discord_bot.cogs.deathwatch.list_all_deathwatches",
        MagicMock(return_value=watches),
    )

    cog = DeathWatchCog(bot=MagicMock())
    await cog.list.callback(cog, mock_ctx)

    args, _ = mock_ctx.respond.call_args
    # "(3/20)" or "3/20" — accept either format
    assert "3/20" in args[0]
```

Plus **usuń** stary test `test_list_command_renders_character_names` (zastąpiony przez `test_list_command_renders_all_users_watches`) i stary `test_list_command_empty_state` (zastąpiony przez `test_list_command_empty_state_when_no_watches`).

- [ ] **Step 3: Run cog tests — expected FAIL**

```bash
poetry run pytest tests/unit/discord_bot/test_deathwatch_cog.py -v
```

Expected: 5 new list-related testów FAIL (import error / `list_all_deathwatches` nie istnieje na cog level, plus old `list` semantyka nie matchuje new tests).

- [ ] **Step 4: Update cog `/list`**

W `discord_bot/cogs/deathwatch.py`, zmień import section:

```python
from apps.deathwatch.services import set_deathwatch_channel_for_guild
from discord_bot.services import (
    add_deathwatch_for_discord_user,
    list_all_deathwatches,  # was: list_deathwatches_for_discord_user
    remove_deathwatch_for_discord_user,
)
```

I **zastąp** całą metodę `list` (`/deathwatch list`):

```python
    @deathwatch.command(name="list", description="Show all active deathwatches")
    async def list(self, ctx: discord.ApplicationContext) -> None:
        """Public list visibility (M12 follow-up).

        Shows EVERY active watch across all users, with `<@discord_id>`
        mention syntax — Discord renders as "@alice" natively but we pass
        `AllowedMentions.none()` so listing 20 watches doesn't ping 20 users.
        Ephemeral response (only caller sees) — explicit user choice in spec.
        """
        import discord
        from django.conf import settings

        watches = await sync_to_async(list_all_deathwatches)()
        if not watches:
            await ctx.respond(
                "No active deathwatches. "
                "Add one with `/deathwatch add <name>`.",
                ephemeral=True,
            )
            return

        cap = settings.DEATHWATCH_MAX_WATCHED_CHARACTERS
        # Unique characters across all watches — matches cap semantics.
        unique_count = len({w.character.name for w in watches})

        lines = [
            f"• `{w.character.name}` (added by <@{w.user.discord_id or 'unknown'}>)"
            for w in watches
        ]
        body = (
            f"Active deathwatches ({unique_count}/{cap}):\n"
            + "\n".join(lines)
        )

        await ctx.respond(
            body,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
```

- [ ] **Step 5: Run cog tests — expected PASS**

```bash
poetry run pytest tests/unit/discord_bot/test_deathwatch_cog.py -v
```

Expected: wszystkie 14 testów PASS (was 12, +5 nowych -3 starych = 14).

- [ ] **Step 6: Update test_deathwatch_cog.py top-level `list_deathwatches_for_discord_user` references**

```bash
grep -n "list_deathwatches_for_discord_user" tests/unit/discord_bot/test_deathwatch_cog.py
```

Expected: zero hits (po Step 2 update). Jeśli są lingering — usuń (były tylko w usuniętych test bodies).

- [ ] **Step 7: Verify no orphaned references**

```bash
grep -rn "list_deathwatches_for_discord_user" --include="*.py"
```

Expected: zero hits.

- [ ] **Step 8: Commit**

```bash
git add discord_bot/services.py discord_bot/cogs/deathwatch.py tests/unit/discord_bot/test_deathwatch_cog.py
git commit -m "feat(deathwatch): public /list with all watches + mentions + cap indicator"
```

---

## Task 3 — GraphQL rename + `addedByDiscordId` field + tests

**Files:**
- Modify: `apps/deathwatch/schema.py` — rename query, add resolved field.
- Modify: `tests/unit/deathwatch/test_graphql_deathwatch.py` — rename + drop 1 test + add 2 tests.

### TDD steps

- [ ] **Step 1: Write failing GraphQL tests**

W `tests/unit/deathwatch/test_graphql_deathwatch.py`, **rename** wszystkie `test_my_death_watches_*` na `test_deathwatches_*` (find/replace). **Usuń** `test_my_death_watches_filters_by_request_user` całkowicie (anti-feature). Update query strings z `myDeathWatches` na `deathwatches`.

Po rename, ten test już istnieje (dawniej `test_my_death_watches_requires_authentication`) — zostaw jako `test_deathwatches_requires_authentication`, ale update query:

```python
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_deathwatches_requires_authentication() -> None:
    payload = await _post(AsyncClient(), "{ deathwatches { id } }", bearer=None)
    assert "errors" in payload
    msg = payload["errors"][0]["message"]
    assert "auth" in msg.lower()
```

Po rename, ten test (dawniej `test_my_death_watches_returns_empty_list_for_user_without_watches`) zmienia semantykę — nie ma już per-user filtru. **Zastąp** treść:

```python
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_deathwatches_returns_empty_list_when_no_watches() -> None:
    """Empty system → empty list, NOT errors. Distinguishes "no data" from auth fail."""
    _, bearer = await _make_user_and_token("anyone")
    payload = await _post(AsyncClient(), "{ deathwatches { id } }", bearer)
    assert "errors" not in payload, payload
    assert payload["data"]["deathwatches"] == []
```

Dopisz 2 nowe testy w sekcji `# myDeathWatches query` (rename sekcji na `# deathwatches query`):

```python
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_deathwatches_returns_watches_from_all_users() -> None:
    """Public list visibility (spec §3.4) — alice sees bob's watches too."""
    user_a, bearer_a = await _make_user_and_token("alice")
    user_b, _ = await _make_user_and_token("bob")

    def _seed() -> None:
        c1 = Character.objects.create(name="Yhral")
        c2 = Character.objects.create(name="Bubble")
        DeathWatch.objects.create(user=user_a, character=c1)
        DeathWatch.objects.create(user=user_b, character=c2)

    await sync_to_async(_seed)()

    payload = await _post(
        AsyncClient(),
        "{ deathwatches { character { name } } }",
        bearer_a,
    )

    assert "errors" not in payload, payload
    names = sorted(w["character"]["name"] for w in payload["data"]["deathwatches"])
    assert names == ["Bubble", "Yhral"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_deathwatches_exposes_added_by_discord_id() -> None:
    """Resolved field `addedByDiscordId` returns watch.user.discord_id (spec §4.4)."""
    user, bearer = await _make_user_and_token("alice")
    user.discord_id = "99999"
    await sync_to_async(user.save)(update_fields=["discord_id"])
    char = await sync_to_async(Character.objects.create)(name="Yhral")
    await sync_to_async(DeathWatch.objects.create)(user=user, character=char)

    payload = await _post(
        AsyncClient(),
        "{ deathwatches { addedByDiscordId character { name } } }",
        bearer,
    )

    assert "errors" not in payload, payload
    data = payload["data"]["deathwatches"]
    assert len(data) == 1
    assert data[0]["addedByDiscordId"] == "99999"
    assert data[0]["character"]["name"] == "Yhral"
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest tests/unit/deathwatch/test_graphql_deathwatch.py -v -k "deathwatches"
```

Expected: nowe testy FAIL (`Cannot query field 'deathwatches'` lub `addedByDiscordId`).

- [ ] **Step 3: Update GraphQL schema**

W `apps/deathwatch/schema.py`, **rozszerz** `DeathWatchType` o resolved field. Znajdź:

```python
@strawberry_django.type(DeathWatch)
class DeathWatchType:
    id: auto
    created_at: auto
    active: auto
    character: CharacterType
```

**Zastąp** całą klasę:

```python
@strawberry_django.type(DeathWatch)
class DeathWatchType:
    id: auto
    created_at: auto
    active: auto
    character: CharacterType

    @strawberry.field
    def added_by_discord_id(self) -> str:
        """Discord ID of the user who added this watch (spec §3.2 / §4.4).

        Returns User.discord_id raw — frontend renders as wants (Discord
        `<@id>` mention in bot output, plain string elsewhere). Empty
        string if user has no linked Discord (manual Django admin user).
        """
        return self.user.discord_id or ""
```

W tej samej klasie `Query`, znajdź `async def my_death_watches`:

```python
    @strawberry.field
    async def my_death_watches(
        self, info: strawberry.Info
    ) -> list[DeathWatchType]:
        user = _require_auth(info)
        qs = (
            DeathWatch.objects.filter(user=user)
            .select_related("character")
            .order_by("-created_at")
        )
        return cast("list[DeathWatchType]", [w async for w in qs])
```

**Zastąp** całą metodę:

```python
    @strawberry.field
    async def deathwatches(
        self, info: strawberry.Info
    ) -> list[DeathWatchType]:
        """All active deathwatches across all users (M12 follow-up).

        Public list — every authenticated client sees every watch + added_by_discord_id.
        Spec §3.4 — semantic break from M12 `myDeathWatches` (per-user filter).
        Project has no external GraphQL consumers, so breaking rename OK.
        """
        _require_auth(info)
        qs = (
            DeathWatch.objects.filter(active=True)
            .select_related("user", "character")
            .order_by("-created_at")
        )
        return cast("list[DeathWatchType]", [w async for w in qs])
```

- [ ] **Step 4: Run tests — expected PASS**

```bash
poetry run pytest tests/unit/deathwatch/test_graphql_deathwatch.py -v
```

Expected: wszystkie testy PASS (was 16, drop 1 + rename 3 + add 2 = 17).

- [ ] **Step 5: Verify no orphaned `my_death_watches` references**

```bash
grep -rn "my_death_watches\|myDeathWatches" --include="*.py"
```

Expected: zero hits.

- [ ] **Step 6: Commit**

```bash
git add apps/deathwatch/schema.py tests/unit/deathwatch/test_graphql_deathwatch.py
git commit -m "feat(deathwatch): rename myDeathWatches to deathwatches + addedByDiscordId field"
```

---

## Task 4 — Final pre-commit + PR

- [ ] **Step 1: Pre-commit full pass**

```bash
poetry run pre-commit run --all-files
```

Expected: wszystkie hooki PASS (lub auto-fix + re-stage + re-run).

Jeśli `ruff-format` lub `mixed-line-ending` fixują pliki — `git add` + `git commit --amend --no-edit` ostatniego commita (lub fold w osobny "style" commit jeśli wiele).

- [ ] **Step 2: Full DW test suite**

```bash
poetry run pytest tests/unit/deathwatch tests/unit/discord_bot/test_deathwatch_cog.py tests/integration/deathwatch -v
```

Expected: wszystkie testy PASS. Sanity że żaden M12 test nie regresszał.

- [ ] **Step 3: Push branch**

```bash
git push -u origin feat/deathwatch-public-list
```

- [ ] **Step 4: Create PR**

```bash
gh pr create --title "feat(deathwatch): public /list visibility (M12 follow-up)" --body "$(cat <<'EOF'
## Summary

M12 follow-up — `/deathwatch list` widoczne dla wszystkich (drop per-user filter), GraphQL query rename, added by-mention rendering, no-ping `AllowedMentions.none()`. Cap globalny już istniał od M12 spec §3.2, bez zmian.

**Spec:** \`docs/superpowers/specs/2026-05-17-public-deathwatch-list-design.md\`
**Plan:** \`docs/superpowers/plans/2026-05-17-public-deathwatch-list-implementation-plan.md\`

## Changes

- \`apps/deathwatch/services.py\` — \`list_death_watches(user)\` → \`list_all_death_watches()\`, drop user param, \`select_related("user", "character")\`.
- \`discord_bot/services.py\` — \`list_deathwatches_for_discord_user(discord_id)\` → \`list_all_deathwatches()\`.
- \`discord_bot/cogs/deathwatch.py\` — \`/list\` rewrite: all watches, \`<@discord_id>\` mention syntax, \`AllowedMentions.none()\`, \`count/cap\` indicator. Ephemeral preserved.
- \`apps/deathwatch/schema.py\` — query rename \`myDeathWatches\` → \`deathwatches\`, drop per-user filter, add \`addedByDiscordId\` resolved field.
- Tests updated we wszystkich 3 warstwach (services + cog + GraphQL).

## Breaking changes

- **GraphQL** — \`myDeathWatches\` rename → \`deathwatches\`. Projekt nie ma external GraphQL consumers, akceptowalne.
- **Discord cog** — \`/deathwatch list\` zmienia output shape (multi-user, mentions, count/cap). User-facing, ale konsystentne z user request.

## Test plan

- [x] All M12 tests still PASS (no regression).
- [x] 2 new service tests (\`list_all_death_watches\` happy path + inactive filter).
- [x] 5 new cog tests (empty state, all-users render, mention syntax, allowed_mentions=none, cap indicator).
- [x] 2 new GraphQL tests (multi-user visibility, addedByDiscordId field).
- [x] Pre-commit zielony.
- [ ] Manual smoke per \`docs/dev-runbook.md §7\` — verify mentions render as @username bez pingowania, cap indicator visible.
EOF
)"
```

Expected: PR URL printed.

---

## Self-review (run after writing the plan)

**1. Spec coverage:**
- Spec §3.1 (`list_all_death_watches` rename) → Task 1 ✓
- Spec §3.2 (`<@discord_id>` mention) → Task 2 Step 4 + test Step 2 ✓
- Spec §3.3 (`AllowedMentions.none()`) → Task 2 Step 4 + test ✓
- Spec §3.4 (GraphQL rename) → Task 3 ✓
- Spec §3.5 (count/cap indicator) → Task 2 Step 4 + test ✓
- Spec §3.6 (ephemeral preserved) → Task 2 Step 4 + test assertion `ephemeral is True` ✓
- Spec §3.7 (auth nadal required) → Task 3 (`_require_auth(info)` zachowany w resolverze) ✓
- Spec §5 (`<@unknown>` fallback) → Task 2 Step 4 (`w.user.discord_id or 'unknown'`) ✓
- Spec §6 (testy 3 warstwy) → Task 1 + 2 + 3 ✓

**2. Placeholder scan:** brak TBD/TODO. Wszystkie steps mają konkretny kod.

**3. Type consistency:**
- `list_all_death_watches()` (service) — używane w T1, T2 (`from apps.deathwatch.services import list_all_death_watches` w bot wrapper) ✓
- `list_all_deathwatches()` (bot wrapper) — używane w T2 cog import + tests ✓
- `added_by_discord_id` (Python snake_case w schema) ↔ `addedByDiscordId` (GraphQL camelCase) — Strawberry auto-conversion, OK ✓
- `discord_id` field na `User` — string, M2-D9, used in T2 cog (`w.user.discord_id`) i T3 schema (`self.user.discord_id`) ✓

Self-review pass.
