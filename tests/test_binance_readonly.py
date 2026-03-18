from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.binance.adaptive import AdaptiveDecisionReport, RecentHistorySnapshot
from app.binance.config import Config as BinanceConfig
from app.binance.main import _adaptive_runtime_allows
from app.binance.models import AccountSnapshot, WalletHolding
from app.binance.readonly_report import build_live_readonly_report, write_live_readonly_report
from app.binance.exchange import SymbolRules
from app.binance.state import BotState
from app.selection.models import MarketMetrics
from app.selection.profiles import build_strategy_profile
from app.selection.runtime import RuntimeSelection


class BinanceLiveReadonlyTest(unittest.TestCase):
    def _make_config(self) -> BinanceConfig:
        config = BinanceConfig(
            api_key="test-key",
            api_secret="test-secret",
            bot_mode="live_readonly",
            execution_mode="auto",
            selection_mode="scan",
            strategy_profile="auto",
            adaptive_mode="paper",
            use_testnet=False,
        )
        config.symbol = "SOL/USDT"
        config.timeframe = "15m"
        config.max_trade_usd = 25
        config.risk_per_trade = 0.01
        config.stop_loss_pct = 0.02
        config.take_profit_pct = 0.03
        config.fee_rate = 0.001
        config.slippage_buffer_pct = 0.001
        config.use_rsi_filter = True
        return config

    def test_validate_requires_mainnet_for_live_readonly(self) -> None:
        config = self._make_config()
        config.validate()

        blocked = self._make_config()
        blocked.use_testnet = True
        with self.assertRaises(ValueError):
            blocked.validate()

    def test_adaptive_runtime_allows_paper_overlay_in_live_readonly(self) -> None:
        config = self._make_config()
        self.assertTrue(_adaptive_runtime_allows(config))

    def test_live_readonly_report_writes_text_and_json(self) -> None:
        config = self._make_config()
        profile_metrics = MarketMetrics(
            last_price=150.0,
            bid=149.8,
            ask=150.2,
            spread=0.4,
            spread_bps=26.6,
            volume_quote_24h=25_000_000.0,
            trade_count_24h=18_000,
            price_change_pct_24h=2.5,
            range_pct_24h=4.2,
            high_24h=154.0,
            low_24h=145.5,
        )
        selection_profile = build_strategy_profile("trend", "binance", profile_metrics)
        assert selection_profile is not None
        selection = RuntimeSelection(
            venue="binance",
            symbol="SOL/USDT",
            market_id="SOLUSDT",
            source="scan",
            metrics=profile_metrics,
            strategy_profile=selection_profile,
            path=Path("data/market/binance_candidates.csv"),
            report_path=Path("data/market/binance_candidates_report.txt"),
            report_json_path=Path("data/market/binance_candidates_report.json"),
            summary="SOL/USDT score=91.2 rank=1 profile=trend",
            explanation="Selected market\nWhy: highest score in scan",
        )
        history = RecentHistorySnapshot(
            symbol="SOL/USDT",
            timeframe="15m",
            scanned_at="2026-03-18T00:00:00+00:00",
            candle_limit=300,
            closed_candles=280,
            analysis_candles=96,
            last_close=150.0,
            bid=149.8,
            ask=150.2,
            spread_bps=26.6,
            return_6_pct=1.2,
            return_24_pct=4.8,
            realized_volatility_pct=1.9,
            atr_pct=1.4,
            trend_strength_pct=2.1,
            slope_pct_per_candle=0.17,
            range_pct=4.2,
            volume_quote_recent=12_500_000.0,
            volume_quote_prior=9_800_000.0,
            volume_ratio=1.28,
            direction_consistency=0.67,
            close_location_pct=78.0,
        )
        adaptive_profile = build_strategy_profile("trend", "binance", profile_metrics)
        assert adaptive_profile is not None
        adaptive_report = AdaptiveDecisionReport(
            venue="binance",
            symbol="SOL/USDT",
            timeframe="15m",
            scanned_at=history.scanned_at,
            bot_mode="live_readonly",
            adaptive_mode="paper",
            base_profile_name="trend",
            base_profile_reason="scan-selected base profile",
            regime="trend",
            regime_reason="sustained momentum",
            evidence=("trend strength positive", "volume expanding"),
            history=history,
            selected_profile=adaptive_profile,
            applied=True,
            fallback_reason="",
        )
        snapshot = AccountSnapshot(
            quote_asset="USDT",
            quote_free=180.0,
            quote_locked=0.0,
            base_asset="SOL",
            base_free=1.2,
            base_locked=0.0,
            holdings=[
                WalletHolding(asset="USDT", free=180.0, locked=0.0, total=180.0),
                WalletHolding(asset="SOL", free=1.2, locked=0.0, total=1.2),
            ],
            maker_fee=0.001,
            taker_fee=0.001,
            captured_at="2026-03-18T00:00:00+00:00",
        )
        state = BotState(account_snapshot=snapshot)
        market_rules = SymbolRules(
            symbol="SOL/USDT",
            base_asset="SOL",
            quote_asset="USDT",
            min_qty=0.01,
            max_qty=10_000,
            qty_step=0.01,
            market_min_qty=0.01,
            market_max_qty=10_000,
            market_qty_step=0.01,
            min_price=0.01,
            max_price=100_000,
            tick_size=0.01,
            min_notional=5.0,
            max_notional=100_000.0,
        )
        report = build_live_readonly_report(
            config=config,
            state=state,
            market_rules=market_rules,
            signal="buy",
            signal_price=150.0,
            live_price=151.0,
            ema_fast=149.2,
            ema_slow=148.4,
            rsi=62.0,
            gates={
                "crossed_up": True,
                "crossed_down": False,
                "rsi_buy_ok": True,
                "rsi_sell_ok": False,
            },
            htf_text="1h_rsi=56.0",
            htf_ok=True,
            available_quote=180.0,
            candle_time="2026-03-18T00:15:00+00:00",
            selection=selection,
            selection_note="scan selected the strongest trending market",
            adaptive_report=adaptive_report,
            adaptive_note="adaptive overlay applied in read-only mode",
        )

        path = Path(__file__).resolve().parent / ".tmp_binance_live_readonly_report.txt"
        json_path = path.with_suffix(".json")
        try:
            write_live_readonly_report(report, path)
            text = path.read_text(encoding="utf-8")
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        finally:
            path.unlink(missing_ok=True)
            json_path.unlink(missing_ok=True)

        self.assertIn("Binance live read-only report", text)
        self.assertIn("Live read-only guard", text)
        self.assertIn("Selected candidate", text)
        self.assertIn("Adaptive overlay", text)
        self.assertIn("Proposed action: `BUY`", text)
        self.assertIn("Entry plan:", text)
        self.assertEqual(payload["decision_action"], "BUY")
        self.assertEqual(payload["blocked_by"], "live_readonly (no submit/test/cancel)")
        self.assertEqual(payload["selection"]["symbol"], "SOL/USDT")
        self.assertEqual(payload["adaptive_report"]["selected_profile"]["name"], adaptive_profile.name)


if __name__ == "__main__":
    unittest.main()
