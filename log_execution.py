from __future__ import annotations

import argparse
from pathlib import Path

from tickets import ExecutionRecord, append_execution_log, now_iso, update_ticket_status


def main() -> None:
    parser = argparse.ArgumentParser(description="Log a manual live execution record.")
    parser.add_argument("--ticket", required=True, help="Related ticket ID")
    parser.add_argument("--action", required=True, choices=["BUY", "SELL"], help="Execution side")
    parser.add_argument("--symbol", required=True, help="Trading pair like SOL/USDT")
    parser.add_argument("--type", required=True, choices=["entry", "exit"], help="Execution type")
    parser.add_argument("--price", required=True, type=float, help="Manual fill price")
    parser.add_argument("--qty", required=True, type=float, help="Manual fill quantity")
    parser.add_argument("--fee", default=0.0, type=float, help="Fee in USD")
    parser.add_argument("--note", default="", help="Optional note")
    args = parser.parse_args()

    notional = args.price * args.qty
    record = ExecutionRecord(
        timestamp=now_iso(),
        ticket_id=args.ticket,
        action=args.action,
        symbol=args.symbol,
        execution_type=args.type,
        price=args.price,
        qty=args.qty,
        notional_usd=notional,
        fee_usd=args.fee,
        notes=args.note,
    )

    append_execution_log(Path("live_execution_log.csv"), record)
    target_status = "executed" if args.type == "entry" else "closed"
    update_ticket_status(Path("manual_tickets.csv"), args.ticket, target_status)
    print(f"Logged {args.type} execution for ticket {args.ticket} -> status {target_status}")


if __name__ == "__main__":
    main()
