from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..common.env import env_bool
from ..selection.profiles import PROFILE_NAMES, StrategyProfileSelection
from ..selection.runtime import RotationController, default_selection_csv_path
from ..utils.storage import (
    binance_backtest_output_path,
    binance_decision_log_path,
    binance_execution_log_path,
    binance_readonly_report_json_path,
    binance_readonly_report_path,
    binance_state_path,
    binance_tickets_path,
    binance_trades_path,
    market_data_path,
    resolve_project_path,
)


@dataclass
class Config:
    api_key: str = os.getenv("BINANCE_API_KEY", "")
    api_secret: str = os.getenv("BINANCE_SECRET", "")
    bot_mode: str = os.getenv("BOT_MODE", "paper").lower()
    symbol: str = os.getenv("SYMBOL", "ETH/USDT")
    timeframe: str = os.getenv("TIMEFRAME", "15m")
    starting_balance: float = float(os.getenv("STARTING_BALANCE", "100"))
    risk_per_trade: float = float(os.getenv("RISK_PER_TRADE", "0.01"))
    stop_loss_pct: float = float(os.getenv("STOP_LOSS_PCT", "0.02"))
    take_profit_pct: float = float(os.getenv("TAKE_PROFIT_PCT", "0.03"))
    cooldown_candles: int = int(os.getenv("COOLDOWN_CANDLES", "2"))
    kill_switch: bool = env_bool(os.getenv("KILL_SWITCH"), False)
    poll_seconds: int = int(os.getenv("POLL_SECONDS", "30"))
    enable_live_trading: bool = env_bool(os.getenv("ENABLE_LIVE_TRADING"), False)
    discord_webhook_url: str = os.getenv("DISCORD_WEBHOOK_URL", "")
    status_every_loops: int = int(os.getenv("STATUS_EVERY_LOOPS", "10"))
    use_rsi_filter: bool = env_bool(os.getenv("USE_RSI_FILTER"), False)
    ema_fast_period: int = int(os.getenv("EMA_FAST_PERIOD", "9"))
    ema_slow_period: int = int(os.getenv("EMA_SLOW_PERIOD", "21"))
    rsi_buy_min: float = float(os.getenv("RSI_BUY_MIN", "55"))
    rsi_sell_max: float = float(os.getenv("RSI_SELL_MAX", "45"))
    rsi_period: int = int(os.getenv("RSI_PERIOD", "14"))
    signal_on_closed_candle: bool = env_bool(os.getenv("SIGNAL_ON_CLOSED_CANDLE"), True)
    approval_mode: str = os.getenv("APPROVAL_MODE", "discord").lower()
    execution_mode: str = os.getenv("EXECUTION_MODE", "manual").lower()
    max_trade_usd: float = float(os.getenv("MAX_TRADE_USD", "5"))
    max_daily_loss_usd: float = float(os.getenv("MAX_DAILY_LOSS_USD", "1"))
    max_trades_per_day: int = int(os.getenv("MAX_TRADES_PER_DAY", "3"))
    use_htf_filter: bool = env_bool(os.getenv("USE_HTF_FILTER"), False)
    htf_1_timeframe: str = os.getenv("HTF_1_TIMEFRAME", "4h")
    htf_1_rsi_min: float = float(os.getenv("HTF_1_RSI_MIN", "50"))
    htf_1_rsi_period: int = int(os.getenv("HTF_1_RSI_PERIOD", "14"))
    htf_2_enabled: bool = env_bool(os.getenv("HTF_2_ENABLED"), False)
    htf_2_timeframe: str = os.getenv("HTF_2_TIMEFRAME", "1d")
    htf_2_rsi_min: float = float(os.getenv("HTF_2_RSI_MIN", "50"))
    htf_2_rsi_period: int = int(os.getenv("HTF_2_RSI_PERIOD", "14"))
    reconcile_on_start: bool = env_bool(os.getenv("RECONCILE_ON_START"), True)
    use_testnet: bool = env_bool(os.getenv("USE_TESTNET"), True)
    order_test_before_submit: bool = env_bool(os.getenv("ORDER_TEST_BEFORE_SUBMIT"), False)
    entry_size_mode: str = os.getenv("ENTRY_SIZE_MODE", "quote_budget").lower()
    recv_window_ms: int = int(os.getenv("RECV_WINDOW_MS", "5000"))
    binance_api_base_url: str = os.getenv("BINANCE_API_BASE_URL", "").strip()
    fee_rate: float = float(os.getenv("FEE_RATE", "0.001"))
    slippage_buffer_pct: float = float(os.getenv("SLIPPAGE_BUFFER_PCT", "0.001"))
    selection_mode: str = os.getenv("BINANCE_SELECTION_MODE", "manual").strip().lower()
    strategy_profile: str = os.getenv("BINANCE_STRATEGY_PROFILE", "").strip().lower()
    adaptive_mode: str = os.getenv("BINANCE_ADAPTIVE_MODE", "off").strip().lower()
    selection_csv_path: Path = field(
        default_factory=lambda: resolve_project_path(os.getenv("BINANCE_SELECTION_CSV", str(default_selection_csv_path("binance"))))
    )
    adaptive_report_path: Path = field(
        default_factory=lambda: resolve_project_path(
            os.getenv("BINANCE_ADAPTIVE_REPORT_PATH", str(market_data_path("binance_adaptive_report.txt")))
        )
    )
    readonly_report_path: Path = field(default_factory=binance_readonly_report_path)
    readonly_report_json_path: Path = field(default_factory=binance_readonly_report_json_path)
    readonly_compact_interval_seconds: int = int(os.getenv("BINANCE_READONLY_COMPACT_INTERVAL_SECONDS", "120"))
    readonly_heartbeat_interval_seconds: int = int(os.getenv("BINANCE_READONLY_HEARTBEAT_INTERVAL_SECONDS", "1800"))
    selection_rotation_loops: int = int(os.getenv("BINANCE_SELECTION_ROTATE_EVERY_LOOPS", "0"))
    selection_rotation_only_when_flat: bool = env_bool(os.getenv("BINANCE_SELECTION_ROTATE_ONLY_WHEN_FLAT"), True)
    active_strategy_profile: str = field(default="", init=False, repr=False)
    active_strategy_profile_reason: str = field(default="", init=False, repr=False)
    active_selection_profile: str = field(default="", init=False, repr=False)
    active_selection_profile_reason: str = field(default="", init=False, repr=False)
    state_path: Path = field(default_factory=binance_state_path)
    trades_path: Path = field(default_factory=binance_trades_path)
    tickets_path: Path = field(default_factory=binance_tickets_path)
    decision_log_path: Path = field(default_factory=binance_decision_log_path)
    execution_log_path: Path = field(default_factory=binance_execution_log_path)
    backtest_output_path: Path = field(default_factory=binance_backtest_output_path)

    def validate(self) -> None:
        if self.bot_mode not in {"paper", "live", "live_readonly"}:
            raise ValueError("BOT_MODE must be 'paper', 'live', or 'live_readonly'")
        if self.execution_mode not in {"manual", "auto"}:
            raise ValueError("EXECUTION_MODE must be 'manual' or 'auto'")
        if self.approval_mode not in {"none", "discord", "terminal"}:
            raise ValueError("APPROVAL_MODE must be 'none', 'discord', or 'terminal'")
        if self.entry_size_mode not in {"quote_budget", "quantity"}:
            raise ValueError("ENTRY_SIZE_MODE must be 'quote_budget' or 'quantity'")
        if self.selection_mode not in {"manual", "csv", "scan"}:
            raise ValueError("BINANCE_SELECTION_MODE must be 'manual', 'csv', or 'scan'")
        allowed_profiles = {"", "auto", "manual", *PROFILE_NAMES}
        if self.strategy_profile not in allowed_profiles:
            raise ValueError(
                "BINANCE_STRATEGY_PROFILE must be one of 'auto', 'manual', 'trend', 'range', 'volatile', 'slow_liquid'"
            )
        if self.adaptive_mode not in {"off", "paper", "on"}:
            raise ValueError("BINANCE_ADAPTIVE_MODE must be 'off', 'paper', or 'on'")
        if self.strategy_profile == "auto" and self.selection_mode == "manual":
            raise ValueError("BINANCE_STRATEGY_PROFILE=auto requires BINANCE_SELECTION_MODE=csv or scan")
        if self.readonly_compact_interval_seconds <= 0:
            raise ValueError("BINANCE_READONLY_COMPACT_INTERVAL_SECONDS must be > 0")
        if self.readonly_heartbeat_interval_seconds <= 0:
            raise ValueError("BINANCE_READONLY_HEARTBEAT_INTERVAL_SECONDS must be > 0")
        if self.selection_rotation_loops < 0:
            raise ValueError("BINANCE_SELECTION_ROTATE_EVERY_LOOPS must be >= 0")
        if self.bot_mode == "live" and not self.enable_live_trading:
            raise ValueError("Live mode requires ENABLE_LIVE_TRADING=true")
        if self.bot_mode in {"live", "live_readonly"} and (not self.api_key or not self.api_secret):
            raise ValueError("Live modes require BINANCE_API_KEY and BINANCE_SECRET")
        if self.bot_mode == "live_readonly" and self.use_testnet:
            raise ValueError("Live read-only mode requires USE_TESTNET=false")
        if self.bot_mode == "live_readonly" and self.execution_mode not in {"manual", "auto"}:
            raise ValueError("Live read-only mode requires EXECUTION_MODE to be 'manual' or 'auto'")
        if self.risk_per_trade <= 0 or self.risk_per_trade > 0.05:
            raise ValueError("RISK_PER_TRADE must be between 0 and 0.05")
        if self.stop_loss_pct <= 0:
            raise ValueError("STOP_LOSS_PCT must be > 0")
        if self.take_profit_pct <= 0:
            raise ValueError("TAKE_PROFIT_PCT must be > 0")
        if self.status_every_loops < 0:
            raise ValueError("STATUS_EVERY_LOOPS must be >= 0")
        if not (0 <= self.rsi_buy_min <= 100 and 0 <= self.rsi_sell_max <= 100):
            raise ValueError("RSI thresholds must be between 0 and 100")
        if self.rsi_period <= 1:
            raise ValueError("RSI_PERIOD must be > 1")
        if self.max_trade_usd <= 0:
            raise ValueError("MAX_TRADE_USD must be > 0")
        if self.max_daily_loss_usd <= 0:
            raise ValueError("MAX_DAILY_LOSS_USD must be > 0")
        if self.max_trades_per_day <= 0:
            raise ValueError("MAX_TRADES_PER_DAY must be > 0")
        if self.recv_window_ms <= 0:
            raise ValueError("RECV_WINDOW_MS must be > 0")
        if self.fee_rate < 0:
            raise ValueError("FEE_RATE must be >= 0")
        if self.slippage_buffer_pct < 0:
            raise ValueError("SLIPPAGE_BUFFER_PCT must be >= 0")
        if self.ema_fast_period <= 0 or self.ema_slow_period <= 0:
            raise ValueError("EMA_FAST_PERIOD and EMA_SLOW_PERIOD must be > 0")
        if self.ema_fast_period >= self.ema_slow_period:
            raise ValueError("EMA_FAST_PERIOD must be smaller than EMA_SLOW_PERIOD")
        if self.use_htf_filter:
            if self.htf_1_rsi_period <= 1 or self.htf_2_rsi_period <= 1:
                raise ValueError("HTF RSI periods must be > 1")
            if not (0 <= self.htf_1_rsi_min <= 100 and 0 <= self.htf_2_rsi_min <= 100):
                raise ValueError("HTF RSI thresholds must be between 0 and 100")

    @property
    def live_api_url(self) -> str | None:
        if self.binance_api_base_url:
            return self.binance_api_base_url
        return None

    @property
    def live_readonly_mode(self) -> bool:
        return self.bot_mode == "live_readonly"

    @property
    def live_data_mode(self) -> bool:
        return self.bot_mode in {"live", "live_readonly"}

    @property
    def resolved_strategy_profile_mode(self) -> str:
        if self.strategy_profile:
            return self.strategy_profile
        return "auto" if self.selection_mode in {"csv", "scan"} else "manual"

    def apply_strategy_profile(self, profile: StrategyProfileSelection | None) -> None:
        if profile is None:
            self.active_strategy_profile = ""
            self.active_strategy_profile_reason = ""
            self.active_selection_profile = ""
            self.active_selection_profile_reason = ""
            return
        self.active_strategy_profile = profile.name
        self.active_strategy_profile_reason = profile.reason
        for field_name in (
            "risk_per_trade",
            "stop_loss_pct",
            "take_profit_pct",
            "cooldown_candles",
            "timeframe",
            "ema_fast_period",
            "ema_slow_period",
            "rsi_period",
            "use_rsi_filter",
            "rsi_buy_min",
            "rsi_sell_max",
            "use_htf_filter",
            "htf_1_timeframe",
            "htf_1_rsi_min",
            "htf_2_enabled",
            "htf_2_timeframe",
            "htf_2_rsi_min",
            "signal_on_closed_candle",
        ):
            value = getattr(profile, field_name)
            if value is not None:
                setattr(self, field_name, value)

    @property
    def rotation_controller(self) -> RotationController:
        enabled = self.selection_mode in {"csv", "scan"} and self.selection_rotation_loops > 0
        return RotationController(
            enabled=enabled,
            every_loops=self.selection_rotation_loops,
            only_when_flat=self.selection_rotation_only_when_flat,
            next_due_loop=self.selection_rotation_loops if enabled else 0,
        )
