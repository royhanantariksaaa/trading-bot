from __future__ import annotations

from config import Config
from exchange import ExchangeValidationError, SymbolRules, build_min_notional_warning, validate_market_quote_budget, validate_market_sell_quantity
from models import EntryPlan, ExitPlan
from state import BotState, has_open_order


def calc_position_size(balance_usdt: float, risk_per_trade: float, entry_price: float, stop_loss_pct: float) -> float:
    risk_budget = balance_usdt * risk_per_trade
    stop_distance = entry_price * stop_loss_pct
    if stop_distance <= 0:
        return 0.0
    qty = risk_budget / stop_distance
    max_affordable_qty = balance_usdt / entry_price
    return max(0.0, min(qty, max_affordable_qty))


def can_open_new_position(state: BotState, config: Config, candle_time: str) -> tuple[bool, str]:
    if state.position is not None:
        return False, "position already open"
    if has_open_order(state):
        return False, "unresolved live order exists"
    if state.pending_ticket_id:
        return False, "pending manual ticket exists"
    if state.realized_pnl_today <= -config.max_daily_loss_usd:
        return False, "daily loss limit reached"
    if state.daily_trade_count >= config.max_trades_per_day:
        return False, "max trades per day reached"
    if state.cooldown_until_candle_time and candle_time and candle_time <= state.cooldown_until_candle_time:
        return False, "cooldown still active"
    return True, ""


def build_entry_plan(
    *,
    config: Config,
    state: BotState,
    available_quote: float,
    signal_price: float,
    candle_time: str,
    rules: SymbolRules,
) -> EntryPlan:
    allowed, reason = can_open_new_position(state, config, candle_time)
    if not allowed:
        return EntryPlan(allowed=False, reason=reason)
    if available_quote <= 0:
        return EntryPlan(allowed=False, reason="no quote balance available")

    quote_cap = min(config.max_trade_usd, available_quote)
    risk_qty = calc_position_size(
        available_quote,
        config.risk_per_trade,
        signal_price,
        config.stop_loss_pct,
    )
    if risk_qty <= 0:
        return EntryPlan(allowed=False, reason="risk sizing returned zero")

    raw_quote_budget = min(quote_cap, risk_qty * signal_price)
    fee_buffer_usd = raw_quote_budget * config.fee_rate
    slippage_buffer_usd = raw_quote_budget * config.slippage_buffer_pct
    buffered_budget = raw_quote_budget - fee_buffer_usd - slippage_buffer_usd
    if buffered_budget <= 0:
        return EntryPlan(allowed=False, reason="fee/slippage buffer reduced quote budget to zero")

    try:
        quote_budget = validate_market_quote_budget(buffered_budget, signal_price, rules)
    except ExchangeValidationError as exc:
        return EntryPlan(allowed=False, reason=str(exc))

    estimated_qty = quote_budget / signal_price
    stop_loss = signal_price * (1 - config.stop_loss_pct)
    take_profit = signal_price * (1 + config.take_profit_pct)
    return EntryPlan(
        allowed=True,
        quote_budget=quote_budget,
        estimated_qty=estimated_qty,
        stop_loss=stop_loss,
        take_profit=take_profit,
        fee_buffer_usd=fee_buffer_usd,
        slippage_buffer_usd=slippage_buffer_usd,
        market_warning=build_min_notional_warning(config.symbol, estimated_qty, signal_price, rules),
    )


def build_exit_plan(
    *,
    config: Config,
    state: BotState,
    signal_price: float,
    rules: SymbolRules,
    reason: str,
) -> ExitPlan:
    if state.position is None:
        return ExitPlan(allowed=False, reason="no open position")
    if has_open_order(state, "BUY"):
        return ExitPlan(allowed=False, reason="entry order still unresolved")
    try:
        qty = validate_market_sell_quantity(state.position.qty, signal_price, rules)
    except ExchangeValidationError as exc:
        return ExitPlan(allowed=False, reason=str(exc))
    return ExitPlan(
        allowed=True,
        reason=reason,
        qty=qty,
        market_warning=build_min_notional_warning(config.symbol, qty, signal_price, rules),
    )
