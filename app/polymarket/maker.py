from __future__ import annotations

import csv
import json
import time
from dataclasses import replace
from pathlib import Path

from ..selection.runtime import maybe_rotate_runtime_selection
from .adaptive import evaluate_adaptive_policy
from .config import Config
from .models import BotState, BookSnapshot, FillResult, QuotePlan, utc_now


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def round_to_tick(price: float, tick_size: float) -> float:
    if tick_size <= 0:
        return price
    ticks = round(price / tick_size)
    return round(ticks * tick_size, 8)


def load_state(path: Path) -> BotState:
    if not path.exists():
        return BotState()
    return BotState.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_state(path: Path, state: BotState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")


def append_run_log(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "timestamp",
        "loop",
        "mid",
        "best_bid",
        "best_ask",
        "spread",
        "inventory",
        "cash",
        "mark_pnl",
        "bid_quote",
        "ask_quote",
        "buy_size",
        "sell_size",
        "fills",
        "notes",
    ]
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def mark_to_market(state: BotState, mid: float) -> float:
    return state.cash + state.inventory * mid


def adaptive_runtime_allows(config: Config) -> bool:
    if config.adaptive_mode == "off":
        return False
    if config.adaptive_mode == "paper" and not config.paper_mode:
        return False
    return True


def resolve_runtime_config(config: Config, book: BookSnapshot, state: BotState, client) -> tuple[Config, object | None]:
    if not adaptive_runtime_allows(config):
        return config, None
    try:
        metadata = client.get_market_metadata(config.token_id)
    except Exception:
        metadata = {}
    report = evaluate_adaptive_policy(config, book, previous_mid=state.last_mid if state.loops > 0 else None, metadata=metadata)
    runtime_config = replace(
        config,
        base_spread=report.overrides.base_spread,
        edge_offset=report.overrides.edge_offset,
        quote_size=report.overrides.quote_size,
        max_inventory=report.overrides.max_inventory,
        max_position_notional=report.overrides.max_position_notional,
        inventory_skew_per_share=report.overrides.inventory_skew_per_share,
    )
    return runtime_config, report


def compute_quote_plan(config: Config, state: BotState, book: BookSnapshot) -> QuotePlan:
    half_spread = max(config.base_spread / 2, book.tick_size)
    inventory_gap = state.inventory - config.inventory_target
    skew = inventory_gap * config.inventory_skew_per_share

    raw_bid = book.midpoint - half_spread - config.edge_offset - skew
    raw_ask = book.midpoint + half_spread + config.edge_offset - skew

    bid_price = clamp(round_to_tick(raw_bid, book.tick_size), book.tick_size, 0.99)
    ask_price = clamp(round_to_tick(raw_ask, book.tick_size), bid_price + book.tick_size, 0.999)

    buy_size = 0.0 if state.inventory >= config.max_inventory else max(config.min_order_size, config.quote_size)
    sell_size = 0.0 if state.inventory <= -config.max_inventory else max(config.min_order_size, config.quote_size)

    if state.inventory * book.midpoint >= config.max_position_notional:
        buy_size = 0.0
    if abs(state.inventory) * book.midpoint >= config.max_position_notional and state.inventory <= 0:
        sell_size = 0.0

    reason = "inventory-balanced"
    if inventory_gap > 0:
        reason = "long-inventory-skew"
    elif inventory_gap < 0:
        reason = "short-inventory-skew"

    return QuotePlan(
        bid_price=bid_price,
        ask_price=ask_price,
        buy_size=buy_size,
        sell_size=sell_size,
        inventory_skew=skew,
        reason=reason,
    )


def maybe_fill_quotes(state: BotState, book: BookSnapshot, plan: QuotePlan) -> list[FillResult]:
    fills: list[FillResult] = []
    if plan.buy_size > 0 and plan.bid_price >= book.best_ask:
        fills.append(FillResult(side="BUY", price=book.best_ask, size=plan.buy_size, notional=book.best_ask * plan.buy_size, reason="crossed-best-ask"))
    if plan.sell_size > 0 and state.inventory >= plan.sell_size and plan.ask_price <= book.best_bid:
        fills.append(FillResult(side="SELL", price=book.best_bid, size=plan.sell_size, notional=book.best_bid * plan.sell_size, reason="crossed-best-bid"))
    return fills


def apply_fill(state: BotState, fill: FillResult) -> None:
    if fill.side == "BUY":
        state.inventory += fill.size
        state.cash -= fill.notional
        state.bought_cost += fill.notional
    else:
        state.inventory -= fill.size
        state.cash += fill.notional
        state.sold_proceeds += fill.notional
    state.realized_pnl = state.sold_proceeds - state.bought_cost
    state.fills += 1
    state.updated_at = utc_now()


def _can_rotate_market(config: Config, state: BotState) -> tuple[bool, str]:
    if config.selection_mode == "manual":
        return False, "rotation disabled in manual selection mode"
    if not config.rotation_controller.only_when_flat:
        return True, "rotation allowed"
    if abs(state.inventory) > 1e-9:
        return False, "rotation skipped: non-flat inventory"
    return True, "rotation allowed while flat"


def run_loop(config: Config, client) -> None:
    config.validate()
    state = load_state(config.state_path)
    rotation = config.rotation_controller

    remaining = config.loops
    while True:
        if rotation.should_rotate(state.loops):
            allowed, reason = _can_rotate_market(config, state)
            if allowed:
                decision = maybe_rotate_runtime_selection(
                    "polymarket",
                    mode=config.selection_mode,
                    output_path=config.selection_csv_path,
                    current_market_id=config.token_id,
                )
                if decision.changed and decision.selection is not None:
                    config.token_id = decision.selection.market_id
                    print(f"rotation_applied token_id={config.token_id} report={decision.selection.report_path}")
                else:
                    print(f"rotation_check {decision.reason}")
            else:
                print(reason)
            rotation.mark_executed(state.loops)

        book = client.get_book(config.token_id)
        runtime_config, adaptive_report = resolve_runtime_config(config, book, state, client)
        state.last_mid = book.midpoint
        plan = compute_quote_plan(runtime_config, state, book)
        fills = maybe_fill_quotes(state, book, plan) if config.paper_mode else []
        for fill in fills:
            apply_fill(state, fill)

        state.loops += 1
        state.updated_at = utc_now()
        save_state(config.state_path, state)
        note = plan.reason
        if adaptive_report is not None:
            note = f"{note}; adaptive={adaptive_report.policy_name}; report={adaptive_report.report_path}"
        append_run_log(
            config.log_path,
            {
                "timestamp": state.updated_at,
                "loop": state.loops,
                "mid": f"{book.midpoint:.4f}",
                "best_bid": f"{book.best_bid:.4f}",
                "best_ask": f"{book.best_ask:.4f}",
                "spread": f"{book.spread:.4f}",
                "inventory": f"{state.inventory:.2f}",
                "cash": f"{state.cash:.4f}",
                "mark_pnl": f"{mark_to_market(state, book.midpoint):.4f}",
                "bid_quote": f"{plan.bid_price:.4f}",
                "ask_quote": f"{plan.ask_price:.4f}",
                "buy_size": f"{plan.buy_size:.2f}",
                "sell_size": f"{plan.sell_size:.2f}",
                "fills": "; ".join(f"{fill.side}@{fill.price:.4f}x{fill.size:.2f}" for fill in fills) or "none",
                "notes": note,
            },
        )

        status = f"loop={state.loops} mid={book.midpoint:.4f} bid={plan.bid_price:.4f} ask={plan.ask_price:.4f} inv={state.inventory:.2f} mtm={mark_to_market(state, book.midpoint):.4f} fills={len(fills)}"
        if adaptive_report is not None:
            status = f"{status} adaptive={adaptive_report.policy_name}"
        print(status)

        if remaining > 0:
            remaining -= 1
            if remaining == 0:
                break
        time.sleep(config.poll_seconds)
