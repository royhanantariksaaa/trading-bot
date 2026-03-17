from __future__ import annotations

from datetime import datetime


def now_local() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_event(level: str, message: str) -> None:
    print(f"[{now_local()}] [{level}] {message}", flush=True)


def fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"
