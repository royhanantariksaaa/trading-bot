from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import MarketMetrics


PROFILE_NAMES = ("trend", "range", "volatile", "slow_liquid")


_OVERRIDE_FIELDS = (
    "risk_per_trade",
    "stop_loss_pct",
    "take_profit_pct",
    "cooldown_candles",
    "use_rsi_filter",
    "rsi_buy_min",
    "rsi_sell_max",
    "use_htf_filter",
    "htf_1_rsi_min",
    "htf_2_enabled",
    "htf_2_rsi_min",
    "signal_on_closed_candle",
)


_PROFILE_PRESETS: dict[str, dict[str, Any]] = {
    "trend": {
        "description": "Directional market with enough liquidity to follow momentum while keeping confirmation gates on.",
        "risk_per_trade": 0.008,
        "stop_loss_pct": 0.020,
        "take_profit_pct": 0.035,
        "cooldown_candles": 2,
        "use_rsi_filter": True,
        "rsi_buy_min": 55.0,
        "rsi_sell_max": 45.0,
        "use_htf_filter": True,
        "htf_1_rsi_min": 52.0,
        "htf_2_enabled": False,
        "htf_2_rsi_min": 50.0,
        "signal_on_closed_candle": True,
    },
    "range": {
        "description": "Contained market with moderate swings. Lean on tighter mean-reversion style entries.",
        "risk_per_trade": 0.006,
        "stop_loss_pct": 0.012,
        "take_profit_pct": 0.018,
        "cooldown_candles": 3,
        "use_rsi_filter": True,
        "rsi_buy_min": 50.0,
        "rsi_sell_max": 50.0,
        "use_htf_filter": False,
        "htf_1_rsi_min": 50.0,
        "htf_2_enabled": False,
        "htf_2_rsi_min": 50.0,
        "signal_on_closed_candle": True,
    },
    "volatile": {
        "description": "Wide swings or spread pressure. Reduce size and demand more confirmation before entry.",
        "risk_per_trade": 0.005,
        "stop_loss_pct": 0.030,
        "take_profit_pct": 0.050,
        "cooldown_candles": 4,
        "use_rsi_filter": True,
        "rsi_buy_min": 58.0,
        "rsi_sell_max": 42.0,
        "use_htf_filter": True,
        "htf_1_rsi_min": 55.0,
        "htf_2_enabled": False,
        "htf_2_rsi_min": 50.0,
        "signal_on_closed_candle": True,
    },
    "slow_liquid": {
        "description": "Deep market with quiet tape. Keep risk small and wait for cleaner entries.",
        "risk_per_trade": 0.007,
        "stop_loss_pct": 0.015,
        "take_profit_pct": 0.022,
        "cooldown_candles": 4,
        "use_rsi_filter": True,
        "rsi_buy_min": 52.0,
        "rsi_sell_max": 48.0,
        "use_htf_filter": True,
        "htf_1_rsi_min": 50.0,
        "htf_2_enabled": False,
        "htf_2_rsi_min": 50.0,
        "signal_on_closed_candle": True,
    },
}


_REGIME_THRESHOLDS = {
    "binance": {
        "volatile_spread_bps": 35.0,
        "volatile_range_pct": 10.0,
        "volatile_move_pct": 8.0,
        "trend_volume_quote_24h": 25_000_000.0,
        "trend_trade_count_24h": 12_000,
        "trend_spread_bps": 20.0,
        "trend_range_pct": 5.0,
        "trend_move_pct": 4.0,
        "slow_volume_quote_24h": 50_000_000.0,
        "slow_trade_count_24h": 15_000,
        "slow_spread_bps": 12.0,
        "slow_range_pct": 3.0,
        "slow_move_pct": 2.0,
    },
    "polymarket": {
        "volatile_spread_bps": 150.0,
        "volatile_range_pct": 14.0,
        "volatile_move_pct": 12.0,
        "trend_volume_quote_24h": 15_000.0,
        "trend_trade_count_24h": 100,
        "trend_spread_bps": 100.0,
        "trend_range_pct": 8.0,
        "trend_move_pct": 6.0,
        "slow_volume_quote_24h": 60_000.0,
        "slow_trade_count_24h": 250,
        "slow_spread_bps": 60.0,
        "slow_range_pct": 4.0,
        "slow_move_pct": 2.5,
    },
}


