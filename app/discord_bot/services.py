from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..binance.command_queue import CommandRecord, append_command, new_command_id, now_iso
from ..binance.config import Config as BinanceConfig
from ..binance.outlook import default_outlook_report_path, generate_outlook_report, write_outlook_report
from ..binance.state import load_state
from ..binance.tickets import list_tickets
from ..selection.main import main as selection_main


@dataclass(slots=True)
class QueuedCommandResult:
    command_id: str
    command_text: str
    actor_label: str
    source: str


class BinanceDiscordService:
    def __init__(self, config: BinanceConfig | None = None) -> None:
        self.config = config or BinanceConfig()
        self.config.validate()

    def help_text(self) -> str:
        commands = [
            "`/status` runtime snapshot from local bot state",
            "`/outlook [symbol]` generate an explainable market outlook",
            "`/scan [venue] [top]` run the existing market scanner and show the chosen market",
            "`/readonly` show the latest saved live-readonly report, if any",
            "`/approve <ticket-or-symbol>` queue a manual approval command",
            "`/deny <ticket-or-symbol>` queue a manual deny command",
            "`/confirm_sell <asset>` queue `confirm sell <asset>` into the existing command queue",
        ]
        return "Discord bot commands:\n" + "\n".join(f"- {item}" for item in commands)

    def status_text(self) -> str:
        state = load_state(self.config.state_path)
        tickets = list_tickets(self.config.tickets_path)
        pending = [row for row in tickets if (row.get("status") or "").strip().lower() == "pending"]
        last_ticket = tickets[-1] if tickets else None
        position = "flat"
        if state.position is not None:
            position = (
                f"long qty={state.position.qty:.6f} entry={state.position.entry_price:.4f} "
                f"stop={state.position.stop_loss:.4f} tp={state.position.take_profit:.4f}"
            )
        last_ticket_text = "none"
        if last_ticket is not None:
            last_ticket_text = (
                f"{last_ticket.get('action','?')}:{last_ticket.get('ticket_id','?')}:{last_ticket.get('status','?')}"
            )
        lines = [
            "Binance bot status",
            f"- mode={self.config.bot_mode} execution={self.config.execution_mode} approval={self.config.approval_mode}",
            f"- symbol={self.config.symbol} timeframe={self.config.timeframe}",
            f"- position={position}",
            f"- realized_pnl_today={state.realized_pnl_today:.4f} trade_count={state.daily_trade_count}",
            f"- pending_ticket={state.pending_ticket_id or 'none'} queue_path={self.config.command_queue_path}",
            f"- pending_tickets_total={len(pending)} last_ticket={last_ticket_text}",
            f"- readonly_report={self.config.readonly_report_path}",
            f"- webhook={'enabled' if self.config.discord_webhook_url else 'disabled'}",
        ]
        return "\n".join(lines)

    def generate_outlook_text(self, symbol: str | None = None) -> str:
        report = generate_outlook_report(self.config, symbol=symbol or None)
        output_path = default_outlook_report_path(report.symbol)
        text_path, json_path = write_outlook_report(report, output_path)
        return report.to_text() + f"\n\nSaved: {text_path}\nJSON: {json_path}"

    def latest_readonly_text(self) -> str:
        report_path = self.config.readonly_report_path
        if not report_path.exists():
            return (
                f"No readonly report found at `{report_path}`. "
                "Run the Binance bot in BOT_MODE=live_readonly first if you want a fresh snapshot."
            )
        text = report_path.read_text(encoding="utf-8").strip()
        return text or f"Readonly report exists but is empty: `{report_path}`"

    def scan_text(self, *, venue: str = "binance", top: int = 5) -> str:
        output_path = f"data/market/{venue}_candidates.csv"
        exit_code = selection_main(["--venue", venue, "--top", str(top), "--output", output_path])
        if exit_code != 0:
            raise RuntimeError(f"selection scan failed for venue={venue} exit_code={exit_code}")
        report_txt = Path(output_path.replace(".csv", "_report.txt"))
        if report_txt.exists():
            return report_txt.read_text(encoding="utf-8").strip()
        return f"Scan completed for venue={venue}. CSV: `{output_path}`"

    def queue_command(self, *, command_text: str, actor_id: str = "", actor_label: str = "", source: str = "discord-bot") -> QueuedCommandResult:
        record = CommandRecord(
            command_id=new_command_id(),
            created_at=now_iso(),
            actor_id=actor_id.strip(),
            actor_label=actor_label.strip(),
            source=source.strip() or "discord-bot",
            command_text=command_text.strip(),
        )
        append_command(self.config.command_queue_path, record)
        return QueuedCommandResult(
            command_id=record.command_id,
            command_text=record.command_text,
            actor_label=record.actor_label or record.actor_id or "unknown",
            source=record.source,
        )
