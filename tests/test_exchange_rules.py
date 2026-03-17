from __future__ import annotations

import unittest

from app.binance.exchange import SymbolRules, validate_market_quote_budget, validate_market_sell_quantity


class ExchangeRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = SymbolRules(
            symbol="SOL/USDT",
            base_asset="SOL",
            quote_asset="USDT",
            min_qty=0.01,
            max_qty=1000,
            qty_step=0.01,
            market_min_qty=0.01,
            market_max_qty=1000,
            market_qty_step=0.01,
            min_price=0.01,
            max_price=100000,
            tick_size=0.01,
            min_notional=5.0,
            max_notional=100000.0,
        )

    def test_quote_budget_is_truncated_and_validated(self) -> None:
        quote_budget = validate_market_quote_budget(5.678912345, 100.0, self.rules)
        self.assertEqual(quote_budget, 5.67891234)

    def test_sell_quantity_rounds_down_to_market_step(self) -> None:
        qty = validate_market_sell_quantity(0.123456, 100.0, self.rules)
        self.assertEqual(qty, 0.12)

    def test_sell_quantity_rejects_below_notional(self) -> None:
        with self.assertRaises(ValueError):
            validate_market_sell_quantity(0.02, 100.0, self.rules)


if __name__ == "__main__":
    unittest.main()
