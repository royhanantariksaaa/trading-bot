# Trading Bot Refactor Plan

## Goal

Turn the current repo from a **Binance Spot supervised/manual ticket bot** into a **single-symbol, long-only, automated Binance Spot bot** that is restart-safe, exchange-safe, and ready for controlled live trading.

This plan keeps the current strategy scope intentionally narrow:

- single symbol at a time
- spot only
- long only
- closed-candle entries by default
- one open position at a time

That scope is enough to become production-usable without overcomplicating the first live version.

---

## What the repo is today

The repo already has useful separation:

- `strategy.py` for EMA/RSI signal logic
- `risk.py` for basic position sizing
- `exchange.py` for market data and market-rule lookup
- `tickets.py` for manual execution tickets
- `log_execution.py` / `review_day.py` for operator bookkeeping
- `backtest.py` for historical simulation
- `paper_wallet.py` for simulated position accounting
- `state.py` for a small runtime JSON state

That is a good foundation. The main problem is that the runtime is still **ticket-driven**, while a real trading bot must be **position-driven**.

Right now the runtime loop creates BUY/SELL tickets, but the trading engine does not persist a real order/position lifecycle. That is the core refactor.

---

## Target architecture

```text
market data -> strategy -> risk -> execution plan -> exchange -> fills -> state -> reconcile -> reporting
```

### Core rule

**A ticket must not be the source of truth for a trade.**

The source of truth must be a persistent state model containing:

- current position
- open orders
- last processed candle
- last submitted client order id
- realized pnl
- cooldown / kill-switch state
- reconciliation timestamp

Tickets can still exist, but only as:

- optional approval workflow
- audit trail
- operator UX

---

## New core data models

Create a small `models.py` and move shared runtime objects there.

### `PositionState`

```python
@dataclass
class PositionState:
    symbol: str
    side: str                   # LONG
    qty: float
    entry_price: float
    stop_loss: float
    take_profit: float
    opened_at: str
    entry_order_id: str = ""
    entry_client_order_id: str = ""
    status: str = "OPEN"
```

### `OrderState`

```python
@dataclass
class OrderState:
    symbol: str
    side: str
    order_type: str
    order_id: str
    client_order_id: str
    status: str
    qty: float = 0.0
    quote_order_qty: float = 0.0
    price: float = 0.0
    stop_price: float = 0.0
    submitted_at: str = ""
    updated_at: str = ""
```

### `BotState`

```python
@dataclass
class BotState:
    last_processed_candle_time: str = ""
    last_signal_candle_time: str = ""
    last_order_client_id: str = ""
    realized_pnl_today: float = 0.0
    realized_pnl_date: str = ""
    consecutive_losses: int = 0
    daily_trade_count: int = 0
    cooldown_until_candle_time: str = ""
    position: PositionState | None = None
    open_orders: list[OrderState] = field(default_factory=list)
    pending_ticket_id: str = ""
    pending_action: str = ""
    pending_created_at: str = ""
    last_exchange_sync_at: str = ""
```

### `AccountSnapshot`

```python
@dataclass
class AccountSnapshot:
    quote_free: float
    quote_locked: float
    base_free: float
    base_locked: float
    maker_fee: float | None = None
    taker_fee: float | None = None
```

---

## Module boundaries after refactor

### `config.py`

Keep environment parsing, but add explicit operational modes:

- `BOT_MODE = paper | live`
- `EXECUTION_MODE = manual | auto`
- `APPROVAL_MODE = none | terminal | discord`
- `RECONCILE_ON_START = true`
- `USE_TESTNET = true | false`
- `ORDER_STYLE = market | limit`
- `ENTRY_SIZE_MODE = quote_budget | quantity`

Also validate:

- API credentials exist for live mode
- webhook optional, never required for execution
- testnet/live are mutually explicit

### `strategy.py`

Keep this pure.

Input:

- candles
- optional higher timeframe filter values

Output:

- `SignalDecision(action, reason, strategy_values, candle_time)`

No exchange calls. No file writes. No order placement.

### `risk.py`

Expand this from a single calculator into a real risk gate.

Add:

- `can_open_new_position(...)`
- `build_entry_plan(...)`
- `build_exit_plan(...)`
- daily loss guard
- max trade count per day
- cooldown enforcement
- duplicate-signal prevention
- fee/slippage buffer
- min notional / precision / step-size validation
- max position / free balance validation

### `exchange.py`

This should become the **only exchange-facing module**.

Add wrappers for:

- `fetch_ohlcv(...)`
- `get_exchange_info(...)`
- `get_account_snapshot(...)`
- `get_open_orders(...)`
- `get_order(...)`
- `place_market_buy(...)`
- `place_market_sell(...)`
- `place_exit_orders(...)`
- `cancel_order(...)`
- `cancel_all_symbol_orders(...)`
- `fetch_recent_fills(...)`

Also add a market-rules object that normalizes:

- price tick size
- quantity step size
- min/max quantity
- market lot size
- min/max notional
- order count caps

### `state.py`

Move from a tiny JSON blob to a robust storage layer.

Recommended path:

- keep JSON only during refactor if speed matters
- migrate to SQLite before live automation

Why SQLite is better:

- safer updates
- easier reconciliation
- easier order journal queries
- less fragile than rewriting CSV/JSON repeatedly

### `tickets.py`

Keep it, but demote it to an optional audit/approval layer.

Good uses after refactor:

- operator notifications
- manual override queue
- compliance/audit history
- paper review

Bad use after refactor:

- being the only representation of an open trade

### `paper_wallet.py`

Keep it only for paper mode and backtest simulation.

Add:

