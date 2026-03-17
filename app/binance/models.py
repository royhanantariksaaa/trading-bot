from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PositionState:
    symbol: str
    side: str
    qty: float
    entry_price: float
    stop_loss: float
    take_profit: float
    opened_at: str
    entry_order_id: str = ""
    entry_client_order_id: str = ""
    status: str = "OPEN"
    entry_fee_usd: float = 0.0


@dataclass
class OrderState:
    symbol: str
    side: str
    order_type: str
    order_id: str
    client_order_id: str
    status: str
    qty: float = 0.0
    executed_qty: float = 0.0
    quote_order_qty: float = 0.0
    quote_executed: float = 0.0
    price: float = 0.0
    stop_price: float = 0.0
    submitted_at: str = ""
    updated_at: str = ""


@dataclass
class AccountSnapshot:
    quote_asset: str
    quote_free: float
    quote_locked: float
    base_asset: str
    base_free: float
    base_locked: float
    maker_fee: float | None = None
    taker_fee: float | None = None
    captured_at: str = ""


@dataclass
class EntryPlan:
    allowed: bool
    reason: str = ""
    quote_budget: float = 0.0
    estimated_qty: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    fee_buffer_usd: float = 0.0
    slippage_buffer_usd: float = 0.0
    market_warning: str = ""


@dataclass
class ExitPlan:
    allowed: bool
    reason: str = ""
    qty: float = 0.0
    market_warning: str = ""


@dataclass
class ReconstructedPosition:
    qty: float = 0.0
    entry_price: float = 0.0
    opened_at: str = ""
    entry_fee_usd: float = 0.0
    trade_ids: list[str] = field(default_factory=list)
