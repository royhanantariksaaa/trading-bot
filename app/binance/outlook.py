from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adaptive import RecentHistorySnapshot, classify_recent_market_regime
from .config import Config
from .exchange import create_exchange, fetch_ohlcv_df
from .strategy import add_indicators
from ..utils.storage import ensure_parent, market_data_path


_OUTLOOK_WINDOWS: tuple[tuple[str, str, int], ...] = (
    ("6h", "15m", 24),
    ("24h", "1h", 24),
    ("3d", "4h", 18),
)

_HORIZON_WEIGHTS: dict[str, float] = {
    "6h": 0.2,
    "24h": 0.5,
    "3d": 0.3,
}

_BIAS_TO_SIGN: dict[str, int] = {
    "bullish": 1,
    "neutral": 0,
    "bearish": -1,
}


@dataclass(slots=True)
class OutlookHorizon:
    label: str
    timeframe: str
    candles: int
    bias: str
    confidence: str
    score: float
    regime: str
    rationale: tuple[str, ...] = field(default_factory=tuple)
    bullish_confirmation: tuple[str, ...] = field(default_factory=tuple)
    bullish_invalidation: tuple[str, ...] = field(default_factory=tuple)
    bearish_confirmation: tuple[str, ...] = field(default_factory=tuple)
    bearish_invalidation: tuple[str, ...] = field(default_factory=tuple)
    metrics: dict[str, float | None] = field(default_factory=dict)


@dataclass(slots=True)
class MarketOutlookReport:
    symbol: str
    generated_at: str
    venue: str = "binance"
    horizons: tuple[OutlookHorizon, ...] = field(default_factory=tuple)
    summary_bias: str = "neutral"
    summary_confidence: str = "low"
    summary_score: float = 0.0
    summary_rationale: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)
    report_path: str = ""
    report_json_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "symbol": self.symbol,
            "generated_at": self.generated_at,
            "summary_bias": self.summary_bias,
            "summary_confidence": self.summary_confidence,
            "summary_score": self.summary_score,
            "summary_rationale": list(self.summary_rationale),
            "notes": list(self.notes),
            "horizons": [asdict(item) for item in self.horizons],
            "report_path": self.report_path,
            "report_json_path": self.report_json_path,
        }

    def to_text(self) -> str:
        lines = [
            f"Binance outlook report | symbol={self.symbol} | generated_at={self.generated_at}",
            f"Summary: bias={self.summary_bias} confidence={self.summary_confidence} score={self.summary_score:.1f}",
        ]
        if self.summary_rationale:
            lines.extend(f"- {item}" for item in self.summary_rationale)
        lines.append("")
        for horizon in self.horizons:
            lines.append(
                f"[{horizon.label}] bias={horizon.bias} confidence={horizon.confidence} score={horizon.score:.1f} regime={horizon.regime} timeframe={horizon.timeframe} candles={horizon.candles}"
            )
            lines.extend(f"- {item}" for item in horizon.rationale)
            if horizon.bias == "bullish":
                if horizon.bullish_confirmation:
                    lines.append("  Bullish confirmation:")
                    lines.extend(f"  * {item}" for item in horizon.bullish_confirmation)
                if horizon.bullish_invalidation:
                    lines.append("  Bullish invalidation:")
                    lines.extend(f"  * {item}" for item in horizon.bullish_invalidation)
            elif horizon.bias == "bearish":
                if horizon.bearish_confirmation:
                    lines.append("  Bearish confirmation:")
                    lines.extend(f"  * {item}" for item in horizon.bearish_confirmation)
                if horizon.bearish_invalidation:
                    lines.append("  Bearish invalidation:")
                    lines.extend(f"  * {item}" for item in horizon.bearish_invalidation)
            else:
                if horizon.bullish_confirmation:
                    lines.append("  Bullish confirmation:")
                    lines.extend(f"  * {item}" for item in horizon.bullish_confirmation)
                if horizon.bullish_invalidation:
                    lines.append("  Bullish invalidation:")
                    lines.extend(f"  * {item}" for item in horizon.bullish_invalidation)
                if horizon.bearish_confirmation:
                    lines.append("  Bearish confirmation:")
                    lines.extend(f"  * {item}" for item in horizon.bearish_confirmation)
                if horizon.bearish_invalidation:
                    lines.append("  Bearish invalidation:")
                    lines.extend(f"  * {item}" for item in horizon.bearish_invalidation)
            if horizon.metrics:
                lines.append(
                    "  Metrics: " + ", ".join(
                        f"{key}={value:.2f}" if isinstance(value, float) and value == value else f"{key}={value}"
                        for key, value in horizon.metrics.items()
                    )
                )
            lines.append("")
        if self.notes:
            lines.append("Notes:")
            lines.extend(f"- {item}" for item in self.notes)
            lines.append("")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def _safe_float(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result):
        return None
    return result


