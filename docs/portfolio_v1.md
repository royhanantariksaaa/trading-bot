# Portfolio Bot v1 Foundation

This repo now includes a conservative portfolio layer that sits alongside the existing single-symbol Binance bot.

## What landed

- A generic portfolio state model with multiple open positions
- A bounded allocation engine that works on Binance or Polymarket market scans
- Conservative risk caps for:
  - max open positions
  - max positions per venue
  - max total deployed notional
  - max per-position notional
  - cash reserve
  - minimum score threshold
- Explainable allocation reports in text and JSON
- Portfolio paper-state persistence for restart safety

## What it is for

The portfolio layer is meant to answer:

- Which markets are eligible?
- How much capital should each market receive?
- Which caps blocked a candidate?
- What is the current portfolio ledger?

It is intentionally narrow. It is not a full quant platform, and it does not replace the existing Binance execution loop.

## How to run safely

Use the portfolio entrypoint in report or paper mode:

```bat
set PORTFOLIO_VENUE=binance
set PORTFOLIO_SELECTION_MODE=scan
set PORTFOLIO_RUN_MODE=paper
python -m app.portfolio
```

For a zero-mutation dry run, use:

```bat
set PORTFOLIO_RUN_MODE=report
python -m app.portfolio
```

Paper mode only updates the portfolio ledger in `data/state/portfolio_state.json`. It does not submit exchange orders.

## Compatibility notes

- `python -m app.binance` still runs the existing single-symbol Binance loop.
- Manual ticket flows remain unchanged.
- Polymarket support is available through the same allocation/report path, but live trading remains in the dedicated Polymarket runtime.

## What remains

- No live order execution from the portfolio layer yet
- No portfolio-level exit automation yet
- No cross-venue capital transfer model yet
- No full rebalancer / optimizer

