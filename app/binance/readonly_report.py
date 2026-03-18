from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..selection.runtime import RuntimeSelection
from .adaptive import AdaptiveDecisionReport
from .config import Config
from .exchange import SymbolRules
from .models import AccountSnapshot, EntryPlan, ExitPlan, OrderState, PositionState
from .risk import build_entry_plan, build_exit_plan
from .state import BotState


@dataclass(slots=True)
class HoldingSignalSnapshot:
    asset: str
    symbol: str
    total: float
    free: float
    locked: float
    tradable: bool
    note: str = ""
    signal: str = "hold"
    action: str = "HOLD"
    reason: str = ""
    signal_price: float = 0.0
    live_price: float = 0.0
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    rsi: float = 0.0
    htf_text: str = ""
    htf_ok: bool = True
    gates: dict[str, bool] = field(default_factory=dict)
    estimated_notional: float | None = None


def _format_float(value: float | None, *, precision: int = 4) -> str:
    if value is None:
        return "missing"
    return f"{value:.{precision}f}"


def _format_order(order: OrderState) -> str:
    parts = [
        f"{order.side}",
        f"type={order.order_type or 'unknown'}",
        f"status={order.status or 'unknown'}",
        f"qty={order.qty:.6f}",
    ]
    if order.executed_qty > 0:
        parts.append(f"filled={order.executed_qty:.6f}")
    if order.quote_order_qty > 0:
        parts.append(f"quote={order.quote_order_qty:.4f}")
    if order.price > 0:
        parts.append(f"price={order.price:.4f}")
    if order.stop_price > 0:
        parts.append(f"stop={order.stop_price:.4f}")
    if order.client_order_id:
        parts.append(f"client={order.client_order_id}")
    return " | ".join(parts)


def _format_holding(asset: str, free: float, locked: float, total: float) -> str:
    return f"{asset}: free={free:.6f} locked={locked:.6f} total={total:.6f}"


def _format_dust_holding(asset: str, total: float, notional: float, actionable_threshold: float, reason: str, symbol: str = "") -> str:
    market_text = f" via {symbol}" if symbol else ""
    return (
        f"{asset}: action=CANNOT ACT total={total:.6f} notional≈{notional:.4f} actionable_threshold≈{actionable_threshold:.4f}{market_text}"
        f" | reason={reason}"
    )


def _format_owned_asset(asset: str, total: float, action: str, reason: str, *, notional: float | None = None, symbol: str = "") -> str:
    parts = [f"{asset}: action={action}", f"total={total:.6f}"]
    if notional is not None:
        parts.append(f"notional≈{notional:.4f}")
    if symbol:
        parts.append(f"symbol={symbol}")
    parts.append(f"reason={reason}")
    return " | ".join(parts)


