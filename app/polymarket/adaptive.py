from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import math

from .models import BookSnapshot

_MIN_BID_PRICE = 0.01
_MAX_ASK_PRICE = 0.99
_MIN_SPREAD = 0.01
_MAX_SPREAD = 0.12
_MIN_EDGE = 0.0
_MAX_EDGE = 0.05
_MIN_QUOTE_MULTIPLIER = 0.25
_MAX_QUOTE_MULTIPLIER = 1.5
_MIN_INVENTORY_MULTIPLIER = 0.35
_MAX_INVENTORY_MULTIPLIER = 1.25
_MIN_SKEW_MULTIPLIER = 0.5
_MAX_SKEW_MULTIPLIER = 1.75

_WIDE_SPREAD_PCT = 0.08
_TIGHT_SPREAD_PCT = 0.03
_ONE_SIDED_DEPTH_RATIO = 1.8
_HIGH_IMBALANCE = 0.35
_STRONG_DRIFT = 0.03
_NEAR_RESOLUTION_HOURS = 24.0


@dataclass(slots=True)
class AdaptivePolicySelection:
    name: str
    description: str
    base_spread_multiplier: float
    edge_offset_multiplier: float
    quote_size_multiplier: float
    max_inventory_multiplier: float
    max_position_notional_multiplier: float
    inventory_skew_multiplier: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AdaptiveBookSnapshot:
    token_id: str
    scanned_at: str
    midpoint: float
    best_bid: float
    best_ask: float
    spread: float
    spread_pct: float
    tick_size: float
    top_bid_size: float
    top_ask_size: float
    depth_bid_3: float
    depth_ask_3: float
    depth_total_3: float
    imbalance_3: float
    weighted_bid_price_3: float | None
    weighted_ask_price_3: float | None
    weighted_spread_3: float | None
    weighted_spread_pct_3: float | None
    midpoint_drift_pct: float | None
    midpoint_distance_to_even_pct: float | None
    liquidity_quality_score: float | None
    time_to_resolution_hours: float | None = None

    def summary(self) -> str:
        return (
            f"mid={self.midpoint:.4f} spread={self.spread:.4f} ({self.spread_pct * 100:.2f}%) "
            f"imbalance={self.imbalance_3:.2f} depth3={self.depth_total_3:.2f} "
            f"drift={_fmt_pct(self.midpoint_drift_pct)}"
        )

    def evidence_lines(self) -> tuple[str, ...]:
        return (
            f"midpoint={self.midpoint:.4f}",
            f"best_bid={self.best_bid:.4f}",
            f"best_ask={self.best_ask:.4f}",
            f"spread={self.spread:.4f}",
            f"spread_pct={self.spread_pct * 100:.2f}%",
            f"tick_size={self.tick_size:.4f}",
            f"top_bid_size={self.top_bid_size:.2f}",
            f"top_ask_size={self.top_ask_size:.2f}",
            f"depth_bid_3={self.depth_bid_3:.2f}",
            f"depth_ask_3={self.depth_ask_3:.2f}",
            f"depth_total_3={self.depth_total_3:.2f}",
            f"imbalance_3={self.imbalance_3:.2f}",
            f"weighted_bid_price_3={_fmt_float(self.weighted_bid_price_3, 4)}",
            f"weighted_ask_price_3={_fmt_float(self.weighted_ask_price_3, 4)}",
            f"weighted_spread_3={_fmt_float(self.weighted_spread_3, 4)}",
            f"weighted_spread_pct_3={_fmt_pct(self.weighted_spread_pct_3)}",
            f"midpoint_drift_pct={_fmt_pct(self.midpoint_drift_pct)}",
            f"midpoint_distance_to_even_pct={_fmt_pct(self.midpoint_distance_to_even_pct)}",
            f"liquidity_quality_score={_fmt_float(self.liquidity_quality_score, 2)}",
            f"time_to_resolution_hours={_fmt_float(self.time_to_resolution_hours, 2)}",
        )


@dataclass(slots=True)
class AdaptiveOverrides:
    policy_name: str
    policy_description: str
    base_spread: float
    edge_offset: float
    quote_size: float
    max_inventory: float
    max_position_notional: float
    inventory_skew_per_share: float

    def as_reason_lines(self) -> tuple[str, ...]:
        return (
            f"base_spread={self.base_spread:.4f}",
            f"edge_offset={self.edge_offset:.4f}",
            f"quote_size={self.quote_size:.2f}",
            f"max_inventory={self.max_inventory:.2f}",
            f"max_position_notional={self.max_position_notional:.2f}",
            f"inventory_skew_per_share={self.inventory_skew_per_share:.5f}",
        )


