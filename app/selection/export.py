from __future__ import annotations

import csv
import json
from pathlib import Path

from .profiles import StrategyProfileSelection
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
    "score_depth",
    "score_accessibility",
    "score_stability",
    "score_penalties",
    "score_explanation",
    "filter_failures",
    "strategy_profile_name",
    "strategy_profile_regime",
    "strategy_profile_source",
    "strategy_profile_reason",
    "strategy_profile",
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


def _profile_row(profile: StrategyProfileSelection | None, *, selected: bool) -> dict[str, str]:
    if not selected or profile is None:
        return {
            "strategy_profile_name": "",
            "strategy_profile_regime": "",
            "strategy_profile_source": "",
            "strategy_profile_reason": "",
            "strategy_profile": "",
        }
    return {
        "strategy_profile_name": profile.name,
        "strategy_profile_regime": profile.regime,
        "strategy_profile_source": profile.source,
        "strategy_profile_reason": profile.reason,
        "strategy_profile": profile.to_json(),
    }


def candidate_to_row(item: ScoredCandidate, *, profile: StrategyProfileSelection | None = None, selected: bool = False) -> dict[str, str]:
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
        "score_depth": _format_value(item.score_breakdown.depth),
        "score_accessibility": _format_value(item.score_breakdown.accessibility),
        "score_stability": _format_value(item.score_breakdown.stability),
        "score_penalties": _format_value(item.score_breakdown.penalties),
        "score_explanation": " | ".join(item.score_breakdown.explanation),
        "filter_failures": " | ".join(failures),
        **_profile_row(profile, selected=selected),
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


def _report_payload(result: SelectionResult) -> dict:
    def component_to_dict(component):
        return {
            "name": component.name,
            "raw_value": component.raw_value,
            "score": component.score,
            "weight": component.weight,
            "contribution": component.contribution,
            "detail": component.detail,
        }

    def penalty_to_dict(penalty):
        return {"name": penalty.name, "points": penalty.points, "reason": penalty.reason}

    selected = None
    if result.selected is not None:
        item = result.selected
        selected = {
            "symbol": item.candidate.symbol,
            "market_id": item.candidate.market_id,
            "score": item.score,
            "rank": item.rank,
            "explanation": list(item.score_breakdown.explanation),
            "components": [component_to_dict(component) for component in item.score_breakdown.components],
            "penalties": [penalty_to_dict(penalty) for penalty in item.score_breakdown.penalty_items],
            "filter_failures": [f"{decision.name}:{decision.reason}" for decision in item.filter_decisions if not decision.passed],
            "strategy_profile": result.strategy_profile.to_dict() if result.strategy_profile is not None else None,
        }

    return {
        "scanned_at": result.scanned_at,
        "venue": result.venue,
        "summary": result.summary(),
        "selected": selected,
        "strategy_profile": result.strategy_profile.to_dict() if result.strategy_profile is not None else None,
        "ranked_symbols": [item.candidate.symbol for item in result.ranked],
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
            writer.writerow(candidate_to_row(item, profile=result.strategy_profile, selected=item is result.selected))
    return path


def report_paths_from_csv_path(path: Path) -> tuple[Path, Path]:
    base = path.with_suffix("")
    return (base.with_name(base.name + "_report.txt"), base.with_name(base.name + "_report.json"))


def build_selection_report(result: SelectionResult, *, top: int = 5) -> str:
    lines = [
        f"Selection report for venue={result.venue} at {result.scanned_at}",
        result.summary(),
        "",
    ]
    if result.strategy_profile is not None:
        lines.append("Selected profile")
        lines.extend(f"- {line}" for line in result.strategy_profile.why_lines())
        lines.append("")
    if result.selected is None:
        lines.append("No candidate passed the filters.")
    else:
        lines.append("Chosen market")
        lines.extend(f"- {line}" for line in result.selected.why_lines())
        lines.append("")
    if result.ranked:
        lines.append(f"Top {min(top, len(result.ranked))} ranked candidates")
        for item in result.ranked[: max(1, top)]:
            parts = ", ".join(
                f"{component.name}={component.score:.1f}"
                for component in sorted(item.score_breakdown.components, key=lambda value: value.contribution, reverse=True)[:3]
            )
            penalties = ", ".join(f"{penalty.name}:-{penalty.points:.1f}" for penalty in item.score_breakdown.penalty_items) or "none"
            lines.append(f"- #{item.rank} {item.candidate.symbol} score={item.score:.2f} drivers=[{parts}] penalties=[{penalties}]")
    else:
        lines.append("Top ranked candidates: none")
    return "\n".join(lines).strip() + "\n"


def write_selection_report(result: SelectionResult, path: Path, *, top: int = 5) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_selection_report(result, top=top), encoding="utf-8")
    return path


def write_selection_report_json(result: SelectionResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_report_payload(result), indent=2), encoding="utf-8")
    return path
