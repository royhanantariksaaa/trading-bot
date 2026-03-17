from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ..utils.storage import market_data_path
from .binance import scan_binance_markets
from .export import report_paths_from_csv_path, write_selection_csv, write_selection_report, write_selection_report_json
from .polymarket import scan_polymarket_markets
from .models import MarketMetrics
from .profiles import StrategyProfileSelection, build_strategy_profile
from .selector import SelectionResult


@dataclass(slots=True)
class RuntimeSelection:
    venue: str
    symbol: str = ""
    market_id: str = ""
    source: str = ""
    metrics: MarketMetrics | None = None
    strategy_profile: StrategyProfileSelection | None = None
    path: Path | None = None
    report_path: Path | None = None
    report_json_path: Path | None = None
    summary: str = ""
    explanation: str = ""


@dataclass(slots=True)
class RotationDecision:
    changed: bool
    reason: str
    previous_symbol: str = ""
    new_symbol: str = ""
    previous_market_id: str = ""
    new_market_id: str = ""
    previous_strategy_profile: str = ""
    new_strategy_profile: str = ""
    selection: RuntimeSelection | None = None


@dataclass(slots=True)
class RotationController:
    enabled: bool = False
    every_loops: int = 0
    only_when_flat: bool = True
    next_due_loop: int = 0

    def should_rotate(self, loop_number: int) -> bool:
        if not self.enabled or self.every_loops <= 0:
            return False
        return loop_number >= self.next_due_loop

    def mark_executed(self, loop_number: int) -> None:
        if self.enabled and self.every_loops > 0:
            self.next_due_loop = loop_number + self.every_loops


def default_selection_csv_path(venue: str) -> Path:
    venue_name = venue.strip().lower()
    if venue_name == "polymarket":
        return market_data_path("polymarket_candidates.csv")
    return market_data_path("binance_candidates.csv")


def load_runtime_selection(path: Path, *, venue: str) -> RuntimeSelection | None:
    if not path.exists():
        return None
    report_path, report_json_path = report_paths_from_csv_path(path)
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if str(row.get("venue") or "").strip().lower() != venue.strip().lower():
                continue
            if str(row.get("accepted") or "").strip().lower() != "true":
                continue
            metrics = _row_metrics(row)
            profile = _profile_from_row(row, venue=venue)
            explanation_parts = []
            if profile is not None:
                explanation_parts.extend(profile.why_lines())
            score_explanation = str(row.get("score_explanation") or "").strip()
            if score_explanation:
                explanation_parts.append(score_explanation)
            explanation = "\n".join(explanation_parts).strip()
            profile_text = f" profile={profile.name}" if profile is not None else ""
            summary = f"{row.get('symbol') or ''} score={row.get('score_total') or '0'} rank={row.get('rank') or '-'}{profile_text}"
            return RuntimeSelection(
                venue=venue,
                symbol=str(row.get("symbol") or ""),
                market_id=str(row.get("market_id") or ""),
                source="csv",
                metrics=metrics,
                strategy_profile=profile,
                path=path,
                report_path=report_path if report_path.exists() else None,
                report_json_path=report_json_path if report_json_path.exists() else None,
                summary=summary,
                explanation=explanation,
            )
    return None


def _persist_runtime_selection(result: SelectionResult, path: Path) -> tuple[Path, Path, Path]:
    csv_path = write_selection_csv(result, path)
    report_path, report_json_path = report_paths_from_csv_path(csv_path)
    write_selection_report(result, report_path)
    write_selection_report_json(result, report_json_path)
    return csv_path, report_path, report_json_path


def scan_and_select_runtime_market(venue: str, *, output_path: Path | None = None) -> RuntimeSelection | None:
    venue_name = venue.strip().lower()
    path = output_path or default_selection_csv_path(venue_name)
    if venue_name == "polymarket":
        result = scan_polymarket_markets()
    else:
        result = scan_binance_markets()
    csv_path, report_path, report_json_path = _persist_runtime_selection(result, path)
    selected = result.selected
    if selected is None:
        return None
    return RuntimeSelection(
        venue=venue_name,
        symbol=selected.candidate.symbol,
        market_id=selected.candidate.market_id,
        source="scan",
        metrics=selected.candidate.metrics,
        strategy_profile=result.strategy_profile,
        path=csv_path,
        report_path=report_path,
        report_json_path=report_json_path,
        summary=result.summary(),
        explanation=result.selected_report(),
    )


def maybe_rotate_runtime_selection(
    venue: str,
    *,
    mode: str,
    output_path: Path,
    current_symbol: str = "",
    current_market_id: str = "",
    current_strategy_profile: str = "",
    track_strategy_profile: bool = True,
) -> RotationDecision:
    selection = load_runtime_selection(output_path, venue=venue) if mode == "csv" else scan_and_select_runtime_market(venue, output_path=output_path)
    if selection is None:
        return RotationDecision(changed=False, reason=f"No selection available via mode={mode}")
    selected_profile = selection.strategy_profile.name if selection.strategy_profile is not None else ""
    profile_matches = True
    if track_strategy_profile:
        profile_matches = selected_profile == current_strategy_profile
    if selection.symbol == current_symbol and selection.market_id == current_market_id and profile_matches:
        profile_note = f" profile={selected_profile}" if track_strategy_profile and selected_profile else ""
        return RotationDecision(
            changed=False,
            reason=f"Selection unchanged ({selection.symbol or selection.market_id}{profile_note})",
            previous_symbol=current_symbol,
            new_symbol=selection.symbol,
            previous_market_id=current_market_id,
            new_market_id=selection.market_id,
            previous_strategy_profile=current_strategy_profile,
            new_strategy_profile=selected_profile,
            selection=selection,
        )
    profile_note = f" profile={selected_profile}" if track_strategy_profile and selected_profile else ""
    return RotationDecision(
        changed=True,
        reason=f"Rotated to {selection.symbol or selection.market_id}{profile_note} via mode={mode}",
        previous_symbol=current_symbol,
        new_symbol=selection.symbol,
        previous_market_id=current_market_id,
        new_market_id=selection.market_id,
        previous_strategy_profile=current_strategy_profile,
        new_strategy_profile=selected_profile,
        selection=selection,
    )


def _row_metrics(row: dict[str, str]) -> MarketMetrics:
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

    return MarketMetrics(
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


def _profile_from_row(row: dict[str, str], *, venue: str) -> StrategyProfileSelection | None:
    profile = StrategyProfileSelection.from_json(row.get("strategy_profile"))
    if profile is not None:
        return profile
    metrics = _row_metrics(row)
    return build_strategy_profile("auto", venue, metrics)
