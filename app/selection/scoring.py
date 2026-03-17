from __future__ import annotations

from dataclasses import dataclass, field
import math

from .models import MarketCandidate, ScoreComponent, ScorePenalty


@dataclass(slots=True)
class ScoringConfig:
    liquidity_weight: float = 0.32
    spread_weight: float = 0.20
    activity_weight: float = 0.14
    movement_weight: float = 0.10
    depth_weight: float = 0.12
    accessibility_weight: float = 0.07
    stability_weight: float = 0.05
    volume_target_quote_24h: float = 50_000_000.0
    trade_count_target_24h: float = 20_000.0
    spread_cap_bps: float = 100.0
    movement_target_pct: float = 5.0
    depth_target_base_24h: float = 500_000.0
    ideal_last_price_min: float = 0.05
    ideal_last_price_max: float = 500.0
    soft_penalty_spread_bps: float = 30.0
    soft_penalty_low_trade_count: float = 500.0
    soft_penalty_extreme_move_pct: float = 15.0


@dataclass(slots=True)
class ScoreBreakdown:
    liquidity: float = 0.0
    spread: float = 0.0
    activity: float = 0.0
    movement: float = 0.0
    depth: float = 0.0
    accessibility: float = 0.0
    stability: float = 0.0
    penalties: float = 0.0
    total: float = 0.0
    components: tuple[ScoreComponent, ...] = field(default_factory=tuple)
    penalty_items: tuple[ScorePenalty, ...] = field(default_factory=tuple)
    explanation: tuple[str, ...] = field(default_factory=tuple)


@dataclass(slots=True)
class _VenueScoreProfile:
    volume_target_quote_24h: float | None = None
    trade_count_target_24h: float | None = None
    spread_cap_bps: float | None = None
    movement_target_pct: float | None = None
    depth_target_base_24h: float | None = None
    liquidity_weight: float | None = None
    spread_weight: float | None = None
    activity_weight: float | None = None
    movement_weight: float | None = None
    depth_weight: float | None = None
    accessibility_weight: float | None = None
    stability_weight: float | None = None
    soft_penalty_spread_bps: float | None = None
    soft_penalty_low_trade_count: float | None = None
    soft_penalty_extreme_move_pct: float | None = None


def _log_score(value: float | None, target: float) -> float:
    if value is None or value <= 0 or target <= 0:
        return 0.0
    score = math.log1p(value) / math.log1p(target)
    return max(0.0, min(1.0, score)) * 100.0


def _clamp_pct(value: float) -> float:
    return max(0.0, min(100.0, value))


def _detail(label: str, value: float | None, *, suffix: str = "", fallback: str = "missing") -> str:
    if value is None:
        return f"{label}={fallback}"
    return f"{label}={value:.4f}{suffix}"


def _apply_profile(config: ScoringConfig, profile: _VenueScoreProfile) -> ScoringConfig:
    return ScoringConfig(
        liquidity_weight=profile.liquidity_weight if profile.liquidity_weight is not None else config.liquidity_weight,
        spread_weight=profile.spread_weight if profile.spread_weight is not None else config.spread_weight,
        activity_weight=profile.activity_weight if profile.activity_weight is not None else config.activity_weight,
        movement_weight=profile.movement_weight if profile.movement_weight is not None else config.movement_weight,
        depth_weight=profile.depth_weight if profile.depth_weight is not None else config.depth_weight,
        accessibility_weight=profile.accessibility_weight if profile.accessibility_weight is not None else config.accessibility_weight,
        stability_weight=profile.stability_weight if profile.stability_weight is not None else config.stability_weight,
        volume_target_quote_24h=profile.volume_target_quote_24h if profile.volume_target_quote_24h is not None else config.volume_target_quote_24h,
        trade_count_target_24h=profile.trade_count_target_24h if profile.trade_count_target_24h is not None else config.trade_count_target_24h,
        spread_cap_bps=profile.spread_cap_bps if profile.spread_cap_bps is not None else config.spread_cap_bps,
        movement_target_pct=profile.movement_target_pct if profile.movement_target_pct is not None else config.movement_target_pct,
        depth_target_base_24h=profile.depth_target_base_24h if profile.depth_target_base_24h is not None else config.depth_target_base_24h,
        ideal_last_price_min=config.ideal_last_price_min,
        ideal_last_price_max=config.ideal_last_price_max,
        soft_penalty_spread_bps=profile.soft_penalty_spread_bps if profile.soft_penalty_spread_bps is not None else config.soft_penalty_spread_bps,
        soft_penalty_low_trade_count=profile.soft_penalty_low_trade_count if profile.soft_penalty_low_trade_count is not None else config.soft_penalty_low_trade_count,
        soft_penalty_extreme_move_pct=profile.soft_penalty_extreme_move_pct if profile.soft_penalty_extreme_move_pct is not None else config.soft_penalty_extreme_move_pct,
    )


