# Binance Ready Gap Analysis

## Executive summary

The current repo is **not yet ready for automated Binance trading**.

The biggest hidden problem is not only that live mode is blocked. The bigger problem is that the runtime loop is still built around **manual tickets**, while the bot does not maintain a real executable position/order state.

After reanalysis, the most important missed items are:

1. the runtime never actually opens or closes a paper position
2. stop-loss and take-profit are checked on **closed candle close price**, not by actual exchange protection or intrabar logic
3. manual approval/execution scripts do not feed back into runtime state
4. restart safety is not implemented
5. exchange filters are only warnings, not hard validation
6. timezones and daily resets are inconsistent

If you fix only the live-order placement but keep those issues, the bot will still not be safe to use.

---

## Newly discovered gaps from the second pass

## 1. Runtime never calls the paper wallet entry/exit methods

This is the most important architectural gap.

`main.py` creates manual BUY/SELL tickets, but it never calls `wallet.enter_long(...)` or `wallet.exit_long(...)`. `PaperWallet` only changes `position` and `balance_usdt` inside those methods.

So in the current runtime, the wallet can remain flat forever even while tickets are generated.

### Why this matters

- no true paper execution loop
- no position persistence path
- no automatic exit path from actual held state
- runtime behavior diverges from backtest behavior

### Fix

Before anything live-related, wire the runtime to a real execution path:

- paper entry must call `wallet.enter_long`
- paper exit must call `wallet.exit_long`
- state must persist the result

---

## 2. Backtest and runtime do not share the same execution behavior

`backtest.py` does use the wallet entry/exit methods, but runtime ticket flow does not.

That means your backtest and your live-ish runtime are not testing the same thing.

### Why this matters

A strategy that looks correct in backtest can fail operationally because the runtime has a different state machine.

### Fix

Use one shared execution flow:

- strategy decides
- risk approves
- execution applies
- storage persists

Backtest should swap only the execution adapter, not the overall control flow.

---

## 3. Stop-loss / take-profit are not real protective exits

Current logic compares stop-loss and take-profit against the chosen candle close value.

That means exits are effectively **closed-candle software exits**, not actual protective exchange orders.

### Hidden risk

A candle can trade through your stop intrabar and close back above it. The bot would miss the stop and show a better exit than you would really get.

### Fix options

#### Better first live version

- submit actual stop / take-profit orders after entry
- reconcile them after partial fills or cancellations

#### Simpler fallback

- keep software exits, but monitor faster than the strategy timeframe and use high/low-aware simulation in backtest

If you keep closed-candle stop logic in live trading, real losses can be materially larger than modeled.

---

## 4. Runtime state does not track actual open trade state

`state.py` only keeps:

- last signal candle
- pending ticket fields
- realized pnl today
- daily summary date

It does **not** keep:

- open position qty
- entry price
- stop/tp
- open order ids
- last client order id
- base/quote balance snapshot
- last exchange sync timestamp

### Why this matters

Without persistent position/order state, restart safety is impossible.

### Fix

Add full runtime position/order state immediately.

---

## 5. Restart resets the runtime wallet

`main.py` initializes a fresh `PaperWallet(balance_usdt=config.starting_balance, ...)` on startup.

`PaperWallet` itself does not load a saved position or saved balance from disk.

### Why this matters

After restart, the bot can forget:

- open paper positions
- reduced quote balance from a paper entry
- cooldown state tied to the prior position

For live trading, the equivalent bug would be catastrophic.

### Fix

On startup, reconstruct state from storage and exchange truth.

---

## 6. Manual execution logging does not update runtime state or daily pnl

`log_execution.py` writes `live_execution_log.csv` and updates ticket status, but it does not update:

- `runtime_state.json`
- open position state
- realized pnl today
- pending ticket state

### Why this matters

Your daily loss guard and status messages can become stale even if manual executions are recorded.

### Fix

Create a shared fill-application function and use it for:

- paper fills
- manual fills
- real exchange fills

---

## 7. Pending ticket state becomes stale under the default Discord workflow

With `APPROVAL_MODE=discord`, the bot sends ticket messages, but state cleanup only happens in the local terminal approval branch.

`update_ticket.py` updates the CSV ticket status but does not touch runtime state.

### Why this matters

You can end up with:

- `runtime_state.json` still showing a pending ticket after approval/denial/execution
- stale pending ticket in status messages and daily summary
- incorrect operator view of the current state

### Fix

Whenever a ticket becomes approved, denied, executed, or closed, update runtime state too.

---

## 8. Daily loss logic is not yet trustworthy for real operation

