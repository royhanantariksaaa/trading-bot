from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from trading_bot.binance.models import AccountSnapshot, OrderState, PositionState


@dataclass
class BotState:
    last_processed_candle_time: str = ""
    last_signal_candle_time: str = ""
    last_order_client_id: str = ""
    realized_pnl_today: float = 0.0
    realized_pnl_date: str = ""
    consecutive_losses: int = 0
    daily_trade_count: int = 0
    cooldown_until_candle_time: str = ""
    position: PositionState | None = None
    open_orders: list[OrderState] = field(default_factory=list)
    pending_ticket_id: str = ""
    pending_action: str = ""
    pending_created_at: str = ""
    last_daily_summary_date: str = ""
    last_exchange_sync_at: str = ""
    paper_balance_usdt: float = 0.0
    account_snapshot: AccountSnapshot | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utc_now().isoformat(timespec="seconds")


def today_str() -> str:
    return utc_now().strftime("%Y-%m-%d")


def _coerce_position(payload: dict | None) -> PositionState | None:
    if not payload:
        return None
    return PositionState(**payload)


def _coerce_orders(payload: list[dict] | None) -> list[OrderState]:
    if not payload:
        return []
    return [OrderState(**row) for row in payload]


def _coerce_account_snapshot(payload: dict | None) -> AccountSnapshot | None:
    if not payload:
        return None
    return AccountSnapshot(**payload)


def _normalize_loaded_state(data: dict) -> BotState:
    payload = dict(data)
    payload["position"] = _coerce_position(payload.get("position"))
    payload["open_orders"] = _coerce_orders(payload.get("open_orders"))
    payload["account_snapshot"] = _coerce_account_snapshot(payload.get("account_snapshot"))
    state = BotState(**payload)
    if not state.realized_pnl_date:
        state.realized_pnl_date = today_str()
    if state.realized_pnl_date != today_str():
        state.realized_pnl_today = 0.0
        state.daily_trade_count = 0
        state.realized_pnl_date = today_str()
    return state


def load_state(path: Path) -> BotState:
    if not path.exists():
        return BotState(realized_pnl_date=today_str())
    data = json.loads(path.read_text(encoding="utf-8"))
    return _normalize_loaded_state(data)


def save_state(path: Path, state: BotState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def clear_pending_ticket(state: BotState) -> None:
    state.pending_ticket_id = ""
    state.pending_action = ""
    state.pending_created_at = ""


def set_pending_ticket(state: BotState, ticket_id: str, action: str, created_at: str) -> None:
    state.pending_ticket_id = ticket_id
    state.pending_action = action
    state.pending_created_at = created_at


def find_open_order(state: BotState, *, client_order_id: str = "", order_id: str = "") -> OrderState | None:
    for order in state.open_orders:
        if client_order_id and order.client_order_id == client_order_id:
            return order
        if order_id and order.order_id == order_id:
            return order
    return None


def upsert_open_order(state: BotState, order: OrderState) -> None:
    existing = find_open_order(state, client_order_id=order.client_order_id, order_id=order.order_id)
    if existing is None:
        state.open_orders.append(order)
        return
    existing.symbol = order.symbol
    existing.side = order.side
    existing.order_type = order.order_type
    existing.order_id = order.order_id
    existing.client_order_id = order.client_order_id
    existing.status = order.status
    existing.qty = order.qty
    existing.executed_qty = order.executed_qty
    existing.quote_order_qty = order.quote_order_qty
    existing.quote_executed = order.quote_executed
    existing.price = order.price
    existing.stop_price = order.stop_price
    existing.submitted_at = order.submitted_at
    existing.updated_at = order.updated_at


def remove_open_order(state: BotState, *, client_order_id: str = "", order_id: str = "") -> None:
    state.open_orders = [
        order
        for order in state.open_orders
        if not (
            (client_order_id and order.client_order_id == client_order_id)
            or (order_id and order.order_id == order_id)
        )
    ]


def has_open_order(state: BotState, side: str | None = None) -> bool:
    if side is None:
        return bool(state.open_orders)
    return any(order.side.upper() == side.upper() for order in state.open_orders)


def apply_entry_fill(
    state: BotState,
    *,
    symbol: str,
    qty: float,
    price: float,
    stop_loss: float,
    take_profit: float,
    filled_at: str,
    fee_usd: float = 0.0,
    order_id: str = "",
    client_order_id: str = "",
) -> None:
    if qty <= 0:
        return
    was_flat = state.position is None
    if state.position is None:
        state.position = PositionState(
            symbol=symbol,
            side="LONG",
            qty=qty,
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            opened_at=filled_at,
            entry_order_id=order_id,
            entry_client_order_id=client_order_id,
            entry_fee_usd=fee_usd,
        )
    else:
        current = state.position
        total_qty = current.qty + qty
        if total_qty <= 0:
            return
        weighted_price = ((current.entry_price * current.qty) + (price * qty)) / total_qty
        current.qty = total_qty
        current.entry_price = weighted_price
        current.stop_loss = stop_loss or current.stop_loss
        current.take_profit = take_profit or current.take_profit
        current.entry_fee_usd += fee_usd
        if client_order_id:
            current.entry_client_order_id = client_order_id
        if order_id:
            current.entry_order_id = order_id
    state.last_order_client_id = client_order_id or state.last_order_client_id
    if was_flat:
        state.daily_trade_count += 1
        clear_pending_ticket(state)


def apply_exit_fill(
    state: BotState,
    *,
    symbol: str,
    qty: float,
    price: float,
    filled_at: str,
    fee_usd: float = 0.0,
) -> float:
    if qty <= 0 or state.position is None:
        return 0.0
    if state.position.symbol != symbol:
        return 0.0

    position = state.position
    close_qty = min(qty, position.qty)
    if close_qty <= 0:
        return 0.0

    entry_fee_share = 0.0
    if position.qty > 0 and position.entry_fee_usd > 0:
        entry_fee_share = position.entry_fee_usd * (close_qty / position.qty)

    gross_proceeds = price * close_qty
    gross_cost = position.entry_price * close_qty
    pnl = gross_proceeds - gross_cost - entry_fee_share - fee_usd

    remaining_qty = position.qty - close_qty
    state.realized_pnl_today += pnl

    if remaining_qty > 1e-12:
        position.qty = remaining_qty
        position.entry_fee_usd = max(0.0, position.entry_fee_usd - entry_fee_share)
    else:
        state.position = None
        clear_pending_ticket(state)
        state.consecutive_losses = state.consecutive_losses + 1 if pnl < 0 else 0
    return pnl
