from __future__ import annotations

import csv
import json
import time
from dataclasses import replace
from pathlib import Path

from ..selection.runtime import maybe_rotate_runtime_selection
from .adaptive import evaluate_adaptive_policy
from .config import Config
from .execution import UnimplementedLiveGateway
from .models import BotState, BookSnapshot, FillResult, QuotePlan, SupervisionReport, utc_now


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


def budget_floor_reached(config: Config, state: BotState, mid: float) -> bool:
    return mark_to_market(state, mid) <= config.reserve_cash


def drawdown_pct(state: BotState, mid: float) -> float:
    equity = mark_to_market(state, mid)
    if state.peak_mark_to_market <= 0:
        return 0.0
    return max(0.0, (state.peak_mark_to_market - equity) / state.peak_mark_to_market)


def run_loss_usd(config: Config, state: BotState, mid: float) -> float:
    return max(0.0, config.starting_cash - mark_to_market(state, mid))


def update_budget_state(config: Config, state: BotState, mid: float) -> str | None:
    equity = mark_to_market(state, mid)
    if state.peak_mark_to_market <= 0:
        state.peak_mark_to_market = max(config.starting_cash, equity)
    else:
        state.peak_mark_to_market = max(state.peak_mark_to_market, equity)

    halt_reason = ""
    if budget_floor_reached(config, state, mid):
        halt_reason = f"budget floor reached: equity={equity:.4f} reserve={config.reserve_cash:.4f}"
    else:
        current_drawdown = drawdown_pct(state, mid)
        if current_drawdown >= config.max_drawdown_pct:
            halt_reason = f"max drawdown reached: drawdown={current_drawdown:.2%} limit={config.max_drawdown_pct:.2%}"
        else:
            current_run_loss = run_loss_usd(config, state, mid)
            if current_run_loss >= config.max_run_loss_usd:
                halt_reason = f"max run loss reached: loss={current_run_loss:.4f} limit={config.max_run_loss_usd:.4f}"

    if halt_reason:
        state.halted = True
        state.halt_reason = halt_reason
        if config.hard_halt_mode == "flat_stop":
            state.stop_after_flatten = True
            state.flatten_pending = state.inventory > 0
        return halt_reason

    if not state.stopped:
        state.halted = False
        state.halt_reason = ""
        state.stop_after_flatten = False
        state.flatten_pending = False
    return None


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

    current_equity = mark_to_market(state, book.midpoint)
    spendable_cash = max(0.0, state.cash - config.reserve_cash)
    survival_buffer = max(config.reserve_cash, config.starting_cash * config.min_cash_buffer_pct)
    survival_spendable = max(0.0, state.cash - survival_buffer)
    per_loop_budget = min(spendable_cash, survival_spendable, spendable_cash * config.max_buy_fraction_of_spendable)
    if spendable_cash <= 0 or per_loop_budget <= 0:
        buy_size = 0.0
    else:
        buy_size = min(buy_size, per_loop_budget / max(book.best_ask, book.tick_size))
        if buy_size < config.min_order_size:
            buy_size = 0.0

    inventory_room = max(0.0, config.max_inventory - state.inventory)
    if inventory_room <= 0:
        buy_size = 0.0
    else:
        buy_size = min(buy_size, inventory_room)

    max_notional_room = max(0.0, config.max_position_notional - max(0.0, state.inventory) * book.midpoint)
    if max_notional_room <= 0:
        buy_size = 0.0
    else:
        buy_size = min(buy_size, max_notional_room / max(book.best_ask, book.tick_size))
        if buy_size < config.min_order_size:
            buy_size = 0.0

    sell_size = min(sell_size, max(0.0, state.inventory))
    if sell_size < config.min_order_size:
        sell_size = 0.0
    if current_equity <= config.reserve_cash or state.halted:
        buy_size = 0.0

    reason = "inventory-balanced"
    if state.stopped:
        reason = f"stopped:{state.stop_reason or state.halt_reason}"
    elif state.halted:
        reason = f"halted:{state.halt_reason}"
    elif current_equity <= config.reserve_cash:
        reason = "budget-floor-protect"
    elif inventory_gap > 0:
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


def maybe_flatten_on_halt(config: Config, state: BotState, book: BookSnapshot) -> list[FillResult]:
    if not config.paper_mode or not state.halted or not state.stop_after_flatten or state.stopped:
        return []
    if state.inventory <= 0:
        state.flatten_pending = False
        state.stopped = True
        state.stop_reason = state.halt_reason or "flat-stop completed while already flat"
        return []
    fill = FillResult(
        side="SELL",
        price=book.best_bid,
        size=state.inventory,
        notional=book.best_bid * state.inventory,
        reason=f"flat-stop:{state.halt_reason or 'paper halt'}",
    )
    apply_fill(state, fill)
    state.flatten_pending = False
    state.stopped = True
    state.stop_reason = state.halt_reason or "flat-stop completed"
    state.updated_at = utc_now()
    return [fill]


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