The runtime blocks new tickets if `realized_pnl_today` breaches the daily loss cap.

But after reanalysis, I do not see a full visible path that reliably updates `realized_pnl_today` from:

- manual live execution logs
- runtime paper exits
- denied / approved / closed ticket flow

### Why this matters

A bot can think it is still allowed to trade when it already hit the daily stop.

### Fix

Daily realized pnl must be updated from the same source of truth as fills/position closures.

---

## 9. Daily reset logic can drop unresolved pending state

`state.py` resets day-scoped fields when the stored date is not today, and it also clears pending ticket fields during that rollover.

### Why this matters

An unresolved overnight ticket/order can disappear from runtime state at local midnight.

### Fix

Only reset day counters on date rollover.

Do **not** erase:

- open position
- open order
- pending ticket/order references

unless reconciliation confirms they are gone.

---

## 10. Time handling is inconsistent

`PaperWallet` trade logs use UTC timestamps, while `state.py` and `review_day.py` use local `datetime.now()` date strings.

### Why this matters

You can get:

- daily pnl reset at local midnight instead of a chosen trading day boundary
- review/day counts not matching logged trades near midnight
- hard-to-debug discrepancies between runtime state and logs

### Fix

Standardize everything to timezone-aware UTC.

If you want a custom trading day boundary later, implement it explicitly.

---

## 11. `STATUS_EVERY_LOOPS=0` behavior appears inverted

The environment comments say setting `STATUS_EVERY_LOOPS=0` disables periodic status messages, but the runtime currently sends a no-trade message when the value is `0`.

### Why this matters

That setting can accidentally spam notifications.

### Fix

Make `0` truly mean disabled.

Add a test for this exact case.

---

## 12. Exchange rule handling is only advisory

`exchange.py` pulls a few market fields and can build a warning if notional or amount look too small.

That is useful for supervision, but not enough for automation.

### What is missing

Before real order placement you need hard enforcement for Binance symbol filters, including:

- `LOT_SIZE`
- `MARKET_LOT_SIZE`
- `MIN_NOTIONAL`
- `NOTIONAL`
- `PRICE_FILTER`
- open-order count limits where relevant

### Fix

Convert rule handling from “message warning” into “validate and round or reject before submit.”

---

## 13. Quantities and prices are not rounded to exchange rules

Current sizing logic returns a float quantity, but there is no full pre-submit rounding pipeline for:

- quantity step size
- market lot size
- price tick size
- post-round min notional recheck

### Why this matters

A bot can compute a theoretically valid size that Binance still rejects.

### Fix

Implement a deterministic pre-submit function:

1. compute raw size
2. round to permitted precision/step
3. re-check all filters
4. reject or reduce if needed

---

## 14. Fees and slippage are not modeled in the execution engine

`PaperWallet` and backtest pnl are basically gross pnl.

### Why this matters

A small-TP strategy can look profitable gross and unprofitable net.

### Fix

Add configurable:

- maker/taker fee assumptions
- slippage model
- spread buffer

Use them in paper mode, backtest, and live expectations.

---

## 15. Backtest fill model is optimistic

The current backtest works off candle data and uses the row close price as the execution reference.

### Why this matters

It can overstate results because it does not fully model:

- intrabar stop/tp hits
- spread
- slippage
- partial fills
- next-bar execution delay

### Fix

At minimum:

- model fees/slippage
- use next-bar/open or a clearly documented fill assumption
- test stop/tp against high/low or real protective order rules

---

## 16. Live idempotency is not implemented yet

A ready Binance bot must treat order submission as idempotent.

### Why this matters

Without idempotency, retries after timeouts/network errors can duplicate orders.

### Fix

Use Binance `newClientOrderId` and persist it before/with submission.

Recommended pattern:

- client id includes symbol + side + candle time + nonce
- persist before sending
- on retry, query by client id or order status first

---

## 17. Timeout / unknown-status handling is not in place yet

Binance documents that a request can time out with execution status unknown.

### Why this matters

A placement can succeed at the matching engine even if your request path times out.

### Fix

After ambiguous submit errors:

1. do not blindly resubmit
2. query order status
3. check user-data stream events
4. reconcile local state before any retry

---

## 18. User-data streaming is missing

For real live operation, polling alone is not enough for order/fill truth.

### Why this matters

You need real-time visibility into:

- execution reports
- balance updates
- order transitions

### Fix

Add a user-data stream consumer plus reconnect logic.

---

## 19. There is no full startup reconciliation yet

A production bot must begin by asking the exchange:

- what balances are available?
- what open orders exist?
- what fills happened recently?
- am I already in a position?

