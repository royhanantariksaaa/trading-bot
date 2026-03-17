from __future__ import annotations

import csv
import unittest
from pathlib import Path

from app.binance.config import Config as BinanceConfig
from app.polymarket.config import Config as PolymarketConfig
from app.selection.binance import BinanceMarketScanner
from app.selection.export import report_paths_from_csv_path, write_selection_csv, write_selection_report, write_selection_report_json
from app.selection.filters import SelectionFilters
from app.selection.models import MarketCandidate, MarketConstraints, MarketMetrics
from app.selection.polymarket import PolymarketMarketScanner, scan_polymarket_markets
from app.selection.runtime import RotationController, load_runtime_selection, maybe_rotate_runtime_selection
from app.selection.scoring import ScoringConfig
from app.selection.selector import MarketSelectionConfig, select_markets


def make_candidate(
    symbol: str,
    *,
    venue: str = "binance",
    base_asset: str = "SOL",
    quote_asset: str = "USDT",
    last_price: float = 100.0,
    bid: float = 99.95,
    ask: float = 100.05,
    volume_quote_24h: float = 10_000_000.0,
    trade_count_24h: int = 5_000,
    spread_bps: float = 10.0,
    range_pct_24h: float = 4.0,
    min_notional: float = 5.0,
    min_qty: float = 0.01,
    qty_step: float = 0.01,
) -> MarketCandidate:
    return MarketCandidate(
        venue=venue,
        symbol=symbol,
        market_id=symbol.replace("/", "").replace(":", "_"),
        base_asset=base_asset,
        quote_asset=quote_asset,
        market_type="binary" if venue == "polymarket" else "spot",
        status="ACTIVE" if venue == "polymarket" else "TRADING",
        active=True,
        tradable=True,
        constraints=MarketConstraints(
            min_qty=min_qty,
            qty_step=qty_step,
            min_notional=min_notional,
        ),
        metrics=MarketMetrics(
            last_price=last_price,
            bid=bid,
            ask=ask,
            spread=ask - bid,
            spread_bps=spread_bps,
            volume_base_24h=volume_quote_24h / last_price,
            volume_quote_24h=volume_quote_24h,
            trade_count_24h=trade_count_24h,
            price_change_pct_24h=2.0,
            range_pct_24h=range_pct_24h,
            high_24h=last_price * 1.02,
            low_24h=last_price * 0.98,
        ),
        scanned_at="2026-03-18T00:00:00+00:00",
        source="test",
    )


