from __future__ import annotations

import argparse
from pathlib import Path

from config import Config
from execution import apply_manual_execution
from state import load_state, save_state


def main() -> None:
    parser = argparse.ArgumentParser(description="Log a manual live execution record.")
    parser.add_argument("--ticket", required=True, help="Related ticket ID")
    parser.add_argument("--action", required=True, choices=["BUY", "SELL"], help="Execution side")
    parser.add_argument("--symbol", required=True, help="Trading pair like SOL/USDT")
    parser.add_argument("--type", required=True, choices=["entry", "exit"], help="Execution type")
    parser.add_argument("--price", required=True, type=float, help="Manual fill price")
    parser.add_argument("--qty", required=True, type=float, help="Manual fill quantity")
    parser.add_argument("--fee", default=0.0, type=float, help="Fee in USD")
    parser.add_argument("--order-id", default="", help="Optional exchange order id")
    parser.add_argument("--client-order-id", default="", help="Optional exchange client order id")
    parser.add_argument("--note", default="", help="Optional note")
    args = parser.parse_args()

    config = Config()
    state_path = Path("runtime_state.json")
    state = load_state(state_path)
    realized, _record = apply_manual_execution(
        state=state,
        config=config,
        ticket_id=args.ticket,
        action=args.action,
        execution_type=args.type,
        price=args.price,
        qty=args.qty,
        fee_usd=args.fee,
        note=args.note,
        order_id=args.order_id,
        client_order_id=args.client_order_id,
    )
    save_state(state_path, state)
    print(f"Logged {args.type} execution for ticket {args.ticket} | realized_pnl={realized:.4f}")


if __name__ == "__main__":
    main()
