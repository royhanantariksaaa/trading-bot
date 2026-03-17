from __future__ import annotations

import argparse

from .config import Config
from .state import clear_pending_ticket, load_state, save_state
from .tickets import VALID_TICKET_STATUSES, append_decision_log, update_ticket_status


def main() -> None:
    parser = argparse.ArgumentParser(description="Update manual ticket lifecycle status.")
    parser.add_argument("--ticket", required=True, help="Ticket ID to update")
    parser.add_argument("--status", required=True, choices=sorted(VALID_TICKET_STATUSES), help="New ticket status")
    parser.add_argument("--note", default="", help="Optional note")
    args = parser.parse_args()

    config = Config()
    tickets_path = config.tickets_path
    decision_log_path = config.decision_log_path
    state_path = config.state_path

    updated = update_ticket_status(tickets_path, args.ticket, args.status)
    if not updated:
        raise SystemExit(f"Ticket not found: {args.ticket}")

    state = load_state(state_path)
    if state.pending_ticket_id == args.ticket and args.status in {"approved", "denied", "expired", "skipped", "executed", "closed"}:
        clear_pending_ticket(state)
        save_state(state_path, state)

    append_decision_log(decision_log_path, args.ticket, args.status, note=args.note or "ticket status updated")
    print(f"Updated ticket {args.ticket} -> {args.status}")


if __name__ == "__main__":
    main()