@dataclass(slots=True)
class AdaptiveDecisionReport:
    venue: str
    token_id: str
    scanned_at: str
    adaptive_mode: str
    paper_mode: bool
    base_settings: dict[str, float]
    book: AdaptiveBookSnapshot
    policy_name: str
    policy_reason: str
    selected_policy: AdaptivePolicySelection
    overrides: AdaptiveOverrides
    applied: bool
    fallback_reason: str = ""
    report_path: Path | None = None
    report_json_path: Path | None = None

    def summary(self) -> str:
        return f"venue={self.venue} token_id={self.token_id} policy={self.policy_name} applied={'yes' if self.applied else 'no'}"

    def why_lines(self) -> tuple[str, ...]:
        lines = [self.summary()]
        lines.append(f"Policy reason: {self.policy_reason}")
        lines.append(f"Book snapshot: {self.book.summary()}")
        lines.extend(f"Evidence: {line}" for line in self.book.evidence_lines())
        lines.append("Base settings")
        for key, value in self.base_settings.items():
            if key in {"quote_size", "max_inventory", "max_position_notional"}:
                lines.append(f"- {key}={value:.2f}")
            elif key == "inventory_skew_per_share":
                lines.append(f"- {key}={value:.5f}")
            else:
                lines.append(f"- {key}={value:.4f}")
        lines.append("Adaptive overrides")
        lines.append(f"- name={self.overrides.policy_name}")
        lines.append(f"- description={self.overrides.policy_description}")
        lines.extend(f"- {line}" for line in self.overrides.as_reason_lines())
        if self.fallback_reason:
            lines.append(f"Fallback: {self.fallback_reason}")
        return tuple(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "token_id": self.token_id,
            "scanned_at": self.scanned_at,
            "adaptive_mode": self.adaptive_mode,
            "paper_mode": self.paper_mode,
            "base_settings": self.base_settings,
            "book": asdict(self.book),
            "policy_name": self.policy_name,
            "policy_reason": self.policy_reason,
            "selected_policy": self.selected_policy.to_dict(),
            "overrides": asdict(self.overrides),
            "applied": self.applied,
            "fallback_reason": self.fallback_reason,
            "report_path": str(self.report_path) if self.report_path else "",
            "report_json_path": str(self.report_json_path) if self.report_json_path else "",
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


_POLICY_PRESETS: dict[str, AdaptivePolicySelection] = {
    "tight_balanced": AdaptivePolicySelection(
        name="tight_balanced",
        description="Tighter, more neutral quoting when the book is dense and spread-efficient around fair value.",
        base_spread_multiplier=0.85,
        edge_offset_multiplier=0.80,
        quote_size_multiplier=1.15,
        max_inventory_multiplier=1.00,
        max_position_notional_multiplier=1.00,
        inventory_skew_multiplier=0.95,
    ),
    "drift_follow": AdaptivePolicySelection(
        name="drift_follow",
        description="Mildly lean with the book drift while staying two-sided and capped.",
        base_spread_multiplier=0.95,
        edge_offset_multiplier=1.10,
        quote_size_multiplier=0.95,
        max_inventory_multiplier=0.85,
        max_position_notional_multiplier=0.85,
        inventory_skew_multiplier=1.25,
    ),
    "imbalanced_defensive": AdaptivePolicySelection(
        name="imbalanced_defensive",
        description="Back off size and widen quotes when one side dominates or liquidity is patchy.",
        base_spread_multiplier=1.25,
        edge_offset_multiplier=1.25,
        quote_size_multiplier=0.60,
        max_inventory_multiplier=0.70,
        max_position_notional_multiplier=0.70,
        inventory_skew_multiplier=1.45,
    ),
    "resolution_caution": AdaptivePolicySelection(
        name="resolution_caution",
        description="Near resolution or event risk: quote smaller, wider, and unwind inventory faster.",
        base_spread_multiplier=1.35,
        edge_offset_multiplier=1.30,
        quote_size_multiplier=0.45,
        max_inventory_multiplier=0.50,
        max_position_notional_multiplier=0.50,
        inventory_skew_multiplier=1.65,
    ),
}


def _fmt_float(value: float | None, precision: int = 2) -> str:
    if value is None:
        return "missing"
    return f"{value:.{precision}f}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "missing"
    return f"{value * 100:.2f}%"


def _sum_sizes(levels, count: int = 3) -> float:
    return float(sum(max(float(level.size), 0.0) for level in levels[:count]))


def _weighted_price(levels, count: int = 3) -> float | None:
    sample = levels[:count]
    total_size = sum(max(float(level.size), 0.0) for level in sample)
    if total_size <= 0:
        return None
    weighted_sum = sum(float(level.price) * max(float(level.size), 0.0) for level in sample)
    return weighted_sum / total_size


def _estimate_resolution_hours(metadata: dict[str, Any] | None) -> float | None:
    if not metadata:
        return None
    raw_value = metadata.get("endDate") or metadata.get("end_date") or metadata.get("resolution_time") or metadata.get("closedTime")
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except ValueError:
        return None
    now = datetime.now(timezone.utc)
    delta = parsed - now
    return max(delta.total_seconds() / 3600.0, 0.0)


def build_adaptive_book_snapshot(book: BookSnapshot, *, previous_mid: float | None = None, metadata: dict[str, Any] | None = None) -> AdaptiveBookSnapshot:
    midpoint = book.midpoint
    spread = book.spread
    spread_pct = (spread / midpoint) if midpoint > 0 else 0.0
    top_bid_size = float(book.bids[0].size) if book.bids else 0.0
    top_ask_size = float(book.asks[0].size) if book.asks else 0.0
    depth_bid_3 = _sum_sizes(book.bids, 3)
    depth_ask_3 = _sum_sizes(book.asks, 3)
    depth_total_3 = depth_bid_3 + depth_ask_3
    imbalance_3 = ((depth_bid_3 - depth_ask_3) / depth_total_3) if depth_total_3 > 0 else 0.0
    weighted_bid_price = _weighted_price(book.bids, 3)
    weighted_ask_price = _weighted_price(book.asks, 3)
    weighted_spread = None
    weighted_spread_pct = None
    if weighted_bid_price is not None and weighted_ask_price is not None and weighted_ask_price >= weighted_bid_price:
        weighted_spread = weighted_ask_price - weighted_bid_price
        weighted_mid = (weighted_bid_price + weighted_ask_price) / 2
        if weighted_mid > 0:
            weighted_spread_pct = weighted_spread / weighted_mid
    midpoint_drift_pct = None
    if previous_mid is not None and previous_mid > 0:
        midpoint_drift_pct = (midpoint - previous_mid) / previous_mid
    midpoint_distance_to_even_pct = ((midpoint - 0.5) / 0.5) if 0.5 > 0 else None

    liquidity_quality_score = None
    if depth_total_3 > 0:
        spread_penalty = min(spread_pct / _WIDE_SPREAD_PCT, 1.5)
        balance_penalty = abs(imbalance_3)
        depth_bonus = min(depth_total_3 / max(book.min_order_size * 6.0, 1.0), 2.0)
        liquidity_quality_score = max(0.0, min(100.0, 55.0 + depth_bonus * 20.0 - spread_penalty * 25.0 - balance_penalty * 20.0))

    return AdaptiveBookSnapshot(
        token_id=book.token_id,
        scanned_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        midpoint=midpoint,
        best_bid=book.best_bid,
        best_ask=book.best_ask,
        spread=spread,
        spread_pct=spread_pct,
        tick_size=book.tick_size,
        top_bid_size=top_bid_size,
        top_ask_size=top_ask_size,
        depth_bid_3=depth_bid_3,
        depth_ask_3=depth_ask_3,
        depth_total_3=depth_total_3,
        imbalance_3=imbalance_3,
        weighted_bid_price_3=weighted_bid_price,
        weighted_ask_price_3=weighted_ask_price,
        weighted_spread_3=weighted_spread,
        weighted_spread_pct_3=weighted_spread_pct,
        midpoint_drift_pct=midpoint_drift_pct,
        midpoint_distance_to_even_pct=midpoint_distance_to_even_pct,
        liquidity_quality_score=liquidity_quality_score,
        time_to_resolution_hours=_estimate_resolution_hours(metadata),
    )


def choose_adaptive_policy(snapshot: AdaptiveBookSnapshot) -> tuple[AdaptivePolicySelection, str]:
    if snapshot.time_to_resolution_hours is not None and snapshot.time_to_resolution_hours <= _NEAR_RESOLUTION_HOURS:
        return _POLICY_PRESETS["resolution_caution"], "Market appears close to resolution, so inventory and size are cut aggressively."

    one_sided_ratio = max(snapshot.depth_bid_3, snapshot.depth_ask_3) / max(min(snapshot.depth_bid_3, snapshot.depth_ask_3), 1e-9)
    if (
        snapshot.spread_pct >= _WIDE_SPREAD_PCT
        or abs(snapshot.imbalance_3) >= _HIGH_IMBALANCE
        or one_sided_ratio >= _ONE_SIDED_DEPTH_RATIO
        or (snapshot.liquidity_quality_score is not None and snapshot.liquidity_quality_score < 45.0)
    ):
        return _POLICY_PRESETS["imbalanced_defensive"], "Book is wide, one-sided, or low quality, so the overlay widens out and reduces inventory appetite."

    if (
        snapshot.midpoint_drift_pct is not None
        and abs(snapshot.midpoint_drift_pct) >= _STRONG_DRIFT
        and abs(snapshot.imbalance_3) >= 0.12
    ):
        return _POLICY_PRESETS["drift_follow"], "Midpoint is drifting with supporting book pressure, so the overlay keeps quoting but leans more defensively into drift."

    if (
        snapshot.spread_pct <= _TIGHT_SPREAD_PCT
        and abs(snapshot.imbalance_3) <= 0.18
        and (snapshot.liquidity_quality_score is None or snapshot.liquidity_quality_score >= 60.0)
    ):
        return _POLICY_PRESETS["tight_balanced"], "Book is tight and balanced enough to quote a bit sharper without getting silly."

    return _POLICY_PRESETS["tight_balanced"], "Defaulting to the balanced preset because the book looks tradable but not extreme."


def _clamp_by_tick(value: float, tick_size: float, lower: float, upper: float) -> float:
    if tick_size <= 0:
        return max(lower, min(value, upper))
    rounded = round(value / tick_size) * tick_size
    decimals = max(2, int(round(-math.log10(tick_size))) if tick_size < 1 else 2)
    return round(max(lower, min(rounded, upper)), decimals)


def build_adaptive_overrides(config, policy: AdaptivePolicySelection, book: BookSnapshot) -> AdaptiveOverrides:
    return AdaptiveOverrides(
        policy_name=policy.name,
        policy_description=policy.description,
        base_spread=_clamp_by_tick(config.base_spread * policy.base_spread_multiplier, book.tick_size, max(book.tick_size, _MIN_SPREAD), _MAX_SPREAD),
        edge_offset=_clamp_by_tick(config.edge_offset * policy.edge_offset_multiplier, book.tick_size, _MIN_EDGE, _MAX_EDGE),
        quote_size=max(config.min_order_size, round(config.quote_size * min(max(policy.quote_size_multiplier, _MIN_QUOTE_MULTIPLIER), _MAX_QUOTE_MULTIPLIER), 2)),
        max_inventory=round(max(config.min_order_size, config.max_inventory * min(max(policy.max_inventory_multiplier, _MIN_INVENTORY_MULTIPLIER), _MAX_INVENTORY_MULTIPLIER)), 2),
        max_position_notional=round(max(config.min_order_size * max(book.midpoint, 0.01), config.max_position_notional * min(max(policy.max_position_notional_multiplier, _MIN_INVENTORY_MULTIPLIER), _MAX_INVENTORY_MULTIPLIER)), 2),
        inventory_skew_per_share=round(config.inventory_skew_per_share * min(max(policy.inventory_skew_multiplier, _MIN_SKEW_MULTIPLIER), _MAX_SKEW_MULTIPLIER), 5),
    )


def evaluate_adaptive_policy(config, book: BookSnapshot, *, previous_mid: float | None = None, metadata: dict[str, Any] | None = None) -> AdaptiveDecisionReport:
    snapshot = build_adaptive_book_snapshot(book, previous_mid=previous_mid, metadata=metadata)
    policy, reason = choose_adaptive_policy(snapshot)
    overrides = build_adaptive_overrides(config, policy, book)
    report = AdaptiveDecisionReport(
        venue="polymarket",
        token_id=book.token_id,
        scanned_at=snapshot.scanned_at,
        adaptive_mode=config.adaptive_mode,
        paper_mode=config.paper_mode,
        base_settings={
            "base_spread": config.base_spread,
            "edge_offset": config.edge_offset,
            "quote_size": config.quote_size,
            "max_inventory": config.max_inventory,
            "max_position_notional": config.max_position_notional,
            "inventory_skew_per_share": config.inventory_skew_per_share,
        },
        book=snapshot,
        policy_name=policy.name,
        policy_reason=reason,
        selected_policy=policy,
        overrides=overrides,
        applied=True,
    )
    write_adaptive_report(report, config.adaptive_report_path)
    return report


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
        "\n".join([f"Adaptive decision report for venue={report.venue} at {report.scanned_at}", "", *report.why_lines(), ""]),
        encoding="utf-8",
    )
    report_json_path.write_text(report.to_json(), encoding="utf-8")
    return report_path, report_json_path
