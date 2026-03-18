from __future__ import annotations

import unittest

from app.binance.config import Config as BinanceConfig
from app.binance.exchange import SymbolRules
from app.binance.reconcile import reconcile_live_state
from app.binance.state import BotState


class _StubExchange:
    def fetch_open_orders(self, symbol):
        return []

    def fetch_my_trades(self, symbol, limit=100):
        return []

    def fetch_ticker(self, symbol):
        return {"last": 0.55}

    def fetch_balance(self):
        return {
            "free": {"USDT": 100.0, "XRP": 2.0},
            "used": {"USDT": 0.0, "XRP": 0.0},
            "total": {"USDT": 100.0, "XRP": 2.0},
            "USDT": {"free": 100.0, "used": 0.0},
            "XRP": {"free": 2.0, "used": 0.0},
            "info": {"makerCommission": 10, "takerCommission": 10},
        }


class BinanceReconcileDustTest(unittest.TestCase):
    def test_reconcile_keeps_dust_visible_but_not_as_managed_position(self) -> None:
        config = BinanceConfig(
            api_key="test-key",
            api_secret="test-secret",
            bot_mode="live_readonly",
            execution_mode="auto",
            use_testnet=False,
        )
        config.symbol = "XRP/USDT"
        config.stop_loss_pct = 0.02
        config.take_profit_pct = 0.03
        rules = SymbolRules(
            symbol="XRP/USDT",
            base_asset="XRP",
            quote_asset="USDT",
            min_qty=1.0,
            max_qty=1_000_000.0,
            qty_step=1.0,
            market_min_qty=1.0,
            market_max_qty=1_000_000.0,
            market_qty_step=1.0,
            min_price=0.0001,
            max_price=100_000.0,
            tick_size=0.0001,
            min_notional=5.0,
            max_notional=1_000_000.0,
        )

        state = BotState()
        snapshot = reconcile_live_state(config, _StubExchange(), state, rules)

        self.assertIsNone(state.position)
        self.assertEqual(snapshot.base_free, 2.0)
        self.assertEqual(len(snapshot.dust_holdings), 1)
        self.assertEqual(snapshot.dust_holdings[0].asset, "XRP")
        self.assertGreater(snapshot.dust_holdings[0].actionable_threshold, snapshot.dust_holdings[0].notional)


if __name__ == "__main__":
    unittest.main()
