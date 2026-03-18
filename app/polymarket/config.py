from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..common.env import env_bool
from ..selection.runtime import RotationController, default_selection_csv_path
from ..utils.storage import polymarket_log_path, polymarket_state_path, resolve_project_path
from .execution import PolymarketLiveCredentials


@dataclass
class Config:
    host: str = os.getenv("POLYMARKET_HOST", "https://clob.polymarket.com")
    token_id: str = os.getenv("POLYMARKET_TOKEN_ID", "")
    min_order_size: float = float(os.getenv("PM_MIN_ORDER_SIZE", "5"))
    quote_size: float = float(os.getenv("PM_QUOTE_SIZE", "25"))
    starting_cash: float = float(os.getenv("PM_STARTING_CASH", "100"))
    reserve_cash: float = float(os.getenv("PM_RESERVE_CASH", "25"))
    max_drawdown_pct: float = float(os.getenv("PM_MAX_DRAWDOWN_PCT", "0.15"))
    max_run_loss_usd: float = float(os.getenv("PM_MAX_RUN_LOSS_USD", "20"))
    max_buy_fraction_of_spendable: float = float(os.getenv("PM_MAX_BUY_FRACTION_OF_SPENDABLE", "0.33"))
    min_cash_buffer_pct: float = float(os.getenv("PM_MIN_CASH_BUFFER_PCT", "0.10"))
    hard_halt_mode: str = os.getenv("PM_HARD_HALT_MODE", "flat_stop").strip().lower()
    supervision_report_path: Path = field(
        default_factory=lambda: resolve_project_path(os.getenv("PM_SUPERVISION_REPORT_PATH", "data/market/polymarket_supervision_report.txt"))
    )
    base_spread: float = float(os.getenv("PM_BASE_SPREAD", "0.04"))
    edge_offset: float = float(os.getenv("PM_EDGE_OFFSET", "0.01"))
    inventory_target: float = float(os.getenv("PM_INVENTORY_TARGET", "0"))
    max_inventory: float = float(os.getenv("PM_MAX_INVENTORY", "100"))
    max_position_notional: float = float(os.getenv("PM_MAX_POSITION_NOTIONAL", "60"))
    inventory_skew_per_share: float = float(os.getenv("PM_INVENTORY_SKEW_PER_SHARE", "0.0025"))
    poll_seconds: int = int(os.getenv("PM_POLL_SECONDS", "5"))
    loops: int = int(os.getenv("PM_LOOPS", "0"))
    paper_mode: bool = env_bool(os.getenv("PM_PAPER_MODE"), True)
    adaptive_mode: str = os.getenv("PM_ADAPTIVE_MODE", "off").strip().lower()
    selection_mode: str = os.getenv("PM_SELECTION_MODE", "manual").strip().lower()
    selection_csv_path: Path = field(
        default_factory=lambda: resolve_project_path(os.getenv("PM_SELECTION_CSV", str(default_selection_csv_path("polymarket"))))
    )
    selection_rotation_loops: int = int(os.getenv("PM_SELECTION_ROTATE_EVERY_LOOPS", "0"))
    selection_rotation_only_when_flat: bool = env_bool(os.getenv("PM_SELECTION_ROTATE_ONLY_WHEN_FLAT"), True)
    state_path: Path = field(default_factory=polymarket_state_path)
    log_path: Path = field(default_factory=polymarket_log_path)
    adaptive_report_path: Path = field(
        default_factory=lambda: resolve_project_path(os.getenv("PM_ADAPTIVE_REPORT_PATH", "data/market/polymarket_adaptive_report.txt"))
    )
    live_enabled: bool = env_bool(os.getenv("PM_LIVE_ENABLED"), False)
    live_allow_unverified: bool = env_bool(os.getenv("PM_ALLOW_UNVERIFIED_LIVE"), False)
    live_credentials: PolymarketLiveCredentials = field(
        default_factory=lambda: PolymarketLiveCredentials(
            api_key=os.getenv("PM_CLOB_API_KEY", ""),
            api_secret=os.getenv("PM_CLOB_SECRET", ""),
            api_passphrase=os.getenv("PM_CLOB_PASSPHRASE", ""),
            private_key=os.getenv("PM_PRIVATE_KEY", ""),
            funder=os.getenv("PM_FUNDER", ""),
            chain_id=int(os.getenv("PM_CHAIN_ID", "137")),
            signature_type=int(os.getenv("PM_SIGNATURE_TYPE", "0")),
        )
    )

    def validate(self) -> None:
        if not self.token_id:
            raise ValueError("POLYMARKET_TOKEN_ID is required")
        if self.adaptive_mode not in {"off", "paper", "on"}:
            raise ValueError("PM_ADAPTIVE_MODE must be 'off', 'paper', or 'on'")
        if self.hard_halt_mode not in {"pause", "flat_stop"}:
            raise ValueError("PM_HARD_HALT_MODE must be 'pause' or 'flat_stop'")
        if self.selection_mode not in {"manual", "csv", "scan"}:
            raise ValueError("PM_SELECTION_MODE must be 'manual', 'csv', or 'scan'")
        if self.selection_rotation_loops < 0:
            raise ValueError("PM_SELECTION_ROTATE_EVERY_LOOPS must be >= 0")
        if self.quote_size <= 0:
            raise ValueError("PM_QUOTE_SIZE must be > 0")
        if self.starting_cash <= 0:
            raise ValueError("PM_STARTING_CASH must be > 0")
        if self.reserve_cash < 0:
            raise ValueError("PM_RESERVE_CASH must be >= 0")
        if self.reserve_cash >= self.starting_cash:
            raise ValueError("PM_RESERVE_CASH must be less than PM_STARTING_CASH")
        if self.max_drawdown_pct < 0 or self.max_drawdown_pct >= 1:
            raise ValueError("PM_MAX_DRAWDOWN_PCT must be in [0, 1)")
        if self.max_run_loss_usd < 0:
            raise ValueError("PM_MAX_RUN_LOSS_USD must be >= 0")
        if self.max_buy_fraction_of_spendable <= 0 or self.max_buy_fraction_of_spendable > 1:
            raise ValueError("PM_MAX_BUY_FRACTION_OF_SPENDABLE must be in (0, 1]")
        if self.min_cash_buffer_pct < 0 or self.min_cash_buffer_pct >= 1:
            raise ValueError("PM_MIN_CASH_BUFFER_PCT must be in [0, 1)")
        if self.base_spread <= 0 or self.base_spread >= 1:
            raise ValueError("PM_BASE_SPREAD must be between 0 and 1")
        if self.edge_offset < 0 or self.edge_offset >= 1:
            raise ValueError("PM_EDGE_OFFSET must be between 0 and 1")
        if self.max_inventory <= 0:
            raise ValueError("PM_MAX_INVENTORY must be > 0")
        if self.max_position_notional <= 0:
            raise ValueError("PM_MAX_POSITION_NOTIONAL must be > 0")
        if self.min_order_size <= 0:
            raise ValueError("PM_MIN_ORDER_SIZE must be > 0")
        if self.poll_seconds <= 0:
            raise ValueError("PM_POLL_SECONDS must be > 0")
        if self.live_enabled and self.paper_mode:
            raise ValueError("PM_LIVE_ENABLED=true is incompatible with PM_PAPER_MODE=true")

    @property
    def rotation_controller(self) -> RotationController:
        enabled = self.selection_mode in {"csv", "scan"} and self.selection_rotation_loops > 0
        return RotationController(
            enabled=enabled,
            every_loops=self.selection_rotation_loops,
            only_when_flat=self.selection_rotation_only_when_flat,
            next_due_loop=self.selection_rotation_loops if enabled else 0,
        )
