from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.portfolio.allocator import allocate_portfolio
from app.portfolio.models import PortfolioCandidate, PortfolioPosition, PortfolioRiskCaps, PortfolioState, VenueAccountingState
from app.portfolio.reports import build_allocation_report, write_allocation_report, write_allocation_report_json
from app.portfolio.state import apply_allocation_report, load_state, save_state, today_str
from app.selection.models import MarketMetrics
from app.selection.profiles import build_strategy_profile


def make_candidate(
    symbol: str,
    *,
    venue: str = "binance",
    score: float = 90.0,
    rank: int = 1,
    accepted: bool = True,
    last_price: float = 100.0,
    min_notional: float = 5.0,
    max_notional: float = 50.0,
    spread_bps: float = 10.0,
    volume_quote_24h: float = 25_000_000.0,
    filter_failures: tuple[str, ...] = (),
    source: str = "test",
) -> PortfolioCandidate:
    metrics = MarketMetrics(last_price=last_price, volume_quote_24h=volume_quote_24h, spread_bps=spread_bps)
    profile = build_strategy_profile("trend", venue, metrics)
    return PortfolioCandidate(
        venue=venue,
        symbol=symbol,
        market_id=symbol.replace("/", ""),
        market_type="spot",
        quote_asset="USDT",
        accepted=accepted,
        rank=rank,
        score=score,
        source=source,
        last_price=last_price,
        volume_quote_24h=volume_quote_24h,
        spread_bps=spread_bps,
        min_notional=min_notional,
        max_notional=max_notional,
        strategy_profile=profile,
        score_explanation=(f"score={score:.2f}",),
        filter_failures=filter_failures,
    )


