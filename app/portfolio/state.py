from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .models import AllocationDecision, PortfolioPosition, PortfolioState, VenueAccountingState


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utc_now().isoformat(timespec="seconds")


def today_str() -> str:
    return utc_now().strftime("%Y-%m-%d")


def _reset_daily_counters(state: PortfolioState) -> None:
    state.realized_pnl_today = 0.0
    state.daily_trade_count = 0
    state.realized_pnl_date = today_str()
    for venue_state in state.venue_accounts.values():
        venue_state.realized_pnl_today = 0.0


def _normalize_loaded_state(data: dict) -> PortfolioState:
    state = PortfolioState.from_dict(data)
    if not state.realized_pnl_date:
        state.realized_pnl_date = today_str()
    if state.realized_pnl_date != today_str():
        _reset_daily_counters(state)
    return state


def load_state(path: Path) -> PortfolioState:
    if not path.exists():
        return PortfolioState(realized_pnl_date=today_str())
    data = json.loads(path.read_text(encoding="utf-8"))
    return _normalize_loaded_state(data)


def save_state(path: Path, state: PortfolioState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def find_position(state: PortfolioState, *, venue: str, symbol: str) -> PortfolioPosition | None:
    return state.find_position(venue, symbol)


def upsert_position(state: PortfolioState, position: PortfolioPosition) -> None:
    state.upsert_position(position)


def ensure_venue_account(state: PortfolioState, venue: str) -> VenueAccountingState:
    key = venue.strip().lower()
    account = state.venue_accounts.get(key)
    if account is None:
        account = VenueAccountingState(venue=key)
        state.venue_accounts[key] = account
    return account


def apply_allocation_decision(
    state: PortfolioState,
    decision: AllocationDecision,
    *,
    market_price: float,
    opened_at: str,
) -> PortfolioPosition | None:
    if decision.action != "open" or decision.target_notional <= 0 or market_price <= 0:
        return None
    existing = state.find_position(decision.venue, decision.symbol)
    if existing is not None and existing.status.upper() == "OPEN":
        if decision.current_price is not None and decision.current_price > 0:
            existing.market_price = decision.current_price
        existing.updated_at = opened_at
        return existing

    qty = decision.quantity if decision.quantity > 0 else decision.target_notional / market_price
    if qty <= 0:
        return None
    position = PortfolioPosition(
        venue=decision.venue,
        symbol=decision.symbol,
        market_id=decision.market_id,
        qty=qty,
        entry_price=market_price,
        market_price=market_price,
        entry_notional=decision.target_notional,
        target_notional=decision.target_notional,
        opened_at=opened_at,
        updated_at=opened_at,
        strategy_profile_name=decision.strategy_profile_name,
        allocation_score=decision.score,
        allocation_reason=decision.reason,
    )
    state.positions.append(position)
    state.cash_free = max(0.0, state.cash_free - decision.target_notional)
    state.cash_locked = max(0.0, state.cash_locked)
    state.daily_trade_count += 1

    venue_account = ensure_venue_account(state, decision.venue)
    venue_account.cash_free = state.cash_free
    venue_account.deployed_notional += decision.target_notional
    venue_account.open_positions += 1
    venue_account.last_allocation_at = opened_at
    venue_account.last_allocation_summary = decision.summary()
    return position


def apply_allocation_report(
    state: PortfolioState,
    report,
    *,
    market_prices: dict[tuple[str, str], float] | None = None,
) -> None:
    market_prices = market_prices or {}
    for decision in report.decisions:
        key = (decision.venue.strip().lower(), decision.symbol.strip().lower())
        price = market_prices.get(key, decision.current_price or 0.0)
        if decision.action == "hold" and price > 0:
            position = state.find_position(decision.venue, decision.symbol)
            if position is not None:
                position.market_price = price
                position.updated_at = report.generated_at
            continue
        apply_allocation_decision(state, decision, market_price=price, opened_at=report.generated_at)

    state.last_allocation_report_at = report.generated_at
    state.last_allocation_report_path = str(report.report_path) if report.report_path is not None else ""
    state.last_allocation_report_json_path = str(report.report_json_path) if report.report_json_path is not None else ""
    state.last_rebalance_at = report.generated_at
    state.last_sync_at = now_iso()
    state.last_source = report.selection_mode

