import unittest

from app.polymarket.config import Config
from app.polymarket.execution import PolymarketLiveCredentials, UnimplementedLiveGateway


class PolymarketLiveScaffoldTest(unittest.TestCase):
    def test_live_gateway_fails_closed_without_credentials(self):
        gateway = UnimplementedLiveGateway(PolymarketLiveCredentials())
        with self.assertRaises(NotImplementedError) as ctx:
            gateway.validate_ready()
        self.assertIn("not ready", str(ctx.exception))

    def test_live_enabled_and_paper_mode_conflict(self):
        config = Config(token_id="123", paper_mode=True, live_enabled=True)
        with self.assertRaises(ValueError) as ctx:
            config.validate()
        self.assertIn("incompatible", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