class PortfolioStateTest(unittest.TestCase):
    def test_load_state_rollover_resets_daily_counters_but_keeps_positions(self) -> None:
        path = Path(__file__).resolve().parent / ".tmp_portfolio_state.json"
        try:
            path.write_text(
                json.dumps(
                    {
                        "quote_asset": "USDT",
                        "starting_balance": 100.0,
                        "cash_free": 42.0,
                        "cash_locked": 0.0,
                        "realized_pnl_today": -4.5,
                        "realized_pnl_date": "2026-03-17",
                        "daily_trade_count": 3,
                        "positions": [
                            {
                                "venue": "binance",
                                "symbol": "SOL/USDT",
                                "market_id": "SOLUSDT",
                                "side": "LONG",
                                "status": "OPEN",
                                "qty": 0.5,
                                "entry_price": 100.0,
                                "market_price": 101.0,
                                "entry_notional": 50.0,
                                "target_notional": 50.0,
                                "realized_pnl": 0.0,
                                "entry_fee_usd": 0.1,
                                "opened_at": "2026-03-17T00:00:00+00:00",
                                "updated_at": "2026-03-17T00:00:00+00:00",
                                "strategy_profile_name": "trend",
                                "allocation_score": 91.0,
                                "allocation_reason": "seed",
                                "notes": "",
                            }
                        ],
                        "venue_accounts": {
                            "binance": {
                                "venue": "binance",
                                "cash_free": 42.0,
                                "cash_locked": 0.0,
                                "deployed_notional": 50.0,
                                "open_positions": 1,
                                "realized_pnl_today": -1.0,
                                "last_allocation_at": "2026-03-17T00:00:00+00:00",
                                "last_allocation_summary": "seed",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            state = load_state(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(state.realized_pnl_today, 0.0)
        self.assertEqual(state.realized_pnl_date, today_str())
        self.assertEqual(state.daily_trade_count, 0)
        self.assertEqual(state.cash_free, 42.0)
        self.assertEqual(state.open_position_count, 1)
        self.assertAlmostEqual(state.deployed_notional, 50.0)
        self.assertEqual(state.venue_accounts["binance"].realized_pnl_today, 0.0)


class PortfolioAllocationTest(unittest.TestCase):
    def test_allocate_portfolio_opens_multiple_positions_and_explains_caps(self) -> None:
        state = PortfolioState(
            starting_balance=100.0,
            cash_free=100.0,
            realized_pnl_date=today_str(),
        )
        caps = PortfolioRiskCaps(
            max_total_positions=3,
            max_positions_per_venue=3,
            max_new_positions_per_run=2,
            max_total_notional=10.0,
            max_position_notional=5.0,
            max_venue_notional=10.0,
            reserve_cash_usd=70.0,
            reserve_cash_pct=0.70,
            min_candidate_score=70.0,
            min_entry_notional=5.0,
            max_symbol_positions=1,
        )
        candidates = [
            make_candidate("SOL/USDT", score=92.0, rank=1),
            make_candidate("BTC/USDT", score=84.0, rank=2, last_price=70_000.0, min_notional=5.0),
            make_candidate("ADA/USDT", score=78.0, rank=3),
            make_candidate("WIDE/USDT", score=55.0, rank=4, accepted=False, filter_failures=("spread_bps:wide",)),
        ]

        report = allocate_portfolio(
            candidates,
            state,
            caps,
            available_cash=state.cash_free,
            venue="binance",
            selection_mode="scan",
            source_path="selection.csv",
        )

        self.assertEqual(report.target_positions, 2)
        self.assertEqual(report.accepted_count, 3)
        self.assertEqual(report.rejected_count, 1)
        self.assertEqual(len([decision for decision in report.decisions if decision.action == "open"]), 2)
        self.assertTrue(any(decision.action == "skip" and decision.reason.startswith("No new position slots") for decision in report.decisions))
        self.assertTrue(any("Selector filters rejected" in decision.reason for decision in report.decisions))
        self.assertTrue(any("Opened at a conservative score-weighted size" in decision.reason for decision in report.decisions))

        report_path = Path(__file__).resolve().parent / ".tmp_portfolio_report.txt"
        report_json_path = Path(__file__).resolve().parent / ".tmp_portfolio_report.json"
        try:
            write_allocation_report(report, report_path, top=8)
            write_allocation_report_json(report, report_json_path)
            text = report_path.read_text(encoding="utf-8")
            payload = json.loads(report_json_path.read_text(encoding="utf-8"))
        finally:
            report_path.unlink(missing_ok=True)
            report_json_path.unlink(missing_ok=True)

        self.assertIn("reserve=", text)
        self.assertIn("selector_rejected", text)
        self.assertEqual(len(payload["decisions"]), len(report.decisions))

        apply_allocation_report(
            state,
            report,
            market_prices={
                ("binance", "sol/usdt"): 100.0,
                ("binance", "btc/usdt"): 70000.0,
            },
        )
        self.assertEqual(state.open_position_count, 2)
        self.assertAlmostEqual(state.deployed_notional, 10.0, places=6)
        self.assertAlmostEqual(state.cash_free, 90.0, places=6)
        self.assertEqual(state.venue_position_count("binance"), 2)

    def test_apply_allocation_report_keeps_existing_positions_when_holding(self) -> None:
        state = PortfolioState(
            starting_balance=100.0,
            cash_free=90.0,
            realized_pnl_date=today_str(),
            positions=[
                PortfolioPosition(
                    venue="binance",
                    symbol="SOL/USDT",
                    market_id="SOLUSDT",
                    qty=0.05,
                    entry_price=100.0,
                    market_price=102.0,
                    entry_notional=5.0,
                    target_notional=5.0,
                    opened_at="2026-03-18T00:00:00+00:00",
                    updated_at="2026-03-18T00:00:00+00:00",
                    strategy_profile_name="trend",
                    allocation_score=92.0,
                )
            ],
            venue_accounts={"binance": VenueAccountingState(venue="binance", cash_free=90.0, deployed_notional=5.0, open_positions=1)},
        )
        report = allocate_portfolio(
            [make_candidate("SOL/USDT", score=92.0, rank=1)],
            state,
            PortfolioRiskCaps(max_total_positions=3, max_positions_per_venue=3, max_new_positions_per_run=1, max_total_notional=10.0),
            available_cash=state.cash_free,
            venue="binance",
            selection_mode="scan",
            source_path="selection.csv",
        )
        self.assertTrue(any(decision.action == "hold" for decision in report.decisions))


if __name__ == "__main__":
    unittest.main()
