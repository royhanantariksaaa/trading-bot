from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from datetime import datetime


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def count_csv_rows_today(path: Path, timestamp_field: str) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get(timestamp_field, "").startswith(today_str()):
                rows.append(row)
    return rows


def main() -> None:
    tickets = count_csv_rows_today(Path("manual_tickets.csv"), "created_at")
    decisions = count_csv_rows_today(Path("decision_log.csv"), "timestamp")
    executions = count_csv_rows_today(Path("live_execution_log.csv"), "timestamp")

    ticket_status_counts = Counter(row.get("status", "unknown") for row in tickets)
    decision_counts = Counter(row.get("decision", "unknown") for row in decisions)
    execution_counts = Counter(row.get("execution_type", "unknown") for row in executions)

    print("=== DAY REVIEW ===")
    print(f"Date: {today_str()}")
    print(f"Tickets today: {len(tickets)}")
    print(f"Decisions today: {len(decisions)}")
    print(f"Execution logs today: {len(executions)}")
    print(f"Ticket statuses: {dict(ticket_status_counts)}")
    print(f"Decision counts: {dict(decision_counts)}")
    print(f"Execution counts: {dict(execution_counts)}")

    if tickets:
        last_ticket = tickets[-1]
        print(f"Last ticket: {last_ticket.get('action')} {last_ticket.get('ticket_id')} status={last_ticket.get('status')}")
    else:
        print("Last ticket: none")

    if executions:
        gross = 0.0
        fees = 0.0
        for row in executions:
            gross += float(row.get("notional_usd", 0) or 0)
            fees += float(row.get("fee_usd", 0) or 0)
        print(f"Gross notional logged: {gross:.4f}")
        print(f"Fees logged: {fees:.4f}")


if __name__ == "__main__":
    main()
