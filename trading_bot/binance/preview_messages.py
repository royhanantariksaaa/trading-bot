from __future__ import annotations

import argparse
from pathlib import Path

from .config import Config
from .formatters import format_no_trade_message, format_startup_message, format_status_message
from .notifier import DiscordNotifier
from .tickets import ManualTicket, append_ticket, build_daily_summary, build_ticket_message, now_iso


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview formatted bot messages.")
    parser.add_argument("--persist-tickets", action="store_true", help="Also write preview tickets into manual_tickets.csv")
    args = parser.parse_args()

    config = Config()
    notifier = DiscordNotifier(config.discord_webhook_url)

    startup = format_startup_message(
        config.symbol,
        config.timeframe,
        config.starting_balance,
        f"{config.risk_per_trade * 100:.2f}%",
        f"{config.stop_loss_pct * 100:.2f}%",
        f"{config.take_profit_pct * 100:.2f}%",
        "EMA 9/21 + RSI preview",
        config.execution_mode,
        config.approval_mode,
        config.signal_on_closed_candle,
    )

    buy_ticket = ManualTicket(
        ticket_id="preview01",
        created_at=now_iso(),
        action="BUY",
        symbol=config.symbol,
        timeframe=config.timeframe,
        price=94.3000,
        qty=0.0530,
        notional_usd=5.0,
        stop_loss=92.4140,
        take_profit=97.1290,
        reason="preview buy ticket | ema9 > ema21 | htf pass",
        rsi=53.20,
    )

    sell_ticket = ManualTicket(
        ticket_id="preview02",
        created_at=now_iso(),
        action="SELL",
        symbol=config.symbol,
        timeframe=config.timeframe,
        price=96.1200,
        qty=0.0530,
        notional_usd=5.0944,
        stop_loss=92.4140,
        take_profit=97.1290,
        reason="preview sell ticket | take profit zone",
        rsi=47.10,
    )

    no_trade = format_no_trade_message(
        config.symbol,
        config.timeframe,
        "hold",
        True,
        94.50,
        94.44,
        94.2591,
        94.3522,
        49.94,
        False,
        False,
        False,
        False,
        "4h_rsi=65.31",
        100.0,
    )

    status = format_status_message(
        config.symbol,
        config.timeframe,
        "hold",
        True,
        94.44,
        94.50,
        49.94,
        False,
        False,
        False,
        False,
        "4h_rsi=65.31",
        100.0,
        0.0,
        "none",
        "flat",
    )

    summary = build_daily_summary(
        config.symbol,
        config.timeframe,
        0.0,
        config.max_daily_loss_usd,
        "none",
        2,
        0,
        "BUY:preview01:pending",
    )

    print("Sending preview messages...", flush=True)
    print(startup, flush=True)
    print(build_ticket_message(buy_ticket, config.max_daily_loss_usd, 0.0), flush=True)
    print(build_ticket_message(sell_ticket, config.max_daily_loss_usd, 0.0), flush=True)
    print(no_trade, flush=True)
    print(status, flush=True)
    print(summary, flush=True)

    if args.persist_tickets:
        append_ticket(Path("manual_tickets.csv"), buy_ticket)
        append_ticket(Path("manual_tickets.csv"), sell_ticket)
        print("Preview tickets persisted to manual_tickets.csv", flush=True)

    if notifier.enabled:
        notifier.send(startup)
        notifier.send(build_ticket_message(buy_ticket, config.max_daily_loss_usd, 0.0))
        notifier.send(build_ticket_message(sell_ticket, config.max_daily_loss_usd, 0.0))
        notifier.send(no_trade)
        notifier.send(status)
        notifier.send(summary)
        print("Preview messages sent to Discord.", flush=True)
    else:
        print("No DISCORD_WEBHOOK_URL configured; printed previews locally only.", flush=True)


if __name__ == "__main__":
    main()
