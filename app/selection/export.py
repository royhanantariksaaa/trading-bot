from __future__ import annotations

import csv
from pathlib import Path

from .selector import ScoredCandidate, SelectionResult


CSV_COLUMNS = [
    "scanned_at",
    "venue",
    "symbol",
    "market_id",
    "market_type",
    "base_asset",
    "quote_asset",
    "status",
    "active",
    "tradable",
    "accepted",
    "rank",
    "score_total",
    "score_liquidity",
    "score_spread",
    "score_activity",
    "score_movement",
    "filter_failures",
    "last_price",
    "bid",
    "ask",
    "spread",
    "spread_bps",
    "volume_base_24h",
    "volume_quote_24h",
    "trade_count_24h",
    "price_change_pct_24h",
    "range_pct_24h",
    "high_24h",
    "low_24h",
    "min_qty",
    "max_qty",
    "qty_step",
    "min_notional",
    "max_notional",
    "tick_size",
    "source",
]


def _format_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def candidate_to_row(item: ScoredCandidate) -> dict[str, str]:
    candidate = item.candidate
    metrics = candidate.metrics
    constraints = candidate.constraints
    failures = [f"{decision.name}:{decision.reason}" for decision in item.filter_decisions if not decision.passed]
    return {
        "scanned_at": candidate.scanned_at,
        "venue": candidate.venue,
        "symbol": candidate.symbol,
        "market_id": candidate.market_id,
        "market_type": candidate.market_type,
        "base_asset": candidate.base_asset,
        "quote_asset": candidate.quote_asset,
        "status": candidate.status,
        "active": _format_value(candidate.active),
        "tradable": _format_value(candidate.tradable),
        "accepted": _format_value(item.accepted),
        "rank": _format_value(item.rank),
        "score_total": _format_value(item.score),
        "score_liquidity": _format_value(item.score_breakdown.liquidity),
        "score_spread": _format_value(item.score_breakdown.spread),
        "score_activity": _format_value(item.score_breakdown.activity),
        "score_movement": _format_value(item.score_breakdown.movement),
        "filter_failures": " | ".join(failures),
        "last_price": _format_value(metrics.last_price),
        "bid": _format_value(metrics.bid),
        "ask": _format_value(metrics.ask),
        "spread": _format_value(metrics.spread),
        "spread_bps": _format_value(metrics.spread_bps),
        "volume_base_24h": _format_value(metrics.volume_base_24h),
        "volume_quote_24h": _format_value(metrics.volume_quote_24h),
        "trade_count_24h": _format_value(metrics.trade_count_24h),
        "price_change_pct_24h": _format_value(metrics.price_change_pct_24h),
        "range_pct_24h": _format_value(metrics.range_pct_24h),
        "high_24h": _format_value(metrics.high_24h),
        "low_24h": _format_value(metrics.low_24h),
        "min_qty": _format_value(constraints.min_qty),
        "max_qty": _format_value(constraints.max_qty),
        "qty_step": _format_value(constraints.qty_step),
        "min_notional": _format_value(constraints.min_notional),
        "max_notional": _format_value(constraints.max_notional),
        "tick_size": _format_value(constraints.tick_size),
        "source": candidate.source,
    }


def write_selection_csv(result: SelectionResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        result.evaluated,
        key=lambda item: (
            0 if item.accepted else 1,
            item.rank if item.rank is not None else 10**9,
            -(item.score_breakdown.total or 0.0),
            item.candidate.symbol,
        ),
    )
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for item in ordered:
            writer.writerow(candidate_to_row(item))
    return path
