from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import csv
from pathlib import Path

from trading_bot.binance.models import PositionState
from trading_bot.binance.state import BotState


@dataclass
class Position:
    entry_price: float
    qty: float
    stop_loss: float
    take_profit: float
    entry_time: str
    entry_fee_usd: float = 0.0


@dataclass
class PaperWallet:
    balance_usdt: float
    trades_path: Path
    fee_rate: float = 0.0
    slippage_pct: float = 0.0
    position: Position | None = None
    _initialized: bool = field(default=False, init=False)

    @classmethod
    def from_state(
        cls,
        state: BotState,
        trades_path: Path,
        starting_balance: float,
        fee_rate: float = 0.0,
        slippage_pct: float = 0.0,
    ) -> PaperWallet:
        position = None
        if state.position is not None:
            position = Position(
                entry_price=state.position.entry_price,
                qty=state.position.qty,
                stop_loss=state.position.stop_loss,
                take_profit=state.position.take_profit,
                entry_time=state.position.opened_at,
                entry_fee_usd=state.position.entry_fee_usd,
            )
        balance = state.paper_balance_usdt if state.paper_balance_usdt > 0 else starting_balance
        return cls(
            balance_usdt=balance,
            trades_path=trades_path,
            fee_rate=fee_rate,
            slippage_pct=slippage_pct,
            position=position,
        )

    def sync_to_state(self, state: BotState) -> None:
        state.paper_balance_usdt = self.balance_usdt
        if self.position is None:
            return
        state.position = PositionState(
            symbol=state.position.symbol if state.position is not None else "",
            side="LONG",
            qty=self.position.qty,
            entry_price=self.position.entry_price,
            stop_loss=self.position.stop_loss,
            take_profit=self.position.take_profit,
            opened_at=self.position.entry_time,
            entry_order_id=state.position.entry_order_id if state.position is not None else "",
            entry_client_order_id=state.position.entry_client_order_id if state.position is not None else "",
            entry_fee_usd=self.position.entry_fee_usd,
        )

    def _ensure_csv(self) -> None:
        if self._initialized:
            return
        self.trades_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.trades_path.exists():
            with self.trades_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp",
                    "side",
                    "price",
                    "qty",
                    "notional",
                    "fee_usd",
                    "pnl",
                    "balance_usdt",
                    "note",
                ])
        self._initialized = True

    def log_trade(self, side: str, price: float, qty: float, fee_usd: float, pnl: float, note: str) -> None:
        self._ensure_csv()
        with self.trades_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now(timezone.utc).isoformat(),
                side,
                round(price, 6),
                round(qty, 8),
                round(price * qty, 6),
                round(fee_usd, 6),
                round(pnl, 6),
                round(self.balance_usdt, 6),
                note,
            ])

    def can_enter(self) -> bool:
        return self.position is None

    def enter_long(self, price: float, qty: float, stop_loss: float, take_profit: float) -> tuple[float, float]:
        if self.position is not None:
            return 0.0, 0.0
        if qty <= 0:
            return 0.0, 0.0

        fill_price = price * (1 + self.slippage_pct)
        notional = fill_price * qty
        fee_usd = notional * self.fee_rate
        total_cost = notional + fee_usd
        if total_cost > self.balance_usdt:
            return 0.0, 0.0

        self.balance_usdt -= total_cost
        self.position = Position(
            entry_price=fill_price,
            qty=qty,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_time=datetime.now(timezone.utc).isoformat(),
            entry_fee_usd=fee_usd,
        )
        self.log_trade("BUY", fill_price, qty, fee_usd, 0.0, "entry")
        return fill_price, fee_usd

    def exit_long(self, price: float, qty: float | None = None, note: str = "exit") -> tuple[float, float, float]:
        if self.position is None:
            return 0.0, 0.0, 0.0

        close_qty = self.position.qty if qty is None else min(qty, self.position.qty)
        if close_qty <= 0:
            return 0.0, 0.0, 0.0

        fill_price = price * (1 - self.slippage_pct)
        proceeds = fill_price * close_qty
        exit_fee_usd = proceeds * self.fee_rate
        entry_fee_share = 0.0
        if self.position.entry_fee_usd > 0 and self.position.qty > 0:
            entry_fee_share = self.position.entry_fee_usd * (close_qty / self.position.qty)
        pnl = proceeds - exit_fee_usd - (self.position.entry_price * close_qty) - entry_fee_share
        self.balance_usdt += proceeds - exit_fee_usd

        remaining_qty = self.position.qty - close_qty
        if remaining_qty > 1e-12:
            self.position.qty = remaining_qty
            self.position.entry_fee_usd = max(0.0, self.position.entry_fee_usd - entry_fee_share)
        else:
            self.position = None

        self.log_trade("SELL", fill_price, close_qty, exit_fee_usd, pnl, note)
        return fill_price, exit_fee_usd, pnl
