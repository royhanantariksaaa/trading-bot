from __future__ import annotations

import json
import unittest
from pathlib import Path

from trading_bot.binance.state import load_state, today_str


class StateRolloverTest(unittest.TestCase):
    def test_day_rollover_resets_daily_counters_but_keeps_live_state(self) -> None:
        path = Path(__file__).resolve().parent / ".tmp_runtime_state.json"
        try:
            path.write_text(
                json.dumps(
                    {
                        "last_processed_candle_time": "2026-03-17T00:00:00+00:00",
                        "last_signal_candle_time": "2026-03-17T00:15:00+00:00",
                        "realized_pnl_today": -3.5,
                        "realized_pnl_date": "2026-03-16",
                        "daily_trade_count": 2,
                        "pending_ticket_id": "abc12345",
                        "pending_action": "BUY",
                        "pending_created_at": "2026-03-16T23:59:00+00:00",
                        "position": {
                            "symbol": "SOL/USDT",
                            "side": "LONG",
                            "qty": 0.5,
                            "entry_price": 100.0,
                            "stop_loss": 98.0,
                            "take_profit": 103.0,
                            "opened_at": "2026-03-16T12:00:00+00:00",
                            "entry_order_id": "1",
                            "entry_client_order_id": "client-1",
                            "status": "OPEN",
                            "entry_fee_usd": 0.1,
                        },
                        "open_orders": [
                            {
                                "symbol": "SOL/USDT",
                                "side": "SELL",
                                "order_type": "STOP_LOSS",
                                "order_id": "2",
                                "client_order_id": "client-2",
                                "status": "OPEN",
                                "qty": 0.5,
                                "executed_qty": 0.0,
                                "quote_order_qty": 0.0,
                                "quote_executed": 0.0,
                                "price": 0.0,
                                "stop_price": 98.0,
                                "submitted_at": "2026-03-16T12:00:01+00:00",
                                "updated_at": "2026-03-16T12:00:01+00:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            state = load_state(path)
        finally:
            if path.exists():
                path.unlink()

        self.assertEqual(state.realized_pnl_today, 0.0)
        self.assertEqual(state.realized_pnl_date, today_str())
        self.assertEqual(state.daily_trade_count, 0)
        self.assertEqual(state.pending_ticket_id, "abc12345")
        self.assertIsNotNone(state.position)
        self.assertEqual(len(state.open_orders), 1)


if __name__ == "__main__":
    unittest.main()
