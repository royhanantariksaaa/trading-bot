from __future__ import annotations


def format_startup_message(
    symbol: str,
    timeframe: str,
    balance: float,
    risk_pct: str,
    sl_pct: str,
    tp_pct: str,
    strategy_label: str,
    execution_mode: str,
    approval_mode: str,
    closed_candle: bool,
) -> str:
    return (
        f"[STARTED] BOT ONLINE\n"
        f"Pair: `{symbol}` | TF: `{timeframe}`\n"
        f"Balance: `{balance:.2f} USDT` | Risk: `{risk_pct}`\n"
        f"SL / TP: `{sl_pct}` / `{tp_pct}`\n"
        f"Strategy: `{strategy_label}`\n"
        f"Execution: `{execution_mode}` | Approval: `{approval_mode}` | Closed candle: `{closed_candle}`"
    )


def format_readonly_startup_message(
    symbol: str,
    timeframe: str,
    balance: float,
    strategy_label: str,
    execution_mode: str,
    selection_mode: str,
    report_path: str,
    report_json_path: str,
    *,
    selection_summary: str = "",
    adaptive_summary: str = "",
    use_testnet: bool = False,
    enable_live_trading: bool = False,
) -> str:
    lines = [
        "[STARTED] BINANCE LIVE READ-ONLY",
        f"Pair: `{symbol}` | TF: `{timeframe}`",
        f"Balance: `{balance:.2f} USDT`",
        f"Strategy: `{strategy_label}`",
        f"Execution preview: `{execution_mode}` | Selection mode: `{selection_mode}`",
        f"Guard: `no submit/test/cancel` | Testnet: `{use_testnet}` | Live trading flag ignored: `{enable_live_trading}`",
    ]
    if selection_summary:
        lines.append(f"Selected candidate: `{selection_summary}`")
    if adaptive_summary:
        lines.append(f"Adaptive overlay: `{adaptive_summary}`")
    lines.append(f"Report files: `{report_path}` | `{report_json_path}`")
    return "\n".join(lines)


def format_status_message(
    symbol: str,
    timeframe: str,
    signal: str,
    htf_ok: bool,
    signal_price: float,
    live_price: float,
    entry_rsi_15m: float,
    ema_cross_up: bool,
    ema_cross_down: bool,
    rsi_entry_ok: bool,
    rsi_exit_ok: bool,
    htf_text: str,
    balance: float,
    daily_pnl: float,
    pending_ticket: str,
    position_state: str,
) -> str:
    pending = pending_ticket or "none"
    return (
        f"[STATUS]\n"
        f"Pair: `{symbol}` | TF: `{timeframe}` | Signal: `{signal}`\n"
        f"Live / Signal price: `{live_price:.4f}` / `{signal_price:.4f}`\n"
        f"15m RSI: `{entry_rsi_15m:.2f}` | HTF ok: `{htf_ok}`\n"
        f"Gates: EMA up=`{ema_cross_up}` EMA down=`{ema_cross_down}` RSI entry=`{rsi_entry_ok}` RSI exit=`{rsi_exit_ok}`\n"
        f"HTF: `{htf_text}`\n"
        f"Balance: `{balance:.4f}` | Daily PnL: `{daily_pnl:.4f}`\n"
        f"Pending ticket: `{pending}` | Position: `{position_state}`"
    )


def format_no_trade_message(
    symbol: str,
    timeframe: str,
    signal: str,
    htf_ok: bool,
    live_price: float,
    signal_price: float,
    ema9: float,
    ema21: float,
    entry_rsi_15m: float,
    ema_cross_up: bool,
    ema_cross_down: bool,
    rsi_entry_ok: bool,
    rsi_exit_ok: bool,
    htf_text: str,
    balance: float,
) -> str:
    return (
        f"[NO TRADE]\n"
        f"Pair: `{symbol}` | TF: `{timeframe}` | Signal: `{signal}`\n"
        f"Live / Signal price: `{live_price:.4f}` / `{signal_price:.4f}`\n"
        f"EMA9 / EMA21: `{ema9:.4f}` / `{ema21:.4f}`\n"
        f"15m RSI: `{entry_rsi_15m:.2f}` | HTF ok: `{htf_ok}`\n"
        f"Gates: EMA up=`{ema_cross_up}` EMA down=`{ema_cross_down}` RSI entry=`{rsi_entry_ok}` RSI exit=`{rsi_exit_ok}`\n"
        f"HTF: `{htf_text}`\n"
        f"Balance: `{balance:.4f}`"
    )
