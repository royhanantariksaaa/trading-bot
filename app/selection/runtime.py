from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ..utils.storage import market_data_path
from .binance import scan_binance_markets
from .export import write_selection_csv
from .polymarket import scan_polymarket_markets


@dataclass(slots=True)
class RuntimeSelection:
    venue: str
    symbol: str = ""
    market_id: str = ""
    source: str = ""
    path: Path | None = None


def default_selection_csv_path(venue: str) -> Path:
    venue_name = venue.strip().lower()
    if venue_name == "polymarket":
        return market_data_path("polymarket_candidates.csv")
    return market_data_path("binance_candidates.csv")


def load_runtime_selection(path: Path, *, venue: str) -> RuntimeSelection | None:
    if not path.exists():
        return None
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if str(row.get("venue") or "").strip().lower() != venue.strip().lower():
                continue
            if str(row.get("accepted") or "").strip().lower() != "true":
                continue
            return RuntimeSelection(
                venue=venue,
                symbol=str(row.get("symbol") or ""),
                market_id=str(row.get("market_id") or ""),
                source="csv",
                path=path,
            )
    return None


def scan_and_select_runtime_market(venue: str, *, output_path: Path | None = None) -> RuntimeSelection | None:
    venue_name = venue.strip().lower()
    path = output_path or default_selection_csv_path(venue_name)
    if venue_name == "polymarket":
        result = scan_polymarket_markets()
    else:
        result = scan_binance_markets()
    write_selection_csv(result, path)
    selected = result.selected
    if selected is None:
        return None
    return RuntimeSelection(
        venue=venue_name,
        symbol=selected.candidate.symbol,
        market_id=selected.candidate.market_id,
        source="scan",
        path=path,
    )
