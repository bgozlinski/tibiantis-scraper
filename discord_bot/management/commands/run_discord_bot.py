"""Management command that boots the Discord bot loop.

Run as a long-lived process, typically inside its own container so it can be
restarted independently of the web/Celery workers.
"""

from __future__ import annotations
from typing import Any
from django.conf import settings
from django.core.management.base import BaseCommand
from discord_bot.bot import setup_bot


class Command(BaseCommand):
    """``manage.py run_discord_bot`` — start the bot and block."""

    help = "Run the Discord bot (blocks until interrupted)"

    def handle(self, *args: Any, **options: Any) -> None:
        """Refuse to start without a bot token, otherwise hand control to py-cord."""
        if not settings.DISCORD_BOT_TOKEN:
            self.stderr.write("DISCORD_BOT_TOKEN not set in env")
            return
        bot = setup_bot()
        bot.run(settings.DISCORD_BOT_TOKEN)
