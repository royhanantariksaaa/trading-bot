from __future__ import annotations

import csv
import unittest
from pathlib import Path

from app.selection.binance import BinanceMarketScanner
from app.selection.export import write_selection_csv
from app.selection.filters import SelectionFilters
from app.selection.models import MarketCandidate, MarketConstraints, MarketMetrics
from app.selection.scoring import ScoringConfig
from app.selection.selector import MarketSelectionConfig, select_markets


def make_candidate(
    symbol: str,
    *,
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
        venue="binance",
        symbol=symbol,
        market_id=symbol.replace("/", ""),
        base_asset=base_asset,
        quote_asset=quote_asset,
        market_type="spot",
        status="TRADING",
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

    def test_csv_export_writes_ranked_rows(self) -> None:
        result = select_markets(
            [make_candidate("SOL/USDT"), make_candidate("ADA/USDT", base_asset="ADA", volume_quote_24h=25_000_000.0, spread_bps=250.0)],
            MarketSelectionConfig(filters=SelectionFilters(allowed_quotes=("USDT",), max_entry_notional=5.0)),
            venue="binance",
            scanned_at="2026-03-18T00:00:00+00:00",
        )

        path = Path(__file__).resolve().parent / ".tmp_selection_candidates.csv"
        try:
            write_selection_csv(result, path)
            with path.open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        finally:
            if path.exists():
                path.unlink()

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["symbol"], "SOL/USDT")
        self.assertEqual(rows[0]["accepted"], "true")
        self.assertIn("score_total", rows[0])
        self.assertIn("filter_failures", rows[0])

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


if __name__ == "__main__":
    unittest.main()
