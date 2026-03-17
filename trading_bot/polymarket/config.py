from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from trading_bot.common.env import env_bool


@dataclass
class Config:
    host: str = os.getenv("POLYMARKET_HOST", "https://clob.polymarket.com")
    token_id: str = os.getenv("POLYMARKET_TOKEN_ID", "")
    min_order_size: float = float(os.getenv("PM_MIN_ORDER_SIZE", "5"))
    quote_size: float = float(os.getenv("PM_QUOTE_SIZE", "25"))
    base_spread: float = float(os.getenv("PM_BASE_SPREAD", "0.04"))
    edge_offset: float = float(os.getenv("PM_EDGE_OFFSET", "0.01"))
    inventory_target: float = float(os.getenv("PM_INVENTORY_TARGET", "0"))
    max_inventory: float = float(os.getenv("PM_MAX_INVENTORY", "100"))
    max_position_notional: float = float(os.getenv("PM_MAX_POSITION_NOTIONAL", "60"))
    inventory_skew_per_share: float = float(os.getenv("PM_INVENTORY_SKEW_PER_SHARE", "0.0025"))
    poll_seconds: int = int(os.getenv("PM_POLL_SECONDS", "5"))
    loops: int = int(os.getenv("PM_LOOPS", "0"))
    paper_mode: bool = env_bool(os.getenv("PM_PAPER_MODE"), True)
    state_path: Path = Path(os.getenv("PM_STATE_PATH", "polymarket_mm/state.json"))
    log_path: Path = Path(os.getenv("PM_LOG_PATH", "polymarket_mm/runs.csv"))

    def validate(self) -> None:
        if not self.token_id:
            raise ValueError("POLYMARKET_TOKEN_ID is required")
        if self.quote_size <= 0:
            raise ValueError("PM_QUOTE_SIZE must be > 0")
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
