from __future__ import annotations

import csv
import time
from pathlib import Path

from config import Config
from exchange import create_exchange, fetch_ohlcv_df, prepare_htf_rsi_filter, get_market_rules, build_min_notional_warning
from formatters import format_no_trade_message, format_startup_message, format_status_message
from logger import fmt_pct, log_event
from notifier import DiscordNotifier
from paper_wallet import PaperWallet
from risk import calc_position_size
from state import load_state, save_state, today_str
from strategy import add_indicators, gate_status_for_index, signal_for_index
from tickets import (
    ManualTicket,
    append_decision_log,
    append_ticket,
    build_daily_summary,
    build_decision_message,
    build_ticket_message,
    new_ticket_id,
    now_iso,
)


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
        from tickets import update_ticket_status
        update_ticket_status(tickets_path, state.pending_ticket_id, "approved" if decision == "approve" else "denied")
        send_status(notifier, build_decision_message(state.pending_ticket_id, decision))
        state.pending_ticket_id = ""
        state.pending_action = ""
        state.pending_created_at = ""
        save_state(state_path, state)


def create_manual_ticket(
    tickets_path: Path,
    notifier: DiscordNotifier,
    state_path: Path,
    state,
    config: Config,
    action: str,
    signal_price: float,
    qty: float,
    stop_loss: float,
    take_profit: float,
    reason: str,
    rsi: float,
    candle_time: str,
    market_warning: str,
) -> None:
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
    state.pending_ticket_id = ticket.ticket_id
    state.pending_action = ticket.action
    state.pending_created_at = ticket.created_at
    save_state(state_path, state)
    send_status(notifier, build_ticket_message(ticket, config.max_daily_loss_usd, state.realized_pnl_today, market_warning=market_warning))


