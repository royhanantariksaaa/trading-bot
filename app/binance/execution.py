from __future__ import annotations

from uuid import uuid4

from .config import Config
from .exchange import (
    SymbolRules,
    cancel_order_by_client_id,
    order_average_price,
    submit_market_buy,
    submit_market_sell,
    submit_stop_loss_sell,
    validate_market_buy_order,
    validate_market_sell_quantity,
    validate_market_sell_order,
    validate_stop_loss_sell_order,
)
from .models import EntryPlan, ExitPlan, OrderState
from .paper_wallet import PaperWallet
from .state import (
    BotState,
    apply_entry_fill,
    apply_exit_fill,
    clear_pending_ticket,
    now_iso,
    remove_open_order,
    set_pending_ticket,
    upsert_open_order,
)
from .tickets import ManualTicket, ExecutionRecord, append_execution_log, append_ticket, get_ticket, new_ticket_id, update_ticket_status


def build_client_order_id(symbol: str, side: str, candle_time: str, label: str = "") -> str:
    compact_symbol = symbol.replace("/", "").lower()[:10]
    compact_time = (
        candle_time.replace("-", "")
        .replace(":", "")
        .replace("T", "")
        .replace("+00:00", "")
        .replace(" ", "")
    )
    suffix = uuid4().hex[:6]
    label_part = f"-{label[:4].lower()}" if label else ""
    return f"kl-{compact_symbol}-{side[:1].lower()}{label_part}-{compact_time[-10:]}-{suffix}"[:36]


def create_manual_ticket(
    *,
    tickets_path: Path,
    state: BotState,
    config: Config,
    action: str,
    signal_price: float,
    qty: float,
    stop_loss: float,
    take_profit: float,
    reason: str,
    rsi: float,
    candle_time: str,
) -> ManualTicket:
    ticket = ManualTicket(
        ticket_id=new_ticket_id(),
        created_at=now_iso(),
        action=action,
        symbol=config.symbol,
        timeframe=config.timeframe,
        price=signal_price,
        qty=qty,
        notional_usd=qty * signal_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        reason=reason,
        rsi=rsi,
    )
    append_ticket(tickets_path, ticket)
    state.last_signal_candle_time = candle_time
    set_pending_ticket(state, ticket.ticket_id, ticket.action, ticket.created_at)
    return ticket


def execute_paper_entry(
    *,
    wallet: PaperWallet,
    state: BotState,
    config: Config,
    entry_plan: EntryPlan,
    candle_time: str,
) -> str:
    fill_price, fee_usd = wallet.enter_long(
        price=entry_plan.quote_budget / max(entry_plan.estimated_qty, 1e-12),
        qty=entry_plan.estimated_qty,
        stop_loss=entry_plan.stop_loss,
        take_profit=entry_plan.take_profit,
    )
    if fill_price <= 0:
        raise RuntimeError("Paper entry failed after sizing approval")
    apply_entry_fill(
        state,
        symbol=config.symbol,
        qty=entry_plan.estimated_qty,
        price=fill_price,
        stop_loss=entry_plan.stop_loss,
        take_profit=entry_plan.take_profit,
        filled_at=now_iso(),
        fee_usd=fee_usd,
        order_id="paper-entry",
        client_order_id=build_client_order_id(config.symbol, "BUY", candle_time, "paper"),
    )
    state.paper_balance_usdt = wallet.balance_usdt
    state.last_signal_candle_time = candle_time
    return (
        f"[AUTO ENTRY] PAPER BUY filled | pair=`{config.symbol}` qty=`{entry_plan.estimated_qty:.6f}` "
        f"price=`{fill_price:.4f}` stop=`{entry_plan.stop_loss:.4f}` tp=`{entry_plan.take_profit:.4f}`"
    )


