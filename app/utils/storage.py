from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
MARKET_DATA_DIR = DATA_DIR / "market"
LOG_DATA_DIR = DATA_DIR / "logs"
BACKTEST_DATA_DIR = DATA_DIR / "backtests"
STATE_DATA_DIR = DATA_DIR / "state"


def resolve_project_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def resolve_env_path(env_name: str, default_path: str | Path) -> Path:
    raw_value = os.getenv(env_name)
    return resolve_project_path(raw_value if raw_value else default_path)


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def ensure_runtime_directories() -> None:
    for directory in (MARKET_DATA_DIR, LOG_DATA_DIR, BACKTEST_DATA_DIR, STATE_DATA_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def market_data_path(filename: str) -> Path:
    return ensure_parent(MARKET_DATA_DIR / filename)


def binance_state_path() -> Path:
    return ensure_parent(resolve_env_path("BINANCE_STATE_PATH", STATE_DATA_DIR / "runtime_state.json"))


def binance_trades_path() -> Path:
    return ensure_parent(resolve_env_path("BINANCE_TRADES_PATH", LOG_DATA_DIR / "trades.csv"))


def binance_tickets_path() -> Path:
    return ensure_parent(resolve_env_path("BINANCE_TICKETS_PATH", LOG_DATA_DIR / "manual_tickets.csv"))


def binance_decision_log_path() -> Path:
    return ensure_parent(resolve_env_path("BINANCE_DECISION_LOG_PATH", LOG_DATA_DIR / "decision_log.csv"))


def binance_execution_log_path() -> Path:
    return ensure_parent(resolve_env_path("BINANCE_EXECUTION_LOG_PATH", LOG_DATA_DIR / "live_execution_log.csv"))


def binance_backtest_output_path() -> Path:
    return ensure_parent(resolve_env_path("BINANCE_BACKTEST_OUTPUT_PATH", BACKTEST_DATA_DIR / "backtest_trades.csv"))


def polymarket_state_path() -> Path:
    return ensure_parent(resolve_env_path("PM_STATE_PATH", STATE_DATA_DIR / "polymarket_state.json"))


def polymarket_log_path() -> Path:
    return ensure_parent(resolve_env_path("PM_LOG_PATH", LOG_DATA_DIR / "polymarket_runs.csv"))
