from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ..utils.storage import market_data_path
from .binance import scan_binance_markets
from .export import report_paths_from_csv_path, write_selection_csv, write_selection_report, write_selection_report_json
from .polymarket import scan_polymarket_markets
from .selector import SelectionResult


@dataclass(slots=True)
class RuntimeSelection:
    venue: str
    symbol: str = ""
    market_id: str = ""
    source: str = ""
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
            explanation = str(row.get("score_explanation") or "").strip()
            summary = f"{row.get('symbol') or ''} score={row.get('score_total') or '0'} rank={row.get('rank') or '-'}"
            return RuntimeSelection(
                venue=venue,
                symbol=str(row.get("symbol") or ""),
                market_id=str(row.get("market_id") or ""),
                source="csv",
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
) -> RotationDecision:
    selection = load_runtime_selection(output_path, venue=venue) if mode == "csv" else scan_and_select_runtime_market(venue, output_path=output_path)
    if selection is None:
        return RotationDecision(changed=False, reason=f"No selection available via mode={mode}")
    if selection.symbol == current_symbol and selection.market_id == current_market_id:
        return RotationDecision(
            changed=False,
            reason=f"Selection unchanged ({selection.symbol or selection.market_id})",
            previous_symbol=current_symbol,
            new_symbol=selection.symbol,
            previous_market_id=current_market_id,
            new_market_id=selection.market_id,
            selection=selection,
        )
    return RotationDecision(
        changed=True,
        reason=f"Rotated to {selection.symbol or selection.market_id} via mode={mode}",
        previous_symbol=current_symbol,
        new_symbol=selection.symbol,
        previous_market_id=current_market_id,
        new_market_id=selection.market_id,
        selection=selection,
    )
