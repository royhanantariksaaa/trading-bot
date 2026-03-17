from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path


@dataclass
class BotState:
    last_signal_candle_time: str = ""
    pending_ticket_id: str = ""
    pending_action: str = ""
    pending_created_at: str = ""
    realized_pnl_today: float = 0.0
    realized_pnl_date: str = ""
    last_daily_summary_date: str = ""


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_state(path: Path) -> BotState:
    if not path.exists():
        return BotState(realized_pnl_date=today_str())
    data = json.loads(path.read_text(encoding="utf-8"))
    state = BotState(**data)
    if state.realized_pnl_date != today_str():
        state.realized_pnl_today = 0.0
        state.realized_pnl_date = today_str()
        state.pending_ticket_id = ""
        state.pending_action = ""
        state.pending_created_at = ""
    return state


def save_state(path: Path, state: BotState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
