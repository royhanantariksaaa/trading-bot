from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ..common.env import env_bool
from ..utils.storage import market_data_path, resolve_project_path
from .binance import scan_binance_markets
from .export import write_selection_csv
from .filters import SelectionFilters
from .polymarket import polymarket_filters, polymarket_scoring, scan_polymarket_markets
from .scoring import ScoringConfig


def _parse_quotes(raw: list[str]) -> tuple[str, ...]:
    quotes: list[str] = []
    for item in raw:
        for part in item.split(","):
            part = part.strip().upper()
            if part:
                quotes.append(part)
    return tuple(quotes)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.selection",
        description="Scan Binance or Polymarket markets, score candidates, and export a ranked CSV to data/market/.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--venue", choices=("binance", "polymarket"), default="binance", help="Venue to scan")
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="CSV output path. Defaults to data/market/<venue>_candidates.csv",
    )
    parser.add_argument("--top", type=int, default=20, help="How many ranked candidates to print")
    parser.add_argument("--allowed-quotes", nargs="+", default=["USDT", "USDC"], help="Allowed quote assets")
    parser.add_argument("--min-last-price", type=float, default=0.0001, help="Minimum last price")
    parser.add_argument("--min-quote-volume", type=float, default=1_000_000.0, help="Minimum 24h quote volume")
    parser.add_argument("--min-trade-count", type=int, default=100, help="Minimum 24h trade count")
    parser.add_argument("--max-spread-bps", type=float, default=100.0, help="Maximum spread in basis points")
    parser.add_argument(
        "--max-entry-notional",
        type=float,
        default=float(os.getenv("MAX_TRADE_USD", "5")),
        help="Maximum entry notional used by filters",
    )
    parser.add_argument("--liquidity-target", type=float, default=50_000_000.0, help="Liquidity target used for scoring")
    parser.add_argument("--trade-count-target", type=float, default=20_000.0, help="Trade-count target used for scoring")
    parser.add_argument("--spread-cap-bps", type=float, default=100.0, help="Worst spread used by scoring")
    parser.add_argument("--movement-target-pct", type=float, default=5.0, help="Movement target used for scoring")
    parser.add_argument(
        "--testnet",
        action="store_true",
        default=env_bool(os.getenv("BINANCE_SELECTION_TESTNET"), False),
        help="Use Binance testnet endpoints",
    )
    parser.add_argument(
        "--polymarket-outcome",
        choices=("yes", "no", "all"),
        default=os.getenv("PM_SELECTION_OUTCOME", "yes").strip().lower() or "yes",
        help="Which Polymarket outcomes to scan",
    )
    parser.add_argument(
        "--book-limit",
        type=int,
        default=int(os.getenv("PM_SELECTION_BOOK_LIMIT", "25")),
        help="How many Polymarket markets get a live CLOB book fetch",
    )
    return parser.parse_args(argv)


def _resolve_output_path(raw_output: str, venue: str) -> Path:
    if raw_output:
        return resolve_project_path(raw_output)
    return market_data_path(f"{venue.strip().lower()}_candidates.csv")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    venue = args.venue.strip().lower()
    parsed_quotes = _parse_quotes(args.allowed_quotes)
    if venue == "polymarket":
        filters = polymarket_filters(args.max_entry_notional, allowed_quotes=parsed_quotes or ("USDC",))
        filters.min_last_price = args.min_last_price
        filters.min_quote_volume_24h = args.min_quote_volume
        filters.min_trade_count_24h = args.min_trade_count
        filters.max_spread_bps = args.max_spread_bps
        scoring = polymarket_scoring()
        scoring.volume_target_quote_24h = args.liquidity_target
        scoring.trade_count_target_24h = args.trade_count_target
        scoring.spread_cap_bps = args.spread_cap_bps
        scoring.movement_target_pct = args.movement_target_pct
    else:
        filters = SelectionFilters(
            allowed_quotes=parsed_quotes,
            min_last_price=args.min_last_price,
            min_quote_volume_24h=args.min_quote_volume,
            min_trade_count_24h=args.min_trade_count,
            max_spread_bps=args.max_spread_bps,
            max_entry_notional=args.max_entry_notional,
        )
        scoring = ScoringConfig(
            volume_target_quote_24h=args.liquidity_target,
            trade_count_target_24h=args.trade_count_target,
            spread_cap_bps=args.spread_cap_bps,
            movement_target_pct=args.movement_target_pct,
        )

    try:
        if venue == "polymarket":
            result = scan_polymarket_markets(
                filters=filters,
                scoring=scoring,
                allowed_quotes=filters.allowed_quotes,
                outcome_mode=args.polymarket_outcome,
                limit=max(args.top, args.book_limit, 25),
                book_limit=args.book_limit,
            )
        else:
            result = scan_binance_markets(
                filters=filters,
                scoring=scoring,
                allowed_quotes=filters.allowed_quotes,
                use_testnet=args.testnet,
            )
        output_path = _resolve_output_path(args.output, venue)
        write_selection_csv(result, output_path)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(result.summary())
    for item in result.ranked[: max(0, args.top)]:
        metrics = item.candidate.metrics
        print(
            f"{item.rank:>3}. {item.candidate.symbol:<18} score={item.score:6.2f} "
            f"vol={metrics.volume_quote_24h or 0:,.0f} spread_bps={metrics.spread_bps or 0:.2f} "
            f"last={metrics.last_price or 0:.8f}"
        )
    if not result.ranked:
        print("No candidates passed the filters.")
    print(f"CSV exported to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
