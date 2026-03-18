from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..selection.profiles import StrategyProfileSelection


def _format_float(value: float | None, *, precision: int = 2, suffix: str = "") -> str:
    if value is None:
        return "missing"
    return f"{value:.{precision}f}{suffix}"


@dataclass(slots=True)
class PortfolioCandidate:
    venue: str
    symbol: str
    market_id: str = ""
    market_type: str = ""
    quote_asset: str = ""
    accepted: bool = True
    rank: int = 0
    score: float = 0.0
    source: str = ""
    last_price: float | None = None
    volume_quote_24h: float | None = None
    spread_bps: float | None = None
    min_notional: float | None = None
    max_notional: float | None = None
    qty_step: float | None = None
    tick_size: float | None = None
    strategy_profile: StrategyProfileSelection | None = None
    score_explanation: tuple[str, ...] = field(default_factory=tuple)
    filter_failures: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> str:
        profile = self.strategy_profile.name if self.strategy_profile is not None else "none"
        return (
            f"{self.symbol} [{self.venue}] accepted={self.accepted} rank={self.rank or '-'} "
            f"score={self.score:.2f} profile={profile}"
        )

    def why_lines(self) -> tuple[str, ...]:
        lines = [self.summary()]
        lines.append(
            "Metrics: "
            f"last={_format_float(self.last_price, precision=4)} "
            f"spread={_format_float(self.spread_bps, precision=2, suffix='bps')} "
            f"volume={_format_float(self.volume_quote_24h, precision=2)}"
        )
        if self.score_explanation:
            lines.extend(f"Score: {line}" for line in self.score_explanation)
        if self.filter_failures:
            lines.append("Rejected by selection filters: " + " | ".join(self.filter_failures))
        if self.strategy_profile is not None:
            lines.extend(f"Profile: {line}" for line in self.strategy_profile.why_lines())
        return tuple(lines)


@dataclass(slots=True)
class PortfolioRiskCaps:
    max_total_positions: int = 3
    max_positions_per_venue: int = 3
    max_new_positions_per_run: int = 2
    max_total_notional: float = 15.0
    max_position_notional: float = 5.0
    max_venue_notional: float = 10.0
    reserve_cash_usd: float = 70.0
    reserve_cash_pct: float = 0.70
    min_candidate_score: float = 65.0
    min_entry_notional: float = 5.0
    max_symbol_positions: int = 1
    allow_scale_up_existing: bool = False

    def describe(self) -> str:
        return (
            f"positions<= {self.max_total_positions}, venue_positions<= {self.max_positions_per_venue}, "
            f"new_per_run<= {self.max_new_positions_per_run}, total_notional<= {self.max_total_notional:.2f}, "
            f"position_notional<= {self.max_position_notional:.2f}, venue_notional<= {self.max_venue_notional:.2f}, "
            f"reserve>= {self.reserve_cash_usd:.2f} or {self.reserve_cash_pct:.0%}, min_score>= {self.min_candidate_score:.1f}"
        )


@dataclass(slots=True)
class PortfolioPosition:
    venue: str
    symbol: str
    market_id: str = ""
    side: str = "LONG"
    status: str = "OPEN"
    qty: float = 0.0
    entry_price: float = 0.0
    market_price: float = 0.0
    entry_notional: float = 0.0
    target_notional: float = 0.0
    realized_pnl: float = 0.0
    entry_fee_usd: float = 0.0
    opened_at: str = ""
    updated_at: str = ""
    strategy_profile_name: str = ""
    allocation_score: float = 0.0
    allocation_reason: str = ""
    notes: str = ""

    @property
    def market_value(self) -> float:
        price = self.market_price if self.market_price > 0 else self.entry_price
        return self.qty * price

    @property
    def unrealized_pnl(self) -> float:
        price = self.market_price if self.market_price > 0 else self.entry_price
        return (price - self.entry_price) * self.qty

    def summary(self) -> str:
        return (
            f"{self.venue}:{self.symbol} qty={self.qty:.6f} entry={self.entry_price:.4f} "
            f"mark={self.market_price if self.market_price > 0 else self.entry_price:.4f} "
            f"target={self.target_notional:.2f} pnl={self.realized_pnl:.4f}"
        )


@dataclass(slots=True)
class VenueAccountingState:
    venue: str
    cash_free: float = 0.0
    cash_locked: float = 0.0
    deployed_notional: float = 0.0
    open_positions: int = 0
    realized_pnl_today: float = 0.0
    last_allocation_at: str = ""
    last_allocation_summary: str = ""


