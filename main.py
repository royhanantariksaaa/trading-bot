from __future__ import annotations

import csv
import time
from pathlib import Path

from config import Config
from exchange import create_exchange, fetch_account_snapshot, fetch_ohlcv_df, get_market_rules, prepare_htf_rsi_filter
from execution import create_manual_ticket, ensure_live_stop_loss, execute_live_entry, execute_live_exit, execute_paper_entry, execute_paper_exit
from formatters import format_no_trade_message, format_startup_message, format_status_message
from logger import fmt_pct, log_event
from notifier import DiscordNotifier
from paper_wallet import PaperWallet
from reconcile import reconcile_live_state
from risk import build_entry_plan, build_exit_plan
from state import clear_pending_ticket, load_state, save_state, today_str
from strategy import add_indicators, gate_status_for_index, signal_for_index
from tickets import append_decision_log, build_daily_summary, build_decision_message, build_ticket_message, update_ticket_status


def send_status(notifier: DiscordNotifier, message: str) -> None:
    log_event("INFO", message)
    notifier.send(message)


def _count_rows_for_today(path: Path, timestamp_field: str) -> int:
    if not path.exists():
        return 0
    today = today_str()
    count = 0
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row.get(timestamp_field, "")
            if ts.startswith(today):
                count += 1
    return count


def _last_ticket_info(path: Path) -> str:
    if not path.exists():
        return ""
    last_row = None
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            last_row = row
    if not last_row:
        return ""
    return f"{last_row.get('action', '?')}:{last_row.get('ticket_id', '?')}:{last_row.get('status', '?')}"


def maybe_send_daily_summary(config: Config, notifier: DiscordNotifier, state_path: Path, tickets_path: Path, trades_path: Path) -> None:
    state = load_state(state_path)
    today = today_str()
    if state.last_daily_summary_date == today:
        return
    send_status(
        notifier,
        build_daily_summary(
            config.symbol,
            config.timeframe,
            state.realized_pnl_today,
            config.max_daily_loss_usd,
            state.pending_ticket_id,
            _count_rows_for_today(tickets_path, "created_at"),
            _count_rows_for_today(trades_path, "timestamp"),
            _last_ticket_info(tickets_path),
        ),
    )
    state.last_daily_summary_date = today
    save_state(state_path, state)


def maybe_log_terminal_decision(config: Config, notifier: DiscordNotifier, state_path: Path, decision_log_path: Path, tickets_path: Path) -> None:
    if config.approval_mode != "terminal":
        return
    state = load_state(state_path)
    if not state.pending_ticket_id:
        return

    print(
        f"Pending ticket {state.pending_ticket_id}. Type 'approve {state.pending_ticket_id}' or 'deny {state.pending_ticket_id}' then press Enter, or just press Enter to skip.",
        flush=True,
    )
    response = input().strip().lower()
    if response in {f"approve {state.pending_ticket_id}", f"deny {state.pending_ticket_id}"}:
        decision = response.split()[0]
        append_decision_log(decision_log_path, state.pending_ticket_id, decision, note="terminal approval workflow")
        update_ticket_status(tickets_path, state.pending_ticket_id, "approved" if decision == "approve" else "denied")
        send_status(notifier, build_decision_message(state.pending_ticket_id, decision))
        clear_pending_ticket(state)
        save_state(state_path, state)


def _current_quote_balance(config: Config, state, wallet: PaperWallet | None) -> float:
    if config.bot_mode == "paper":
        return wallet.balance_usdt if wallet is not None else state.paper_balance_usdt
    if state.account_snapshot is None:
        return 0.0
    return state.account_snapshot.quote_free


def _position_state_text(state) -> str:
    if state.position is None:
        return "flat"
    return (
        f"long qty={state.position.qty:.6f} entry={state.position.entry_price:.4f} "
        f"stop={state.position.stop_loss:.4f} tp={state.position.take_profit:.4f}"
    )


def _build_strategy_label(config: Config) -> str:
    strategy_label = "EMA 9/21"
    if config.use_rsi_filter:
        strategy_label += f" + RSI({config.rsi_period}) buy>={config.rsi_buy_min:.1f} sell<={config.rsi_sell_max:.1f}"
    if config.use_htf_filter:
        strategy_label += f" + HTF[{config.htf_1_timeframe}] RSI>={config.htf_1_rsi_min:.1f}"
        if config.htf_2_enabled:
            strategy_label += f" + HTF[{config.htf_2_timeframe}] RSI>={config.htf_2_rsi_min:.1f}"
    return strategy_label


