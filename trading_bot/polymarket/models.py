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