@dataclass(slots=True)
class ReadonlyReport:
    venue: str
    symbol: str
    timeframe: str
    scanned_at: str
    bot_mode: str
    execution_mode: str
    selection_mode: str
    use_testnet: bool
    enable_live_trading: bool
    order_test_before_submit: bool
    selection_note: str = ""
    selection: RuntimeSelection | None = None
    adaptive_note: str = ""
    adaptive_report: AdaptiveDecisionReport | None = None
    account_snapshot: AccountSnapshot | None = None
    open_orders: list[OrderState] = field(default_factory=list)
    position: PositionState | None = None
    signal: str = ""
    signal_price: float = 0.0
    live_price: float = 0.0
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    rsi: float = 0.0
    htf_text: str = ""
    htf_ok: bool = True
    available_quote: float = 0.0
    gates: dict[str, bool] = field(default_factory=dict)
    sell_reason: str = ""
    decision_action: str = "HOLD"
    decision_reason: str = ""
    decision_reasons: tuple[str, ...] = field(default_factory=tuple)
    decision_path: str = "none"
    blocked_by: str = "live_readonly"
    entry_plan: EntryPlan | None = None
    exit_plan: ExitPlan | None = None
    report_path: Path | None = None
    report_json_path: Path | None = None
    holding_signals: list[HoldingSignalSnapshot] = field(default_factory=list)

    def summary(self) -> str:
        exposure = "flat"
        if self.position is not None:
            exposure = f"long qty={self.position.qty:.6f}"
        selection = self.selection.summary if self.selection is not None else self.selection_note or "manual"
        return (
            f"mode={self.bot_mode} symbol={self.symbol} signal={self.signal or 'hold'} action={self.decision_action} "
            f"selection={selection} quote_free={self.quote_free:.4f} exposure={exposure}"
        )

    @property
    def quote_free(self) -> float:
        if self.account_snapshot is None:
            return 0.0
        return self.account_snapshot.quote_free

    @property
    def quote_locked(self) -> float:
        if self.account_snapshot is None:
            return 0.0
        return self.account_snapshot.quote_locked

    @property
    def base_free(self) -> float:
        if self.account_snapshot is None:
            return 0.0
        return self.account_snapshot.base_free

    @property
    def base_locked(self) -> float:
        if self.account_snapshot is None:
            return 0.0
        return self.account_snapshot.base_locked

    @property
    def base_total(self) -> float:
        return self.base_free + self.base_locked

    @property
    def current_exposure_notional(self) -> float:
        if self.position is not None:
            return self.position.qty * self.live_price
        return 0.0

    def why_lines(self) -> tuple[str, ...]:
        lines = [self.summary()]
        lines.append(f"Live read-only guard: `no submit/test/cancel`")
        lines.append(f"Execution mode preview: `{self.execution_mode}`")
        lines.append(f"Selection mode: `{self.selection_mode}`")
        lines.append(f"Testnet: `{self.use_testnet}` | Live trading flag: `{self.enable_live_trading}` | Order test flag: `{self.order_test_before_submit}`")

        if self.account_snapshot is not None:
            lines.append("Wallet holdings")
            lines.append(
                f"Quote free / locked: `{self.quote_free:.6f}` / `{self.quote_locked:.6f}` {self.account_snapshot.quote_asset}"
            )
            lines.append(
                f"Base free / locked: `{self.base_free:.6f}` / `{self.base_locked:.6f}` {self.account_snapshot.base_asset}"
            )
            lines.append(
                f"Wallet base inventory: `{self.base_total:.6f} {self.account_snapshot.base_asset}`"
            )
            lines.append(
                f"Managed exposure: `~{self.current_exposure_notional:.4f} {self.account_snapshot.quote_asset}` at live price"
            )
            if self.account_snapshot.maker_fee is not None or self.account_snapshot.taker_fee is not None:
                lines.append(
                    f"Fees: maker=`{_format_float(self.account_snapshot.maker_fee, precision=6)}` "
                    f"taker=`{_format_float(self.account_snapshot.taker_fee, precision=6)}`"
                )
            holdings = self.account_snapshot.holdings or []
            dust_holdings = self.account_snapshot.dust_holdings or []
            dust_assets = {item.asset for item in dust_holdings}
            if self.position is not None:
                lines.append("Managed positions:")
                lines.append(
                    f"- {_format_owned_asset(self.account_snapshot.base_asset, self.position.qty, 'HOLD' if not self.sell_reason else self.decision_action, self.decision_reason or 'managed by bot state', notional=self.current_exposure_notional, symbol=self.position.symbol)}"
                )
            wallet_only = [
                item
                for item in holdings
                if item.asset not in {self.account_snapshot.quote_asset}
                and item.asset not in dust_assets
                and not (self.position is not None and item.asset == self.account_snapshot.base_asset)
            ]
            if wallet_only:
                lines.append("Wallet-only holdings:")
                ordered_wallet = sorted(wallet_only, key=lambda row: (-row.total, row.asset))
                for item in ordered_wallet[:12]:
                    notional = item.total * self.live_price if item.asset == self.account_snapshot.base_asset else None
                    reason = (
                        "selected symbol held in wallet but not tracked as a managed bot position"
                        if item.asset == self.account_snapshot.base_asset
                        else "wallet holding outside current managed symbol scope"
                    )
                    action = "HOLD" if item.asset == self.account_snapshot.base_asset else "IGNORE"
                    symbol = self.symbol if item.asset == self.account_snapshot.base_asset else ""
                    lines.append(f"- {_format_owned_asset(item.asset, item.total, action, reason, notional=notional, symbol=symbol)}")
                if len(ordered_wallet) > 12:
                    lines.append(f"- ... {len(ordered_wallet) - 12} more assets")
            if self.holding_signals:
                lines.append("Holding signals")
                for row in self.holding_signals[:12]:
                    base = (
                        f"- {row.asset}: total=`{row.total:.6f}` | symbol=`{row.symbol or 'n/a'}` | "
                        f"action=`{row.action}` | signal=`{row.signal}`"
                    )
                    if row.estimated_notional is not None:
                        base += f" | notional≈`{row.estimated_notional:.4f}`"
                    lines.append(base)
                    if row.tradable:
                        lines.append(
                            f"  - px/live=`{row.signal_price:.4f}`/`{row.live_price:.4f}` | RSI=`{row.rsi:.2f}` | EMA=`{row.ema_fast:.4f}/{row.ema_slow:.4f}` | HTF=`{row.htf_text or 'htf=off'}` | HTF ok=`{row.htf_ok}`"
                        )
                        lines.append(
                            f"  - gates: ema_up=`{row.gates.get('crossed_up', False)}` ema_down=`{row.gates.get('crossed_down', False)}` rsi_entry=`{row.gates.get('rsi_buy_ok', False)}` rsi_exit=`{row.gates.get('rsi_sell_ok', False)}`"
                        )
                        lines.append(f"  - reason: {row.reason or 'none'}")
                    else:
                        lines.append(f"  - note: {row.note or row.reason or 'not tradable under current strategy'}")
                if len(self.holding_signals) > 12:
                    lines.append(f"- ... {len(self.holding_signals) - 12} more holding signals")
            if holdings:
                lines.append("Raw holdings:")
                ordered = sorted(
                    holdings,
                    key=lambda row: (0 if row.asset in {self.account_snapshot.quote_asset, self.account_snapshot.base_asset} else 1, -row.total, row.asset),
                )
                for item in ordered[:12]:
                    lines.append(f"- {_format_holding(item.asset, item.free, item.locked, item.total)}")
                if len(ordered) > 12:
                    lines.append(f"- ... {len(ordered) - 12} more assets")
            if dust_holdings:
                lines.append("Dust / unactionable inventory:")
                for item in dust_holdings:
                    lines.append(
                        f"- {_format_dust_holding(item.asset, item.total, item.notional, item.actionable_threshold, item.reason, item.symbol)}"
                    )
                if self.position is None:
                    lines.append("- Managed position state stays flat; dust is visible but excluded from tradable exposure logic.")

        if self.open_orders:
            lines.append("Open orders:")
            for order in self.open_orders:
                lines.append(f"- {_format_order(order)}")
        else:
            lines.append("Open orders: none")

        if self.selection is not None:
            lines.append("Selected candidate")
            lines.append(f"- {self.selection.summary}")
            if self.selection.source:
                lines.append(f"- Source: {self.selection.source}")
            if self.selection.path is not None:
                lines.append(f"- Selection CSV: {self.selection.path}")
            if self.selection.report_path is not None:
                lines.append(f"- Selection report: {self.selection.report_path}")
            if self.selection.explanation:
                lines.append("- Why:")
                lines.extend(f"  - {line}" for line in self.selection.explanation.splitlines())
        elif self.selection_note:
            lines.append(f"Selected candidate: {self.selection_note}")
        else:
            lines.append(f"Selected candidate: manual symbol `{self.symbol}`")

        if self.adaptive_report is not None:
            lines.append("Adaptive overlay")
            lines.extend(f"- {line}" for line in self.adaptive_report.why_lines())
        elif self.adaptive_note:
            lines.append(f"Adaptive overlay: {self.adaptive_note}")

        lines.append("Signal snapshot")
        lines.append(f"- Signal: `{self.signal or 'hold'}`")
        lines.append(f"- Live / Signal price: `{self.live_price:.4f}` / `{self.signal_price:.4f}`")
        lines.append(f"- EMA fast / slow: `{self.ema_fast:.4f}` / `{self.ema_slow:.4f}`")
        lines.append(f"- RSI: `{self.rsi:.2f}`")
        lines.append(f"- HTF: `{self.htf_text or 'off'}`")
        lines.append(f"- HTF ok: `{self.htf_ok}`")
        if self.gates:
            lines.append(
                "- Gates: "
                f"EMA up=`{self.gates.get('crossed_up', False)}` "
                f"EMA down=`{self.gates.get('crossed_down', False)}` "
                f"RSI entry=`{self.gates.get('rsi_buy_ok', False)}` "
                f"RSI exit=`{self.gates.get('rsi_sell_ok', False)}`"
            )
        lines.append(f"- Available quote: `{self.available_quote:.4f}`")

        lines.append("Decision preview")
        lines.append(f"- Proposed action: `{self.decision_action}`")
        lines.append(f"- Execution path preview: `{self.decision_path}`")
        lines.append(f"- Blocked by: `{self.blocked_by}`")
        if self.decision_reason:
            lines.append(f"- Reason: {self.decision_reason}")
        if self.decision_reasons:
            lines.extend(f"- {reason}" for reason in self.decision_reasons)
        if self.position is not None:
            lines.append(
                f"- Position: long qty=`{self.position.qty:.6f}` entry=`{self.position.entry_price:.4f}` "
                f"stop=`{self.position.stop_loss:.4f}` tp=`{self.position.take_profit:.4f}`"
            )
        if self.entry_plan is not None:
            lines.append(
                f"- Entry plan: quote=`{self.entry_plan.quote_budget:.4f}` qty=`{self.entry_plan.estimated_qty:.6f}` "
                f"sl=`{self.entry_plan.stop_loss:.4f}` tp=`{self.entry_plan.take_profit:.4f}`"
            )
            lines.append(
                f"- Entry buffers: fee=`{self.entry_plan.fee_buffer_usd:.4f}` slippage=`{self.entry_plan.slippage_buffer_usd:.4f}`"
            )
            if self.entry_plan.market_warning:
                lines.append(f"- Entry warning: {self.entry_plan.market_warning}")
        if self.exit_plan is not None:
            lines.append(f"- Exit plan: qty=`{self.exit_plan.qty:.6f}`")
            if self.exit_plan.market_warning:
                lines.append(f"- Exit warning: {self.exit_plan.market_warning}")
        if self.sell_reason:
            lines.append(f"- Exit trigger: {self.sell_reason}")

        return tuple(lines)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)