def execute_paper_exit(
    *,
    wallet: PaperWallet,
    state: BotState,
    config: Config,
    exit_plan: ExitPlan,
    market_price: float,
    candle_time: str,
) -> tuple[float, str]:
    if state.position is None:
        return 0.0, "[AUTO EXIT] no open paper position"
    fill_price, fee_usd, pnl = wallet.exit_long(
        price=market_price,
        qty=exit_plan.qty,
        note=exit_plan.reason,
    )
    if fill_price <= 0:
        raise RuntimeError("Paper exit failed after exit approval")
    realized = apply_exit_fill(
        state,
        symbol=config.symbol,
        qty=exit_plan.qty,
        price=fill_price,
        filled_at=now_iso(),
        fee_usd=fee_usd,
    )
    state.paper_balance_usdt = wallet.balance_usdt
    state.cooldown_until_candle_time = candle_time
    state.last_signal_candle_time = candle_time
    return realized, (
        f"[AUTO EXIT] PAPER SELL filled | pair=`{config.symbol}` qty=`{exit_plan.qty:.6f}` "
        f"price=`{fill_price:.4f}` pnl=`{pnl:.4f}` reason=`{exit_plan.reason}`"
    )


def ensure_live_stop_loss(
    *,
    exchange,
    config: Config,
    state: BotState,
    rules: SymbolRules,
    candle_time: str,
) -> OrderState | None:
    if state.position is None:
        return None
    existing = next((order for order in state.open_orders if order.side == "SELL" and order.stop_price > 0), None)
    if existing is not None:
        qty_matches = abs(existing.qty - state.position.qty) <= 1e-12
        stop_matches = abs(existing.stop_price - state.position.stop_loss) <= 1e-12
        if qty_matches and stop_matches:
            return existing
        cancel_order_by_client_id(exchange, config.symbol, existing.client_order_id)
        remove_open_order(state, client_order_id=existing.client_order_id, order_id=existing.order_id)

    protective_qty = validate_market_sell_quantity(state.position.qty, state.position.stop_loss, rules)
    client_order_id = build_client_order_id(config.symbol, "SELL", candle_time, "stop")
    if config.order_test_before_submit:
        validate_stop_loss_sell_order(exchange, config.symbol, protective_qty, state.position.stop_loss, client_order_id)
    order = submit_stop_loss_sell(exchange, config.symbol, protective_qty, state.position.stop_loss, client_order_id)
    upsert_open_order(state, order)
    return order


def execute_live_entry(
    *,
    exchange,
    config: Config,
    state: BotState,
    entry_plan: EntryPlan,
    signal_price: float,
    candle_time: str,
    rules: SymbolRules,
) -> str:
    client_order_id = build_client_order_id(config.symbol, "BUY", candle_time, "entry")
    state.last_order_client_id = client_order_id
    state.last_signal_candle_time = candle_time
    upsert_open_order(
        state,
        OrderState(
            symbol=config.symbol,
            side="BUY",
            order_type="MARKET",
            order_id="",
            client_order_id=client_order_id,
            status="SUBMITTING",
            quote_order_qty=entry_plan.quote_budget,
            submitted_at=now_iso(),
            updated_at=now_iso(),
        ),
    )

    if config.order_test_before_submit:
        validate_market_buy_order(exchange, config.symbol, entry_plan.quote_budget, signal_price, client_order_id)
    order = submit_market_buy(exchange, config.symbol, entry_plan.quote_budget, signal_price, client_order_id)
    upsert_open_order(state, order)

    if order.executed_qty > 0:
        fill_price = order_average_price({
            "average": order.quote_executed / order.executed_qty if order.executed_qty > 0 else 0,
            "filled": order.executed_qty,
            "cost": order.quote_executed,
            "price": signal_price,
        })
        apply_entry_fill(
            state,
            symbol=config.symbol,
            qty=order.executed_qty,
            price=fill_price,
            stop_loss=entry_plan.stop_loss,
            take_profit=entry_plan.take_profit,
            filled_at=order.updated_at or now_iso(),
            order_id=order.order_id,
            client_order_id=order.client_order_id,
        )
    if order.status in {"CLOSED", "FILLED"}:
        remove_open_order(state, client_order_id=order.client_order_id, order_id=order.order_id)

    ensure_live_stop_loss(exchange=exchange, config=config, state=state, rules=rules, candle_time=candle_time)
    return (
        f"[AUTO ENTRY] LIVE BUY submitted | pair=`{config.symbol}` client=`{client_order_id}` "
        f"quote=`{entry_plan.quote_budget:.4f}` filled_qty=`{order.executed_qty:.6f}` status=`{order.status}`"
    )