def _config_for_candidate(candidate: MarketCandidate, config: ScoringConfig) -> ScoringConfig:
    venue = candidate.venue.strip().lower()
    if venue == "polymarket":
        return _apply_profile(
            config,
            _VenueScoreProfile(
                volume_target_quote_24h=min(config.volume_target_quote_24h, 250_000.0),
                trade_count_target_24h=min(config.trade_count_target_24h, 250.0),
                spread_cap_bps=max(config.spread_cap_bps, 800.0),
                movement_target_pct=max(config.movement_target_pct, 10.0),
                depth_target_base_24h=min(config.depth_target_base_24h, 25_000.0),
                liquidity_weight=0.24,
                spread_weight=0.24,
                activity_weight=0.10,
                movement_weight=0.10,
                depth_weight=0.22,
                accessibility_weight=0.05,
                stability_weight=0.05,
                soft_penalty_spread_bps=max(config.soft_penalty_spread_bps, 120.0),
                soft_penalty_low_trade_count=min(config.soft_penalty_low_trade_count, 15.0),
                soft_penalty_extreme_move_pct=max(config.soft_penalty_extreme_move_pct, 25.0),
            ),
        )
    if venue == "binance":
        return _apply_profile(
            config,
            _VenueScoreProfile(
                volume_target_quote_24h=max(config.volume_target_quote_24h, 50_000_000.0),
                trade_count_target_24h=max(config.trade_count_target_24h, 20_000.0),
                spread_cap_bps=min(config.spread_cap_bps, 100.0),
                movement_target_pct=min(config.movement_target_pct, 5.0),
                depth_target_base_24h=max(config.depth_target_base_24h, 500_000.0),
                liquidity_weight=0.34,
                spread_weight=0.20,
                activity_weight=0.16,
                movement_weight=0.10,
                depth_weight=0.10,
                accessibility_weight=0.06,
                stability_weight=0.04,
                soft_penalty_spread_bps=min(config.soft_penalty_spread_bps, 25.0),
                soft_penalty_low_trade_count=max(config.soft_penalty_low_trade_count, 500.0),
                soft_penalty_extreme_move_pct=min(config.soft_penalty_extreme_move_pct, 12.0),
            ),
        )
    return config