def _readonly_report_paths(path: Path, json_path: Path | None = None) -> tuple[Path, Path]:
    if json_path is not None:
        return path, json_path
    if path.suffix:
        return path, path.with_suffix(".json")
    return path, path.with_name(path.name + ".json")


def build_live_readonly_report(
    *,
    config: Config,
    state: BotState,
    market_rules: SymbolRules,
    signal: str,
    signal_price: float,
    live_price: float,
    ema_fast: float,
    ema_slow: float,
    rsi: float,
    gates: dict[str, bool],
    htf_text: str,
    htf_ok: bool,
    available_quote: float,
    candle_time: str,
    sell_reason: str = "",
    selection: RuntimeSelection | None = None,
    selection_note: str = "",
    adaptive_report: AdaptiveDecisionReport | None = None,
    adaptive_note: str = "",
    holding_signals: list[HoldingSignalSnapshot] | None = None,
) -> ReadonlyReport:
    entry_plan = None
    exit_plan = None
    decision_action = "HOLD"
    decision_reason = ""
    decision_reasons: tuple[str, ...] = ()
    decision_path = "none"

    if state.position is not None:
        if sell_reason:
            exit_plan = build_exit_plan(
                config=config,
                state=state,
                signal_price=signal_price,
                rules=market_rules,
                reason=sell_reason,
            )
            if exit_plan.allowed:
                decision_action = "SELL"
                decision_reason = f"exit trigger {sell_reason} approved"
                decision_reasons = (
                    f"position qty={state.position.qty:.6f} entry={state.position.entry_price:.4f}",
                    f"exit trigger={sell_reason}",
                    f"exit qty={exit_plan.qty:.6f}",
                )
            else:
                decision_action = "SKIP SELL"
                decision_reason = f"exit blocked: {exit_plan.reason}"
                decision_reasons = (
                    f"position qty={state.position.qty:.6f} entry={state.position.entry_price:.4f}",
                    f"exit trigger={sell_reason}",
                    f"blocked={exit_plan.reason}",
                )
        else:
            decision_reason = "position open but no exit trigger"
            decision_reasons = (
                f"position qty={state.position.qty:.6f} entry={state.position.entry_price:.4f}",
                f"stop={state.position.stop_loss:.4f} tp={state.position.take_profit:.4f}",
                f"signal={signal or 'hold'}",
            )
    else:
        if signal == "buy" and htf_ok:
            entry_plan = build_entry_plan(
                config=config,
                state=state,
                available_quote=available_quote,
                signal_price=signal_price,
                candle_time=candle_time,
                rules=market_rules,
            )
            if entry_plan.allowed:
                decision_action = "BUY"
                decision_reason = "buy signal passed sizing and filters"
                decision_reasons = (
                    f"signal=buy",
                    f"available_quote={available_quote:.4f}",
                    f"quote_budget={entry_plan.quote_budget:.4f}",
                    f"qty={entry_plan.estimated_qty:.6f}",
                )
            else:
                decision_action = "SKIP BUY"
                decision_reason = f"entry blocked: {entry_plan.reason}"
                decision_reasons = (
                    f"signal=buy",
                    f"available_quote={available_quote:.4f}",
                    f"blocked={entry_plan.reason}",
                )
        elif signal == "buy":
            decision_reason = "buy signal blocked by HTF filter"
            decision_reasons = (
                "signal=buy",
                f"htf_ok={htf_ok}",
                f"htf={htf_text or 'off'}",
            )
        elif signal == "sell":
            decision_reason = "sell signal while flat"
            decision_reasons = (
                "flat account",
                "sell signal ignored because no long position is open",
            )
        else:
            decision_reason = "no long entry signal"
            decision_reasons = (
                f"signal={signal or 'hold'}",
                f"htf_ok={htf_ok}",
                f"ema_cross_up={gates.get('crossed_up', False)}",
                f"ema_cross_down={gates.get('crossed_down', False)}",
                f"rsi_buy_ok={gates.get('rsi_buy_ok', False)}",
                f"rsi_sell_ok={gates.get('rsi_sell_ok', False)}",
            )

    if decision_action in {"BUY", "SELL", "SKIP BUY", "SKIP SELL"}:
        decision_path = "manual ticket" if config.execution_mode == "manual" else "auto live order"

    report = ReadonlyReport(
        venue="binance",
        symbol=config.symbol,
        timeframe=config.timeframe,
        scanned_at=state.account_snapshot.captured_at if state.account_snapshot is not None else candle_time,
        bot_mode=config.bot_mode,
        execution_mode=config.execution_mode,
        selection_mode=config.selection_mode,
        use_testnet=config.use_testnet,
        enable_live_trading=config.enable_live_trading,
        order_test_before_submit=config.order_test_before_submit,
        selection_note=selection_note,
        selection=selection,
        adaptive_note=adaptive_note,
        adaptive_report=adaptive_report,
        account_snapshot=state.account_snapshot,
        open_orders=list(state.open_orders),
        position=state.position,
        signal=signal,
        signal_price=signal_price,
        live_price=live_price,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        rsi=rsi,
        htf_text=htf_text,
        htf_ok=htf_ok,
        available_quote=available_quote,
        gates=gates,
        sell_reason=sell_reason,
        decision_action=decision_action,
        decision_reason=decision_reason,
        decision_reasons=decision_reasons,
        decision_path=decision_path,
        blocked_by="live_readonly (no submit/test/cancel)",
        entry_plan=entry_plan,
        exit_plan=exit_plan,
        holding_signals=list(holding_signals or []),
    )
    return report


