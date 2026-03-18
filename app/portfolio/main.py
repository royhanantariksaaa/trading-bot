from __future__ import annotations

from ..selection.binance import scan_binance_markets
from ..selection.polymarket import scan_polymarket_markets
from .allocator import allocate_portfolio
from .config import Config
from .inputs import load_portfolio_candidates
from .reports import write_allocation_report, write_allocation_report_json
from .state import apply_allocation_report, load_state, save_state


def _scan_candidates(config: Config):
    if config.venue == "polymarket":
        return scan_polymarket_markets()
    return scan_binance_markets()


def _load_candidates(config: Config):
    if config.selection_mode == "scan":
        result = _scan_candidates(config)
        candidates = load_portfolio_candidates(
            venue=config.venue,
            source="scan",
            selection_result=result,
            include_rejected=config.include_rejected,
        )
        return candidates, result.summary()
    candidates = load_portfolio_candidates(
        venue=config.venue,
        source="csv",
        selection_csv_path=config.selection_csv_path,
        include_rejected=config.include_rejected,
    )
    return candidates, str(config.selection_csv_path)


def run_once(config: Config) -> str:
    config.validate()
    state = load_state(config.state_path)
    if state.starting_balance <= 0:
        state.starting_balance = config.starting_balance
    if not state.positions and state.cash_free <= 0:
        state.cash_free = config.starting_balance

    candidates, source_summary = _load_candidates(config)
    report = allocate_portfolio(
        candidates,
        state,
        config.caps,
        available_cash=state.cash_free,
        venue=config.venue,
        selection_mode=config.selection_mode,
        source_path=source_summary,
    )
    write_allocation_report(report, config.report_path, top=config.top_report_rows)
    write_allocation_report_json(report, config.report_json_path)

    if config.run_mode == "paper" and config.paper_apply_allocations:
        market_prices: dict[tuple[str, str], float] = {}
        for candidate in candidates:
            if candidate.last_price is not None and candidate.last_price > 0:
                market_prices[(candidate.venue.strip().lower(), candidate.symbol.strip().lower())] = candidate.last_price
        apply_allocation_report(state, report, market_prices=market_prices)
    else:
        state.last_allocation_report_at = report.generated_at
        state.last_allocation_report_path = str(config.report_path)
        state.last_allocation_report_json_path = str(config.report_json_path)
        state.last_source = config.selection_mode

    save_state(config.state_path, state)
    return report.summary()


def main() -> None:
    config = Config()
    summary = run_once(config)
    print(summary)
    print(f"Report written to {config.report_path}")
    print(f"JSON report written to {config.report_json_path}")


if __name__ == "__main__":
    main()
