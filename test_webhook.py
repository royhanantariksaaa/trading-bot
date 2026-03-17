from __future__ import annotations

from config import Config
from notifier import DiscordNotifier


def main() -> None:
    config = Config()
    notifier = DiscordNotifier(config.discord_webhook_url)

    print(f"Webhook enabled: {notifier.enabled}")
    print(f"Webhook target: {notifier.masked_url()}")

    if not notifier.enabled:
        print("No DISCORD_WEBHOOK_URL configured in .env")
        return

    notifier.send("Klau webhook test: if you can read this, Discord alerts are working.")
    print("Test send attempted. Check Discord and console output.")


if __name__ == "__main__":
    main()