@dataclass(slots=True)
class PortfolioState:
    quote_asset: str = "USDT"
    starting_balance: float = 0.0
    cash_free: float = 0.0
    cash_locked: float = 0.0
    realized_pnl_today: float = 0.0
    realized_pnl_date: str = ""
    daily_trade_count: int = 0
    positions: list[PortfolioPosition] = field(default_factory=list)
    venue_accounts: dict[str, VenueAccountingState] = field(default_factory=dict)
    last_allocation_report_at: str = ""
    last_allocation_report_path: str = ""
    last_allocation_report_json_path: str = ""
    last_rebalance_at: str = ""
    last_sync_at: str = ""
    last_source: str = ""

    @property
    def open_positions(self) -> list[PortfolioPosition]:
        return [position for position in self.positions if position.status.upper() == "OPEN"]

    @property
    def deployed_notional(self) -> float:
        return sum(position.entry_notional for position in self.open_positions)

    @property
    def equity(self) -> float:
        return self.cash_free + self.cash_locked + sum(position.market_value for position in self.open_positions)

    @property
    def open_position_count(self) -> int:
        return len(self.open_positions)

    def venue_position_count(self, venue: str) -> int:
        return sum(1 for position in self.open_positions if position.venue.strip().lower() == venue.strip().lower())

    def venue_deployed_notional(self, venue: str) -> float:
        venue_name = venue.strip().lower()
        return sum(position.entry_notional for position in self.open_positions if position.venue.strip().lower() == venue_name)

    def symbol_position_count(self, venue: str, symbol: str) -> int:
        venue_name = venue.strip().lower()
        symbol_name = symbol.strip().lower()
        return sum(
            1
            for position in self.open_positions
            if position.venue.strip().lower() == venue_name and position.symbol.strip().lower() == symbol_name
        )

    def find_position(self, venue: str, symbol: str) -> PortfolioPosition | None:
        venue_name = venue.strip().lower()
        symbol_name = symbol.strip().lower()
        for position in self.positions:
            if position.status.upper() != "OPEN":
                continue
            if position.venue.strip().lower() == venue_name and position.symbol.strip().lower() == symbol_name:
                return position
        return None

    def upsert_position(self, position: PortfolioPosition) -> None:
        existing = self.find_position(position.venue, position.symbol)
        if existing is None:
            self.positions.append(position)
            return
        existing.market_id = position.market_id
        existing.side = position.side
        existing.status = position.status
        existing.qty = position.qty
        existing.entry_price = position.entry_price
        existing.market_price = position.market_price
        existing.entry_notional = position.entry_notional
        existing.target_notional = position.target_notional
        existing.realized_pnl = position.realized_pnl
        existing.entry_fee_usd = position.entry_fee_usd
        existing.opened_at = position.opened_at
        existing.updated_at = position.updated_at
        existing.strategy_profile_name = position.strategy_profile_name
        existing.allocation_score = position.allocation_score
        existing.allocation_reason = position.allocation_reason
        existing.notes = position.notes

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PortfolioState":
        if not data:
            return cls()
        payload = dict(data)
        payload["positions"] = [PortfolioPosition(**row) for row in payload.get("positions") or []]
        payload["venue_accounts"] = {
            venue: VenueAccountingState(**row)
            for venue, row in (payload.get("venue_accounts") or {}).items()
        }
        return cls(**payload)


@dataclass(slots=True)
class AllocationDecision:
    venue: str
    symbol: str
    market_id: str = ""
    rank: int = 0
    score: float = 0.0
    accepted: bool = True
    action: str = "skip"
    requested_notional: float = 0.0
    target_notional: float = 0.0
    current_notional: float = 0.0
    quantity: float = 0.0
    portfolio_share: float = 0.0
    current_price: float | None = None
    strategy_profile_name: str = ""
    reason: str = ""
    caps: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> str:
        price_text = _format_float(self.current_price, precision=4)
        caps_text = ",".join(self.caps) if self.caps else "none"
        return (
            f"#{self.rank or '-'} {self.venue}:{self.symbol} action={self.action} score={self.score:.2f} "
            f"target={self.target_notional:.2f} requested={self.requested_notional:.2f} price={price_text} caps=[{caps_text}]"
        )

    def why_lines(self) -> tuple[str, ...]:
        lines = [self.summary()]
        if self.reason:
            lines.append(f"Reason: {self.reason}")
        if self.strategy_profile_name:
            lines.append(f"Strategy profile: {self.strategy_profile_name}")
        if self.current_price is not None:
            lines.append(f"Current price: {self.current_price:.4f}")
        return tuple(lines)


@dataclass(slots=True)
class PortfolioAllocationReport:
    generated_at: str
    venue: str
    selection_mode: str
    source_path: str = ""
    available_cash: float = 0.0
    reserve_cash: float = 0.0
    deployable_cash: float = 0.0
    starting_balance: float = 0.0
    current_deployed_notional: float = 0.0
    target_deployed_notional: float = 0.0
    current_positions: int = 0
    target_positions: int = 0
    max_total_positions: int = 0
    max_position_notional: float = 0.0
    max_total_notional: float = 0.0
    max_positions_per_venue: int = 0
    max_venue_notional: float = 0.0
    min_candidate_score: float = 0.0
    min_entry_notional: float = 0.0
    accepted_count: int = 0
    rejected_count: int = 0
    decisions: tuple[AllocationDecision, ...] = field(default_factory=tuple)
    report_path: Path | None = None
    report_json_path: Path | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> str:
        return (
            f"venue={self.venue or 'unknown'} mode={self.selection_mode} candidates={self.accepted_count + self.rejected_count} "
            f"selected={self.target_positions} current={self.current_positions} cash={self.available_cash:.2f} "
            f"reserve={self.reserve_cash:.2f} deployable={self.deployable_cash:.2f} target_notional={self.target_deployed_notional:.2f}"
        )

    def why_lines(self) -> tuple[str, ...]:
        lines = [self.summary()]
        lines.append(
            f"Caps: max_positions={self.max_total_positions}, max_position_notional={self.max_position_notional:.2f}, "
            f"max_total_notional={self.max_total_notional:.2f}, max_positions_per_venue={self.max_positions_per_venue}, "
            f"max_venue_notional={self.max_venue_notional:.2f}, min_score={self.min_candidate_score:.1f}, "
            f"min_entry_notional={self.min_entry_notional:.2f}"
        )
        if self.notes:
            lines.append("Notes: " + " | ".join(self.notes))
        if self.decisions:
            lines.append("Decisions")
            lines.extend(f"- {decision.summary()}" for decision in self.decisions)
            for decision in self.decisions:
                if decision.reason:
                    lines.append(f"  - {decision.reason}")
        return tuple(lines)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["report_path"] = str(self.report_path) if self.report_path is not None else ""
        data["report_json_path"] = str(self.report_json_path) if self.report_json_path is not None else ""
        return data

