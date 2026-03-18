from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..common.env import env_bool
from ..utils.storage import market_data_path, resolve_project_path
from .models import PortfolioRiskCaps


def _caps_from_env() -> PortfolioRiskCaps:
    return PortfolioRiskCaps(
        max_total_positions=int(os.getenv("PORTFOLIO_MAX_POSITIONS", "3")),
        max_positions_per_venue=int(os.getenv("PORTFOLIO_MAX_POSITIONS_PER_VENUE", "3")),
        max_new_positions_per_run=int(os.getenv("PORTFOLIO_MAX_NEW_POSITIONS_PER_RUN", "2")),
        max_total_notional=float(os.getenv("PORTFOLIO_MAX_TOTAL_NOTIONAL", "15")),
        max_position_notional=float(os.getenv("PORTFOLIO_MAX_POSITION_NOTIONAL", "5")),
        max_venue_notional=float(os.getenv("PORTFOLIO_MAX_VENUE_NOTIONAL", "10")),
        reserve_cash_usd=float(os.getenv("PORTFOLIO_RESERVE_CASH_USD", "70")),
        reserve_cash_pct=float(os.getenv("PORTFOLIO_RESERVE_CASH_PCT", "0.70")),
        min_candidate_score=float(os.getenv("PORTFOLIO_MIN_CANDIDATE_SCORE", "65")),
        min_entry_notional=float(os.getenv("PORTFOLIO_MIN_ENTRY_NOTIONAL", "5")),
        max_symbol_positions=int(os.getenv("PORTFOLIO_MAX_SYMBOL_POSITIONS", "1")),
        allow_scale_up_existing=env_bool(os.getenv("PORTFOLIO_ALLOW_SCALE_UP_EXISTING"), False),
    )


@dataclass
class Config:
    venue: str = os.getenv("PORTFOLIO_VENUE", "binance").strip().lower()
    selection_mode: str = os.getenv("PORTFOLIO_SELECTION_MODE", "scan").strip().lower()
    run_mode: str = os.getenv("PORTFOLIO_RUN_MODE", "paper").strip().lower()
    starting_balance: float = float(os.getenv("PORTFOLIO_STARTING_BALANCE", "100"))
    selection_csv_path: Path = field(
        default_factory=lambda: resolve_project_path(os.getenv("PORTFOLIO_SELECTION_CSV", str(market_data_path("portfolio_candidates.csv"))))
    )
    state_path: Path = field(
        default_factory=lambda: resolve_project_path(os.getenv("PORTFOLIO_STATE_PATH", "data/state/portfolio_state.json"))
    )
    report_path: Path = field(
        default_factory=lambda: resolve_project_path(os.getenv("PORTFOLIO_REPORT_PATH", "data/market/portfolio_allocation_report.txt"))
    )
    report_json_path: Path = field(
        default_factory=lambda: resolve_project_path(os.getenv("PORTFOLIO_REPORT_JSON_PATH", "data/market/portfolio_allocation_report.json"))
    )
    candidate_limit: int = int(os.getenv("PORTFOLIO_CANDIDATE_LIMIT", "20"))
    include_rejected: bool = env_bool(os.getenv("PORTFOLIO_INCLUDE_REJECTED"), True)
    top_report_rows: int = int(os.getenv("PORTFOLIO_TOP_REPORT_ROWS", "8"))
    paper_apply_allocations: bool = env_bool(os.getenv("PORTFOLIO_PAPER_APPLY_ALLOCATIONS"), True)
    caps: PortfolioRiskCaps = field(default_factory=_caps_from_env)

    def validate(self) -> None:
        if self.venue not in {"binance", "polymarket"}:
            raise ValueError("PORTFOLIO_VENUE must be 'binance' or 'polymarket'")
        if self.selection_mode not in {"scan", "csv"}:
            raise ValueError("PORTFOLIO_SELECTION_MODE must be 'scan' or 'csv'")
        if self.run_mode not in {"report", "paper"}:
            raise ValueError("PORTFOLIO_RUN_MODE must be 'report' or 'paper'")
        if self.starting_balance <= 0:
            raise ValueError("PORTFOLIO_STARTING_BALANCE must be > 0")
        if self.candidate_limit <= 0:
            raise ValueError("PORTFOLIO_CANDIDATE_LIMIT must be > 0")
        if self.top_report_rows <= 0:
            raise ValueError("PORTFOLIO_TOP_REPORT_ROWS must be > 0")
        if self.caps.max_total_positions <= 0:
            raise ValueError("PORTFOLIO_MAX_POSITIONS must be > 0")
        if self.caps.max_positions_per_venue <= 0:
            raise ValueError("PORTFOLIO_MAX_POSITIONS_PER_VENUE must be > 0")
        if self.caps.max_new_positions_per_run <= 0:
            raise ValueError("PORTFOLIO_MAX_NEW_POSITIONS_PER_RUN must be > 0")
        if self.caps.max_total_notional <= 0:
            raise ValueError("PORTFOLIO_MAX_TOTAL_NOTIONAL must be > 0")
        if self.caps.max_position_notional <= 0:
            raise ValueError("PORTFOLIO_MAX_POSITION_NOTIONAL must be > 0")
        if self.caps.reserve_cash_usd < 0:
            raise ValueError("PORTFOLIO_RESERVE_CASH_USD must be >= 0")
        if not (0 <= self.caps.reserve_cash_pct < 1):
            raise ValueError("PORTFOLIO_RESERVE_CASH_PCT must be in [0, 1)")
        if self.caps.min_candidate_score < 0 or self.caps.min_candidate_score > 100:
            raise ValueError("PORTFOLIO_MIN_CANDIDATE_SCORE must be between 0 and 100")
        if self.caps.min_entry_notional <= 0:
            raise ValueError("PORTFOLIO_MIN_ENTRY_NOTIONAL must be > 0")
        if self.caps.max_symbol_positions <= 0:
            raise ValueError("PORTFOLIO_MAX_SYMBOL_POSITIONS must be > 0")