### Fix

Build `reconcile.py` and run it:

- on startup
- after connectivity issues
- after order timeouts
- after operator restarts the bot

---

## 20. Repo hygiene is not yet production-safe

The public repo currently exposes operational artifacts such as `.env`, runtime JSON, and multiple CSV logs.

### Why this matters

Even if secrets are blank today, this is not a safe production pattern.

### Fix

- remove `.env` from source control
- rotate any exposed secrets
- add `.gitignore`
- separate sample data from runtime data
- keep runtime data outside the repo directory if possible

---

## Binance-specific requirements for a ready bot

## 1. Use current exchange rules, not assumptions

Load symbol rules from exchange info and enforce them before placing orders.

Required checks include:

- lot size / market lot size
- min notional / notional range
- tick size
- max position / open-order limits where applicable

Refresh these rules on startup and periodically.

## 2. Use `newClientOrderId` for every live order

This is the cleanest idempotency anchor.

Persist it alongside local order state.

## 3. Prefer a quote-budget entry path for quote-sized market buys

Because your strategy is currently budgeted in USD/USDT (`MAX_TRADE_USD`), a Binance-compatible live path should support:

- `quoteOrderQty` for market buys, or
- quantity-based orders after full rounding/validation

For market sells that close a position, quantity-based exits are usually clearer.

## 4. Respect `recvWindow` and timestamp correctness

Signed requests depend on valid timestamps and `recvWindow` handling.

Use a small `recvWindow`, keep clock drift under control, and treat `INVALID_TIMESTAMP` as a recoverable sync problem.

## 5. Handle rate limits and backoff correctly

Monitor request weight and order counts.

On 429:

- back off immediately
- honor retry-after behavior
- never keep hammering the API

On repeated abuse, Binance can escalate to IP bans.

## 6. Use user data streams for live order truth

REST is fine for snapshots, but live order transitions should be driven by account/order events.

## 7. Reconnect websockets deliberately

Binance market streams have connection lifetime and ping/pong requirements.

Build a reconnect loop, heartbeat, and stream-resubscribe logic.

## 8. Use the Spot Test Network and order-test path before live

Before real size:

- validate order creation in test mode
- validate size/filter handling on testnet
- validate restart reconciliation
- validate ambiguous-order recovery

Remember testnet data resets can happen periodically.

---

## Recommended go-live sequence

## Stage 1 — Fix architecture

Must be done first:

- paper wallet really enters/exits
- runtime state tracks position/order
- manual fill path updates runtime state
- timezone cleanup
- status/pending-ticket cleanup

## Stage 2 — Make paper mode trustworthy

Run several days without intervention and verify:

- entries and exits line up with strategy
- daily pnl is correct
- restart does not lose state
- no duplicate entries after restart

## Stage 3 — Add Binance execution adapter

Implement:

- filter rounding/validation
- client order ids
- order query/retry logic
- live account snapshot
- open-order reconciliation

## Stage 4 — Run on Binance Spot Test Network

Validate:

- market data flow
- signed requests
- execution updates
- restart recovery
- order lifecycle consistency

## Stage 5 — Use `/api/v3/order/test`

Use it as a final sanity check for order payloads before letting the bot place real orders.

## Stage 6 — Tiny live notional only

First live deployment should use the smallest practical size on one symbol only.

Do not scale size until:

- several days of stable operations
- correct pnl accounting
- no reconciliation surprises
- no duplicate or rejected orders from preventable filter issues

---

## Must-fix before any live automation

### P0 — absolutely required

- wire runtime to real entry/exit state changes
- implement persistent position/order state
- add startup reconciliation
- update state from fills
- enforce Binance filters before submit
- add idempotent client order ids
- fix daily pnl accounting
- replace closed-candle-only software stop logic with real protection or a clearly safer execution design
- standardize UTC timestamps
- remove secrets/runtime files from repo

### P1 — strongly recommended before first real money

- websocket user-data consumer
- rate-limit/backoff handling
- timeout/unknown-status recovery
- fee/slippage model
- test coverage for sizing/rounding/reconciliation
- healthcheck and alerting

### P2 — after first stable live version

- richer monitoring
- multi-symbol support
- more advanced exit structures
- operator dashboard
- CI/CD and packaging improvements

---

## Bottom line

The current repo is a **good supervised-manual starter**, but it is still one major layer away from being a true automated Binance bot.

The single most important change is this:

> move from a ticket-centric workflow to a persistent position/order-centric execution engine.

Once that is done, the rest of the Binance hardening work becomes straightforward and testable.
