from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import csv
import uuid

VALID_TICKET_STATUSES = {"pending", "approved", "denied", "expired", "executed", "closed", "skipped"}


@dataclass
class ManualTicket:
    ticket_id: str
    created_at: str
    action: str
    symbol: str
    timeframe: str
    price: float
    qty: float
    notional_usd: float
    stop_loss: float
    take_profit: float
    reason: str
    rsi: float
    status: str = "pending"


@dataclass
class ExecutionRecord:
    timestamp: str
    ticket_id: str
    action: str
    symbol: str
    execution_type: str
    price: float
    qty: float
    notional_usd: float
    fee_usd: float
    notes: str = ""


def new_ticket_id() -> str:
    return uuid.uuid4().hex[:8]


def append_ticket(path: Path, ticket: ManualTicket) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow([
                "ticket_id", "created_at", "action", "symbol", "timeframe", "price", "qty", "notional_usd",
                "stop_loss", "take_profit", "reason", "rsi", "status"
            ])
        writer.writerow([
            ticket.ticket_id,
            ticket.created_at,
            ticket.action,
            ticket.symbol,
            ticket.timeframe,
            round(ticket.price, 6),
            round(ticket.qty, 8),
            round(ticket.notional_usd, 6),
            round(ticket.stop_loss, 6),
            round(ticket.take_profit, 6),
            ticket.reason,
            round(ticket.rsi, 4),
            ticket.status,
        ])


def update_ticket_status(path: Path, ticket_id: str, new_status: str) -> bool:
    if new_status not in VALID_TICKET_STATUSES:
        raise ValueError(f"Invalid ticket status: {new_status}")
    if not path.exists():
        return False

    rows = []
    updated = False
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            if row.get("ticket_id") == ticket_id:
                row["status"] = new_status
                updated = True
            rows.append(row)

    if not updated:
        return False

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return True


def append_decision_log(path: Path, ticket_id: str, decision: str, note: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["timestamp", "ticket_id", "decision", "note"])
        writer.writerow([now_iso(), ticket_id, decision.lower(), note])


def append_execution_log(path: Path, record: ExecutionRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["timestamp", "ticket_id", "action", "symbol", "execution_type", "price", "qty", "notional_usd", "fee_usd", "notes"])
        writer.writerow([
            record.timestamp,
            record.ticket_id,
            record.action,
            record.symbol,
            record.execution_type,
            round(record.price, 6),
            round(record.qty, 8),
            round(record.notional_usd, 6),
            round(record.fee_usd, 6),
            record.notes,
        ])


def _remaining_loss_buffer(daily_loss_limit: float, realized_pnl_today: float) -> float:
    return daily_loss_limit + realized_pnl_today if realized_pnl_today < 0 else daily_loss_limit


def build_ticket_message(ticket: ManualTicket, daily_loss_limit: float, realized_pnl_today: float, market_warning: str = "") -> str:
    remaining = _remaining_loss_buffer(daily_loss_limit, realized_pnl_today)
    warning_line = f"Market warning: `{market_warning}`\n" if market_warning else ""
    if ticket.action.upper() == "SELL":
        return (
            f"[SELL TICKET] `{ticket.ticket_id}`\n"
            f"Pair: `{ticket.symbol}` | TF: `{ticket.timeframe}`\n"
            f"Signal price: `{ticket.price:.4f}` | Qty: `{ticket.qty:.6f}` | Notional: `${ticket.notional_usd:.2f}`\n"
            f"Reason: `{ticket.reason}`\n"
            f"RSI(closed): `{ticket.rsi:.2f}`\n"
            f"Reference stop/tp: `{ticket.stop_loss:.4f}` / `{ticket.take_profit:.4f}`\n"
            f"Status: `{ticket.status}`\n"
            f"{warning_line}"
            f"Daily PnL: `{realized_pnl_today:.4f}` | Max daily loss: `{daily_loss_limit:.4f}` | Buffer: `{remaining:.4f}`\n"
            f"Reply convention: `approve {ticket.ticket_id}` or `deny {ticket.ticket_id}`\n"
            f"Manual execution only. Bot does not place the sell for you."
        )
    return (
        f"[BUY TICKET] `{ticket.ticket_id}`\n"
        f"Pair: `{ticket.symbol}` | TF: `{ticket.timeframe}`\n"
        f"Signal price: `{ticket.price:.4f}` | Qty: `{ticket.qty:.6f}` | Notional: `${ticket.notional_usd:.2f}`\n"
        f"Stop / TP: `{ticket.stop_loss:.4f}` / `{ticket.take_profit:.4f}`\n"
        f"Reason: `{ticket.reason}`\n"
        f"RSI(closed): `{ticket.rsi:.2f}`\n"
        f"Status: `{ticket.status}`\n"
        f"{warning_line}"
        f"Daily PnL: `{realized_pnl_today:.4f}` | Max daily loss: `{daily_loss_limit:.4f}` | Buffer: `{remaining:.4f}`\n"
        f"Reply convention: `approve {ticket.ticket_id}` or `deny {ticket.ticket_id}`\n"
        f"Manual execution only. Bot does not place the buy for you."
    )


def build_decision_message(ticket_id: str, decision: str) -> str:
    label = "APPROVED" if decision.lower() == "approve" else "DENIED"
    return f"[DECISION LOG] ticket=`{ticket_id}` decision=`{label}` | execution remains manual outside the bot."


def build_daily_summary(
    symbol: str,
    timeframe: str,
    realized_pnl_today: float,
    max_daily_loss: float,
    pending_ticket_id: str,
    ticket_count_today: int,
    trade_count_today: int,
    last_ticket_info: str,
) -> str:
    pending = pending_ticket_id or "none"
    remaining = _remaining_loss_buffer(max_daily_loss, realized_pnl_today)
    last_ticket = last_ticket_info or "none"
    return (
        f"[DAILY SUMMARY]\n"
        f"Pair: `{symbol}` | TF: `{timeframe}`\n"
        f"Realized PnL today: `{realized_pnl_today:.4f}`\n"
        f"Max daily loss: `{max_daily_loss:.4f}` | Buffer: `{remaining:.4f}`\n"
        f"Tickets today: `{ticket_count_today}` | Trades logged today: `{trade_count_today}`\n"
        f"Pending ticket: `{pending}`\n"
        f"Last ticket: `{last_ticket}`"
    )


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
