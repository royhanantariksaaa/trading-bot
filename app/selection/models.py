from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class MarketConstraints:
    min_qty: float | None = None
    max_qty: float | None = None
    qty_step: float | None = None
    min_notional: float | None = None
    max_notional: float | None = None
    tick_size: float | None = None


@dataclass(slots=True)
class MarketMetrics:
    last_price: float | None = None
    bid: float | None = None
    ask: float | None = None
    spread: float | None = None
    spread_bps: float | None = None
    volume_base_24h: float | None = None
    volume_quote_24h: float | None = None
    trade_count_24h: int | None = None
    price_change_pct_24h: float | None = None
    range_pct_24h: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None


@dataclass(slots=True)
class MarketCandidate:
    venue: str
    symbol: str
    market_id: str = ""
    base_asset: str = ""
    quote_asset: str = ""
    market_type: str = "spot"
    status: str = ""
    active: bool = True
    tradable: bool = True
    constraints: MarketConstraints = field(default_factory=MarketConstraints)
    metrics: MarketMetrics = field(default_factory=MarketMetrics)
    scanned_at: str = ""
    source: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(slots=True)
class ScoreComponent:
    name: str
    raw_value: float | None = None
    score: float = 0.0
    weight: float = 0.0
    contribution: float = 0.0
    detail: str = ""


@dataclass(slots=True)
class ScorePenalty:
    name: str
    points: float = 0.0
    reason: str = ""


@runtime_checkable
class MarketScanner(Protocol):
    venue: str

    def scan(self) -> list[MarketCandidate]:
        ...