def cancel_live_orders(exchange, state: BotState, symbol: str) -> None:
    for order in list(state.open_orders):
        cancel_order_by_client_id(exchange, symbol, order.client_order_id)
        remove_open_order(state, client_order_id=order.client_order_id, order_id=order.order_id)


def execute_live_exit(
    *,
    exchange,
    config: Config,
    state: BotState,
    exit_plan: ExitPlan,
    signal_price: float,
    candle_time: str,
) -> tuple[float, str]:
    if state.position is None:
        return 0.0, "[AUTO EXIT] no live position to close"

    cancel_live_orders(exchange, state, config.symbol)
    client_order_id = build_client_order_id(config.symbol, "SELL", candle_time, "exit")
    state.last_order_client_id = client_order_id
    state.last_signal_candle_time = candle_time
    upsert_open_order(
        state,
        OrderState(
            symbol=config.symbol,
            side="SELL",
            order_type="MARKET",
            order_id="",
            client_order_id=client_order_id,
            status="SUBMITTING",
            qty=exit_plan.qty,
            submitted_at=now_iso(),
            updated_at=now_iso(),
        ),
    )

    if config.order_test_before_submit:
        validate_market_sell_order(exchange, config.symbol, exit_plan.qty, client_order_id)
    order = submit_market_sell(exchange, config.symbol, exit_plan.qty, client_order_id)
    upsert_open_order(state, order)

    realized = 0.0
    if order.executed_qty > 0:
        fill_price = order_average_price({
            "average": order.quote_executed / order.executed_qty if order.executed_qty > 0 else 0,
            "filled": order.executed_qty,
            "cost": order.quote_executed,
            "price": signal_price,
        })
        realized = apply_exit_fill(
            state,
            symbol=config.symbol,
            qty=order.executed_qty,
            price=fill_price,
            filled_at=order.updated_at or now_iso(),
        )
        if state.position is None:
            state.cooldown_until_candle_time = candle_time
    if order.status in {"CLOSED", "FILLED"}:
        remove_open_order(state, client_order_id=order.client_order_id, order_id=order.order_id)

    return realized, (
        f"[AUTO EXIT] LIVE SELL submitted | pair=`{config.symbol}` client=`{client_order_id}` "
        f"qty=`{exit_plan.qty:.6f}` filled_qty=`{order.executed_qty:.6f}` pnl=`{realized:.4f}` reason=`{exit_plan.reason}`"
    )


def apply_manual_execution(
    *,
    state: BotState,
    config: Config,
    ticket_id: str,
    action: str,
    execution_type: str,
    price: float,
    qty: float,
    fee_usd: float,
    note: str,
    order_id: str = "",
    client_order_id: str = "",
) -> tuple[float, ExecutionRecord]:
    ticket = get_ticket(config.tickets_path, ticket_id)
    stop_loss = float(ticket.get("stop_loss") or 0) if ticket else price * (1 - config.stop_loss_pct)
    take_profit = float(ticket.get("take_profit") or 0) if ticket else price * (1 + config.take_profit_pct)

    realized = 0.0
    if execution_type == "entry":
        apply_entry_fill(
            state,
            symbol=config.symbol,
            qty=qty,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            filled_at=now_iso(),
            fee_usd=fee_usd,
            order_id=order_id,
            client_order_id=client_order_id,
        )
        target_status = "executed"
    else:
        realized = apply_exit_fill(
            state,
            symbol=config.symbol,
            qty=qty,
            price=price,
            filled_at=now_iso(),
            fee_usd=fee_usd,
        )
        if state.position is None:
            state.cooldown_until_candle_time = state.last_signal_candle_time
        target_status = "closed"

    clear_pending_ticket(state)
    update_ticket_status(config.tickets_path, ticket_id, target_status)
    record = ExecutionRecord(
        timestamp=now_iso(),
        ticket_id=ticket_id,
        action=action,
        symbol=config.symbol,
        execution_type=execution_type,
        price=price,
        qty=qty,
        notional_usd=price * qty,
        fee_usd=fee_usd,
        order_id=order_id,
        client_order_id=client_order_id,
        fill_source="manual",
        notes=note,
    )
    append_execution_log(config.execution_log_path, record)
    return realized, record
