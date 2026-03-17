from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import csv
from pathlib import Path


@dataclass
class Position:
    entry_price: float
    qty: float
    stop_loss: float
    take_profit: float
    entry_time: str


@dataclass
class PaperWallet:
    balance_usdt: float
    trades_path: Path
    position: Position | None = None
    last_exit_index: int | None = None
    _initialized: bool = field(default=False, init=False)

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
                    "pnl",
                    "balance_usdt",
                    "note",
                ])
        self._initialized = True

    def log_trade(self, side: str, price: float, qty: float, pnl: float, note: str) -> None:
        self._ensure_csv()
        with self.trades_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now(timezone.utc).isoformat(),
                side,
                round(price, 6),
                round(qty, 8),
                round(price * qty, 6),
                round(pnl, 6),
                round(self.balance_usdt, 6),
                note,
            ])

    def can_enter(self, candle_index: int, cooldown_candles: int) -> bool:
        if self.position is not None:
            return False
        if self.last_exit_index is None:
            return True
        return candle_index - self.last_exit_index > cooldown_candles

    def enter_long(self, price: float, qty: float, stop_loss: float, take_profit: float) -> None:
        if self.position is not None:
            return
        notional = price * qty
        if notional > self.balance_usdt or qty <= 0:
            return
        self.balance_usdt -= notional
        self.position = Position(
            entry_price=price,
            qty=qty,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_time=datetime.now(timezone.utc).isoformat(),
        )
        self.log_trade("BUY", price, qty, 0.0, "entry")

    def exit_long(self, price: float, candle_index: int, note: str = "exit") -> float:
        if self.position is None:
            return 0.0
        proceeds = price * self.position.qty
        cost = self.position.entry_price * self.position.qty
        pnl = proceeds - cost
        self.balance_usdt += proceeds
        qty = self.position.qty
        self.position = None
        self.last_exit_index = candle_index
        self.log_trade("SELL", price, qty, pnl, note)
        return pnl
