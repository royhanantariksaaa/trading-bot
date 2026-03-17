from __future__ import annotations

import unittest
from pathlib import Path

from app.binance.adaptive import evaluate_adaptive_policy
from app.binance.config import Config as BinanceConfig
from app.selection.models import MarketMetrics
from app.selection.profiles import build_strategy_profile


def build_candles(prices: list[float], *, start_ts: int = 1_700_000_000_000, step_ms: int = 900_000) -> list[list[float]]:
    candles: list[list[float]] = []
    previous = prices[0]
    for index, price in enumerate(prices):
        open_price = previous if index else price
        high = max(open_price, price) * 1.0025
        low = min(open_price, price) * 0.9975
        volume = 1_000 + (index * 25)
        candles.append([start_ts + index * step_ms, open_price, high, low, price, volume])
        previous = price
    return candles


class FakeAdaptiveExchange:
    def __init__(self, candles: list[list[float]], ticker: dict[str, float]) -> None:
        self._candles = candles
        self._ticker = ticker

    def fetch_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 96):
        return self._candles[-limit:]

    def fetch_ticker(self, symbol: str):
        return self._ticker


class BinanceAdaptiveTest(unittest.TestCase):
    def _make_config(self, *, report_path: Path) -> BinanceConfig:
        config = BinanceConfig(selection_mode="scan", adaptive_mode="paper")
        config.symbol = "SOL/USDT"
        config.timeframe = "15m"
        config.adaptive_report_path = report_path
        base_metrics = MarketMetrics(
            last_price=100.0,
            bid=99.9,
            ask=100.1,
            spread=0.2,
            spread_bps=20.0,
            volume_quote_24h=25_000_000.0,
            trade_count_24h=20_000,
            price_change_pct_24h=2.0,
            range_pct_24h=4.0,
            high_24h=102.0,
            low_24h=98.0,
        )
        base_profile = build_strategy_profile("trend", "binance", base_metrics)
        assert base_profile is not None
        config.apply_strategy_profile(base_profile)
        config.active_selection_profile = base_profile.name
        config.active_selection_profile_reason = base_profile.reason
        return config

    def test_evaluate_adaptive_policy_applies_trend_profile(self) -> None:
        prices = [100.0 + (index * 0.55) for index in range(80)]
        exchange = FakeAdaptiveExchange(
            build_candles(prices),
            {"bid": 143.80, "ask": 143.95, "last": 143.88},
        )
        path = Path(__file__).resolve().parent / ".tmp_binance_adaptive_report.txt"
        report_json = path.with_suffix(".json")
        try:
            config = self._make_config(report_path=path)
            report = evaluate_adaptive_policy(config, exchange)
            report_text = path.read_text(encoding="utf-8")
            report_json_text = report_json.read_text(encoding="utf-8")
        finally:
            for item in (path, report_json):
                if item.exists():
                    item.unlink()

        self.assertTrue(report.applied)
        self.assertIsNotNone(report.selected_profile)
        assert report.selected_profile is not None
        self.assertEqual(report.selected_profile.name, "trend_momentum")
        self.assertEqual(config.active_strategy_profile, "trend_momentum")
        self.assertEqual(config.timeframe, "15m")
        self.assertEqual(config.ema_fast_period, 8)
        self.assertEqual(config.ema_slow_period, 21)
        self.assertIn("trend_momentum", report_text)
        self.assertIn("timeframe=15m", report_text)
        self.assertIn("adaptive_mode", report_json_text)

    def test_evaluate_adaptive_policy_falls_back_when_history_is_short(self) -> None:
        prices = [100.0 + (index * 0.1) for index in range(10)]
        exchange = FakeAdaptiveExchange(
            build_candles(prices),
            {"bid": 100.90, "ask": 101.05, "last": 100.98},
        )
        path = Path(__file__).resolve().parent / ".tmp_binance_adaptive_fallback.txt"
        report_json = path.with_suffix(".json")
        try:
            config = self._make_config(report_path=path)
            report = evaluate_adaptive_policy(config, exchange)
            report_text = path.read_text(encoding="utf-8")
        finally:
            for item in (path, report_json):
                if item.exists():
                    item.unlink()

        self.assertFalse(report.applied)
        self.assertIsNone(report.selected_profile)
        self.assertIn("Fallback", report_text)
        self.assertIn("Recent candle history is too short", report.fallback_reason)
        self.assertEqual(config.active_strategy_profile, "trend")


if __name__ == "__main__":
    unittest.main()
