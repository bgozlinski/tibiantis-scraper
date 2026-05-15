"""E2E sanity for M7 — setup_bot wires all 4 slash commands.

Pure in-memory check: `setup_bot()` runs cog registration; we walk each
registered cog's command tree and assert the 4 commands from CLAUDE.md §8
are present. No Discord gateway connection, no `bot.run()`.

Catches the regression class that unit tests miss: cog `.callback` tests
bypass py-cord's command-registration machinery entirely. If someone removes
`bot.add_cog(...)` in `setup_bot`, all unit tests stay green and only this
e2e fails. PR #124 (`fix(discord): remove future annotations from cogs`) is
the canonical example of a bug at this layer — runtime introspection of
slash command parameter types was broken under PEP 563.

We walk `bot.cogs[...].walk_commands()` instead of
`bot.walk_application_commands()`: nested commands inside a
`SlashCommandGroup` (e.g. `/bedmage add` lives under the `bedmage` group)
are stored on the cog and only flushed to the bot's top-level command list
at Discord gateway sync time, which this in-memory test deliberately skips.
"""

from __future__ import annotations

from discord_bot.bot import setup_bot


def test_setup_bot_registers_all_four_slash_commands() -> None:
    """All 4 commands per spec §1 are registered after `setup_bot()`.

    `Cog.walk_commands()` descends into `SlashCommandGroup` children, so the
    qualified names use the `<group> <command>` form.
    """
    bot = setup_bot()

    names: set[str] = set()
    for cog in bot.cogs.values():
        for command in cog.walk_commands():
            names.add(command.qualified_name)

    assert "bedmage add" in names
    assert "bedmage remove" in names
    assert "bedmage list" in names
    assert "deaths threshold" in names
