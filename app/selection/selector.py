from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .filters import SelectionFilters, candidate_passes, evaluate_candidate, failed_filter_reasons
from .models import MarketCandidate, MarketScanner
from .scoring import ScoreBreakdown, ScoringConfig, score_candidate


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class MarketSelectionConfig:
    filters: SelectionFilters = field(default_factory=SelectionFilters)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)


@dataclass(slots=True)
class ScoredCandidate:
    candidate: MarketCandidate
    accepted: bool
    score: float
    score_breakdown: ScoreBreakdown
    filter_decisions: tuple = field(default_factory=tuple)
    rank: int | None = None


@dataclass(slots=True)
class SelectionResult:
    scanned_at: str
    venue: str
    evaluated: list[ScoredCandidate] = field(default_factory=list)
    ranked: list[ScoredCandidate] = field(default_factory=list)
    selected: ScoredCandidate | None = None

    @property
    def accepted_count(self) -> int:
        return len(self.ranked)

    @property
    def rejected_count(self) -> int:
        return len(self.evaluated) - len(self.ranked)

    def summary(self) -> str:
        best = self.selected.candidate.symbol if self.selected else "none"
        return (
            f"venue={self.venue or 'unknown'} scanned={len(self.evaluated)} "
            f"accepted={self.accepted_count} rejected={self.rejected_count} selected={best}"
        )


class MarketSelector:
    def __init__(self, config: MarketSelectionConfig | None = None) -> None:
        self.config = config or MarketSelectionConfig()

    def select(self, candidates: list[MarketCandidate], *, venue: str = "", scanned_at: str = "") -> SelectionResult:
        return select_markets(candidates, self.config, venue=venue, scanned_at=scanned_at)


def _sort_key(item: ScoredCandidate) -> tuple[float, float, str]:
    volume = item.candidate.metrics.volume_quote_24h or 0.0
    return (-item.score, -volume, item.candidate.symbol)


def select_markets(
    candidates: list[MarketCandidate],
    config: MarketSelectionConfig | None = None,
    *,
    venue: str = "",
    scanned_at: str = "",
) -> SelectionResult:
    selection_config = config or MarketSelectionConfig()
    evaluated: list[ScoredCandidate] = []

    for candidate in candidates:
        decisions = evaluate_candidate(candidate, selection_config.filters)
        accepted = candidate_passes(decisions)
        breakdown = score_candidate(candidate, selection_config.scoring)
        score = breakdown.total if accepted else 0.0
        evaluated.append(
            ScoredCandidate(
                candidate=candidate,
                accepted=accepted,
                score=score,
                score_breakdown=breakdown,
                filter_decisions=decisions,
            )
        )

    ranked = sorted((item for item in evaluated if item.accepted), key=_sort_key)
    for index, item in enumerate(ranked, start=1):
        item.rank = index

    selected = ranked[0] if ranked else None
    result_scanned_at = scanned_at or (evaluated[0].candidate.scanned_at if evaluated else utc_now_iso())
    result_venue = venue or (evaluated[0].candidate.venue if evaluated else "")
    return SelectionResult(
        scanned_at=result_scanned_at,
        venue=result_venue,
        evaluated=evaluated,
        ranked=ranked,
        selected=selected,
    )


def select_from_scanner(scanner: MarketScanner, config: MarketSelectionConfig | None = None) -> SelectionResult:
    scanned_at = utc_now_iso()
    candidates = scanner.scan()
    venue = getattr(scanner, "venue", "")
    if candidates and not venue:
        venue = candidates[0].venue
    return select_markets(candidates, config, venue=venue, scanned_at=scanned_at)


def filter_summary(result: SelectionResult) -> dict[str, str]:
    summary: dict[str, str] = {}
    for item in result.evaluated:
        summary[item.candidate.symbol] = failed_filter_reasons(item.filter_decisions)
    return summary
