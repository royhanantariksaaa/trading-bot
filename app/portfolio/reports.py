from __future__ import annotations

import json
from pathlib import Path

from .models import AllocationDecision, PortfolioAllocationReport


def _decision_to_dict(decision: AllocationDecision) -> dict:
    return {
        "venue": decision.venue,
        "symbol": decision.symbol,
        "market_id": decision.market_id,
        "rank": decision.rank,
        "score": decision.score,
        "accepted": decision.accepted,
        "action": decision.action,
        "requested_notional": decision.requested_notional,
        "target_notional": decision.target_notional,
        "current_notional": decision.current_notional,
        "quantity": decision.quantity,
        "portfolio_share": decision.portfolio_share,
        "current_price": decision.current_price,
        "strategy_profile_name": decision.strategy_profile_name,
        "reason": decision.reason,
        "caps": list(decision.caps),
    }


def build_allocation_report(report: PortfolioAllocationReport, *, top: int = 5) -> str:
    lines = [f"Portfolio allocation report for venue={report.venue} at {report.generated_at}", ""]
    lines.extend(report.why_lines())
    return "\n".join(lines).strip() + "\n"


def write_allocation_report(report: PortfolioAllocationReport, path: Path, *, top: int = 5) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_allocation_report(report, top=top), encoding="utf-8")
    report.report_path = path
    return path


def write_allocation_report_json(report: PortfolioAllocationReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict()
    payload["decisions"] = [_decision_to_dict(item) for item in report.decisions]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    report.report_json_path = path
    return path
