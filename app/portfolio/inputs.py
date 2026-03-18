from __future__ import annotations

import csv
from pathlib import Path

from ..selection.models import MarketConstraints, MarketMetrics
from ..selection.profiles import StrategyProfileSelection, build_strategy_profile
from ..selection.selector import ScoredCandidate, SelectionResult
from .models import PortfolioCandidate


def _to_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_bool(value: str | None) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y", "on"}


def _tuple_from_pipe(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split("|") if item.strip())


def candidate_from_scored(item: ScoredCandidate, *, include_rejected: bool = True) -> PortfolioCandidate:
    candidate = item.candidate
    metrics = candidate.metrics
    profile = build_strategy_profile("auto", candidate.venue, metrics)
    if not include_rejected and not item.accepted:
        return PortfolioCandidate(venue=candidate.venue, symbol=candidate.symbol)
    return PortfolioCandidate(
        venue=candidate.venue,
        symbol=candidate.symbol,
        market_id=candidate.market_id,
        market_type=candidate.market_type,
        quote_asset=candidate.quote_asset,
        accepted=item.accepted,
        rank=item.rank or 0,
        score=item.score,
        source=candidate.source,
        last_price=metrics.last_price,
        volume_quote_24h=metrics.volume_quote_24h,
        spread_bps=metrics.spread_bps,
        min_notional=candidate.constraints.min_notional,
        max_notional=candidate.constraints.max_notional,
        qty_step=candidate.constraints.qty_step,
        tick_size=candidate.constraints.tick_size,
        strategy_profile=profile,
        score_explanation=item.score_breakdown.explanation,
        filter_failures=tuple(f"{decision.name}:{decision.reason}" for decision in item.filter_decisions if not decision.passed),
    )


def candidates_from_selection_result(result: SelectionResult, *, include_rejected: bool = True) -> list[PortfolioCandidate]:
    return [candidate_from_scored(item, include_rejected=include_rejected) for item in result.evaluated]


def _strategy_profile_from_row(row: dict[str, str], venue: str, metrics: MarketMetrics) -> StrategyProfileSelection | None:
    raw = row.get("strategy_profile")
    profile = StrategyProfileSelection.from_json(raw)
    if profile is not None:
        return profile
    return build_strategy_profile("auto", venue, metrics)


def candidates_from_selection_csv(path: Path, *, venue: str, include_rejected: bool = True) -> list[PortfolioCandidate]:
    if not path.exists():
        return []
    candidates: list[PortfolioCandidate] = []
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            row_venue = str(row.get("venue") or "").strip().lower()
            if venue and row_venue != venue.strip().lower():
                continue
            accepted = _to_bool(row.get("accepted"))
            if not include_rejected and not accepted:
                continue
            metrics = MarketMetrics(
                last_price=_to_float(row.get("last_price")),
                bid=_to_float(row.get("bid")),
                ask=_to_float(row.get("ask")),
                spread=_to_float(row.get("spread")),
                spread_bps=_to_float(row.get("spread_bps")),
                volume_base_24h=_to_float(row.get("volume_base_24h")),
                volume_quote_24h=_to_float(row.get("volume_quote_24h")),
                trade_count_24h=_to_int(row.get("trade_count_24h")),
                price_change_pct_24h=_to_float(row.get("price_change_pct_24h")),
                range_pct_24h=_to_float(row.get("range_pct_24h")),
                high_24h=_to_float(row.get("high_24h")),
                low_24h=_to_float(row.get("low_24h")),
            )
            constraints = MarketConstraints(
                min_qty=_to_float(row.get("min_qty")),
                max_qty=_to_float(row.get("max_qty")),
                qty_step=_to_float(row.get("qty_step")),
                min_notional=_to_float(row.get("min_notional")),
                max_notional=_to_float(row.get("max_notional")),
                tick_size=_to_float(row.get("tick_size")),
            )
            profile = _strategy_profile_from_row(row, venue=row_venue, metrics=metrics)
            failure_text = str(row.get("filter_failures") or "")
            candidates.append(
                PortfolioCandidate(
                    venue=row_venue,
                    symbol=str(row.get("symbol") or ""),
                    market_id=str(row.get("market_id") or ""),
                    market_type=str(row.get("market_type") or ""),
                    quote_asset=str(row.get("quote_asset") or ""),
                    accepted=accepted,
                    rank=_to_int(row.get("rank")) or 0,
                    score=_to_float(row.get("score_total")) or 0.0,
                    source=str(row.get("source") or ""),
                    last_price=metrics.last_price,
                    volume_quote_24h=metrics.volume_quote_24h,
                    spread_bps=metrics.spread_bps,
                    min_notional=constraints.min_notional,
                    max_notional=constraints.max_notional,
                    qty_step=constraints.qty_step,
                    tick_size=constraints.tick_size,
                    strategy_profile=profile,
                    score_explanation=_tuple_from_pipe(str(row.get("score_explanation") or "")),
                    filter_failures=_tuple_from_pipe(failure_text),
                )
            )
    return candidates


def load_portfolio_candidates(
    *,
    venue: str,
    source: str,
    selection_result: SelectionResult | None = None,
    selection_csv_path: Path | None = None,
    include_rejected: bool = True,
) -> list[PortfolioCandidate]:
    venue_name = venue.strip().lower()
    source_name = source.strip().lower()
    if source_name == "scan":
        if selection_result is None:
            return []
        return candidates_from_selection_result(selection_result, include_rejected=include_rejected)
    if selection_csv_path is None:
        return []
    return candidates_from_selection_csv(selection_csv_path, venue=venue_name, include_rejected=include_rejected)

