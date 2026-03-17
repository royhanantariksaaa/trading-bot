from __future__ import annotations

from .config import Config
from .exchange import (
    SymbolRules,
    fetch_account_snapshot,
    fetch_open_orders,
    fetch_order_by_client_id,
    fetch_recent_trades,
)
from .models import PositionState, ReconstructedPosition
from .state import BotState, apply_entry_fill, apply_exit_fill, now_iso, remove_open_order, upsert_open_order


def _trade_side(trade: dict) -> str:
    side = trade.get("side")
    if side:
        return side.upper()
    info = trade.get("info", {}) or {}
    return "BUY" if info.get("isBuyer") else "SELL"


def _trade_fee_usd(trade: dict, quote_asset: str) -> float:
    fee = trade.get("fee") or {}
    if fee and fee.get("currency") == quote_asset:
        return float(fee.get("cost") or 0)
    info = trade.get("info", {}) or {}
    if info.get("commissionAsset") == quote_asset:
        return float(info.get("commission") or 0)
    return 0.0


def reconstruct_position_from_trades(exchange, symbol: str, rules: SymbolRules, limit: int = 100) -> ReconstructedPosition:
    trades = sorted(fetch_recent_trades(exchange, symbol, limit=limit), key=lambda row: row.get("timestamp") or 0)
    qty = 0.0
    avg_entry = 0.0
    entry_fee_usd = 0.0
    opened_at = ""
    trade_ids: list[str] = []

    for trade in trades:
        side = _trade_side(trade)
        trade_qty = float(trade.get("amount") or trade.get("info", {}).get("qty") or 0)
        trade_price = float(trade.get("price") or trade.get("info", {}).get("price") or 0)
        fee_usd = _trade_fee_usd(trade, rules.quote_asset)
        trade_time = trade.get("datetime") or now_iso()

        if side == "BUY":
            total_qty = qty + trade_qty
            if total_qty <= 0:
                continue
            avg_entry = ((avg_entry * qty) + (trade_price * trade_qty)) / total_qty if qty > 0 else trade_price
            qty = total_qty
            entry_fee_usd += fee_usd
            opened_at = opened_at or trade_time
            trade_ids.append(str(trade.get("id") or trade.get("order") or ""))
        else:
            if qty <= 0:
                continue
            close_qty = min(qty, trade_qty)
            fee_share = entry_fee_usd * (close_qty / qty) if qty > 0 else 0.0
            entry_fee_usd = max(0.0, entry_fee_usd - fee_share)
            qty -= close_qty
            if qty <= 1e-12:
                qty = 0.0
                avg_entry = 0.0
                entry_fee_usd = 0.0
                opened_at = ""
                trade_ids = []

    return ReconstructedPosition(
        qty=qty,
        entry_price=avg_entry,
        opened_at=opened_at,
        entry_fee_usd=entry_fee_usd,
        trade_ids=trade_ids,
    )


def _apply_order_fill_delta(state: BotState, config: Config, order, filled_delta: float, fill_price: float) -> None:
    if filled_delta <= 0:
        return
    if order.side == "BUY":
        existing = state.position
        stop_loss = existing.stop_loss if existing is not None else fill_price * (1 - config.stop_loss_pct)
        take_profit = existing.take_profit if existing is not None else fill_price * (1 + config.take_profit_pct)
        apply_entry_fill(
            state,
            symbol=config.symbol,
            qty=filled_delta,
            price=fill_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            filled_at=order.updated_at or now_iso(),
            order_id=order.order_id,
            client_order_id=order.client_order_id,
        )
    elif order.side == "SELL":
        apply_exit_fill(
            state,
            symbol=config.symbol,
            qty=filled_delta,
            price=fill_price,
            filled_at=order.updated_at or now_iso(),
        )


def reconcile_live_state(config: Config, exchange, state: BotState, rules: SymbolRules):
    previous_orders = {order.client_order_id: order for order in state.open_orders if order.client_order_id}
    current_open_orders = fetch_open_orders(exchange, config.symbol)
    current_by_client = {order.client_order_id: order for order in current_open_orders if order.client_order_id}

    state.open_orders = []
    for order in current_open_orders:
        previous = previous_orders.get(order.client_order_id)
        if previous is not None and order.executed_qty > previous.executed_qty:
            delta = order.executed_qty - previous.executed_qty
            fill_price = (order.quote_executed / order.executed_qty) if order.executed_qty > 0 else order.price
            _apply_order_fill_delta(state, config, order, delta, fill_price)
        upsert_open_order(state, order)

    for client_order_id, previous in previous_orders.items():
        if client_order_id in current_by_client:
            continue
        final_order = fetch_order_by_client_id(exchange, config.symbol, client_order_id)
        delta = max(0.0, final_order.executed_qty - previous.executed_qty)
        if delta > 0:
            fill_price = (final_order.quote_executed / final_order.executed_qty) if final_order.executed_qty > 0 else final_order.price
            _apply_order_fill_delta(state, config, final_order, delta, fill_price)
        remove_open_order(state, client_order_id=previous.client_order_id, order_id=previous.order_id)

    reconstructed = reconstruct_position_from_trades(exchange, config.symbol, rules)
    snapshot = fetch_account_snapshot(exchange, rules)
    state.account_snapshot = snapshot

    live_base_qty = snapshot.base_free + snapshot.base_locked
    if reconstructed.qty > 0 or live_base_qty > 1e-12:
        inferred_qty = reconstructed.qty if reconstructed.qty > 0 else live_base_qty
        inferred_entry = reconstructed.entry_price if reconstructed.entry_price > 0 else (state.position.entry_price if state.position is not None else 0.0)
        stop_loss = state.position.stop_loss if state.position is not None else inferred_entry * (1 - config.stop_loss_pct)
        take_profit = state.position.take_profit if state.position is not None else inferred_entry * (1 + config.take_profit_pct)
        state.position = PositionState(
            symbol=config.symbol,
            side="LONG",
            qty=inferred_qty,
            entry_price=inferred_entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            opened_at=reconstructed.opened_at or (state.position.opened_at if state.position is not None else now_iso()),
            entry_order_id=state.position.entry_order_id if state.position is not None else "",
            entry_client_order_id=state.position.entry_client_order_id if state.position is not None else "",
            entry_fee_usd=reconstructed.entry_fee_usd if reconstructed.entry_fee_usd > 0 else (state.position.entry_fee_usd if state.position is not None else 0.0),
        )
    elif not state.open_orders:
        state.position = None

    state.last_exchange_sync_at = now_iso()
    return snapshot
