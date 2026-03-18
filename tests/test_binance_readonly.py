from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.binance.adaptive import AdaptiveDecisionReport, RecentHistorySnapshot
from app.binance.config import Config as BinanceConfig
from app.binance.main import _adaptive_runtime_allows
from app.binance.models import AccountSnapshot, DustHolding, WalletHolding
from app.binance.readonly_report import (
    HoldingSignalSnapshot,
    build_live_readonly_report,
    format_live_readonly_notification,
    readonly_decision_summary_key,
    readonly_notification_key,
    write_live_readonly_report,
)
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

    def test_validate_requires_positive_readonly_discord_intervals(self) -> None:
        config = self._make_config()
        config.readonly_compact_interval_seconds = 0
        with self.assertRaises(ValueError):
            config.validate()

        config = self._make_config()
        config.readonly_heartbeat_interval_seconds = 0
        with self.assertRaises(ValueError):
            config.validate()

    def _make_symbol_rules(self) -> SymbolRules:
        return SymbolRules(
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
            dust_holdings=[
                DustHolding(
                    asset="XRP",
                    free=2.0,
                    locked=0.0,
                    total=2.0,
                    symbol="XRP/USDT",
                    notional=1.1,
                    actionable_threshold=5.25,
                    reason="notional 1.10000000 < actionable threshold 5.25000000",
                )
            ],
            maker_fee=0.001,
            taker_fee=0.001,
            captured_at="2026-03-18T00:00:00+00:00",
        )
        state = BotState(account_snapshot=snapshot)
        market_rules = self._make_symbol_rules()
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
            holding_signals=[
                HoldingSignalSnapshot(
                    asset="SOL",
                    symbol="SOL/USDT",
                    total=1.2,
                    free=1.2,
                    locked=0.0,
                    tradable=True,
                    signal="buy",
                    action="WATCH BUY",
                    reason="buy setup detected on owned asset",
                    signal_price=150.0,
                    live_price=151.0,
                    ema_fast=149.2,
                    ema_slow=148.4,
                    rsi=62.0,
                    htf_text="htf=off",
                    htf_ok=True,
                    gates={
                        "crossed_up": True,
                        "crossed_down": False,
                        "rsi_buy_ok": True,
                        "rsi_sell_ok": False,
                    },
                    estimated_notional=181.2,
                ),
                HoldingSignalSnapshot(
                    asset="ADA",
                    symbol="ADA/USDT",
                    total=30.0,
                    free=30.0,
                    locked=0.0,
                    tradable=True,
                    signal="sell",
                    action="REVIEW SELL",
                    reason="sell setup detected on owned asset",
                    signal_price=1.1,
                    live_price=1.08,
                    ema_fast=1.09,
                    ema_slow=1.10,
                    rsi=43.0,
                    htf_text="4h_rsi=48.0",
                    htf_ok=False,
                    gates={
                        "crossed_up": False,
                        "crossed_down": True,
                        "rsi_buy_ok": False,
                        "rsi_sell_ok": True,
                    },
                    estimated_notional=32.4,
                ),
                HoldingSignalSnapshot(
                    asset="LDUSDC",
                    symbol="LDUSDC/USDT",
                    total=5.0,
                    free=5.0,
                    locked=0.0,
                    tradable=False,
                    note="no active spot market found for holding against quote asset",
                )
            ],
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
        self.assertIn("Wallet-only holdings:", text)
        self.assertIn("SOL: action=HOLD", text)
        self.assertIn("Holding signals", text)
        self.assertIn("action=`WATCH BUY` | signal=`buy`", text)
        self.assertIn("Dust / unactionable inventory", text)
        self.assertIn("XRP: action=CANNOT ACT", text)
        self.assertIn("Proposed action: `BUY`", text)
        self.assertIn("Entry plan:", text)
        self.assertEqual(payload["decision_action"], "BUY")
        self.assertEqual(payload["blocked_by"], "live_readonly (no submit/test/cancel)")
        self.assertEqual(payload["selection"]["symbol"], "SOL/USDT")
        self.assertEqual(payload["adaptive_report"]["selected_profile"]["name"], adaptive_profile.name)
        self.assertEqual(payload["account_snapshot"]["dust_holdings"][0]["asset"], "XRP")

        notification = format_live_readonly_notification(report, include_selection=True, include_adaptive=True)
        self.assertIn("[BINANCE READONLY]", notification)
        self.assertIn("Selected market:", notification)
        self.assertIn("Adaptive summary:", notification)
        self.assertIn("Action: `BUY`", notification)
        self.assertIn("Reason: `buy signal passed sizing and filters`", notification)
        self.assertIn("Reports:", notification)

        heartbeat = format_live_readonly_notification(
            report,
            include_selection=True,
            include_adaptive=True,
            reminder=True,
        )
        self.assertIn("[BINANCE READONLY HEARTBEAT]", heartbeat)

        compact = format_live_readonly_notification(
            report,
            include_selection=True,
            compact=True,
        )
        self.assertIn("[BINANCE READONLY COMPACT]", compact)
        self.assertIn("Selected market:", compact)
        self.assertIn("RSI:", compact)
        self.assertIn("EMA:", compact)
        self.assertIn("Exposure:", compact)
        self.assertIn("Owned assets:", compact)
        self.assertIn("Owned signals:", compact)
        self.assertIn("Owned setups:", compact)
        self.assertIn("Plan:", compact)
        self.assertIn("ADA=REVIEW SELL", compact)
        self.assertIn("SOL=WATCH BUY", compact)
        self.assertIn("LDUSDC=BLOCKED", compact)
        self.assertIn("SOL=buy_above:", compact)
        self.assertNotIn("Adaptive summary:", compact)
        self.assertNotIn("Reports:", compact)

        first_key = readonly_notification_key(report)
        self.assertIn("BUY", first_key)
        report.decision_reason = "changed reason"
        self.assertNotEqual(first_key, readonly_notification_key(report))

        changed_key = readonly_notification_key(report)
        report.decision_reason = "buy signal passed sizing and filters"
        report.selection = RuntimeSelection(
            venue="binance",
            symbol="ADA/USDT",
            market_id="ADAUSDT",
            source="scan",
            summary="ADA/USDT score=95.0 rank=1 profile=range",
        )
        self.assertNotEqual(changed_key, readonly_notification_key(report))

        changed_key = readonly_notification_key(report)
        report.adaptive_note = "adaptive overlay fallback changed"
        report.adaptive_report = None
        self.assertNotEqual(changed_key, readonly_notification_key(report))

    def test_decision_summary_key_tracks_snapshot_changes_that_notification_key_misses(self) -> None:
        config = self._make_config()
        state = BotState()
        report = build_live_readonly_report(
            config=config,
            state=state,
            market_rules=self._make_symbol_rules(),
            signal="hold",
            signal_price=150.0,
            live_price=151.0,
            ema_fast=149.2,
            ema_slow=148.4,
            rsi=49.0,
            gates={
                "crossed_up": False,
                "crossed_down": False,
                "rsi_buy_ok": False,
                "rsi_sell_ok": False,
                "buy_ready": False,
                "sell_ready": False,
            },
            htf_text="htf=off",
            htf_ok=True,
            available_quote=180.0,
            candle_time="2026-03-18T00:15:00+00:00",
        )

        coarse_key = readonly_notification_key(report)
        summary_key = readonly_decision_summary_key(report)

        report.live_price = 151.75
        report.signal_price = 150.5
        report.ema_fast = 149.55
        report.ema_slow = 148.95
        report.rsi = 51.23
        report.available_quote = 179.5

        self.assertEqual(coarse_key, readonly_notification_key(report))
        self.assertNotEqual(summary_key, readonly_decision_summary_key(report))

    def test_decision_summary_key_ignores_micro_noise_within_rounding_bucket(self) -> None:
        config = self._make_config()
        state = BotState()
        report = build_live_readonly_report(
            config=config,
            state=state,
            market_rules=self._make_symbol_rules(),
            signal="hold",
            signal_price=150.0,
            live_price=151.0,
            ema_fast=149.2,
            ema_slow=148.4,
            rsi=49.0,
            gates={
                "crossed_up": False,
                "crossed_down": False,
                "rsi_buy_ok": False,
                "rsi_sell_ok": False,
                "buy_ready": False,
                "sell_ready": False,
            },
            htf_text="htf=off",
            htf_ok=True,
            available_quote=180.0,
            candle_time="2026-03-18T00:15:00+00:00",
        )

        summary_key = readonly_decision_summary_key(report)
        report.live_price = 151.00004
        report.signal_price = 150.00004
        report.ema_fast = 149.20004
        report.ema_slow = 148.40004
        report.rsi = 49.004
        report.available_quote = 180.004

        self.assertEqual(summary_key, readonly_decision_summary_key(report))


if __name__ == "__main__":
    unittest.main()