def _format_metric(value: float | int | None, *, suffix: str = "", fallback: str = "missing") -> str:
    if value is None:
        return fallback
    if isinstance(value, int):
        return f"{value}{suffix}"
    return f"{value:.2f}{suffix}"


def _format_override(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


@dataclass(slots=True)
class StrategyProfileSelection:
    name: str
    regime: str
    reason: str
    evidence: tuple[str, ...] = field(default_factory=tuple)
    source: str = "auto"
    description: str = ""
    risk_per_trade: float | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    cooldown_candles: int | None = None
    use_rsi_filter: bool | None = None
    rsi_buy_min: float | None = None
    rsi_sell_max: float | None = None
    use_htf_filter: bool | None = None
    htf_1_rsi_min: float | None = None
    htf_2_enabled: bool | None = None
    htf_2_rsi_min: float | None = None
    signal_on_closed_candle: bool | None = None

    def summary(self) -> str:
        return f"profile={self.name} regime={self.regime} source={self.source}"

    def override_summary(self) -> str:
        parts: list[str] = []
        for field_name in _OVERRIDE_FIELDS:
            value = getattr(self, field_name)
            if value is None:
                continue
            parts.append(f"{field_name}={_format_override(value)}")
        return ", ".join(parts)

    def why_lines(self) -> tuple[str, ...]:
        lines = [self.summary()]
        if self.description:
            lines.append(f"Why: {self.description}")
        lines.append(f"Reason: {self.reason}")
        if self.evidence:
            lines.append("Evidence: " + " | ".join(self.evidence))
        overrides = self.override_summary()
        if overrides:
            lines.append(f"Applied overrides: {overrides}")
        return tuple(lines)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> StrategyProfileSelection | None:
        if not data:
            return None
        payload = dict(data)
        evidence = payload.get("evidence") or ()
        if isinstance(evidence, str):
            evidence_items = [item.strip() for item in evidence.split("|") if item.strip()]
        else:
            evidence_items = [str(item) for item in evidence if str(item)]
        payload["evidence"] = tuple(evidence_items)
        return cls(
            name=str(payload.get("name") or ""),
            regime=str(payload.get("regime") or ""),
            reason=str(payload.get("reason") or ""),
            evidence=payload["evidence"],
            source=str(payload.get("source") or "auto"),
            description=str(payload.get("description") or ""),
            risk_per_trade=_to_float(payload.get("risk_per_trade")),
            stop_loss_pct=_to_float(payload.get("stop_loss_pct")),
            take_profit_pct=_to_float(payload.get("take_profit_pct")),
            cooldown_candles=_to_int(payload.get("cooldown_candles")),
            use_rsi_filter=_to_bool(payload.get("use_rsi_filter")),
            rsi_buy_min=_to_float(payload.get("rsi_buy_min")),
            rsi_sell_max=_to_float(payload.get("rsi_sell_max")),
            use_htf_filter=_to_bool(payload.get("use_htf_filter")),
            htf_1_rsi_min=_to_float(payload.get("htf_1_rsi_min")),
            htf_2_enabled=_to_bool(payload.get("htf_2_enabled")),
            htf_2_rsi_min=_to_float(payload.get("htf_2_rsi_min")),
            signal_on_closed_candle=_to_bool(payload.get("signal_on_closed_candle")),
        )

    @classmethod
    def from_json(cls, raw: str | None) -> StrategyProfileSelection | None:
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return cls.from_dict(payload)


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    value_text = str(value).strip().lower()
    if value_text in {"true", "1", "yes", "y", "on"}:
        return True
    if value_text in {"false", "0", "no", "n", "off"}:
        return False
    return None


def _regime_evidence(metrics: MarketMetrics) -> tuple[str, ...]:
    volume = metrics.volume_quote_24h
    trade_count = metrics.trade_count_24h
    spread = metrics.spread_bps
    range_pct = metrics.range_pct_24h
    movement = abs(metrics.price_change_pct_24h or 0.0)
    return (
        f"quote_volume_24h={_format_metric(volume)}",
        f"trade_count_24h={_format_metric(trade_count)}",
        f"spread_bps={_format_metric(spread)}",
        f"range_pct_24h={_format_metric(range_pct, suffix='%')}",
        f"price_change_pct_24h={_format_metric(metrics.price_change_pct_24h, suffix='%')}",
        f"abs_move_pct_24h={movement:.2f}%",
    )


def classify_market_regime(venue: str, metrics: MarketMetrics) -> tuple[str, str, tuple[str, ...]]:
    venue_name = venue.strip().lower()
    thresholds = _REGIME_THRESHOLDS.get(venue_name, _REGIME_THRESHOLDS["binance"])
    evidence = _regime_evidence(metrics)

    volume = metrics.volume_quote_24h
    trade_count = metrics.trade_count_24h
    spread = metrics.spread_bps
    range_pct = metrics.range_pct_24h if metrics.range_pct_24h is not None else abs(metrics.price_change_pct_24h or 0.0)
    move_pct = abs(metrics.price_change_pct_24h or 0.0)

    if volume is None or trade_count is None or spread is None:
        return (
            "slow_liquid",
            "Missing liquidity or spread data, so defaulting to the conservative slow_liquid profile.",
            evidence,
        )

    if spread >= thresholds["volatile_spread_bps"] or range_pct >= thresholds["volatile_range_pct"] or move_pct >= thresholds["volatile_move_pct"]:
        return (
            "volatile",
            f"spread_bps={spread:.2f}, range_pct_24h={range_pct:.2f}, and move_pct_24h={move_pct:.2f} look wide enough to treat this as a volatile regime.",
            evidence,
        )

    if (
        volume >= thresholds["trend_volume_quote_24h"]
        and trade_count >= thresholds["trend_trade_count_24h"]
        and spread <= thresholds["trend_spread_bps"]
        and range_pct >= thresholds["trend_range_pct"]
        and move_pct >= thresholds["trend_move_pct"]
    ):
        return (
            "trend",
            f"quote_volume_24h={volume:.0f}, trade_count_24h={trade_count}, and directional move={move_pct:.2f}% support a trend-following profile.",
            evidence,
        )

    if (
        volume >= thresholds["slow_volume_quote_24h"]
        and trade_count >= thresholds["slow_trade_count_24h"]
        and spread <= thresholds["slow_spread_bps"]
        and range_pct <= thresholds["slow_range_pct"]
        and move_pct <= thresholds["slow_move_pct"]
    ):
        return (
            "slow_liquid",
            f"quote_volume_24h={volume:.0f} with tight spread and muted movement favors the conservative slow_liquid profile.",
            evidence,
        )

    return (
        "range",
        f"Price action is contained enough for a range profile, while liquidity remains adequate for conservative entries.",
        evidence,
    )


def build_strategy_profile(profile_name: str, venue: str, metrics: MarketMetrics, *, source: str = "auto") -> StrategyProfileSelection | None:
    requested = profile_name.strip().lower()
    if not requested or requested == "manual":
        return None

    regime, regime_reason, evidence = classify_market_regime(venue, metrics)
    if requested == "auto":
        requested = regime
        source = "auto"

    preset = _PROFILE_PRESETS.get(requested)
    if preset is None:
        raise ValueError(f"Unknown strategy profile '{profile_name}'")

    reason = regime_reason
    if source != "auto" or requested != regime:
        reason = f"Forced strategy profile={requested}; detected regime={regime}. {regime_reason}"

    return StrategyProfileSelection(
        name=requested,
        regime=regime,
        reason=reason,
        evidence=evidence,
        source=source,
        description=str(preset.get("description", "")),
        risk_per_trade=preset.get("risk_per_trade"),
        stop_loss_pct=preset.get("stop_loss_pct"),
        take_profit_pct=preset.get("take_profit_pct"),
        cooldown_candles=preset.get("cooldown_candles"),
        use_rsi_filter=preset.get("use_rsi_filter"),
        rsi_buy_min=preset.get("rsi_buy_min"),
        rsi_sell_max=preset.get("rsi_sell_max"),
        use_htf_filter=preset.get("use_htf_filter"),
        htf_1_rsi_min=preset.get("htf_1_rsi_min"),
        htf_2_enabled=preset.get("htf_2_enabled"),
        htf_2_rsi_min=preset.get("htf_2_rsi_min"),
        signal_on_closed_candle=preset.get("signal_on_closed_candle"),
    )


def select_strategy_profile(venue: str, metrics: MarketMetrics) -> StrategyProfileSelection | None:
    return build_strategy_profile("auto", venue, metrics)

