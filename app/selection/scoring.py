from __future__ import annotations

from dataclasses import dataclass
import math

from .models import MarketCandidate


@dataclass(slots=True)
class ScoringConfig:
    liquidity_weight: float = 0.45
    spread_weight: float = 0.30
    activity_weight: float = 0.15
    movement_weight: float = 0.10
    volume_target_quote_24h: float = 50_000_000.0
    trade_count_target_24h: float = 20_000.0
    spread_cap_bps: float = 100.0
    movement_target_pct: float = 5.0


@dataclass(slots=True)
class ScoreBreakdown:
    liquidity: float = 0.0
    spread: float = 0.0
    activity: float = 0.0
    movement: float = 0.0
    total: float = 0.0


def _log_score(value: float | None, target: float) -> float:
    if value is None or value <= 0 or target <= 0:
        return 0.0
    score = math.log1p(value) / math.log1p(target)
    return max(0.0, min(1.0, score)) * 100.0


def score_candidate(candidate: MarketCandidate, config: ScoringConfig) -> ScoreBreakdown:
    metrics = candidate.metrics

    liquidity = _log_score(metrics.volume_quote_24h, config.volume_target_quote_24h)
    if metrics.spread_bps is None or config.spread_cap_bps <= 0:
        spread = 0.0
    else:
        spread = max(0.0, 1.0 - (metrics.spread_bps / config.spread_cap_bps)) * 100.0

    activity = _log_score(
        float(metrics.trade_count_24h) if metrics.trade_count_24h is not None else None,
        config.trade_count_target_24h,
    )

    movement_measure = metrics.range_pct_24h
    if movement_measure is None:
        movement_measure = abs(metrics.price_change_pct_24h or 0.0)
    if movement_measure <= 0 or config.movement_target_pct <= 0:
        movement = 0.0
    else:
        movement = max(0.0, min(1.0, movement_measure / config.movement_target_pct)) * 100.0

    weight_total = config.liquidity_weight + config.spread_weight + config.activity_weight + config.movement_weight
    if weight_total <= 0:
        total = 0.0
    else:
        total = (
            liquidity * config.liquidity_weight
            + spread * config.spread_weight
            + activity * config.activity_weight
            + movement * config.movement_weight
        ) / weight_total

    return ScoreBreakdown(
        liquidity=liquidity,
        spread=spread,
        activity=activity,
        movement=movement,
        total=total,
    )