def _history_from_frame(symbol: str, timeframe: str, frame, *, candle_limit: int) -> RecentHistorySnapshot:
    closed = frame.iloc[:-1].copy() if len(frame) > 1 else frame.copy()
    closed = closed.dropna(subset=["open", "high", "low", "close"])
    analysis = closed.tail(candle_limit).copy()
    last_close = _safe_float(analysis["close"].iloc[-1]) if len(analysis) else None
    returns = analysis["close"].pct_change().dropna()
    recent_half = max(2, candle_limit // 2)
    return_half = None
    if len(analysis) >= 2:
        sample = analysis.tail(min(recent_half, len(analysis)))
        if len(sample) >= 2:
            return_half = ((float(sample["close"].iloc[-1]) / float(sample["close"].iloc[0])) - 1.0) * 100.0
    return_full = None
    if len(analysis) >= 2:
        return_full = ((float(analysis["close"].iloc[-1]) / float(analysis["close"].iloc[0])) - 1.0) * 100.0
    realized_vol = float(returns.std(ddof=0) * math.sqrt(len(returns)) * 100.0) if len(returns) > 1 else None
    range_pct = None
    close_location_pct = None
    trend_strength_pct = None
    slope_pct_per_candle = None
    if len(analysis) >= 2 and last_close and last_close > 0:
        range_high = float(analysis["high"].max())
        range_low = float(analysis["low"].min())
        range_pct = ((range_high - range_low) / last_close) * 100.0 if range_high >= range_low else None
        if range_high > range_low:
            close_location_pct = ((last_close - range_low) / (range_high - range_low)) * 100.0
        ema_fast = analysis["close"].ewm(span=8, adjust=False).mean()
        ema_slow = analysis["close"].ewm(span=21, adjust=False).mean()
        trend_strength_pct = float(abs(ema_fast.iloc[-1] - ema_slow.iloc[-1]) / last_close * 100.0)
        y = [float(item) for item in analysis["close"].tolist()]
        if len(y) >= 2:
            x_mean = (len(y) - 1) / 2
            y_mean = sum(y) / len(y)
            cov = sum((idx - x_mean) * (value - y_mean) for idx, value in enumerate(y))
            var = sum((idx - x_mean) ** 2 for idx in range(len(y)))
            slope = cov / var if var > 0 else 0.0
            reference = y[-1] if y[-1] != 0 else y_mean or 1.0
            slope_pct_per_candle = (slope / reference) * 100.0
    direction_consistency = None
    if len(returns) > 0:
        tail = [float(item) for item in returns.tail(min(12, len(returns))).tolist()]
        if tail:
            positive = sum(1 for value in tail if value > 0)
            negative = sum(1 for value in tail if value < 0)
            direction_consistency = max(positive, negative) / len(tail)
    return RecentHistorySnapshot(
        symbol=symbol,
        timeframe=timeframe,
        scanned_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        candle_limit=candle_limit,
        closed_candles=len(closed),
        analysis_candles=len(analysis),
        last_close=last_close,
        return_6_pct=return_half,
        return_24_pct=return_full,
        realized_volatility_pct=realized_vol,
        trend_strength_pct=trend_strength_pct,
        slope_pct_per_candle=slope_pct_per_candle,
        range_pct=range_pct,
        direction_consistency=direction_consistency,
        close_location_pct=close_location_pct,
    )


def _bias_from_score(score: float) -> str:
    if score >= 2.0:
        return "bullish"
    if score <= -2.0:
        return "bearish"
    return "neutral"


def _confidence_from_score(score: float) -> str:
    magnitude = abs(score)
    if magnitude >= 4.0:
        return "high"
    if magnitude >= 2.5:
        return "medium"
    return "low"


def _consensus_rationale(horizons: tuple[OutlookHorizon, ...], summary_score: float) -> tuple[str, ...]:
    if not horizons:
        return ("No outlook horizons were generated.",)
    total_weight = sum(_HORIZON_WEIGHTS.get(item.label, 1.0) for item in horizons) or 1.0
    bullish_weight = sum(_HORIZON_WEIGHTS.get(item.label, 1.0) for item in horizons if item.bias == "bullish")
    bearish_weight = sum(_HORIZON_WEIGHTS.get(item.label, 1.0) for item in horizons if item.bias == "bearish")
    neutral_weight = sum(_HORIZON_WEIGHTS.get(item.label, 1.0) for item in horizons if item.bias == "neutral")
    dominant = max((bullish_weight, "bullish"), (bearish_weight, "bearish"), (neutral_weight, "neutral"))[1]
    lines = [
        f"Weighted consensus score={summary_score:.2f}; heavier horizons dominate (24h=0.5, 3d=0.3, 6h=0.2).",
        f"Weighted bias mix: bullish={bullish_weight/total_weight:.0%} bearish={bearish_weight/total_weight:.0%} neutral={neutral_weight/total_weight:.0%}.",
    ]
    if dominant == "neutral":
        lines.append("Timeframes do not agree strongly enough, so the summary stays cautious.")
    elif bullish_weight > 0 and bearish_weight > 0:
        lines.append("Timeframes are pulling in opposite directions, so confidence is clipped for disagreement.")
    else:
        lines.append(f"{dominant.title()} timeframes dominate the weighted vote.")
    return tuple(lines)


def _adjusted_confidence_from_horizons(summary_score: float, horizons: tuple[OutlookHorizon, ...]) -> str:
    base = _confidence_from_score(summary_score)
    levels = ["low", "medium", "high"]
    index = levels.index(base)
    if not horizons:
        return base
    total_weight = sum(_HORIZON_WEIGHTS.get(item.label, 1.0) for item in horizons) or 1.0
    weighted_direction = sum(_BIAS_TO_SIGN.get(item.bias, 0) * _HORIZON_WEIGHTS.get(item.label, 1.0) for item in horizons) / total_weight
    disagreement_penalty = 0
    if abs(weighted_direction) < 0.34:
        disagreement_penalty += 1
    regimes = {item.regime for item in horizons if item.regime}
    if len(regimes) >= 3:
        disagreement_penalty += 1
    neutral_cluster = sum(1 for item in horizons if abs(item.score) < 2.0)
    if neutral_cluster >= 2:
        disagreement_penalty += 1
    elevated_vol = sum(
        1
        for item in horizons
        if (_safe_float(item.metrics.get("realized_volatility_pct")) or 0.0) >= 4.0
    )
    if elevated_vol >= 2:
        disagreement_penalty += 1
    return levels[max(0, index - disagreement_penalty)]


def _append_outlook_history(report: MarketOutlookReport, path: Path) -> None:
    history_path = ensure_parent(path)
    payload = {
        "generated_at": report.generated_at,
        "venue": report.venue,
        "symbol": report.symbol,
        "summary_bias": report.summary_bias,
        "summary_confidence": report.summary_confidence,
        "summary_score": report.summary_score,
        "summary_rationale": list(report.summary_rationale),
        "horizons": [
            {
                "label": item.label,
                "timeframe": item.timeframe,
                "candles": item.candles,
                "bias": item.bias,
                "confidence": item.confidence,
                "score": item.score,
                "regime": item.regime,
                "metrics": item.metrics,
            }
            for item in report.horizons
        ],
    }
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _build_horizon(exchange, symbol: str, timeframe: str, label: str, candles: int) -> OutlookHorizon:
    limit = max(80, candles + 40)
    df = fetch_ohlcv_df(exchange, symbol, timeframe, limit=limit)
    df = add_indicators(df)
    closed = df.iloc[:-1].copy() if len(df) > 1 else df.copy()
    if len(closed) < max(30, candles):
        return OutlookHorizon(
            label=label,
            timeframe=timeframe,
            candles=candles,
            bias="neutral",
            confidence="low",
            score=0.0,
            regime="unknown",
            rationale=("Not enough closed candles for a confident outlook.",),
            bullish_confirmation=("Need more history before trusting this horizon.",),
            bullish_invalidation=("N/A",),
            bearish_confirmation=("Need more history before trusting this horizon.",),
            bearish_invalidation=("N/A",),
            metrics={},
        )

    recent = closed.tail(candles).copy()
    signal_row = recent.iloc[-1]
    first_close = float(recent["close"].iloc[0])
    last_close = float(signal_row["close"])
    ema_fast = float(signal_row["ema_fast"])
    ema_slow = float(signal_row["ema_slow"])
    rsi = _safe_float(signal_row["rsi"]) or 50.0
    returns = recent["close"].pct_change().dropna()
    realized_vol = float(returns.std(ddof=0) * math.sqrt(len(returns)) * 100.0) if len(returns) > 1 else 0.0
    momentum_pct = ((last_close / first_close) - 1.0) * 100.0 if first_close > 0 else 0.0
    above_slow_ratio = float((recent["close"] > recent["ema_slow"]).mean() * 100.0)
    bullish_candle_ratio = float((recent["close"] > recent["open"]).mean() * 100.0)
    ema_spread_pct = abs(ema_fast - ema_slow) / last_close * 100.0 if last_close > 0 else 0.0
    ema_spread_series = ((recent["ema_fast"] - recent["ema_slow"]).abs() / recent["close"].replace(0, float("nan"))) * 100.0
    ema_spread_delta_pct = float(ema_spread_series.iloc[-1] - ema_spread_series.iloc[0]) if len(ema_spread_series) >= 2 else 0.0
    distance_from_high_pct = ((float(recent["high"].max()) - last_close) / last_close) * 100.0 if last_close > 0 else 0.0
    distance_from_low_pct = ((last_close - float(recent["low"].min())) / last_close) * 100.0 if last_close > 0 else 0.0
    above_slow_streak = 0
    below_slow_streak = 0
    for close_value, slow_value in zip(reversed(recent["close"].tolist()), reversed(recent["ema_slow"].tolist())):
        if float(close_value) > float(slow_value):
            if below_slow_streak == 0:
                above_slow_streak += 1
            else:
                break
        elif float(close_value) < float(slow_value):
            if above_slow_streak == 0:
                below_slow_streak += 1
            else:
                break
        else:
            break

    history = _history_from_frame(symbol, timeframe, df, candle_limit=candles)
    regime, regime_reason, _ = classify_recent_market_regime(history)

    score = 0.0
    rationale: list[str] = []

    if ema_fast > ema_slow:
        score += 1.6
        rationale.append(f"Fast EMA is above slow EMA on {timeframe}, so local structure leans up.")
    else:
        score -= 1.6
        rationale.append(f"Fast EMA is below slow EMA on {timeframe}, so local structure leans down.")

    if momentum_pct >= 1.5:
        score += 1.2
        rationale.append(f"Recent momentum is positive at {momentum_pct:.2f}% across the analysis window.")
    elif momentum_pct <= -1.5:
        score -= 1.2
        rationale.append(f"Recent momentum is negative at {momentum_pct:.2f}% across the analysis window.")
    else:
        rationale.append(f"Recent momentum is muted at {momentum_pct:.2f}%, so edge is weaker.")

    if rsi >= 58:
        score += 1.0
        rationale.append(f"RSI is firm at {rsi:.1f}, which supports bullish continuation.")
    elif rsi <= 42:
        score -= 1.0
        rationale.append(f"RSI is weak at {rsi:.1f}, which supports bearish pressure.")
    else:
        rationale.append(f"RSI sits near the middle at {rsi:.1f}, so momentum confirmation is limited.")

    if above_slow_ratio >= 65:
        score += 0.8
        rationale.append(f"Price held above the slow EMA on {above_slow_ratio:.0f}% of recent candles.")
    elif above_slow_ratio <= 35:
        score -= 0.8
        rationale.append(f"Price stayed below the slow EMA on most recent candles ({100 - above_slow_ratio:.0f}% below).")

    if bullish_candle_ratio >= 58:
        score += 0.5
        rationale.append(f"Bullish candles dominate the recent window ({bullish_candle_ratio:.0f}%).")
    elif bullish_candle_ratio <= 42:
        score -= 0.5
        rationale.append(f"Bearish candles dominate the recent window ({100 - bullish_candle_ratio:.0f}% bearish).")

    if above_slow_streak >= 4:
        score += 0.6
        rationale.append(f"Price has held above the slow EMA for {above_slow_streak} straight closes, so trend persistence is improving.")
    elif below_slow_streak >= 4:
        score -= 0.6
        rationale.append(f"Price has stayed below the slow EMA for {below_slow_streak} straight closes, so downside persistence is real.")

    if ema_spread_delta_pct >= 0.05:
        score += 0.4 if ema_fast > ema_slow else -0.4
        rationale.append(f"EMA spread is widening by {ema_spread_delta_pct:.2f}% of price, which supports persistence.")
    elif ema_spread_delta_pct <= -0.05:
        score -= 0.3 if ema_fast > ema_slow else 0.3
        rationale.append(f"EMA spread is compressing by {abs(ema_spread_delta_pct):.2f}% of price, so trend conviction is fading.")

    if regime == "trend":
        score += 0.9 if score >= 0 else -0.2
        rationale.append(f"Regime classifier says trend: {regime_reason}")
    elif regime == "volatile":
        score -= 0.7 if score >= 0 else 0.2
        rationale.append(f"Regime classifier says volatile: {regime_reason}")
    elif regime == "range":
        score *= 0.75
        rationale.append(f"Regime classifier says range: {regime_reason}")
    elif regime == "slow_liquid":
        score *= 0.85
        rationale.append(f"Regime classifier says slow_liquid: {regime_reason}")

    if realized_vol >= 4.0:
        score *= 0.85
        rationale.append(f"Realized volatility is elevated at {realized_vol:.2f}%, so confidence gets clipped.")

    bias = _bias_from_score(score)
    confidence = _confidence_from_score(score)

    bullish_confirmation = (
        f"Close stays above the slow EMA ({ema_slow:.4f}) on {timeframe}.",
        f"RSI pushes and holds above 55 (current {rsi:.1f}).",
        f"Price breaks or holds above the recent window high near {float(recent['high'].max()):.4f}.",
    )
    bullish_invalidation = (
        f"Fast EMA loses the slow EMA ({ema_fast:.4f} vs {ema_slow:.4f}) on {timeframe}.",
        f"RSI rolls under 45 from here (current {rsi:.1f}).",
        f"Price loses the recent window low near {float(recent['low'].min()):.4f}.",
    )
    bearish_confirmation = (
        f"Close stays below the slow EMA ({ema_slow:.4f}) on {timeframe}.",
        f"RSI stays under 45 (current {rsi:.1f}).",
        f"Price breaks or holds below the recent window low near {float(recent['low'].min()):.4f}.",
    )
    bearish_invalidation = (
        f"Fast EMA reclaims the slow EMA ({ema_fast:.4f} vs {ema_slow:.4f}) on {timeframe}.",
        f"RSI pushes back above 55 from here (current {rsi:.1f}).",
        f"Price reclaims the recent window high near {float(recent['high'].max()):.4f}.",
    )

    return OutlookHorizon(
        label=label,
        timeframe=timeframe,
        candles=candles,
        bias=bias,
        confidence=confidence,
        score=round(score, 2),
        regime=regime,
        rationale=tuple(rationale),
        bullish_confirmation=bullish_confirmation,
        bullish_invalidation=bullish_invalidation,
        bearish_confirmation=bearish_confirmation,
        bearish_invalidation=bearish_invalidation,
        metrics={
            "last_close": round(last_close, 6),
            "ema_fast": round(ema_fast, 6),
            "ema_slow": round(ema_slow, 6),
            "rsi": round(rsi, 2),
            "momentum_pct": round(momentum_pct, 2),
            "realized_volatility_pct": round(realized_vol, 2),
            "above_slow_ratio_pct": round(above_slow_ratio, 2),
            "bullish_candle_ratio_pct": round(bullish_candle_ratio, 2),
            "ema_spread_pct": round(ema_spread_pct, 4),
            "ema_spread_delta_pct": round(ema_spread_delta_pct, 4),
            "above_slow_streak": float(above_slow_streak),
            "below_slow_streak": float(below_slow_streak),
            "distance_from_high_pct": round(distance_from_high_pct, 2),
            "distance_from_low_pct": round(distance_from_low_pct, 2),
        },
    )


def generate_outlook_report(config: Config, *, symbol: str | None = None) -> MarketOutlookReport:
    if symbol:
        config.symbol = symbol
    exchange = create_exchange(config)
    horizons = tuple(_build_horizon(exchange, config.symbol, timeframe, label, candles) for label, timeframe, candles in _OUTLOOK_WINDOWS)
    total_weight = sum(_HORIZON_WEIGHTS.get(item.label, 1.0) for item in horizons) or 1.0
    summary_score = sum(item.score * _HORIZON_WEIGHTS.get(item.label, 1.0) for item in horizons) / total_weight if horizons else 0.0
    summary_bias = _bias_from_score(summary_score)
    summary_confidence = _adjusted_confidence_from_horizons(summary_score, horizons)
    report = MarketOutlookReport(
        symbol=config.symbol,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        horizons=horizons,
        summary_bias=summary_bias,
        summary_confidence=summary_confidence,
        summary_score=round(summary_score, 2),
        summary_rationale=_consensus_rationale(horizons, summary_score),
        notes=(
            "This is an explainable directional outlook, not a guaranteed forecast.",
            "Bias is inferred from recent trend structure, RSI, momentum, regime classification, and weighted multi-timeframe consensus.",
            "Each run is appended to data/market/binance_outlook_history.jsonl for later calibration and hit-rate review.",
            "Use it as supervision/context, not as permission to ape into size.",
        ),
    )
    _append_outlook_history(report, market_data_path("binance_outlook_history.jsonl"))
    return report


def write_outlook_report(report: MarketOutlookReport, path: Path) -> tuple[Path, Path]:
    text_path = ensure_parent(path)
    json_path = ensure_parent(path.with_suffix(".json"))
    text_path.write_text(report.to_text(), encoding="utf-8")
    json_path.write_text(report.to_json(), encoding="utf-8")
    report.report_path = str(text_path)
    report.report_json_path = str(json_path)
    return text_path, json_path


def default_outlook_report_path(symbol: str) -> Path:
    normalized = symbol.replace("/", "_").replace(":", "_").lower()
    return market_data_path(f"binance_outlook_{normalized}.txt")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a lightweight Binance outlook report.")
    parser.add_argument("--symbol", default=os.getenv("SYMBOL", "ETH/USDT"), help="Trading pair, e.g. SOL/USDT")
    parser.add_argument("--output", default="", help="Optional report output path (.txt). JSON is written beside it.")
    parser.add_argument("--timeframe", default="", help="Optional base timeframe override for config consistency.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = Config()
    config.validate()
    if args.timeframe:
        config.timeframe = args.timeframe
    report = generate_outlook_report(config, symbol=args.symbol)
    output_path = Path(args.output) if args.output else default_outlook_report_path(args.symbol)
    text_path, json_path = write_outlook_report(report, output_path)
    print(report.to_text(), end="\n\n")
    print(f"Saved outlook report: {text_path}")
    print(f"Saved outlook JSON: {json_path}")


if __name__ == "__main__":
    main()
