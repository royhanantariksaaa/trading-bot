from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class QuoteLevel:
    price: float
    size: float


@dataclass
class BookSnapshot:
    token_id: str
    tick_size: float
    min_order_size: float
    best_bid: float
    best_ask: float
    bids: list[QuoteLevel] = field(default_factory=list)
    asks: list[QuoteLevel] = field(default_factory=list)
    timestamp: str = ""
    book_hash: str = ""

    @property
    def midpoint(self) -> float:
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread(self) -> float:
        return max(0.0, self.best_ask - self.best_bid)


@dataclass
class BotState:
    inventory: float = 0.0
    cash: float = 0.0
    realized_pnl: float = 0.0
    bought_cost: float = 0.0
    sold_proceeds: float = 0.0
    last_mid: float = 0.5
    loops: int = 0
    fills: int = 0
    peak_mark_to_market: float = 0.0
    halted: bool = False
    halt_reason: str = ""
    stop_after_flatten: bool = False
    flatten_pending: bool = False
    stopped: bool = False
    stop_reason: str = ""
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "BotState":
        if not data:
            return cls()
        return cls(**data)


@dataclass
class QuotePlan:
    bid_price: float
    ask_price: float
    buy_size: float
    sell_size: float
    inventory_skew: float
    reason: str


@dataclass
class FillResult:
    side: str
    price: float
    size: float
    notional: float
    reason: str


@dataclass
class SupervisionReport:
    timestamp: str
    loop: int
    token_id: str
    mode: str
    health: str
    cash: float
    reserve_cash: float
    spendable_cash: float
    mark_to_market: float
    peak_mark_to_market: float
    drawdown_pct: float
    inventory: float
    inventory_mark_value: float
    max_inventory: float
    halt_reason: str = ""
    stop_reason: str = ""
    flatten_pending: bool = False
    buy_quote_size: float = 0.0
    sell_quote_size: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_text(self) -> str:
        note_text = " | ".join(self.notes) if self.notes else "none"
        return (
            f"[{self.timestamp}] loop={self.loop} token={self.token_id} mode={self.mode} health={self.health}\n"
            f"cash={self.cash:.4f} reserve={self.reserve_cash:.4f} spendable={self.spendable_cash:.4f} mtm={self.mark_to_market:.4f} peak={self.peak_mark_to_market:.4f} dd={self.drawdown_pct:.2%}\n"
            f"inventory={self.inventory:.2f} inv_mark={self.inventory_mark_value:.4f} max_inv={self.max_inventory:.2f} flatten_pending={'yes' if self.flatten_pending else 'no'}\n"
            f"quotes buy={self.buy_quote_size:.2f} sell={self.sell_quote_size:.2f}\n"
            f"halt_reason={self.halt_reason or 'none'}\n"
            f"stop_reason={self.stop_reason or 'none'}\n"
            f"notes={note_text}\n"
        )
