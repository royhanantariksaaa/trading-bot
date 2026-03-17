from __future__ import annotations

from dataclasses import dataclass

from .models import MarketCandidate


@dataclass(slots=True)
class SelectionFilters:
    allowed_quotes: tuple[str, ...] = ("USDT", "USDC")
    require_active: bool = True
    require_tradable: bool = True
    require_spot: bool = True
    min_last_price: float = 0.0001
    min_quote_volume_24h: float = 1_000_000.0
    min_trade_count_24h: int = 100
    max_spread_bps: float = 100.0
    max_entry_notional: float = 5.0
    excluded_base_suffixes: tuple[str, ...] = ("UP", "DOWN", "BULL", "BEAR", "3L", "3S")


@dataclass(slots=True)
class FilterDecision:
    name: str
    passed: bool
    reason: str = ""


def _upper_set(values: tuple[str, ...]) -> set[str]:
    return {value.upper() for value in values if value}


def _estimated_entry_notional(candidate: MarketCandidate) -> float | None:
    last_price = candidate.metrics.last_price
    if last_price is None or last_price <= 0:
        return None

    estimates: list[float] = []
    constraints = candidate.constraints
    if constraints.min_notional is not None:
        estimates.append(float(constraints.min_notional))
    if constraints.min_qty is not None:
        estimates.append(float(constraints.min_qty) * last_price)
    if constraints.qty_step is not None:
        estimates.append(float(constraints.qty_step) * last_price)
    if not estimates:
        return None
    return max(estimates)


def evaluate_candidate(candidate: MarketCandidate, filters: SelectionFilters) -> tuple[FilterDecision, ...]:
    decisions: list[FilterDecision] = []
    quote_asset = candidate.quote_asset.upper()
    base_asset = candidate.base_asset.upper()
    market_type = candidate.market_type.lower()
    metrics = candidate.metrics
    constraints = candidate.constraints

    if filters.require_spot:
        decisions.append(
            FilterDecision(
                name="market_type",
                passed=market_type == "spot",
                reason="" if market_type == "spot" else f"market_type={candidate.market_type}",
            )
        )

    if filters.require_active:
        decisions.append(
            FilterDecision(
                name="active",
                passed=bool(candidate.active),
                reason="" if candidate.active else "market inactive",
            )
        )

    if filters.require_tradable:
        decisions.append(
            FilterDecision(
                name="tradable",
                passed=bool(candidate.tradable),
                reason="" if candidate.tradable else "market not tradable",
            )
        )

    allowed_quotes = _upper_set(filters.allowed_quotes)
    if allowed_quotes:
        decisions.append(
            FilterDecision(
                name="quote_asset",
                passed=quote_asset in allowed_quotes,
                reason="" if quote_asset in allowed_quotes else f"quote_asset={candidate.quote_asset}",
            )
        )

    if filters.excluded_base_suffixes:
        excluded = any(base_asset.endswith(suffix.upper()) for suffix in filters.excluded_base_suffixes)
        decisions.append(
            FilterDecision(
                name="base_asset_suffix",
                passed=not excluded,
                reason="" if not excluded else f"base_asset={candidate.base_asset}",
            )
        )

    if metrics.last_price is None or metrics.last_price < filters.min_last_price:
        decisions.append(
            FilterDecision(
                name="last_price",
                passed=False,
                reason="missing last price" if metrics.last_price is None else f"last_price={metrics.last_price}",
            )
        )
    else:
        decisions.append(FilterDecision(name="last_price", passed=True))

    if metrics.volume_quote_24h is None or metrics.volume_quote_24h < filters.min_quote_volume_24h:
        decisions.append(
            FilterDecision(
                name="quote_volume_24h",
                passed=False,
                reason="missing quote volume"
                if metrics.volume_quote_24h is None
                else f"quote_volume_24h={metrics.volume_quote_24h:.4f}",
            )
        )
    else:
        decisions.append(FilterDecision(name="quote_volume_24h", passed=True))

    if metrics.trade_count_24h is None or metrics.trade_count_24h < filters.min_trade_count_24h:
        decisions.append(
            FilterDecision(
                name="trade_count_24h",
                passed=False,
                reason="missing trade count"
                if metrics.trade_count_24h is None
                else f"trade_count_24h={metrics.trade_count_24h}",
            )
        )
    else:
        decisions.append(FilterDecision(name="trade_count_24h", passed=True))

    if metrics.spread_bps is None or metrics.spread_bps > filters.max_spread_bps:
        decisions.append(
            FilterDecision(
                name="spread_bps",
                passed=False,
                reason="missing spread"
                if metrics.spread_bps is None
                else f"spread_bps={metrics.spread_bps:.4f}",
            )
        )
    else:
        decisions.append(FilterDecision(name="spread_bps", passed=True))

    estimated_entry_notional = _estimated_entry_notional(candidate)
    if estimated_entry_notional is None:
        decisions.append(
            FilterDecision(
                name="entry_notional",
                passed=False,
                reason="missing price or trade size metadata",
            )
        )
    else:
        decisions.append(
            FilterDecision(
                name="entry_notional",
                passed=estimated_entry_notional <= filters.max_entry_notional,
                reason=""
                if estimated_entry_notional <= filters.max_entry_notional
                else f"estimated_entry_notional={estimated_entry_notional:.4f}",
            )
        )

    if constraints.max_notional is not None:
        decisions.append(
            FilterDecision(
                name="max_notional",
                passed=constraints.max_notional >= filters.max_entry_notional,
                reason=""
                if constraints.max_notional >= filters.max_entry_notional
                else f"max_notional={constraints.max_notional:.4f}",
            )
        )

    return tuple(decisions)


def candidate_passes(decisions: tuple[FilterDecision, ...]) -> bool:
    return all(decision.passed for decision in decisions)


def failed_filter_reasons(decisions: tuple[FilterDecision, ...]) -> str:
    failures = [f"{decision.name}:{decision.reason}" for decision in decisions if not decision.passed]
    return " | ".join(failures)
