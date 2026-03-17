from .client import PolymarketPublicClient
from .config import Config
from .maker import run_loop


def main() -> None:
    config = Config()
    client = PolymarketPublicClient(config.host)
    run_loop(config, client)


if __name__ == "__main__":
    main()