def _compact_text(value: str, *, limit: int = 160) -> str:
    collapsed = " ".join((value or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(0, limit - 1)].rstrip() + "…"


def _position_state(report: ReadonlyReport, *, price_precision: int = 4) -> str:
    if report.position is None:
        return "flat"
    return (
        f"long:{report.position.qty:.6f}:{report.position.entry_price:.{price_precision}f}:"
        f"{report.position.stop_loss:.{price_precision}f}:{report.position.take_profit:.{price_precision}f}"
    )


def _entry_state(report: ReadonlyReport, *, price_precision: int = 4) -> str:
    if report.entry_plan is None:
        return ""
    return (
        f"entry:{int(report.entry_plan.allowed)}:{report.entry_plan.quote_budget:.4f}:"
        f"{report.entry_plan.estimated_qty:.6f}:{report.entry_plan.stop_loss:.{price_precision}f}:"
        f"{report.entry_plan.take_profit:.{price_precision}f}:{_compact_text(report.entry_plan.reason, limit=120)}"
    )


def _exit_state(report: ReadonlyReport) -> str:
    if report.exit_plan is None:
        return ""
    return (
        f"exit:{int(report.exit_plan.allowed)}:{report.exit_plan.qty:.6f}:"
        f"{_compact_text(report.exit_plan.reason, limit=120)}"
    )


def readonly_notification_key(report: ReadonlyReport) -> str:
    selection_state = ""
    if report.selection is not None:
        selection_state = _compact_text(report.selection.summary, limit=200)
    elif report.selection_note:
        selection_state = _compact_text(report.selection_note, limit=200)
    adaptive_state = ""
    if report.adaptive_report is not None:
        adaptive_state = _compact_text(report.adaptive_report.summary(), limit=200)
    elif report.adaptive_note:
        adaptive_state = _compact_text(report.adaptive_note, limit=200)
    reasons_state = " || ".join(_compact_text(reason, limit=120) for reason in report.decision_reasons[:3])
    open_orders_state = ",".join(
        f"{order.side}:{order.order_type}:{order.status}:{order.qty:.6f}:{order.stop_price:.4f}"
        for order in report.open_orders[:3]
    )
    return "|".join(
        [
            report.symbol,
            report.timeframe,
            report.signal or "hold",
            report.decision_action,
            _compact_text(report.decision_reason, limit=200),
            reasons_state,
            "1" if report.htf_ok else "0",
            _position_state(report),
            report.sell_reason,
            selection_state,
            adaptive_state,
            _entry_state(report),
            _exit_state(report),
            open_orders_state,
        ]
    )


def readonly_decision_summary_key(report: ReadonlyReport) -> str:
    gate_state = ",".join(
        f"{name}={int(bool(report.gates.get(name, False)))}"
        for name in ("crossed_up", "crossed_down", "rsi_buy_ok", "rsi_sell_ok", "buy_ready", "sell_ready")
    )
    return "|".join(
        [
            report.symbol,
            report.timeframe,
            report.signal or "hold",
            report.decision_action,
            _compact_text(report.decision_reason, limit=200),
            f"live={report.live_price:.4f}",
            f"signal_price={report.signal_price:.4f}",
            f"ema_fast={report.ema_fast:.4f}",
            f"ema_slow={report.ema_slow:.4f}",
            f"rsi={report.rsi:.2f}",
            f"quote={report.available_quote:.2f}",
            "1" if report.htf_ok else "0",
            gate_state,
            _position_state(report),
            _entry_state(report),
            _exit_state(report),
            _compact_text(report.sell_reason, limit=120),
        ]
    )


def format_live_readonly_notification(
    report: ReadonlyReport,
    *,
    include_selection: bool = False,
    include_adaptive: bool = False,
    reminder: bool = False,
    compact: bool = False,
) -> str:
    title = "[BINANCE READONLY HEARTBEAT]" if reminder else ("[BINANCE READONLY COMPACT]" if compact else "[BINANCE READONLY]")
    exposure = (
        f"long qty={report.position.qty:.6f} (~{report.current_exposure_notional:.2f})"
        if report.position is not None
        else "flat"
    )
    price_line = (
        f"Price: `{report.live_price:.4f}` | Signal px: `{report.signal_price:.4f}` | "
        f"RSI: `{report.rsi:.2f}` | EMA: `{report.ema_fast:.4f}/{report.ema_slow:.4f}`"
    )
    action_line = f"Action: `{report.decision_action}` | Signal: `{report.signal or 'hold'}` | HTF: `{report.htf_ok}` | Exposure: `{exposure}`"
    lines = [
        title,
        f"Pair: `{report.symbol}` | TF: `{report.timeframe}`",
        action_line,
        price_line,
        f"Reason: `{_compact_text(report.decision_reason or 'none', limit=220)}` | Quote free: `{report.quote_free:.4f}`",
    ]
    if include_selection:
        if report.selection is not None:
            lines.append(f"Selected market: `{_compact_text(report.selection.summary, limit=220)}`")
        elif report.selection_note:
            lines.append(f"Selected market: `{_compact_text(report.selection_note, limit=220)}`")
    if compact:
        if report.account_snapshot is not None:
            dust_assets = len(report.account_snapshot.dust_holdings or [])
            tradable_holdings = sum(1 for item in report.holding_signals if item.tradable)
            blocked_holdings = sum(1 for item in report.holding_signals if not item.tradable)
            wallet_only_assets = sum(
                1
                for item in (report.account_snapshot.holdings or [])
                if item.asset not in {report.account_snapshot.quote_asset}
                and item.asset not in {dust.asset for dust in (report.account_snapshot.dust_holdings or [])}
                and not (report.position is not None and item.asset == report.account_snapshot.base_asset)
            )
            lines.append(
                f"Owned assets: wallet_only=`{wallet_only_assets}` tradable=`{tradable_holdings}` blocked=`{blocked_holdings}` dust=`{dust_assets}`"
            )
        if report.sell_reason:
            lines.append(f"Exit trigger: `{_compact_text(report.sell_reason, limit=180)}`")
        if report.entry_plan is not None:
            lines.append(
                f"Entry preview: quote=`{report.entry_plan.quote_budget:.4f}` qty=`{report.entry_plan.estimated_qty:.6f}`"
            )
        elif report.exit_plan is not None:
            lines.append(f"Exit preview: qty=`{report.exit_plan.qty:.6f}`")
        return "\n".join(lines)
    if report.position is not None:
        lines.append(
            f"Position: `long qty={report.position.qty:.6f} entry={report.position.entry_price:.4f} stop={report.position.stop_loss:.4f} tp={report.position.take_profit:.4f}`"
        )
    else:
        lines.append("Position: `flat`")
    if include_adaptive:
        if report.adaptive_report is not None:
            lines.append(f"Adaptive summary: `{_compact_text(report.adaptive_report.summary(), limit=220)}`")
        elif report.adaptive_note:
            lines.append(f"Adaptive summary: `{_compact_text(report.adaptive_note, limit=220)}`")
    for reason in report.decision_reasons[:3]:
        lines.append(f"- {reason}")
    if report.sell_reason:
        lines.append(f"Exit trigger: `{report.sell_reason}`")
    if report.entry_plan is not None:
        lines.append(
            f"Entry preview: quote=`{report.entry_plan.quote_budget:.4f}` qty=`{report.entry_plan.estimated_qty:.6f}` sl=`{report.entry_plan.stop_loss:.4f}` tp=`{report.entry_plan.take_profit:.4f}`"
        )
        if report.entry_plan.market_warning:
            lines.append(f"Entry warning: {report.entry_plan.market_warning}")
    if report.exit_plan is not None:
        lines.append(f"Exit preview: qty=`{report.exit_plan.qty:.6f}`")
        if report.exit_plan.market_warning:
            lines.append(f"Exit warning: {report.exit_plan.market_warning}")
    if report.report_path is not None or report.report_json_path is not None:
        lines.append(f"Reports: `{report.report_path or ''}` | `{report.report_json_path or ''}`")
    return "\n".join(lines)


def render_live_readonly_report(report: ReadonlyReport) -> str:
    lines = [
        f"Binance live read-only report for venue={report.venue} at {report.scanned_at}",
        "",
    ]
    if report.report_path is not None or report.report_json_path is not None:
        lines.append(
            f"Report files: `{report.report_path or ''}` | `{report.report_json_path or ''}`"
        )
        lines.append("")
    lines.extend(report.why_lines())
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def write_live_readonly_report(report: ReadonlyReport, path: Path, json_path: Path | None = None) -> tuple[Path, Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    report_path, report_json_path = _readonly_report_paths(path, json_path)
    report_json_path.parent.mkdir(parents=True, exist_ok=True)
    report.report_path = report_path
    report.report_json_path = report_json_path
    report_path.write_text(render_live_readonly_report(report), encoding="utf-8")
    report_json_path.write_text(report.to_json(), encoding="utf-8")
    return report_path, report_json_path
