from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_event(level: str, message: str) -> None:
    print(f"[{now_utc()}] [{level}] {message}", flush=True)


def fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"
