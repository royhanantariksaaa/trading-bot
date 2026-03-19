from __future__ import annotations

import argparse

from .config import DiscordBotConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Discord command bot for the trading app.")
    parser.add_argument("--check-config", action="store_true", help="Validate config and exit")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config = DiscordBotConfig()
    config.validate()
    if args.check_config:
        print("Discord bot config OK")
        return 0
    from .runner import run_discord_bot

    run_discord_bot(config)
    return 0
