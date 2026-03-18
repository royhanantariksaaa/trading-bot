import unittest
from pathlib import Path

from app.polymarket.config import Config
from app.polymarket.maker import (
    apply_fill,
    build_supervision_report,
    compute_quote_plan,
    mark_to_market,
    maybe_flatten_on_halt,
    update_budget_state,
    write_supervision_report,
)
from app.polymarket.models import BookSnapshot, BotState, FillResult, QuoteLevel


def sample_book() -> BookSnapshot:
    return BookSnapshot(
        token_id="123",
        tick_size=0.01,
        min_order_size=5,
        best_bid=0.48,
        best_ask=0.52,
        bids=[QuoteLevel(0.48, 100)],
        asks=[QuoteLevel(0.52, 100)],
    )


class PolymarketMakerTest(unittest.TestCase):
    def test_quote_plan_is_symmetric_when_flat(self):
        config = Config(token_id="123", quote_size=10, base_spread=0.04, edge_offset=0.01)
        state = BotState(cash=config.starting_cash)
        plan = compute_quote_plan(config, state, sample_book())
        self.assertEqual(plan.bid_price, 0.47)
        self.assertEqual(plan.ask_price, 0.53)
        self.assertEqual(plan.buy_size, 10)
        self.assertEqual(plan.sell_size, 0)

    def test_inventory_skew_pushes_quotes_down_when_long(self):
        config = Config(token_id="123", quote_size=10, inventory_skew_per_share=0.0025)
        state = BotState(inventory=10, cash=config.starting_cash)
        plan = compute_quote_plan(config, state, sample_book())
        self.assertLess(plan.bid_price, 0.47)
        self.assertLess(plan.ask_price, 0.53)

    def test_apply_fill_updates_state_and_mark(self):
        state = BotState()
        apply_fill(state, FillResult(side="BUY", price=0.50, size=10, notional=5.0, reason="test"))
        self.assertEqual(state.inventory, 10)
        self.assertEqual(state.cash, -5.0)
        self.assertEqual(mark_to_market(state, 0.55), 0.5)

    def test_flat_stop_sells_inventory_and_marks_stopped(self):
        config = Config(token_id="123", hard_halt_mode="flat_stop")
        state = BotState(inventory=10, cash=20, halted=True, halt_reason="dd", stop_after_flatten=True, flatten_pending=True)
        fills = maybe_flatten_on_halt(config, state, sample_book())
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0].side, "SELL")
        self.assertEqual(state.inventory, 0)
        self.assertTrue(state.stopped)
        self.assertFalse(state.flatten_pending)

    def test_budget_halt_sets_flatten_pending_when_configured(self):
        config = Config(token_id="123", starting_cash=100, reserve_cash=25, max_run_loss_usd=10, hard_halt_mode="flat_stop")
        state = BotState(inventory=20, cash=80)
        note = update_budget_state(config, state, 0.40)
        self.assertIsNotNone(note)
        self.assertTrue(state.halted)
        self.assertTrue(state.flatten_pending)

    def test_supervision_report_writes_text_and_json(self):
        tmp_path = Path(__file__).resolve().parent / ".tmp_pm_supervision.txt"
        config = Config(token_id="123", supervision_report_path=tmp_path)
        state = BotState(cash=95, inventory=10, loops=3, peak_mark_to_market=100)
        book = sample_book()
        plan = compute_quote_plan(config, state, book)
        report = build_supervision_report(config, state, book, plan, notes=["ok"])
        txt_path, json_path = write_supervision_report(config.supervision_report_path, report)
        self.assertTrue(txt_path.exists())
        self.assertTrue(json_path.exists())
        text = txt_path.read_text(encoding="utf-8")
        self.assertIn("health=", text)
        self.assertIn("notes=ok", text)
        txt_path.unlink(missing_ok=True)
        json_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