def build_supervision_report(config: Config, state: BotState, book: BookSnapshot, plan: QuotePlan, *, notes: list[str] | None = None) -> SupervisionReport:
    mtm = mark_to_market(state, book.midpoint)
    inventory_mark = state.inventory * book.midpoint
    spendable_cash = max(0.0, state.cash - config.reserve_cash)
    health = "healthy"
    if state.stopped:
        health = "stopped"
    elif state.halted:
        health = "halted"
    elif spendable_cash <= 0:
        health = "reserve_only"
    return SupervisionReport(
        timestamp=state.updated_at,
        loop=state.loops,
        token_id=config.token_id,
        mode="paper" if config.paper_mode else "live_scaffold",
        health=health,
        cash=state.cash,
        reserve_cash=config.reserve_cash,
        spendable_cash=spendable_cash,
        mark_to_market=mtm,
        peak_mark_to_market=state.peak_mark_to_market,
        drawdown_pct=drawdown_pct(state, book.midpoint),
        inventory=state.inventory,
        inventory_mark_value=inventory_mark,
        max_inventory=config.max_inventory,
        halt_reason=state.halt_reason,
        stop_reason=state.stop_reason,
        flatten_pending=state.flatten_pending,
        buy_quote_size=plan.buy_size,
        sell_quote_size=plan.sell_size,
        notes=notes or [],
    )


def write_supervision_report(path: Path, report: SupervisionReport) -> tuple[Path, Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    report_path = path
    report_json_path = path.with_suffix(".json") if path.suffix else path.with_name(path.name + ".json")
    report_path.write_text(report.to_text(), encoding="utf-8")
    report_json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return report_path, report_json_path


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
    if config.live_enabled:
        if not config.live_allow_unverified:
            raise NotImplementedError(
                "PM_LIVE_ENABLED=true is blocked because this repo only has live scaffolding right now. Keep PM_PAPER_MODE=true or set PM_ALLOW_UNVERIFIED_LIVE=true if you only want the explicit readiness error path."
            )
        UnimplementedLiveGateway(config.live_credentials).validate_ready()

    state = load_state(config.state_path)
    if state.loops == 0 and state.cash == 0 and state.inventory == 0:
        state.cash = config.starting_cash
        state.peak_mark_to_market = config.starting_cash
    elif state.peak_mark_to_market <= 0:
        state.peak_mark_to_market = max(config.starting_cash, mark_to_market(state, state.last_mid))
    rotation = config.rotation_controller

    remaining = config.loops
    while True:
        if state.stopped:
            print(f"stopped reason={state.stop_reason or state.halt_reason}")
            break

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
        budget_note = update_budget_state(config, state, book.midpoint)
        plan = compute_quote_plan(runtime_config, state, book)
        fills = maybe_fill_quotes(state, book, plan) if config.paper_mode else []
        for fill in fills:
            apply_fill(state, fill)
        halt_fills = maybe_flatten_on_halt(config, state, book)
        fills.extend(halt_fills)

        state.loops += 1
        state.updated_at = utc_now()
        note = plan.reason
        notes: list[str] = []
        if budget_note:
            note = f"{note}; budget={budget_note}"
            notes.append(budget_note)
        if adaptive_report is not None:
            note = f"{note}; adaptive={adaptive_report.policy_name}; report={adaptive_report.report_path}"
            notes.append(f"adaptive={adaptive_report.policy_name}")
        if halt_fills:
            notes.append("flat-stop-executed")
        report = build_supervision_report(runtime_config, state, book, plan, notes=notes)
        write_supervision_report(config.supervision_report_path, report)
        save_state(config.state_path, state)
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

        status = f"loop={state.loops} health={report.health} mid={book.midpoint:.4f} bid={plan.bid_price:.4f} ask={plan.ask_price:.4f} inv={state.inventory:.2f} cash={state.cash:.4f} mtm={mark_to_market(state, book.midpoint):.4f} dd={drawdown_pct(state, book.midpoint):.2%} fills={len(fills)}"
        if adaptive_report is not None:
            status = f"{status} adaptive={adaptive_report.policy_name}"
        if state.halted:
            status = f"{status} halt={state.halt_reason}"
        if state.stopped:
            status = f"{status} stop={state.stop_reason}"
        print(status)

        if remaining > 0:
            remaining -= 1
            if remaining == 0:
                break
        time.sleep(config.poll_seconds)
