from __future__ import annotations

import unittest
from pathlib import Path

from app.polymarket.adaptive import evaluate_adaptive_policy
from app.polymarket.config import Config
from app.polymarket.maker import adaptive_runtime_allows, compute_quote_plan, resolve_runtime_config
from app.polymarket.models import BookSnapshot, BotState, QuoteLevel


class FakeAdaptiveClient:
    def __init__(self, metadata=None):
        self._metadata = metadata or {}

    def get_market_metadata(self, token_id: str) -> dict:
        return self._metadata


def make_book(*, bid: float = 0.47, ask: float = 0.53, bid_sizes=(140, 120, 90), ask_sizes=(130, 110, 80)) -> BookSnapshot:
    return BookSnapshot(
        token_id="token-123",
        tick_size=0.01,
        min_order_size=5,
        best_bid=bid,
        best_ask=ask,
        bids=[QuoteLevel(bid, bid_sizes[0]), QuoteLevel(max(bid - 0.01, 0.01), bid_sizes[1]), QuoteLevel(max(bid - 0.02, 0.01), bid_sizes[2])],
        asks=[QuoteLevel(ask, ask_sizes[0]), QuoteLevel(min(ask + 0.01, 0.99), ask_sizes[1]), QuoteLevel(min(ask + 0.02, 0.99), ask_sizes[2])],
    )


class PolymarketAdaptiveTest(unittest.TestCase):
    def make_config(self, *, report_path: Path, adaptive_mode: str = "paper", paper_mode: bool = True) -> Config:
        return Config(
            token_id="token-123",
            paper_mode=paper_mode,
            adaptive_mode=adaptive_mode,
            adaptive_report_path=report_path,
            quote_size=20,
            base_spread=0.04,
            edge_offset=0.01,
            max_inventory=100,
            max_position_notional=60,
            inventory_skew_per_share=0.0025,
        )

    def test_evaluate_adaptive_policy_picks_defensive_when_book_is_wide_and_imbalanced(self) -> None:
        path = Path(__file__).resolve().parent / ".tmp_pm_adaptive_report.txt"
        config = self.make_config(report_path=path)
        book = make_book(bid=0.40, ask=0.60, bid_sizes=(220, 200, 180), ask_sizes=(20, 15, 10))
        report = evaluate_adaptive_policy(config, book, previous_mid=0.50)
        self.assertEqual(report.policy_name, "imbalanced_defensive")
        self.assertLess(report.overrides.quote_size, config.quote_size)
        self.assertGreater(report.overrides.base_spread, config.base_spread)
        self.assertTrue(report.report_path and report.report_path.exists())
        self.assertTrue(report.report_json_path and report.report_json_path.exists())
        self.assertIn("Adaptive decision report", report.report_path.read_text(encoding="utf-8"))
        path.unlink(missing_ok=True)
        path.with_suffix(".json").unlink(missing_ok=True)

    def test_resolve_runtime_config_applies_overlay_in_paper_mode(self) -> None:
        path = Path(__file__).resolve().parent / ".tmp_pm_runtime_report.txt"
        config = self.make_config(report_path=path, adaptive_mode="paper", paper_mode=True)
        state = BotState(last_mid=0.50, loops=1)
        book = make_book(bid=0.48, ask=0.52)
        runtime_config, report = resolve_runtime_config(config, book, state, FakeAdaptiveClient())
        self.assertIsNotNone(report)
        self.assertNotEqual(runtime_config.quote_size, config.quote_size)
        plan = compute_quote_plan(runtime_config, state, book)
        self.assertEqual(plan.buy_size, runtime_config.quote_size)
        path.unlink(missing_ok=True)
        path.with_suffix(".json").unlink(missing_ok=True)

    def test_resolve_runtime_config_skips_overlay_when_paper_gate_blocks(self) -> None:
        path = Path(__file__).resolve().parent / ".tmp_pm_gate_report.txt"
        config = self.make_config(report_path=path, adaptive_mode="paper", paper_mode=False)
        state = BotState(last_mid=0.50, loops=1)
        book = make_book()
        runtime_config, report = resolve_runtime_config(config, book, state, FakeAdaptiveClient())
        self.assertFalse(adaptive_runtime_allows(config))
        self.assertEqual(runtime_config, config)
        self.assertIsNone(report)


if __name__ == "__main__":
    unittest.main()
