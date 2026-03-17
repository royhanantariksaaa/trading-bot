from trading_bot.polymarket.config import Config
from trading_bot.polymarket.maker import apply_fill, compute_quote_plan, mark_to_market
from trading_bot.polymarket.models import BookSnapshot, BotState, FillResult, QuoteLevel


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


def test_quote_plan_is_symmetric_when_flat():
    config = Config(token_id="123", quote_size=10, base_spread=0.04, edge_offset=0.01)
    state = BotState()
    plan = compute_quote_plan(config, state, sample_book())
    assert plan.bid_price == 0.47
    assert plan.ask_price == 0.53
    assert plan.buy_size == 10
    assert plan.sell_size == 10


def test_inventory_skew_pushes_quotes_down_when_long():
    config = Config(token_id="123", quote_size=10, inventory_skew_per_share=0.0025)
    state = BotState(inventory=10)
    plan = compute_quote_plan(config, state, sample_book())
    assert plan.bid_price < 0.47
    assert plan.ask_price < 0.53


def test_apply_fill_updates_state_and_mark():
    state = BotState()
    apply_fill(state, FillResult(side="BUY", price=0.50, size=10, notional=5.0, reason="test"))
    assert state.inventory == 10
    assert state.cash == -5.0
    assert mark_to_market(state, 0.55) == 0.5