class SelectionTest(unittest.TestCase):
    def test_selector_filters_and_ranks_candidates(self) -> None:
        candidates = [
            make_candidate("SOL/USDT"),
            make_candidate("BTC/USDT", base_asset="BTC", last_price=70_000.0, bid=69_990.0, ask=70_030.0, min_qty=0.0001, qty_step=0.0001),
            make_candidate("LOW/USDT", base_asset="LOW", volume_quote_24h=50_000.0, trade_count_24h=20),
            make_candidate("WIDE/USDT", base_asset="WIDE", spread_bps=250.0),
        ]

        result = select_markets(
            candidates,
            MarketSelectionConfig(
                filters=SelectionFilters(
                    allowed_quotes=("USDT",),
                    min_quote_volume_24h=1_000_000.0,
                    min_trade_count_24h=100,
                    max_spread_bps=100.0,
                    max_entry_notional=5.0,
                ),
                scoring=ScoringConfig(),
            ),
            venue="binance",
            scanned_at="2026-03-18T00:00:00+00:00",
        )

        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.selected.candidate.symbol, "SOL/USDT")
        self.assertEqual(result.ranked[0].rank, 1)
        self.assertFalse(result.evaluated[1].accepted)
        self.assertFalse(result.evaluated[2].accepted)
        self.assertFalse(result.evaluated[3].accepted)

    def test_explainable_scores_include_components_penalties_and_report(self) -> None:
        result = select_markets(
            [
                make_candidate("SOL/USDT", volume_quote_24h=45_000_000.0, trade_count_24h=30_000, spread_bps=6.0, range_pct_24h=4.5),
                make_candidate("DOGE/USDT", volume_quote_24h=20_000_000.0, trade_count_24h=8_000, spread_bps=32.0, range_pct_24h=16.0),
            ],
            MarketSelectionConfig(filters=SelectionFilters(allowed_quotes=("USDT",), max_entry_notional=5.0), scoring=ScoringConfig()),
            venue="binance",
            scanned_at="2026-03-18T00:00:00+00:00",
        )
        best = result.selected
        assert best is not None
        self.assertGreaterEqual(len(best.score_breakdown.components), 5)
        self.assertTrue(any(component.name == "depth" for component in best.score_breakdown.components))
        self.assertIn("scored", " ".join(best.score_breakdown.explanation))
        other = result.ranked[1]
        self.assertTrue(any(penalty.name == "wide_spread" for penalty in other.score_breakdown.penalty_items))

    def test_csv_export_writes_ranked_rows_and_report_paths(self) -> None:
        result = select_markets(
            [make_candidate("SOL/USDT"), make_candidate("ADA/USDT", base_asset="ADA", volume_quote_24h=25_000_000.0, spread_bps=250.0)],
            MarketSelectionConfig(filters=SelectionFilters(allowed_quotes=("USDT",), max_entry_notional=5.0)),
            venue="binance",
            scanned_at="2026-03-18T00:00:00+00:00",
        )

        path = Path(__file__).resolve().parent / ".tmp_selection_candidates.csv"
        report_path, report_json_path = report_paths_from_csv_path(path)
        try:
            write_selection_csv(result, path)
            write_selection_report(result, report_path)
            write_selection_report_json(result, report_json_path)
            with path.open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        finally:
            for item in (path, report_path, report_json_path):
                if item.exists():
                    item.unlink()

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["symbol"], "SOL/USDT")
        self.assertEqual(rows[0]["accepted"], "true")
        self.assertIn("score_total", rows[0])
        self.assertIn("filter_failures", rows[0])
        self.assertIn("score_explanation", rows[0])

    def test_runtime_selection_reads_explanation_from_csv(self) -> None:
        result = select_markets(
            [make_candidate("SOL/USDT")],
            MarketSelectionConfig(filters=SelectionFilters(allowed_quotes=("USDT",), max_entry_notional=5.0)),
            venue="binance",
            scanned_at="2026-03-18T00:00:00+00:00",
        )
        path = Path(__file__).resolve().parent / ".tmp_runtime_selection.csv"
        try:
            write_selection_csv(result, path)
            selection = load_runtime_selection(path, venue="binance")
        finally:
            if path.exists():
                path.unlink()
        self.assertIsNotNone(selection)
        assert selection is not None
        self.assertEqual(selection.symbol, "SOL/USDT")
        self.assertIn("score", selection.summary)
        self.assertIn("scored", selection.explanation)

    def test_rotation_decision_detects_symbol_change(self) -> None:
        result = select_markets(
            [make_candidate("ADA/USDT"), make_candidate("SOL/USDT", volume_quote_24h=5_000_000.0)],
            MarketSelectionConfig(filters=SelectionFilters(allowed_quotes=("USDT",), max_entry_notional=5.0)),
            venue="binance",
            scanned_at="2026-03-18T00:00:00+00:00",
        )
        path = Path(__file__).resolve().parent / ".tmp_rotation_selection.csv"
        report_path, report_json_path = report_paths_from_csv_path(path)
        try:
            write_selection_csv(result, path)
            write_selection_report(result, report_path)
            write_selection_report_json(result, report_json_path)
            decision = maybe_rotate_runtime_selection("binance", mode="csv", output_path=path, current_symbol="SOL/USDT")
        finally:
            for item in (path, report_path, report_json_path):
                if item.exists():
                    item.unlink()
        self.assertTrue(decision.changed)
        self.assertEqual(decision.new_symbol, "ADA/USDT")
        self.assertIsNotNone(decision.selection)

    def test_rotation_controller_schedule(self) -> None:
        controller = RotationController(enabled=True, every_loops=3, next_due_loop=3)
        self.assertFalse(controller.should_rotate(2))
        self.assertTrue(controller.should_rotate(3))
        controller.mark_executed(3)
        self.assertEqual(controller.next_due_loop, 6)

    def test_binance_config_rotation_defaults(self) -> None:
        config = BinanceConfig(selection_mode="scan", selection_rotation_loops=5)
        controller = config.rotation_controller
        self.assertTrue(controller.enabled)
        self.assertEqual(controller.every_loops, 5)

    def test_polymarket_config_rotation_defaults(self) -> None:
        config = PolymarketConfig(token_id="abc", selection_mode="csv", selection_rotation_loops=2)
        controller = config.rotation_controller
        self.assertTrue(controller.enabled)
        self.assertEqual(controller.next_due_loop, 2)

    def test_binance_scanner_normalizes_candidate_metadata(self) -> None:
        class FakeExchange:
            def __init__(self) -> None:
                self.markets = {
                    "SOL/USDT": {
                        "symbol": "SOL/USDT",
                        "id": "SOLUSDT",
                        "base": "SOL",
                        "quote": "USDT",
                        "spot": True,
                        "active": True,
                        "type": "spot",
                        "status": "TRADING",
                        "info": {
                            "status": "TRADING",
                            "filters": [
                                {"filterType": "LOT_SIZE", "minQty": "0.01", "maxQty": "1000", "stepSize": "0.01"},
                                {"filterType": "MARKET_LOT_SIZE", "minQty": "0.01", "maxQty": "1000", "stepSize": "0.01"},
                                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                                {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
                            ],
                        },
                        "limits": {"amount": {"min": 0.01, "max": 1000}, "cost": {"min": 5}},
                        "precision": {"amount": 2, "price": 2},
                    }
                }

            def load_markets(self):
                return self.markets

            def fetch_tickers(self):
                return {
                    "SOL/USDT": {
                        "symbol": "SOL/USDT",
                        "last": 100.0,
                        "bid": 99.9,
                        "ask": 100.1,
                        "baseVolume": 1234.5,
                        "quoteVolume": 123450.0,
                        "percentage": 4.2,
                        "high": 105.0,
                        "low": 95.0,
                        "info": {"count": 321},
                    }
                }

        scanner = BinanceMarketScanner(exchange=FakeExchange(), allowed_quotes=("USDT",))
        candidates = scanner.scan()

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.symbol, "SOL/USDT")
        self.assertEqual(candidate.constraints.min_notional, 5.0)
        self.assertEqual(candidate.constraints.qty_step, 0.01)
        self.assertAlmostEqual(candidate.metrics.spread_bps or 0.0, 20.0, places=6)
        self.assertEqual(candidate.metrics.trade_count_24h, 321)

    def test_polymarket_scanner_normalizes_yes_outcome(self) -> None:
        class FakePolymarketClient:
            def list_markets(self, **kwargs):
                return [
                    {
                        "id": "123",
                        "slug": "fed-cuts-rates",
                        "question": "Fed cuts rates?",
                        "active": True,
                        "closed": False,
                        "acceptingOrders": True,
                        "enableOrderBook": True,
                        "clobTokenIds": '["yes-token", "no-token"]',
                        "outcomes": '["Yes", "No"]',
                        "outcomePrices": '["0.43", "0.57"]',
                        "volume24hrClob": 25000,
                        "oneDayPriceChange": 0.07,
                        "commentCount": 42,
                    }
                ]

            def get_book(self, token_id: str):
                self.last_book_token = token_id
                return {
                    "asset_id": token_id,
                    "bids": [{"price": "0.42", "size": "100"}],
                    "asks": [{"price": "0.44", "size": "120"}],
                    "min_order_size": "5",
                    "tick_size": "0.01",
                }

        scanner = PolymarketMarketScanner(client=FakePolymarketClient(), allowed_quotes=("USDC",), outcome_mode="yes")
        candidates = scanner.scan()

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.market_id, "yes-token")
        self.assertEqual(candidate.symbol, "fed-cuts-rates:YES")
        self.assertEqual(candidate.quote_asset, "USDC")
        self.assertEqual(candidate.market_type, "binary")
        self.assertAlmostEqual(candidate.metrics.last_price or 0.0, 0.43, places=6)
        self.assertAlmostEqual(candidate.metrics.spread_bps or 0.0, ((0.44 - 0.42) / 0.43) * 10000, places=4)

    def test_polymarket_scan_and_csv_runtime_selection(self) -> None:
        class FakePolymarketClient:
            def list_markets(self, **kwargs):
                return [
                    {
                        "id": "123",
                        "slug": "fed-cuts-rates",
                        "question": "Fed cuts rates?",
                        "active": True,
                        "closed": False,
                        "acceptingOrders": True,
                        "enableOrderBook": True,
                        "clobTokenIds": '["yes-token", "no-token"]',
                        "outcomes": '["Yes", "No"]',
                        "outcomePrices": '["0.43", "0.57"]',
                        "volume24hrClob": 25000,
                        "oneDayPriceChange": 0.07,
                        "commentCount": 42,
                    }
                ]

            def get_book(self, token_id: str):
                return {
                    "asset_id": token_id,
                    "bids": [{"price": "0.42", "size": "100"}],
                    "asks": [{"price": "0.44", "size": "120"}],
                    "min_order_size": "5",
                    "tick_size": "0.01",
                }

        result = scan_polymarket_markets(client=FakePolymarketClient(), limit=5, book_limit=5)
        self.assertIsNotNone(result.selected)
        path = Path(__file__).resolve().parent / ".tmp_polymarket_candidates.csv"
        report_path, report_json_path = report_paths_from_csv_path(path)
        try:
            write_selection_csv(result, path)
            write_selection_report(result, report_path)
            write_selection_report_json(result, report_json_path)
            selection = load_runtime_selection(path, venue="polymarket")
        finally:
            for item in (path, report_path, report_json_path):
                if item.exists():
                    item.unlink()

        self.assertIsNotNone(selection)
        assert selection is not None
        self.assertEqual(selection.market_id, "yes-token")
        self.assertEqual(selection.symbol, "fed-cuts-rates:YES")
        self.assertTrue(selection.report_path is None or selection.report_path.name.endswith("_report.txt"))


if __name__ == "__main__":
    unittest.main()
