from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    kill_switch: bool = _as_bool(os.getenv("KILL_SWITCH"), False)
    poll_seconds: int = int(os.getenv("POLL_SECONDS", "30"))
    enable_live_trading: bool = _as_bool(os.getenv("ENABLE_LIVE_TRADING"), False)
    discord_webhook_url: str = os.getenv("DISCORD_WEBHOOK_URL", "")
    status_every_loops: int = int(os.getenv("STATUS_EVERY_LOOPS", "10"))
    use_rsi_filter: bool = _as_bool(os.getenv("USE_RSI_FILTER"), False)
    rsi_buy_min: float = float(os.getenv("RSI_BUY_MIN", "55"))
    rsi_sell_max: float = float(os.getenv("RSI_SELL_MAX", "45"))
    rsi_period: int = int(os.getenv("RSI_PERIOD", "14"))
    signal_on_closed_candle: bool = _as_bool(os.getenv("SIGNAL_ON_CLOSED_CANDLE"), True)
    approval_mode: str = os.getenv("APPROVAL_MODE", "discord").lower()
    execution_mode: str = os.getenv("EXECUTION_MODE", "manual").lower()
    max_trade_usd: float = float(os.getenv("MAX_TRADE_USD", "5"))
    max_daily_loss_usd: float = float(os.getenv("MAX_DAILY_LOSS_USD", "1"))
    use_htf_filter: bool = _as_bool(os.getenv("USE_HTF_FILTER"), False)
    htf_1_timeframe: str = os.getenv("HTF_1_TIMEFRAME", "4h")
    htf_1_rsi_min: float = float(os.getenv("HTF_1_RSI_MIN", "50"))
    htf_1_rsi_period: int = int(os.getenv("HTF_1_RSI_PERIOD", "14"))
    htf_2_enabled: bool = _as_bool(os.getenv("HTF_2_ENABLED"), False)
    htf_2_timeframe: str = os.getenv("HTF_2_TIMEFRAME", "1d")
    htf_2_rsi_min: float = float(os.getenv("HTF_2_RSI_MIN", "50"))
    htf_2_rsi_period: int = int(os.getenv("HTF_2_RSI_PERIOD", "14"))

    def validate(self) -> None:
        if self.bot_mode not in {"paper", "live"}:
            raise ValueError("BOT_MODE must be 'paper' or 'live'")
        if self.bot_mode == "live" and not self.enable_live_trading:
            raise ValueError(
                "Live mode is blocked. Set ENABLE_LIVE_TRADING=true only when you really mean it."
            )
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
        if self.approval_mode not in {"discord", "terminal"}:
            raise ValueError("APPROVAL_MODE must be 'discord' or 'terminal'")
        if self.execution_mode not in {"manual"}:
            raise ValueError("EXECUTION_MODE currently supports only 'manual'")
        if self.max_trade_usd <= 0:
            raise ValueError("MAX_TRADE_USD must be > 0")
        if self.max_daily_loss_usd <= 0:
            raise ValueError("MAX_DAILY_LOSS_USD must be > 0")
        if self.use_htf_filter:
            if self.htf_1_rsi_period <= 1 or self.htf_2_rsi_period <= 1:
                raise ValueError("HTF RSI periods must be > 1")
            if not (0 <= self.htf_1_rsi_min <= 100 and 0 <= self.htf_2_rsi_min <= 100):
                raise ValueError("HTF RSI thresholds must be between 0 and 100")
