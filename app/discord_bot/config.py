from __future__ import annotations

import os
from dataclasses import dataclass

from ..common.env import env_bool


@dataclass(slots=True)
class DiscordBotConfig:
    token: str = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    application_id: str = os.getenv("DISCORD_BOT_APPLICATION_ID", "").strip()
    guild_id: str = os.getenv("DISCORD_BOT_GUILD_ID", "").strip()
    sync_commands: bool = env_bool(os.getenv("DISCORD_BOT_SYNC_COMMANDS"), True)
    allow_manual_actions: bool = env_bool(os.getenv("DISCORD_BOT_ALLOW_MANUAL_ACTIONS"), True)
    presence_text: str = os.getenv("DISCORD_BOT_PRESENCE", "crypto goblin things").strip()

    def validate(self) -> None:
        if not self.token:
            raise ValueError("DISCORD_BOT_TOKEN is required")

    @property
    def guild_id_int(self) -> int | None:
        if not self.guild_id:
            return None
        return int(self.guild_id)

    @property
    def application_id_int(self) -> int | None:
        if not self.application_id:
            return None
        return int(self.application_id)
