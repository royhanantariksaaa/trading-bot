from __future__ import annotations

import unittest

from app.binance.models import OrderState, PositionState
from app.binance.state import BotState, pending_ticket_clear_reason


class PendingTicketHygieneTest(unittest.TestCase):
    def test_clears_resolved_ticket_when_flat_and_no_open_orders(self) -> None:
        state = BotState(pending_ticket_id="abc12345", pending_action="BUY")

        reason = pending_ticket_clear_reason(
            state,
            bot_mode="live",
            execution_mode="manual",
            ticket_status="approved",
            ticket_exists=True,
        )

        self.assertEqual(reason, "resolved_ticket")

    def test_clears_missing_ticket_when_flat_and_no_open_orders(self) -> None:
        state = BotState(pending_ticket_id="abc12345", pending_action="BUY")

        reason = pending_ticket_clear_reason(
            state,
            bot_mode="live",
            execution_mode="manual",
            ticket_exists=False,
        )

        self.assertEqual(reason, "missing_ticket")

    def test_clears_incompatible_pending_ticket_in_paper_auto_mode(self) -> None:
        state = BotState(pending_ticket_id="abc12345", pending_action="BUY")

        reason = pending_ticket_clear_reason(
            state,
            bot_mode="paper",
            execution_mode="auto",
            ticket_status="pending",
            ticket_exists=True,
        )

        self.assertEqual(reason, "incompatible_auto_mode")

    def test_keeps_pending_ticket_when_position_is_open(self) -> None:
        state = BotState(
            pending_ticket_id="abc12345",
            pending_action="SELL",
            position=PositionState(
                symbol="SOL/USDT",
                side="LONG",
                qty=0.5,
                entry_price=100.0,
                stop_loss=98.0,
                take_profit=103.0,
                opened_at="2026-03-18T00:00:00+00:00",
            ),
        )

        reason = pending_ticket_clear_reason(
            state,
            bot_mode="paper",
            execution_mode="auto",
            ticket_status="pending",
            ticket_exists=True,
        )

        self.assertEqual(reason, "")

    def test_keeps_pending_ticket_when_open_orders_exist(self) -> None:
        state = BotState(
            pending_ticket_id="abc12345",
            pending_action="SELL",
            open_orders=[
                OrderState(
                    symbol="SOL/USDT",
                    side="SELL",
                    order_type="STOP_LOSS",
                    order_id="1",
                    client_order_id="client-1",
                    status="OPEN",
                    qty=0.5,
                    stop_price=98.0,
                    submitted_at="2026-03-18T00:00:00+00:00",
                    updated_at="2026-03-18T00:00:00+00:00",
                )
            ],
        )

        reason = pending_ticket_clear_reason(
            state,
            bot_mode="paper",
            execution_mode="auto",
            ticket_status="pending",
            ticket_exists=True,
        )

        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()
