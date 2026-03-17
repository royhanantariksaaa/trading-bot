# Polymarket Market-Maker MVP

Paper-first MVP for a **single Polymarket outcome token**.

This folder is no longer a Python package. It just holds compatibility docs and env examples for the real implementation in `app.polymarket`.

What it does:
- reads the public CLOB orderbook from `https://clob.polymarket.com/book`
- computes bid/ask quotes around the midpoint
- skews quotes based on inventory
- enforces simple inventory/notional caps
- simulates fills in paper mode when quotes cross the best bid/ask
- persists state to JSON and loop logs to CSV

What it does **not** do yet:
- authenticated live order placement
- websocket book streaming
- cancel/replace order management on the real venue
- smart inventory hedging across YES/NO pairs
- resolution / event lifecycle handling

## Quick start

1. Copy the root env example:

```bat
copy .env.example .env
```

2. Set `POLYMARKET_TOKEN_ID`

3. Run:

```bat
python -m app.polymarket
```

## Config knobs

- `PM_QUOTE_SIZE`: quote size in shares
- `PM_BASE_SPREAD`: total spread you want to quote around fair value
- `PM_EDGE_OFFSET`: extra conservatism so you don't instantly cross too often
- `PM_MAX_INVENTORY`: hard inventory cap in shares
- `PM_MAX_POSITION_NOTIONAL`: crude notional cap using midpoint marks
- `PM_INVENTORY_SKEW_PER_SHARE`: how hard quotes lean away from existing inventory
- `PM_LOOPS`: `0` = run forever

## How the pricing works

For midpoint `m`, target spread `s`, edge `e`, and inventory skew `k`:

- bid = `m - s/2 - e - k`
- ask = `m + s/2 + e - k`

If the bot is too long, both quotes shift down to encourage selling and discourage more buying.
If the bot is too short, both quotes shift up.

## Next step for live trading

The clean upgrade path is:
- add `py-clob-client`
- wire in signed order placement/cancel endpoints
- keep the same quote planner and risk layer
- replace paper fill simulation with real open-order reconciliation

That gets you from MVP to something less embarrassing.
