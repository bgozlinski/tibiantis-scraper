from __future__ import annotations
from typing import Any
from django.conf import settings
from django.core.management.base import BaseCommand
from discord_bot.bot import setup_bot


class Command(BaseCommand):
    help = "Run the Discord bot (blocks until interrupted)"

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DISCORD_BOT_TOKEN:
            self.stderr.write("DISCORD_BOT_TOKEN not set in env")
            return
        bot = setup_bot()
        bot.run(settings.DISCORD_BOT_TOKEN)
