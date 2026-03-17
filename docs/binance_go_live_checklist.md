# Binance Go-Live Checklist

Use this as the final pre-live checklist for the refactored bot.

---

## Scope lock

- [ ] single symbol only for first live version
- [ ] spot only
- [ ] long only
- [ ] one open position max
- [ ] closed-candle entry logic documented

---

## Architecture

- [ ] runtime opens and closes positions through one shared execution path
- [ ] position state is persisted
- [ ] open orders are persisted
- [ ] fills update position and pnl automatically
- [ ] startup reconciliation exists
- [ ] restart does not lose position or pending orders
- [ ] any Binance selection-mode run has the intended strategy profile mode documented (`auto`, `manual`, or forced profile)

---

## Binance execution safety

- [ ] every order has a persisted `newClientOrderId`
- [ ] symbol rules are loaded from exchange info
- [ ] quantity is rounded to valid step size
- [ ] market quantity respects `MARKET_LOT_SIZE`
- [ ] order passes min notional / notional checks after rounding
- [ ] price is rounded to valid tick size where needed
- [ ] live order payload can pass `/api/v3/order/test`
- [ ] testnet execution path works end-to-end

---

## Order lifecycle

- [ ] ambiguous submit errors do not trigger blind resubmits
- [ ] bot can query order status by order id or client order id
- [ ] partial fills are handled correctly
- [ ] exit logic works after partial entry fills
- [ ] canceled and expired orders are reflected in local state
- [ ] stale orphaned orders can be reconciled and cleaned up

---

## Risk controls

- [ ] position sizing includes fee/slippage buffer
- [ ] daily loss guard is driven by actual realized pnl
- [ ] max trades per day exists
- [ ] cooldown after exit exists
- [ ] duplicate entry prevention exists
- [ ] no new entry if an unresolved order already exists
- [ ] available quote/base balances are checked before submit

---

## Exit protection

- [ ] stop-loss is a real executable protection mechanism, not only a closed-candle comparison
- [ ] take-profit handling is explicit and tested
- [ ] exit quantities are rounded correctly
- [ ] bot can recover if protective orders disappear or are partially filled

---

## Data and time

- [ ] all timestamps are timezone-aware UTC
- [ ] daily counters reset without deleting open-trade state
- [ ] trading-day boundary is explicitly defined
- [ ] candle processing is idempotent and tied to one candle timestamp

---

## Streams and connectivity

- [ ] account/user-data stream implemented
- [ ] websocket reconnect logic implemented
- [ ] ping/pong handling implemented
- [ ] 24-hour reconnect behavior handled
- [ ] REST backoff on 429/418 implemented
- [ ] healthcheck/heartbeat alert exists

---

## Testing

- [ ] unit tests for strategy signal edge cases
- [ ] unit tests for quantity/price rounding
- [ ] unit tests for filter validation
- [ ] unit tests for reconciliation
- [ ] unit tests for pending-ticket / pending-order cleanup
- [ ] restart simulation test passes
- [ ] paper mode multi-day dry run passes
- [ ] testnet live simulation passes

---

## Repo and operations

- [ ] `.env` is not in source control
- [ ] secrets have been rotated if ever exposed
- [ ] `.gitignore` excludes runtime artifacts
- [ ] dependency versions are pinned
- [ ] logs are written outside the repo or to a dedicated runtime directory
- [ ] crash recovery procedure is documented
- [ ] deployment runbook exists

---

## Final live rollout

- [ ] first live run uses smallest practical notional
- [ ] only one symbol is enabled
- [ ] notifications are working before live orders are enabled
- [ ] operator can inspect open orders and position quickly
- [ ] reconcile-on-start is enabled
- [ ] kill switch is tested
- [ ] rollback procedure is documented

---

## Release decision

The bot is ready for a tiny live rollout only when every P0/P1 item from the main review is complete and the testnet path has already behaved correctly across:

- normal fills
- partial fills
- rejected orders
- exchange timeout / unknown status
- restart during open position
- restart during pending order
