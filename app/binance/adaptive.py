from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import math

import pandas as pd

from ..selection.profiles import StrategyProfileSelection
from .exchange import fetch_ohlcv_df


_ANALYSIS_CANDLE_LIMIT = 96
_ANALYSIS_WINDOW = 48
_SHORT_WINDOW = 12
_MIN_CLOSED_CANDLES = 30
_ALLOWED_TIMEFRAMES = {"15m", "1h"}
_ALLOWED_HTF_TIMEFRAMES = {"1h", "4h", "1d"}

_VOLATILE_SPREAD_BPS = 25.0
_VOLATILE_REALIZED_VOL_PCT = 3.25
_VOLATILE_RANGE_PCT = 18.0

_TREND_RETURN_PCT = 1.25
_TREND_STRENGTH_PCT = 0.35
_TREND_SLOPE_PCT = 0.03
_TREND_DIRECTION_CONSISTENCY = 0.58

_SLOW_REALIZED_VOL_PCT = 1.0
_SLOW_RANGE_PCT = 3.0
_SLOW_SPREAD_BPS = 18.0


_ADAPTIVE_POLICY_PRESETS: dict[str, dict[str, Any]] = {
    "trend": {
        "name": "trend_momentum",
        "description": "Directional tape with sustained drift. Keep confirmation on, use a moderate stop, and let winners run a little longer.",
        "timeframe": "15m",
        "ema_fast_period": 8,
        "ema_slow_period": 21,
        "rsi_period": 14,
        "risk_per_trade": 0.008,
        "stop_loss_pct": 0.020,
        "take_profit_pct": 0.035,
        "cooldown_candles": 2,
        "use_rsi_filter": True,
        "rsi_buy_min": 54.0,
        "rsi_sell_max": 46.0,
        "use_htf_filter": True,
        "htf_1_timeframe": "1h",
        "htf_1_rsi_min": 52.0,
        "htf_2_enabled": False,
        "signal_on_closed_candle": True,
    },
    "range": {
        "name": "range_reversion",
        "description": "Contained tape with modest swings. Stay on the 15m chart, keep risk small, and use a tighter target.",
        "timeframe": "15m",
        "ema_fast_period": 9,
        "ema_slow_period": 21,
        "rsi_period": 14,
        "risk_per_trade": 0.006,
        "stop_loss_pct": 0.012,
        "take_profit_pct": 0.018,
        "cooldown_candles": 3,
        "use_rsi_filter": True,
        "rsi_buy_min": 50.0,
        "rsi_sell_max": 50.0,
        "use_htf_filter": False,
        "htf_1_timeframe": "1h",
        "htf_1_rsi_min": 50.0,
        "htf_2_enabled": False,
        "signal_on_closed_candle": True,
    },
    "volatile": {
        "name": "volatile_defensive",
        "description": "Wide swings or spread pressure. Reduce size, keep confirmation on, and demand a wider stop/target pair.",
        "timeframe": "15m",
        "ema_fast_period": 10,
        "ema_slow_period": 26,
        "rsi_period": 14,
        "risk_per_trade": 0.005,
        "stop_loss_pct": 0.030,
        "take_profit_pct": 0.050,
        "cooldown_candles": 4,
        "use_rsi_filter": True,
        "rsi_buy_min": 58.0,
        "rsi_sell_max": 42.0,
        "use_htf_filter": True,
        "htf_1_timeframe": "1h",
        "htf_1_rsi_min": 55.0,
        "htf_2_enabled": False,
        "signal_on_closed_candle": True,
    },
    "slow_liquid": {
        "name": "slow_liquid_swing",
        "description": "Quiet but liquid tape. Use the 1h chart to avoid churn and keep the entry gates conservative.",
        "timeframe": "1h",
        "ema_fast_period": 12,
        "ema_slow_period": 26,
        "rsi_period": 14,
        "risk_per_trade": 0.007,
        "stop_loss_pct": 0.015,
        "take_profit_pct": 0.022,
        "cooldown_candles": 4,
        "use_rsi_filter": True,
        "rsi_buy_min": 52.0,
        "rsi_sell_max": 48.0,
        "use_htf_filter": True,
        "htf_1_timeframe": "4h",
        "htf_1_rsi_min": 50.0,
        "htf_2_enabled": False,
        "signal_on_closed_candle": True,
    },
}