def run_paper_bot(config: Config) -> None:
    exchange = create_exchange(config)
    market_rules = get_market_rules(exchange, config.symbol)
    trades_path = Path("trades.csv")
    wallet = PaperWallet(
        balance_usdt=config.starting_balance,
        trades_path=trades_path,
    )
    notifier = DiscordNotifier(config.discord_webhook_url)
    state_path = Path("runtime_state.json")
    tickets_path = Path("manual_tickets.csv")
    decision_log_path = Path("decision_log.csv")
    loops = 0

    strategy_label = "EMA 9/21"
    if config.use_rsi_filter:
        strategy_label += f" + RSI({config.rsi_period}) buy>={config.rsi_buy_min:.1f} sell<={config.rsi_sell_max:.1f}"
    if config.use_htf_filter:
        strategy_label += f" + HTF[{config.htf_1_timeframe}] RSI>={config.htf_1_rsi_min:.1f}"
        if config.htf_2_enabled:
            strategy_label += f" + HTF[{config.htf_2_timeframe}] RSI>={config.htf_2_rsi_min:.1f}"

    startup = format_startup_message(
        config.symbol,
        config.timeframe,
        config.starting_balance,
        fmt_pct(config.risk_per_trade),
        fmt_pct(config.stop_loss_pct),
        fmt_pct(config.take_profit_pct),
        strategy_label,
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

    while True:
        try:
            if config.kill_switch:
                send_status(notifier, "Kill switch enabled. Exiting.")
                break

            state = load_state(state_path)
            if state.realized_pnl_today <= -config.max_daily_loss_usd:
                send_status(
                    notifier,
                    f"Daily loss limit reached. realized_pnl_today={state.realized_pnl_today:.4f} max_daily_loss={config.max_daily_loss_usd:.4f}. No new tickets.",
                )
                time.sleep(config.poll_seconds)
                continue

            df = fetch_ohlcv_df(exchange, config.symbol, config.timeframe)
            df = add_indicators(df, rsi_period=config.rsi_period)

            signal_index = len(df) - 2 if config.signal_on_closed_candle else len(df) - 1
            signal_row = df.iloc[signal_index]
            live_row = df.iloc[-1]
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
            signal_price = float(signal_row["close"])
            live_price = float(live_row["close"])
            candle_index = signal_index
            candle_time = str(signal_row["timestamp"])
            ema_fast = float(signal_row["ema_fast"])
            ema_slow = float(signal_row["ema_slow"])
            rsi = float(signal_row["rsi"]) if signal_row["rsi"] == signal_row["rsi"] else float("nan")
            loops += 1

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

            if wallet.position is not None:
                sell_reason = ""
                if signal_price <= wallet.position.stop_loss:
                    sell_reason = "stop_loss"
                elif signal_price >= wallet.position.take_profit:
                    sell_reason = "take_profit"
                elif signal == "sell":
                    sell_reason = "ema_cross_down"

                if sell_reason:
                    if state.last_signal_candle_time == candle_time and state.pending_action == "SELL":
                        log_event("INFO", f"Sell signal already ticketed for candle {candle_time}; skipping duplicate sell ticket.")
                    else:
                        market_warning = build_min_notional_warning(config.symbol, wallet.position.qty, signal_price, market_rules)
                        create_manual_ticket(
                            tickets_path,
                            notifier,
                            state_path,
                            state,
                            config,
                            "SELL",
                            signal_price,
                            wallet.position.qty,
                            wallet.position.stop_loss,
                            wallet.position.take_profit,
                            f"closed-candle exit | reason={sell_reason} | {htf_text}",
                            rsi,
                            candle_time,
                            market_warning,
                        )
                        maybe_log_terminal_decision(config, notifier, state_path, decision_log_path, tickets_path)
                else:
                    log_event(
                        "INFO",
                        f"HOLDING | live_price={live_price:.4f} | signal_price={signal_price:.4f} | entry={wallet.position.entry_price:.4f} | stop={wallet.position.stop_loss:.4f} | tp={wallet.position.take_profit:.4f} | ema9={ema_fast:.4f} | ema21={ema_slow:.4f} | entry_rsi_15m={rsi:.2f} | ema_cross_up={gates['crossed_up']} ema_cross_down={gates['crossed_down']} rsi_entry_ok={gates['rsi_buy_ok']} rsi_exit_ok={gates['rsi_sell_ok']} | {htf_text}",
                    )
            else:
                if signal == "buy" and htf_ok and wallet.can_enter(candle_index, config.cooldown_candles):
                    if state.last_signal_candle_time == candle_time and state.pending_action == "BUY":
                        log_event("INFO", f"Signal already ticketed for candle {candle_time}; skipping duplicate buy ticket.")
                    else:
                        notional_usd = min(config.max_trade_usd, wallet.balance_usdt)
                        qty = notional_usd / signal_price if signal_price > 0 else 0.0
                        risk_qty = calc_position_size(
                            wallet.balance_usdt,
                            config.risk_per_trade,
                            signal_price,
                            config.stop_loss_pct,
                        )
                        qty = min(qty, risk_qty)
                        stop_loss = signal_price * (1 - config.stop_loss_pct)
                        take_profit = signal_price * (1 + config.take_profit_pct)
                        if qty > 0 and notional_usd > 0:
                            market_warning = build_min_notional_warning(config.symbol, qty, signal_price, market_rules)
                            create_manual_ticket(
                                tickets_path,
                                notifier,
                                state_path,
                                state,
                                config,
                                "BUY",
                                signal_price,
                                qty,
                                stop_loss,
                                take_profit,
                                f"closed-candle signal | ema9={ema_fast:.4f} ema21={ema_slow:.4f} | {htf_text}",
                                rsi,
                                candle_time,
                                market_warning,
                            )
                            maybe_log_terminal_decision(config, notifier, state_path, decision_log_path, tickets_path)
                        else:
                            log_event("WARN", "BUY signal happened, but trade sizing blocked ticket creation.")
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
                        gates['crossed_up'],
                        gates['crossed_down'],
                        gates['rsi_buy_ok'],
                        gates['rsi_sell_ok'],
                        htf_text,
                        wallet.balance_usdt,
                    )
                    log_event("INFO", no_trade_msg)
                    if config.status_every_loops == 0:
                        notifier.send(no_trade_msg)

            if config.status_every_loops > 0 and loops % config.status_every_loops == 0:
                position_state = "flat"
                if wallet.position is not None:
                    position_state = (
                        f"long qty={wallet.position.qty:.6f} entry={wallet.position.entry_price:.4f} "
                        f"stop={wallet.position.stop_loss:.4f} tp={wallet.position.take_profit:.4f}"
                    )
                status_msg = format_status_message(
                    config.symbol,
                    config.timeframe,
                    signal,
                    htf_ok,
                    signal_price,
                    live_price,
                    rsi,
                    gates['crossed_up'],
                    gates['crossed_down'],
                    gates['rsi_buy_ok'],
                    gates['rsi_sell_ok'],
                    htf_text,
                    wallet.balance_usdt,
                    state.realized_pnl_today,
                    state.pending_ticket_id or 'none',
                    position_state,
                )
                send_status(notifier, status_msg)

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

    if config.bot_mode == "live":
        raise NotImplementedError(
            "Live mode is intentionally blocked in this starter build. Use supervised manual mode instead."
        )

    run_paper_bot(config)


if __name__ == "__main__":
    main()
