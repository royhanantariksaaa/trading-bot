from trading_bot.polymarket.client import PolymarketPublicClient
from trading_bot.polymarket.config import Config
from trading_bot.polymarket.maker import run_loop


def main() -> None:
    config = Config()
    client = PolymarketPublicClient(config.host)
    run_loop(config, client)


if __name__ == "__main__":
    main()