def _format_float(value: float | None, *, precision: int = 2, suffix: str = "") -> str:
    if value is None:
        return "missing"
    return f"{value:.{precision}f}{suffix}"


def _slope_pct(series: pd.Series) -> float | None:
    clean = [float(item) for item in series.dropna().tolist()]
    if len(clean) < 2:
        return None
    n = len(clean)
    x_mean = (n - 1) / 2
    y_mean = sum(clean) / n
    cov = sum((idx - x_mean) * (value - y_mean) for idx, value in enumerate(clean))
    var = sum((idx - x_mean) ** 2 for idx in range(n))
    if var <= 0:
        return None
    slope = cov / var
    reference = clean[-1] if clean[-1] != 0 else y_mean or 1.0
    return (slope / reference) * 100.0


def _true_range(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["close"].shift(1)
    ranges = pd.concat(
        [
            (frame["high"] - frame["low"]).abs(),
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def _quote_volume(frame: pd.DataFrame) -> float | None:
    if frame.empty:
        return None
    quote_volume = (frame["close"] * frame["volume"]).sum()
    return float(quote_volume) if quote_volume == quote_volume else None


def _direction_consistency(returns: pd.Series) -> float | None:
    clean = [float(item) for item in returns.dropna().tolist()]
    if not clean:
        return None
    positive = sum(1 for value in clean if value > 0)
    negative = sum(1 for value in clean if value < 0)
    dominant = max(positive, negative)
    return dominant / len(clean)


@dataclass(slots=True)
class RecentHistorySnapshot:
    symbol: str
    timeframe: str
    scanned_at: str
    candle_limit: int
    closed_candles: int
    analysis_candles: int
    last_close: float | None = None
    bid: float | None = None
    ask: float | None = None
    spread_bps: float | None = None
    return_6_pct: float | None = None
    return_24_pct: float | None = None
    realized_volatility_pct: float | None = None
    atr_pct: float | None = None
    trend_strength_pct: float | None = None
    slope_pct_per_candle: float | None = None
    range_pct: float | None = None
    volume_quote_recent: float | None = None
    volume_quote_prior: float | None = None
    volume_ratio: float | None = None
    direction_consistency: float | None = None
    close_location_pct: float | None = None

    def summary(self) -> str:
        return (
            f"window={self.analysis_candles}/{self.closed_candles} candles "
            f"last={_format_float(self.last_close, precision=4)} "
            f"spread={_format_float(self.spread_bps, precision=2, suffix='bps')} "
            f"vol={_format_float(self.realized_volatility_pct, precision=2, suffix='%')} "
            f"range={_format_float(self.range_pct, precision=2, suffix='%')}"
        )

    def evidence_lines(self) -> tuple[str, ...]:
        return (
            f"candles_fetched={self.candle_limit}",
            f"closed_candles={self.closed_candles}",
            f"analysis_candles={self.analysis_candles}",
            f"last_close={_format_float(self.last_close, precision=4)}",
            f"bid={_format_float(self.bid, precision=4)}",
            f"ask={_format_float(self.ask, precision=4)}",
            f"spread_bps={_format_float(self.spread_bps, precision=2)}",
            f"return_6_pct={_format_float(self.return_6_pct, precision=2, suffix='%')}",
            f"return_24_pct={_format_float(self.return_24_pct, precision=2, suffix='%')}",
            f"realized_volatility_pct={_format_float(self.realized_volatility_pct, precision=2, suffix='%')}",
            f"atr_pct={_format_float(self.atr_pct, precision=2, suffix='%')}",
            f"trend_strength_pct={_format_float(self.trend_strength_pct, precision=2, suffix='%')}",
            f"slope_pct_per_candle={_format_float(self.slope_pct_per_candle, precision=2, suffix='%')}",
            f"range_pct={_format_float(self.range_pct, precision=2, suffix='%')}",
            f"volume_quote_recent={_format_float(self.volume_quote_recent, precision=2)}",
            f"volume_quote_prior={_format_float(self.volume_quote_prior, precision=2)}",
            f"volume_ratio={_format_float(self.volume_ratio, precision=2)}",
            f"direction_consistency={_format_float(self.direction_consistency, precision=2)}",
            f"close_location_pct={_format_float(self.close_location_pct, precision=2, suffix='%')}",
        )


@dataclass(slots=True)
class AdaptiveDecisionReport:
    venue: str
    symbol: str
    timeframe: str
    scanned_at: str
    bot_mode: str
    adaptive_mode: str
    base_profile_name: str = ""
    base_profile_reason: str = ""
    regime: str = "unknown"
    regime_reason: str = ""
    evidence: tuple[str, ...] = field(default_factory=tuple)
    history: RecentHistorySnapshot | None = None
    selected_profile: StrategyProfileSelection | None = None
    applied: bool = False
    fallback_reason: str = ""
    report_path: Path | None = None
    report_json_path: Path | None = None

    def summary(self) -> str:
        profile = self.selected_profile.name if self.selected_profile is not None else "none"
        applied = "yes" if self.applied else "no"
        return f"venue={self.venue} symbol={self.symbol} regime={self.regime} policy={profile} applied={applied}"

    def why_lines(self) -> tuple[str, ...]:
        lines = [self.summary()]
        lines.append(f"Base profile: {self.base_profile_name or 'manual'}")
        if self.base_profile_reason:
            lines.append(f"Base reason: {self.base_profile_reason}")
        lines.append(f"Detected regime: {self.regime}")
        if self.regime_reason:
            lines.append(f"Regime reason: {self.regime_reason}")
        if self.history is not None:
            lines.append(f"Recent history: {self.history.summary()}")
            lines.extend(f"Evidence: {item}" for item in self.history.evidence_lines())
        elif self.evidence:
            lines.extend(f"Evidence: {item}" for item in self.evidence)
        if self.selected_profile is not None:
            lines.append("Selected policy")
            lines.extend(f"- {line}" for line in self.selected_profile.why_lines())
        if not self.applied and self.fallback_reason:
            lines.append(f"Fallback: {self.fallback_reason}")
        return tuple(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "scanned_at": self.scanned_at,
            "bot_mode": self.bot_mode,
            "adaptive_mode": self.adaptive_mode,
            "base_profile_name": self.base_profile_name,
            "base_profile_reason": self.base_profile_reason,
            "regime": self.regime,
            "regime_reason": self.regime_reason,
            "evidence": list(self.evidence),
            "history": asdict(self.history) if self.history is not None else None,
            "selected_profile": self.selected_profile.to_dict() if self.selected_profile is not None else None,
            "applied": self.applied,
            "fallback_reason": self.fallback_reason,
            "report_path": str(self.report_path) if self.report_path is not None else "",
            "report_json_path": str(self.report_json_path) if self.report_json_path is not None else "",
        }

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def _report_paths(path: Path) -> tuple[Path, Path]:
    if path.suffix:
        return path, path.with_suffix(".json")
    return path, path.with_name(path.name + ".json")


def write_adaptive_report(report: AdaptiveDecisionReport, path: Path) -> tuple[Path, Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    report_path, report_json_path = _report_paths(path)
    report.report_path = report_path
    report.report_json_path = report_json_path
    report_path.write_text(
        "\n".join(
            [
                f"Adaptive decision report for venue={report.venue} at {report.scanned_at}",
                "",
                *report.why_lines(),
                "",
            ]
        ),
        encoding="utf-8",
    )
    report_json_path.write_text(report.to_json(), encoding="utf-8")
    return report_path, report_json_path


def _build_recent_history(exchange, symbol: str, timeframe: str, *, candle_limit: int = _ANALYSIS_CANDLE_LIMIT) -> RecentHistorySnapshot:
    scanned_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    frame = fetch_ohlcv_df(exchange, symbol, timeframe, limit=candle_limit)
    if len(frame) > 1:
        closed = frame.iloc[:-1].copy()
    else:
        closed = frame.copy()
    closed = closed.dropna(subset=["open", "high", "low", "close"])
    closed_count = len(closed)
    analysis = closed.tail(min(_ANALYSIS_WINDOW, closed_count)).copy()
    analysis_count = len(analysis)

    bid = ask = spread_bps = None
    try:
        ticker = exchange.fetch_ticker(symbol) or {}
    except Exception:
        ticker = {}
    bid_value = ticker.get("bid")
    ask_value = ticker.get("ask")
    if bid_value not in (None, ""):
        try:
            bid = float(bid_value)
        except (TypeError, ValueError):
            bid = None
    if ask_value not in (None, ""):
        try:
            ask = float(ask_value)
        except (TypeError, ValueError):
            ask = None
    if bid is not None and ask is not None and ask >= bid and (bid + ask) > 0:
        midpoint = (bid + ask) / 2
        spread_bps = ((ask - bid) / midpoint) * 10_000 if midpoint > 0 else None

    last_close = float(analysis["close"].iloc[-1]) if analysis_count else None
    close_series = analysis["close"] if analysis_count else pd.Series(dtype=float)
    returns = close_series.pct_change().dropna()
    return_6_pct = None
    return_24_pct = None
    if analysis_count >= 2:
        recent_6 = analysis.tail(min(6, analysis_count))
        if len(recent_6) >= 2:
            return_6_pct = ((recent_6["close"].iloc[-1] / recent_6["close"].iloc[0]) - 1) * 100.0
        recent_24 = analysis.tail(min(24, analysis_count))
        if len(recent_24) >= 2:
            return_24_pct = ((recent_24["close"].iloc[-1] / recent_24["close"].iloc[0]) - 1) * 100.0

    realized_volatility_pct = float(returns.std(ddof=0) * math.sqrt(len(returns)) * 100.0) if len(returns) > 1 else None
    if analysis_count >= 2 and last_close is not None:
        atr_series = _true_range(analysis)
        atr_pct = float((atr_series.mean() / last_close) * 100.0) if atr_series.notna().any() else None
        trend_fast = analysis["close"].ewm(span=8, adjust=False).mean()
        trend_slow = analysis["close"].ewm(span=21, adjust=False).mean()
        trend_strength_pct = float(abs(trend_fast.iloc[-1] - trend_slow.iloc[-1]) / last_close * 100.0)
        slope_pct_per_candle = _slope_pct(analysis["close"])
        range_high = float(analysis["high"].max())
        range_low = float(analysis["low"].min())
        range_pct = ((range_high - range_low) / last_close) * 100.0 if range_high >= range_low and last_close > 0 else None
        if range_high > range_low:
            close_location_pct = ((last_close - range_low) / (range_high - range_low)) * 100.0
        else:
            close_location_pct = None
    else:
        atr_pct = None
        trend_strength_pct = None
        slope_pct_per_candle = None
        range_pct = None
        close_location_pct = None

    recent_quote_volume = _quote_volume(analysis.tail(min(_SHORT_WINDOW, analysis_count)))
    prior_quote_volume = None
    volume_ratio = None
    if analysis_count >= _SHORT_WINDOW * 2:
        prior_frame = analysis.iloc[-(_SHORT_WINDOW * 2) : -_SHORT_WINDOW]
        prior_quote_volume = _quote_volume(prior_frame)
        if recent_quote_volume not in (None, 0) and prior_quote_volume not in (None, 0):
            volume_ratio = recent_quote_volume / prior_quote_volume

    direction_consistency = _direction_consistency(returns.tail(min(_SHORT_WINDOW, len(returns))))

    return RecentHistorySnapshot(
        symbol=symbol,
        timeframe=timeframe,
        scanned_at=scanned_at,
        candle_limit=candle_limit,
        closed_candles=closed_count,
        analysis_candles=analysis_count,
        last_close=last_close,
        bid=bid,
        ask=ask,
        spread_bps=spread_bps,
        return_6_pct=return_6_pct,
        return_24_pct=return_24_pct,
        realized_volatility_pct=realized_volatility_pct,
        atr_pct=atr_pct,
        trend_strength_pct=trend_strength_pct,
        slope_pct_per_candle=slope_pct_per_candle,
        range_pct=range_pct,
        volume_quote_recent=recent_quote_volume,
        volume_quote_prior=prior_quote_volume,
        volume_ratio=volume_ratio,
        direction_consistency=direction_consistency,
        close_location_pct=close_location_pct,
    )


def classify_recent_market_regime(history: RecentHistorySnapshot) -> tuple[str, str, tuple[str, ...]]:
    evidence = history.evidence_lines()
    if history.closed_candles < _MIN_CLOSED_CANDLES or history.last_close is None or history.return_24_pct is None:
        return (
            "unknown",
            "Recent candle history is too short for a confident adaptive decision, so the current profile is preserved.",
            evidence,
        )

    spread = history.spread_bps
    realized_vol = history.realized_volatility_pct
    range_pct = history.range_pct
    trend_strength = history.trend_strength_pct
    slope = abs(history.slope_pct_per_candle or 0.0)
    direction_consistency = history.direction_consistency or 0.0
    volume_ratio = history.volume_ratio or 1.0
    abs_return_24 = abs(history.return_24_pct or 0.0)

    if (
        (spread is not None and spread >= _VOLATILE_SPREAD_BPS)
        or (realized_vol is not None and realized_vol >= _VOLATILE_REALIZED_VOL_PCT and direction_consistency <= 0.55)
        or (range_pct is not None and range_pct >= _VOLATILE_RANGE_PCT and direction_consistency <= 0.55)
    ):
        return (
            "volatile",
            "Recent candles show elevated spread, realized volatility, or range expansion, so the defensive volatile policy is safer.",
            evidence,
        )

    if (
        abs_return_24 >= _TREND_RETURN_PCT
        and (trend_strength or 0.0) >= _TREND_STRENGTH_PCT
        and slope >= _TREND_SLOPE_PCT
        and direction_consistency >= _TREND_DIRECTION_CONSISTENCY
        and volume_ratio >= 0.85
    ):
        return (
            "trend",
            "Recent candles show directional drift, a clean EMA spread, and stable volume behavior, which fits the trend policy.",
            evidence,
        )

    if (
        (realized_vol is not None and realized_vol <= _SLOW_REALIZED_VOL_PCT)
        and (range_pct is not None and range_pct <= _SLOW_RANGE_PCT)
        and (trend_strength is not None and trend_strength <= 0.30)
        and (spread is None or spread <= _SLOW_SPREAD_BPS)
    ):
        return (
            "slow_liquid",
            "Recent candles are quiet, tightly ranged, and spread-efficient, so the slower 1h policy is a better fit.",
            evidence,
        )

    return (
        "range",
        "Recent candles are contained but not quiet enough for the slow_liquid policy and not directional enough for the trend policy.",
        evidence,
    )


def _build_policy_from_preset(
    regime: str,
    history: RecentHistorySnapshot,
    regime_reason: str,
    evidence: tuple[str, ...],
) -> StrategyProfileSelection | None:
    preset = _ADAPTIVE_POLICY_PRESETS.get(regime)
    if preset is None:
        return None

    profile = StrategyProfileSelection(
        name=str(preset["name"]),
        regime=regime,
        reason=f"{regime_reason} Adaptive policy selected from recent candles.",
        evidence=evidence,
        source="adaptive",
        description=str(preset["description"]),
        risk_per_trade=preset.get("risk_per_trade"),
        stop_loss_pct=preset.get("stop_loss_pct"),
        take_profit_pct=preset.get("take_profit_pct"),
        cooldown_candles=preset.get("cooldown_candles"),
        timeframe=preset.get("timeframe"),
        ema_fast_period=preset.get("ema_fast_period"),
        ema_slow_period=preset.get("ema_slow_period"),
        rsi_period=preset.get("rsi_period"),
        use_rsi_filter=preset.get("use_rsi_filter"),
        rsi_buy_min=preset.get("rsi_buy_min"),
        rsi_sell_max=preset.get("rsi_sell_max"),
        use_htf_filter=preset.get("use_htf_filter"),
        htf_1_timeframe=preset.get("htf_1_timeframe"),
        htf_1_rsi_min=preset.get("htf_1_rsi_min"),
        htf_2_enabled=preset.get("htf_2_enabled"),
        signal_on_closed_candle=preset.get("signal_on_closed_candle"),
    )
    validation_error = _validate_policy(profile, history)
    if validation_error:
        return None
    return profile


def _validate_policy(profile: StrategyProfileSelection, history: RecentHistorySnapshot) -> str | None:
    if profile.timeframe not in _ALLOWED_TIMEFRAMES:
        return f"Adaptive policy timeframe {profile.timeframe!r} is not in the allowed set {_ALLOWED_TIMEFRAMES}."
    if profile.ema_fast_period is None or profile.ema_slow_period is None:
        return "Adaptive policy must set both EMA periods."
    if not (5 <= profile.ema_fast_period < profile.ema_slow_period <= 50):
        return "Adaptive policy EMA periods must stay within 5..50 and fast must be below slow."
    if profile.rsi_period is None or not (7 <= profile.rsi_period <= 30):
        return "Adaptive policy RSI period must be between 7 and 30."
    if profile.stop_loss_pct is None or profile.take_profit_pct is None:
        return "Adaptive policy must set stop loss and take profit."
    if not (0.01 <= profile.stop_loss_pct <= 0.035 and 0.015 <= profile.take_profit_pct <= 0.06):
        return "Adaptive policy stop loss / take profit values are outside the conservative bounds."
    if profile.take_profit_pct <= profile.stop_loss_pct:
        return "Adaptive policy take profit must be larger than stop loss."
    if profile.risk_per_trade is None or not (0.004 <= profile.risk_per_trade <= 0.01):
        return "Adaptive policy risk per trade must stay within 0.4% to 1.0%."
    if profile.cooldown_candles is None or not (1 <= profile.cooldown_candles <= 5):
        return "Adaptive policy cooldown must stay between 1 and 5 candles."
    if profile.rsi_buy_min is None or profile.rsi_sell_max is None:
        return "Adaptive policy must set RSI thresholds."
    if not (40 <= profile.rsi_sell_max < profile.rsi_buy_min <= 60):
        return "Adaptive policy RSI thresholds must stay within 40..60 and buy must stay above sell."
    if profile.use_htf_filter:
        if profile.htf_1_timeframe not in _ALLOWED_HTF_TIMEFRAMES:
            return f"Adaptive policy HTF timeframe {profile.htf_1_timeframe!r} is not allowed."
        if profile.htf_1_timeframe == profile.timeframe:
            return "Adaptive policy HTF timeframe must differ from the main timeframe."
        if profile.htf_1_rsi_min is None or not (45 <= profile.htf_1_rsi_min <= 60):
            return "Adaptive policy HTF RSI minimum must stay within 45..60."
    if profile.signal_on_closed_candle is not True:
        return "Adaptive policy must keep signal_on_closed_candle enabled."
    if history.closed_candles < _MIN_CLOSED_CANDLES:
        return "Adaptive policy requires more recent candles before applying."
    return None


def evaluate_adaptive_policy(config, exchange) -> AdaptiveDecisionReport:
    history = _build_recent_history(exchange, config.symbol, config.timeframe)
    regime, regime_reason, evidence = classify_recent_market_regime(history)
    base_profile_name = config.active_selection_profile or config.active_strategy_profile or ""
    if base_profile_name:
        base_profile_reason = config.active_selection_profile_reason or config.active_strategy_profile_reason
    else:
        base_profile_reason = ""
    selected_profile = None
    fallback_reason = ""
    applied = False

    if regime != "unknown":
        selected_profile = _build_policy_from_preset(regime, history, regime_reason, evidence)
        if selected_profile is None:
            fallback_reason = "Adaptive policy preset validation failed; keeping the existing profile."
        else:
            config.apply_strategy_profile(selected_profile)
            applied = True
    else:
        fallback_reason = regime_reason

    report = AdaptiveDecisionReport(
        venue="binance",
        symbol=config.symbol,
        timeframe=config.timeframe,
        scanned_at=history.scanned_at,
        bot_mode=config.bot_mode,
        adaptive_mode=config.adaptive_mode,
        base_profile_name=base_profile_name,
        base_profile_reason=base_profile_reason,
        regime=regime,
        regime_reason=regime_reason,
        evidence=evidence,
        history=history,
        selected_profile=selected_profile,
        applied=applied,
        fallback_reason=fallback_reason,
    )
    write_adaptive_report(report, config.adaptive_report_path)
    return report
