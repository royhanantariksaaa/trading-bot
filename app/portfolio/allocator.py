from __future__ import annotations

from collections import defaultdict

from .models import AllocationDecision, PortfolioAllocationReport, PortfolioCandidate, PortfolioRiskCaps, PortfolioState
from .state import now_iso


def _score_weight(score: float, min_score: float) -> float:
    if score < min_score:
        return 0.0
    if min_score >= 100:
        return 1.0
    return max(0.0, min(1.0, (score - min_score) / max(1.0, 100.0 - min_score)))


def _candidate_price(candidate: PortfolioCandidate) -> float:
    if candidate.last_price is not None and candidate.last_price > 0:
        return candidate.last_price
    return 0.0


def _candidate_min_entry_notional(candidate: PortfolioCandidate, caps: PortfolioRiskCaps) -> float:
    values = [caps.min_entry_notional]
    if candidate.min_notional is not None and candidate.min_notional > 0:
        values.append(candidate.min_notional)
    if candidate.qty_step is not None and candidate.last_price is not None:
        values.append(candidate.qty_step * candidate.last_price)
    return max(values)


def allocate_portfolio(
    candidates: list[PortfolioCandidate],
    state: PortfolioState,
    caps: PortfolioRiskCaps,
    *,
    available_cash: float | None = None,
    venue: str = "",
    selection_mode: str = "scan",
    source_path: str = "",
) -> PortfolioAllocationReport:
    venue_name = venue.strip().lower()
    cash = state.cash_free if available_cash is None else available_cash
    if cash <= 0:
        cash = state.starting_balance if state.starting_balance > 0 else 0.0

    reserve_cash = max(caps.reserve_cash_usd, cash * caps.reserve_cash_pct)
    deployable_cash = max(0.0, cash - reserve_cash)
    current_positions = state.open_position_count
    current_deployed = state.deployed_notional
    total_headroom = max(0.0, min(deployable_cash, caps.max_total_notional - current_deployed))
    current_total_positions = current_positions
    current_venue_positions = state.venue_position_count(venue_name) if venue_name else 0
    current_venue_notional = state.venue_deployed_notional(venue_name) if venue_name else 0.0
    current_symbol_counts: dict[tuple[str, str], int] = defaultdict(int)
    for position in state.open_positions:
        current_symbol_counts[(position.venue.strip().lower(), position.symbol.strip().lower())] += 1

    accepted = [candidate for candidate in candidates if candidate.accepted]
    rejected = [candidate for candidate in candidates if not candidate.accepted]
    ordered = sorted(
        accepted,
        key=lambda item: (
            -(item.score or 0.0),
            item.rank or 10**9,
            item.venue,
            item.symbol,
        ),
    )
    remaining_slots = max(0, caps.max_total_positions - current_total_positions)
    remaining_new_positions = min(caps.max_new_positions_per_run, remaining_slots)
    venue_slots = max(0, caps.max_positions_per_venue - current_venue_positions) if venue_name else remaining_slots
    venue_headroom = max(0.0, caps.max_venue_notional - current_venue_notional) if venue_name else total_headroom

    decisions: list[AllocationDecision] = []
    selected_count = 0

    for candidate in rejected:
        profile_name = candidate.strategy_profile.name if candidate.strategy_profile is not None else ""
        reason = "Selector filters rejected the candidate."
        if candidate.filter_failures:
            reason = "Selector filters rejected the candidate: " + " | ".join(candidate.filter_failures)
        decisions.append(
            AllocationDecision(
                venue=candidate.venue,
                symbol=candidate.symbol,
                market_id=candidate.market_id,
                rank=candidate.rank,
                score=candidate.score,
                accepted=False,
                action="skip",
                current_notional=0.0,
                reason=reason,
                strategy_profile_name=profile_name,
                caps=("selector_rejected",),
                current_price=candidate.last_price,
            )
        )

    for candidate in ordered:
        profile_name = candidate.strategy_profile.name if candidate.strategy_profile is not None else ""
        price = _candidate_price(candidate)
        existing = state.find_position(candidate.venue, candidate.symbol)
        symbol_key = (candidate.venue.strip().lower(), candidate.symbol.strip().lower())
        current_symbol_count = current_symbol_counts.get(symbol_key, 0)

        if current_symbol_count >= caps.max_symbol_positions and existing is None:
            decisions.append(
                AllocationDecision(
                    venue=candidate.venue,
                    symbol=candidate.symbol,
                    market_id=candidate.market_id,
                    rank=candidate.rank,
                    score=candidate.score,
                    accepted=True,
                    action="skip",
                    current_price=price if price > 0 else None,
                    strategy_profile_name=profile_name,
                    reason=f"Symbol cap reached for {candidate.symbol}.",
                    caps=("symbol_cap",),
                )
            )
            continue

        if existing is not None and existing.status.upper() == "OPEN":
            if not caps.allow_scale_up_existing:
                decisions.append(
                    AllocationDecision(
                        venue=candidate.venue,
                        symbol=candidate.symbol,
                        market_id=candidate.market_id,
                        rank=candidate.rank,
                        score=candidate.score,
                        accepted=True,
                        action="hold",
                        requested_notional=existing.target_notional or existing.entry_notional,
                        target_notional=existing.target_notional or existing.entry_notional,
                        current_notional=existing.entry_notional,
                        quantity=existing.qty,
                        portfolio_share=(existing.entry_notional / state.deployed_notional) if state.deployed_notional > 0 else 0.0,
                        current_price=price if price > 0 else None,
                        strategy_profile_name=profile_name or existing.strategy_profile_name,
                        reason="Position already open in portfolio state.",
                        caps=("existing_position",),
                    )
                )
                continue
            current_symbol_count = max(0, current_symbol_count - 1)

        if candidate.score < caps.min_candidate_score:
            decisions.append(
                AllocationDecision(
                    venue=candidate.venue,
                    symbol=candidate.symbol,
                    market_id=candidate.market_id,
                    rank=candidate.rank,
                    score=candidate.score,
                    accepted=True,
                    action="skip",
                    current_price=price if price > 0 else None,
                    strategy_profile_name=profile_name,
                    reason=f"Score {candidate.score:.2f} is below the minimum allocation score {caps.min_candidate_score:.2f}.",
                    caps=("min_score",),
                )
            )
            continue

        if remaining_new_positions <= 0:
            decisions.append(
                AllocationDecision(
                    venue=candidate.venue,
                    symbol=candidate.symbol,
                    market_id=candidate.market_id,
                    rank=candidate.rank,
                    score=candidate.score,
                    accepted=True,
                    action="skip",
                    current_price=price if price > 0 else None,
                    strategy_profile_name=profile_name,
                    reason="No new position slots remain in this portfolio run.",
                    caps=("new_position_cap",),
                )
            )
            continue

        if current_total_positions >= caps.max_total_positions:
            decisions.append(
                AllocationDecision(
                    venue=candidate.venue,
                    symbol=candidate.symbol,
                    market_id=candidate.market_id,
                    rank=candidate.rank,
                    score=candidate.score,
                    accepted=True,
                    action="skip",
                    current_price=price if price > 0 else None,
                    strategy_profile_name=profile_name,
                    reason="Total position cap has already been reached.",
                    caps=("max_total_positions",),
                )
            )
            continue

        if venue_name and candidate.venue.strip().lower() == venue_name:
            if venue_slots <= 0:
                decisions.append(
                    AllocationDecision(
                        venue=candidate.venue,
                        symbol=candidate.symbol,
                        market_id=candidate.market_id,
                        rank=candidate.rank,
                        score=candidate.score,
                        accepted=True,
                        action="skip",
                        current_price=price if price > 0 else None,
                        strategy_profile_name=profile_name,
                        reason=f"Venue {venue_name} hit its open-position cap.",
                        caps=("venue_position_cap",),
                    )
                )
                continue
            if venue_headroom <= 0:
                decisions.append(
                    AllocationDecision(
                        venue=candidate.venue,
                        symbol=candidate.symbol,
                        market_id=candidate.market_id,
                        rank=candidate.rank,
                        score=candidate.score,
                        accepted=True,
                        action="skip",
                        current_price=price if price > 0 else None,
                        strategy_profile_name=profile_name,
                        reason=f"Venue {venue_name} has no notional headroom remaining.",
                        caps=("venue_notional_cap",),
                    )
                )
                continue

        if total_headroom <= 0:
            decisions.append(
                AllocationDecision(
                    venue=candidate.venue,
                    symbol=candidate.symbol,
                    market_id=candidate.market_id,
                    rank=candidate.rank,
                    score=candidate.score,
                    accepted=True,
                    action="skip",
                    current_price=price if price > 0 else None,
                    strategy_profile_name=profile_name,
                    reason="No deployable cash remains after portfolio reserve.",
                    caps=("reserve_cash",),
                )
            )
            continue

        score_weight = _score_weight(candidate.score, caps.min_candidate_score)
        remaining_slots_after = max(1, remaining_new_positions)
        equal_share_cap = total_headroom / remaining_slots_after
        requested_notional = min(caps.max_position_notional, equal_share_cap)
        confidence_notional = requested_notional * (0.5 + 0.5 * score_weight)
        min_entry_notional = _candidate_min_entry_notional(candidate, caps)
        target_notional = min(
            max(min_entry_notional, confidence_notional),
            total_headroom,
            caps.max_position_notional,
            venue_headroom if venue_name and candidate.venue.strip().lower() == venue_name else total_headroom,
        )
        if candidate.max_notional is not None and candidate.max_notional > 0:
            target_notional = min(target_notional, candidate.max_notional)
        if target_notional < min_entry_notional:
            decisions.append(
                AllocationDecision(
                    venue=candidate.venue,
                    symbol=candidate.symbol,
                    market_id=candidate.market_id,
                    rank=candidate.rank,
                    score=candidate.score,
                    accepted=True,
                    action="skip",
                    requested_notional=requested_notional,
                    current_price=price if price > 0 else None,
                    strategy_profile_name=profile_name,
                    reason=(
                        f"Target notional {target_notional:.2f} is below the minimum entry notional {min_entry_notional:.2f} "
                        f"after applying portfolio caps."
                    ),
                    caps=("min_entry_notional",),
                )
            )
            continue

        quantity = target_notional / price if price > 0 else 0.0
        caps_used: list[str] = []
        if target_notional >= caps.max_position_notional:
            caps_used.append("position_notional_cap")
        if target_notional >= total_headroom:
            caps_used.append("portfolio_headroom")
        if venue_name and candidate.venue.strip().lower() == venue_name and target_notional >= venue_headroom:
            caps_used.append("venue_notional_cap")
        if candidate.max_notional is not None and candidate.max_notional > 0 and target_notional >= candidate.max_notional:
            caps_used.append("candidate_max_notional")
        if not caps_used:
            caps_used.append("score_weighted")

        decisions.append(
            AllocationDecision(
                venue=candidate.venue,
                symbol=candidate.symbol,
                market_id=candidate.market_id,
                rank=candidate.rank,
                score=candidate.score,
                accepted=True,
                action="open",
                requested_notional=requested_notional,
                target_notional=target_notional,
                current_notional=0.0,
                quantity=quantity,
                portfolio_share=(target_notional / cash) if cash > 0 else 0.0,
                current_price=price if price > 0 else None,
                strategy_profile_name=profile_name,
                reason=(
                    f"Opened at a conservative score-weighted size of {target_notional:.2f} from {requested_notional:.2f} "
                    f"requested notional."
                ),
                caps=tuple(caps_used),
            )
        )
        selected_count += 1
        remaining_new_positions -= 1
        current_total_positions += 1
        current_venue_positions += 1
        total_headroom = max(0.0, total_headroom - target_notional)
        if venue_name and candidate.venue.strip().lower() == venue_name:
            venue_slots = max(0, venue_slots - 1)
            venue_headroom = max(0.0, venue_headroom - target_notional)

    target_deployed = sum(decision.target_notional for decision in decisions if decision.action == "open")
    target_positions = sum(1 for decision in decisions if decision.action == "open")
    return PortfolioAllocationReport(
        generated_at=now_iso(),
        venue=venue_name or (candidates[0].venue if candidates else ""),
        selection_mode=selection_mode,
        source_path=source_path,
        available_cash=cash,
        reserve_cash=reserve_cash,
        deployable_cash=deployable_cash,
        starting_balance=state.starting_balance,
        current_deployed_notional=current_deployed,
        target_deployed_notional=target_deployed,
        current_positions=current_positions,
        target_positions=target_positions,
        max_total_positions=caps.max_total_positions,
        max_position_notional=caps.max_position_notional,
        max_total_notional=caps.max_total_notional,
        max_positions_per_venue=caps.max_positions_per_venue,
        max_venue_notional=caps.max_venue_notional,
        min_candidate_score=caps.min_candidate_score,
        min_entry_notional=caps.min_entry_notional,
        accepted_count=len(accepted),
        rejected_count=len(rejected),
        decisions=tuple(decisions),
        notes=(
            f"remaining_new_position_slots={remaining_new_positions}",
            f"selected_count={selected_count}",
            caps.describe(),
        ),
    )