def score_candidate(candidate: MarketCandidate, config: ScoringConfig) -> ScoreBreakdown:
    tuned = _config_for_candidate(candidate, config)
    metrics = candidate.metrics
    constraints = candidate.constraints

    liquidity = _log_score(metrics.volume_quote_24h, tuned.volume_target_quote_24h)
    if metrics.spread_bps is None or tuned.spread_cap_bps <= 0:
        spread = 0.0
    else:
        spread = _clamp_pct((1.0 - (metrics.spread_bps / tuned.spread_cap_bps)) * 100.0)

    activity = _log_score(
        float(metrics.trade_count_24h) if metrics.trade_count_24h is not None else None,
        tuned.trade_count_target_24h,
    )

    movement_measure = metrics.range_pct_24h
    if movement_measure is None:
        movement_measure = abs(metrics.price_change_pct_24h or 0.0)
    if movement_measure <= 0 or tuned.movement_target_pct <= 0:
        movement = 0.0
    else:
        movement = _clamp_pct((movement_measure / tuned.movement_target_pct) * 100.0)

    depth = _log_score(metrics.volume_base_24h, tuned.depth_target_base_24h)

    accessibility = 100.0
    if metrics.last_price is None or metrics.last_price <= 0:
        accessibility = 0.0
    elif metrics.last_price < tuned.ideal_last_price_min:
        accessibility = _clamp_pct((metrics.last_price / tuned.ideal_last_price_min) * 100.0)
    elif metrics.last_price > tuned.ideal_last_price_max:
        accessibility = _clamp_pct((tuned.ideal_last_price_max / metrics.last_price) * 100.0)
    if constraints.min_notional is not None and constraints.min_notional > 0:
        accessibility = min(accessibility, _clamp_pct((5.0 / constraints.min_notional) * 100.0))

    stability = 100.0
    if metrics.range_pct_24h is not None and tuned.movement_target_pct > 0:
        stability = _clamp_pct((1.0 - max(0.0, metrics.range_pct_24h - tuned.movement_target_pct) / (tuned.movement_target_pct * 2)) * 100.0)

    components = (
        ScoreComponent("liquidity", metrics.volume_quote_24h, liquidity, tuned.liquidity_weight, liquidity * tuned.liquidity_weight, _detail("quote_volume_24h", metrics.volume_quote_24h)),
        ScoreComponent("spread", metrics.spread_bps, spread, tuned.spread_weight, spread * tuned.spread_weight, _detail("spread_bps", metrics.spread_bps, suffix=" bps")),
        ScoreComponent("activity", float(metrics.trade_count_24h) if metrics.trade_count_24h is not None else None, activity, tuned.activity_weight, activity * tuned.activity_weight, _detail("trade_count_24h", float(metrics.trade_count_24h) if metrics.trade_count_24h is not None else None)),
        ScoreComponent("movement", movement_measure, movement, tuned.movement_weight, movement * tuned.movement_weight, _detail("movement_pct", movement_measure, suffix="%")),
        ScoreComponent("depth", metrics.volume_base_24h, depth, tuned.depth_weight, depth * tuned.depth_weight, _detail("volume_base_24h", metrics.volume_base_24h)),
        ScoreComponent("accessibility", constraints.min_notional, accessibility, tuned.accessibility_weight, accessibility * tuned.accessibility_weight, _detail("min_notional", constraints.min_notional)),
        ScoreComponent("stability", metrics.range_pct_24h, stability, tuned.stability_weight, stability * tuned.stability_weight, _detail("range_pct_24h", metrics.range_pct_24h, suffix="%")),
    )

    penalty_items: list[ScorePenalty] = []
    if metrics.spread_bps is not None and metrics.spread_bps > tuned.soft_penalty_spread_bps:
        penalty_items.append(
            ScorePenalty(
                "wide_spread",
                points=min(15.0, (metrics.spread_bps - tuned.soft_penalty_spread_bps) / max(1.0, tuned.soft_penalty_spread_bps) * 10.0),
                reason=f"spread_bps={metrics.spread_bps:.2f} above soft threshold {tuned.soft_penalty_spread_bps:.2f}",
            )
        )
    if metrics.trade_count_24h is not None and metrics.trade_count_24h < tuned.soft_penalty_low_trade_count:
        penalty_items.append(
            ScorePenalty(
                "thin_activity",
                points=min(12.0, (1.0 - (metrics.trade_count_24h / max(1.0, tuned.soft_penalty_low_trade_count))) * 12.0),
                reason=f"trade_count_24h={metrics.trade_count_24h} below soft threshold {tuned.soft_penalty_low_trade_count:.0f}",
            )
        )
    if movement_measure is not None and movement_measure > tuned.soft_penalty_extreme_move_pct:
        penalty_items.append(
            ScorePenalty(
                "overheated_move",
                points=min(10.0, (movement_measure - tuned.soft_penalty_extreme_move_pct) / max(1.0, tuned.soft_penalty_extreme_move_pct) * 8.0),
                reason=f"movement_pct={movement_measure:.2f} above soft threshold {tuned.soft_penalty_extreme_move_pct:.2f}",
            )
        )

    weight_total = sum(component.weight for component in components)
    weighted_total = sum(component.contribution for component in components) / weight_total if weight_total > 0 else 0.0
    penalties = sum(item.points for item in penalty_items)
    total = _clamp_pct(weighted_total - penalties)

    sorted_components = sorted(components, key=lambda item: item.contribution, reverse=True)
    explanation = [
        f"{candidate.symbol} scored {total:.2f} on {candidate.venue}.",
        f"Top supports: {', '.join(f'{item.name}={item.score:.1f}' for item in sorted_components[:3])}.",
    ]
    if penalty_items:
        explanation.append("Penalties: " + "; ".join(f"{item.name} -{item.points:.1f} ({item.reason})" for item in penalty_items))
    else:
        explanation.append("Penalties: none.")

    return ScoreBreakdown(
        liquidity=liquidity,
        spread=spread,
        activity=activity,
        movement=movement,
        depth=depth,
        accessibility=accessibility,
        stability=stability,
        penalties=penalties,
        total=total,
        components=components,
        penalty_items=tuple(penalty_items),
        explanation=tuple(explanation),
    )