def _resolve_exit_reason(config: Config, state, signal: str, signal_price: float, live_row) -> str:
    if state.position is None:
        return ""
    low_price = float(live_row["low"])
    high_price = float(live_row["high"])
    if config.bot_mode == "paper":
        if low_price <= state.position.stop_loss:
            return "stop_loss"
    if config.bot_mode == "live" and not any(order.side == "SELL" and order.stop_price > 0 for order in state.open_orders):
        if low_price <= state.position.stop_loss:
            return "stop_loss"
    if high_price >= state.position.take_profit:
        return "take_profit"
    if signal == "sell":
        return "ema_cross_down"
    if signal_price <= state.position.stop_loss and config.bot_mode != "live":
        return "stop_loss"
    return ""


def run_bot(config: Config) -> None:
    exchange = create_exchange(config)
    market_rules = get_market_rules(exchange, config.symbol)
    trades_path = Path("trades.csv")
    notifier = DiscordNotifier(config.discord_webhook_url)
    state_path = Path("runtime_state.json")
    tickets_path = Path("manual_tickets.csv")
    decision_log_path = Path("decision_log.csv")

    state = load_state(state_path)
    if state.paper_balance_usdt <= 0:
        state.paper_balance_usdt = config.starting_balance
    wallet = PaperWallet.from_state(
        state,
        trades_path=trades_path,
        starting_balance=config.starting_balance,
        fee_rate=config.fee_rate,
        slippage_pct=config.slippage_buffer_pct,
    )

    if config.bot_mode == "live" and config.reconcile_on_start:
        state.account_snapshot = reconcile_live_state(config, exchange, state, market_rules)
    elif config.bot_mode == "live":
        state.account_snapshot = fetch_account_snapshot(exchange, market_rules)
    save_state(state_path, state)

    startup = format_startup_message(
        config.symbol,
        config.timeframe,
        _current_quote_balance(config, state, wallet),
        fmt_pct(config.risk_per_trade),
        fmt_pct(config.stop_loss_pct),
        fmt_pct(config.take_profit_pct),
        _build_strategy_label(config),
        config.execution_mode,
        config.approval_mode,
        config.signal_on_closed_candle,
    )
    send_status(notifier, startup)
    maybe_send_daily_summary(config, notifier, state_path, tickets_path, trades_path)

    htf1 = None
    htf2 = None
    if config.use_htf_filter:
        htf1 = prepare_htf_rsi_filter(exchange, config.symbol, config.htf_1_timeframe, config.htf_1_rsi_period, config.htf_1_rsi_min)
        if config.htf_2_enabled:
            htf2 = prepare_htf_rsi_filter(exchange, config.symbol, config.htf_2_timeframe, config.htf_2_rsi_period, config.htf_2_rsi_min)

    loops = 0
    while True:
        try:
            if config.kill_switch:
                send_status(notifier, "Kill switch enabled. Exiting.")
                break

            state = load_state(state_path)
            if config.bot_mode == "paper":
                wallet = PaperWallet.from_state(
                    state,
                    trades_path=trades_path,
                    starting_balance=config.starting_balance,
                    fee_rate=config.fee_rate,
                    slippage_pct=config.slippage_buffer_pct,
                )
                state.paper_balance_usdt = wallet.balance_usdt
            else:
                if state.open_orders or state.position is not None or loops == 0:
                    state.account_snapshot = reconcile_live_state(config, exchange, state, market_rules)
                else:
                    state.account_snapshot = fetch_account_snapshot(exchange, market_rules)
                if config.execution_mode == "auto" and state.position is not None:
                    ensure_live_stop_loss(exchange=exchange, config=config, state=state, rules=market_rules, candle_time=state.last_signal_candle_time or today_str())

            if state.realized_pnl_today <= -config.max_daily_loss_usd:
                send_status(
                    notifier,
                    f"Daily loss limit reached. realized_pnl_today={state.realized_pnl_today:.4f} max_daily_loss={config.max_daily_loss_usd:.4f}. No new entries.",
                )
                save_state(state_path, state)
                time.sleep(config.poll_seconds)
                loops += 1
                continue

            df = fetch_ohlcv_df(exchange, config.symbol, config.timeframe)
            df = add_indicators(df, rsi_period=config.rsi_period)

            signal_index = len(df) - 2 if config.signal_on_closed_candle else len(df) - 1
            signal_row = df.iloc[signal_index]
            live_row = df.iloc[-1]
            candle_time = str(signal_row["timestamp"])
            signal_price = float(signal_row["close"])
            live_price = float(live_row["close"])
            ema_fast = float(signal_row["ema_fast"])
            ema_slow = float(signal_row["ema_slow"])
            rsi = float(signal_row["rsi"]) if signal_row["rsi"] == signal_row["rsi"] else float("nan")
            gates = gate_status_for_index(
                df,
                signal_index,
                use_rsi_filter=config.use_rsi_filter,
                rsi_buy_min=config.rsi_buy_min,
                rsi_sell_max=config.rsi_sell_max,
            )
            signal = signal_for_index(
                df,
                signal_index,
                use_rsi_filter=config.use_rsi_filter,
                rsi_buy_min=config.rsi_buy_min,
                rsi_sell_max=config.rsi_sell_max,
            )

            htf_ok = True
            htf_parts = []
            if config.use_htf_filter and htf1 is not None:
                htf1_row = htf1[htf1["timestamp"] <= signal_row["timestamp"]].tail(1)
                if htf1_row.empty:
                    htf_ok = False
                    htf_parts.append(f"{config.htf_1_timeframe}=missing")
                else:
                    htf1_rsi = float(htf1_row.iloc[0][f"htf_rsi_{config.htf_1_timeframe}"])
                    htf1_pass = bool(htf1_row.iloc[0][f"htf_pass_{config.htf_1_timeframe}"])
                    htf_ok = htf_ok and htf1_pass
                    htf_parts.append(f"{config.htf_1_timeframe}_rsi={htf1_rsi:.2f}")
                if config.htf_2_enabled and htf2 is not None:
                    htf2_row = htf2[htf2["timestamp"] <= signal_row["timestamp"]].tail(1)
                    if htf2_row.empty:
                        htf_ok = False
                        htf_parts.append(f"{config.htf_2_timeframe}=missing")
                    else:
                        htf2_rsi = float(htf2_row.iloc[0][f"htf_rsi_{config.htf_2_timeframe}"])
                        htf2_pass = bool(htf2_row.iloc[0][f"htf_pass_{config.htf_2_timeframe}"])
                        htf_ok = htf_ok and htf2_pass
                        htf_parts.append(f"{config.htf_2_timeframe}_rsi={htf2_rsi:.2f}")

            htf_text = " | ".join(htf_parts) if htf_parts else "htf=off"
            available_quote = _current_quote_balance(config, state, wallet if config.bot_mode == "paper" else None)

            if state.position is not None:
                sell_reason = _resolve_exit_reason(config, state, signal, signal_price, live_row)
                if sell_reason:
                    if state.last_signal_candle_time == candle_time and (state.pending_action == "SELL" or any(order.side == "SELL" for order in state.open_orders)):
                        log_event("INFO", f"Sell action already registered for candle {candle_time}; skipping duplicate sell signal.")
                    else:
                        exit_plan = build_exit_plan(
                            config=config,
                            state=state,
                            signal_price=live_price,
                            rules=market_rules,
                            reason=sell_reason,
                        )
                        if exit_plan.allowed:
                            if config.execution_mode == "manual":
                                ticket = create_manual_ticket(
                                    tickets_path=tickets_path,
                                    state=state,
                                    config=config,
                                    action="SELL",
                                    signal_price=live_price,
                                    qty=exit_plan.qty,
                                    stop_loss=state.position.stop_loss,
                                    take_profit=state.position.take_profit,
                                    reason=f"exit | reason={sell_reason} | {htf_text}",
                                    rsi=rsi,
                                    candle_time=candle_time,
                                )
                                send_status(
                                    notifier,
                                    build_ticket_message(ticket, config.max_daily_loss_usd, state.realized_pnl_today, market_warning=exit_plan.market_warning),
                                )
                                save_state(state_path, state)
                                maybe_log_terminal_decision(config, notifier, state_path, decision_log_path, tickets_path)
                            elif config.bot_mode == "paper":
                                realized, message = execute_paper_exit(
                                    wallet=wallet,
                                    state=state,
                                    config=config,
                                    exit_plan=exit_plan,
                                    market_price=live_price,
                                    candle_time=candle_time,
                                )
                                send_status(notifier, f"{message} | realized=`{realized:.4f}`")
                            else:
                                realized, message = execute_live_exit(
                                    exchange=exchange,
                                    config=config,
                                    state=state,
                                    exit_plan=exit_plan,
                                    signal_price=live_price,
                                    candle_time=candle_time,
                                )
                                send_status(notifier, f"{message} | market_warning=`{exit_plan.market_warning or 'none'}`")
                        else:
                            log_event("WARN", f"Exit blocked: {exit_plan.reason}")
                else:
                    log_event(
                        "INFO",
                        f"HOLDING | live_price={live_price:.4f} | signal_price={signal_price:.4f} | entry={state.position.entry_price:.4f} | "
                        f"stop={state.position.stop_loss:.4f} | tp={state.position.take_profit:.4f} | ema9={ema_fast:.4f} | ema21={ema_slow:.4f} | "
                        f"entry_rsi_15m={rsi:.2f} | ema_cross_up={gates['crossed_up']} ema_cross_down={gates['crossed_down']} "
                        f"rsi_entry_ok={gates['rsi_buy_ok']} rsi_exit_ok={gates['rsi_sell_ok']} | {htf_text}",
                    )
            else:
                if signal == "buy" and htf_ok:
                    entry_plan = build_entry_plan(
                        config=config,
                        state=state,
                        available_quote=available_quote,
                        signal_price=signal_price,
                        candle_time=candle_time,
                        rules=market_rules,
                    )
                    if entry_plan.allowed:
                        if state.last_signal_candle_time == candle_time and state.pending_action == "BUY":
                            log_event("INFO", f"Signal already ticketed for candle {candle_time}; skipping duplicate buy ticket.")
                        else:
                            if config.execution_mode == "manual":
                                ticket = create_manual_ticket(
                                    tickets_path=tickets_path,
                                    state=state,
                                    config=config,
                                    action="BUY",
                                    signal_price=signal_price,
                                    qty=entry_plan.estimated_qty,
                                    stop_loss=entry_plan.stop_loss,
                                    take_profit=entry_plan.take_profit,
                                    reason=f"entry | ema9={ema_fast:.4f} ema21={ema_slow:.4f} | {htf_text}",
                                    rsi=rsi,
                                    candle_time=candle_time,
                                )
                                send_status(
                                    notifier,
                                    build_ticket_message(ticket, config.max_daily_loss_usd, state.realized_pnl_today, market_warning=entry_plan.market_warning),
                                )
                                save_state(state_path, state)
                                maybe_log_terminal_decision(config, notifier, state_path, decision_log_path, tickets_path)
                            elif config.bot_mode == "paper":
                                send_status(
                                    notifier,
                                    execute_paper_entry(
                                        wallet=wallet,
                                        state=state,
                                        config=config,
                                        entry_plan=entry_plan,
                                        candle_time=candle_time,
                                    ),
                                )
                            else:
                                send_status(
                                    notifier,
                                    execute_live_entry(
                                        exchange=exchange,
                                        config=config,
                                        state=state,
                                        entry_plan=entry_plan,
                                        signal_price=signal_price,
                                        candle_time=candle_time,
                                        rules=market_rules,
                                    ),
                                )
                    else:
                        log_event("INFO", f"BUY blocked | reason={entry_plan.reason}")
                else:
                    no_trade_msg = format_no_trade_message(
                        config.symbol,
                        config.timeframe,
                        signal,
                        htf_ok,
                        live_price,
                        signal_price,
                        ema_fast,
                        ema_slow,
                        rsi,
                        gates["crossed_up"],
                        gates["crossed_down"],
                        gates["rsi_buy_ok"],
                        gates["rsi_sell_ok"],
                        htf_text,
                        available_quote,
                    )
                    log_event("INFO", no_trade_msg)

            loops += 1
            state.last_processed_candle_time = candle_time

            if config.status_every_loops > 0 and loops % config.status_every_loops == 0:
                status_msg = format_status_message(
                    config.symbol,
                    config.timeframe,
                    signal,
                    htf_ok,
                    signal_price,
                    live_price,
                    rsi,
                    gates["crossed_up"],
                    gates["crossed_down"],
                    gates["rsi_buy_ok"],
                    gates["rsi_sell_ok"],
                    htf_text,
                    available_quote,
                    state.realized_pnl_today,
                    state.pending_ticket_id or "none",
                    _position_state_text(state),
                )
                send_status(notifier, status_msg)

            save_state(state_path, state)
            time.sleep(config.poll_seconds)
        except KeyboardInterrupt:
            send_status(notifier, "Keyboard interrupt received. Exiting bot.")
            break
        except EOFError:
            send_status(notifier, "Terminal input closed. Exiting bot.")
            break
        except Exception as exc:
            send_status(notifier, f"ERROR -> {type(exc).__name__}: {exc}")
            time.sleep(max(5, config.poll_seconds))


def main() -> None:
    config = Config()
    config.validate()
    run_bot(config)


if __name__ == "__main__":
    main()
