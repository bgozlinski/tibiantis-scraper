# Tibiantis Monitor

Backend application that scrapes two Tibiantis services on a schedule, stores character data and events in a database, and communicates with users through a Discord bot.

## Core features

1. **Character monitoring** — profile scraper for [`tibiantis.online`](https://tibiantis.online).
2. **Death monitoring** — death-list scraper for [`tibiantis.info`](https://tibiantis.info/stats/deaths).
3. **Bedmage tracker** — reminds users when 100 minutes have passed since a character's last login (end of in-bed mana regeneration).
4. **Discord bot** — user-facing interface: notifications about high-level character deaths and commands for managing the bedmages list.

The application is modular — more features are planned, so the architecture must be extensible.

## Tech stack

Python 3.13 · Django 6 · PostgreSQL · MongoDB (logs only) · Scrapy · Celery + Redis · Strawberry-Django (GraphQL) · DRF (auth only) · discord.py · Docker.

## Documentation

- [`CLAUDE.md`](./CLAUDE.md) — full project specification (stack, structure, conventions, CI rules).
- [`docs/superpowers/specs/2026-04-17-tibiantis-execution-plan-design.md`](./docs/superpowers/specs/2026-04-17-tibiantis-execution-plan-design.md) — execution process (roles, workflow, milestones).
- [`docs/superpowers/plans/2026-04-17-m0-m1-implementation-plan.md`](./docs/superpowers/plans/2026-04-17-m0-m1-implementation-plan.md) — detailed plan for M0 + M1.
- [`PROGRESS.md`](./PROGRESS.md) — current milestone status.

## Status

Work in progress. See `PROGRESS.md` and [open issues](https://github.com/bgozlinski/tibiantis-scraper/issues) for the current state.