- persistent save/load
- fee model
- slippage model
- funding of quote/base balances
- position reconstruction on restart

### `backtest.py`

Keep shared strategy/risk logic, but improve execution realism:

- next-candle/open fills or slippage-aware fills
- fee assumptions
- stop/take-profit on candle high/low or true order simulation
- report max adverse excursion / max favorable excursion if possible

### `notifier.py`

Keep notifications separate from execution.

It should never be required for order placement.

### New files to add

#### `models.py`
Shared dataclasses.

#### `execution.py`
Turns a strategy/risk output into a submitted order and post-submit state updates.

#### `reconcile.py`
Compares local state to exchange truth at startup and after failures.

#### `storage.py`
Read/write abstraction for JSON or SQLite.

#### `healthcheck.py`
Simple heartbeat, ping, exchange availability, last successful cycle time.

#### `tests/`
Unit tests for strategy, risk, rounding, ticket lifecycle, reconciliation.

---

## File-by-file changes from the current repo

### `main.py`

Refactor into an orchestrator only.

Target loop:

1. load config
2. load state
3. reconcile if needed
4. fetch candles/account/open orders
5. compute signal on one candle only
6. pass signal through risk engine
7. build execution plan
8. execute plan (paper/manual/auto)
9. persist result
10. notify/log

It should stop doing business logic inline.

### `risk.py`

Replace the current one-function design with:

- sizing
- rule enforcement
- plan building
- rejection reasons

Return structured results, not just a float.

### `state.py`

Add full position/order state and do **not** wipe pending items just because the calendar date changed.

Reset only the day-scoped counters, not the open-trade state.

### `exchange.py`

Convert rule checking from “warning only” to “validate and round before submit.”

### `log_execution.py`

Refactor so it can also call a shared function like:

```python
apply_fill_to_state(fill_record, state, account_snapshot)
```

That way manual and automated fills use the same bookkeeping path.

### `update_ticket.py`

If you keep manual supervision, ticket state changes should also update `runtime_state` when relevant.

Example:

- `approved` should clear pending approval state
- `denied` should clear pending approval state
- `executed` should attach to position state if this is an entry
- `closed` should close the linked position if this is an exit

---

## Migration phases

## Phase 0 — Security and repo hygiene

Do this first.

- remove `.env` from the public repo
- rotate Binance keys and Discord webhooks if they were ever committed
- add `.gitignore` for:
  - `.env`
  - `__pycache__/`
  - `*.csv` generated logs
  - `runtime_state.json`
  - `*.db`
- pin dependency versions

## Phase 1 — Make paper mode actually autonomous

Before live mode, paper mode must become a true trading engine.

Requirements:

- BUY signals call `wallet.enter_long(...)`
- exit logic calls `wallet.exit_long(...)`
- paper balance and paper position persist across restarts
- runtime state reflects paper entries/exits
- daily pnl comes from actual executed paper closes

This is the fastest way to prove the engine works end-to-end.

## Phase 2 — Add robust persistent state

Before any live order placement:

- persist open position
- persist open orders
- persist last submitted client order id
- persist last processed candle time
- persist daily counters without losing overnight order state

## Phase 3 — Add reconciliation

On startup and after failures:

- pull balances
- pull open orders
- pull recent order/fill history
- rebuild position state
- clear or recover orphaned orders
- mark stale local state as repaired

Without reconciliation, restart safety is not real.

## Phase 4 — Add Binance execution adapter

Implement:

- idempotent order submission
- client order ids
- rounded quantities/prices
- exchange filter enforcement
- timeout/unknown status handling
- backoff on rate limits

## Phase 5 — Add user data stream and health layer

For real live operation, add:

- account/order/fill stream
- auto reconnect
- heartbeat
- stalled-loop alert
- last successful sync time

## Phase 6 — Controlled live rollout

Only after all earlier phases pass.

Suggested progression:

1. paper mode for several days
2. Binance Spot Test Network
3. `/api/v3/order/test`
4. tiny live size on one symbol
5. gradual notional increase only after stable operations

---

## Recommended storage design

### Minimum acceptable

- JSON for current bot state
- CSV for audit logs

### Better

- SQLite for runtime/order/position state
- CSV export only for reports

### Suggested tables

- `bot_state`
- `positions`
- `orders`
- `fills`
- `signals`
- `tickets`
- `daily_metrics`

---

## Recommended execution model

### Entry

1. Signal generated on closed candle
2. Risk engine approves
3. Execution plan built
4. Quantity/quote budget rounded and validated
5. Order submitted with client order id
6. Fill confirmed from exchange truth
7. Position state persisted
8. Protective exits armed or software-managed if intentionally chosen

### Exit

1. Exit trigger detected or protective order fires
2. Exit order submitted
3. Fill confirmed
4. Position closed in state
5. Realized pnl updated
6. Cooldown started

---

## Definition of done for the refactor

The bot is structurally ready when all of these are true:

- paper mode can enter and exit positions without manual file edits
- a restart does not lose open position or pending orders
- exchange filters are enforced before submit
- quantities/prices are rounded correctly
- order submission is idempotent
- fills update position and pnl state automatically
- startup reconciliation repairs local state
- no-trade/status/approval UX is optional, not required for execution
- test coverage exists for rounding, sizing, duplicate prevention, and reconciliation

---

## Recommended next implementation order

1. fix runtime so paper mode really opens/closes positions
2. expand persistent state
3. wire execution updates back into state
4. add reconciliation
5. harden Binance execution adapter
6. add websocket user-data tracking
7. move to testnet, then tiny live mode

That sequence gives the fastest path from the current repo to a reliable first live version.
