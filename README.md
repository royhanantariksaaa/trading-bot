# Trading Bot

Multi-venue repo with one importable application package, `app`, and runtime artifacts under `data/`.

## Structure

```text
trading-bot/
  app/
    __main__.py      # `python -m app` -> Binance default entrypoint
    main.py
    portfolio/
      __main__.py    # `python -m app.portfolio` -> portfolio allocator / paper ledger
      main.py
      ...
    selection/
      __main__.py    # `python -m app.selection` -> Binance market scan
      main.py
      ...
    binance/
      __main__.py    # `python -m app.binance`
      main.py
      backtest.py
      ...
    polymarket/
      __main__.py    # `python -m app.polymarket`
      main.py
      ...
    common/
    utils/
  polymarket_mm/
    README.md        # docs and env example for the Polymarket MVP
  data/
    market/
    logs/
    backtests/
    state/
  tests/
  docs/
```

Use `app.*` for imports and module commands. The old compatibility shim package has been removed.

## Install

```bat
python -m pip install -r requirements.txt
```

## Configure

Copy `.env.example` to `.env` and edit only the values you need. The repo uses a single root env file for both venues.

```bat
copy .env.example .env
```

Recommended first automated Binance live setup:

```env
BOT_MODE=live
EXECUTION_MODE=auto
APPROVAL_MODE=none
ENABLE_LIVE_TRADING=true
USE_TESTNET=true
RECONCILE_ON_START=true
ORDER_TEST_BEFORE_SUBMIT=true
SYMBOL=SOL/USDT
TIMEFRAME=15m
MAX_TRADE_USD=5
MAX_DAILY_LOSS_USD=1
MAX_TRADES_PER_DAY=3
```

## Run Binance

Default Binance wrapper:

```bat
python -m app
```

Explicit Binance package entrypoint:

```bat
python -m app.binance
```

Useful Binance helpers:

```bat
python -m app.binance.backtest --symbol SOL/USDT --timeframe 15m --candles 1000 --use-rsi-filter --rsi-buy-min 52 --rsi-sell-max 48
python -m app.binance.update_ticket --ticket abc12345 --status approved
python -m app.binance.log_execution --ticket abc12345 --action BUY --symbol SOL/USDT --type entry --price 94.30 --qty 0.053 --fee 0.01 --note "manual Binance fill"
python -m app.binance.preview_messages
python -m app.binance.review_day
python -m app.binance.test_webhook
```

Scan Binance markets and export ranked candidates to `data/market/binance_candidates.csv` plus human-readable report files:

```bat
python -m app.selection --venue binance
```

Auto-select the Binance market and profile at startup:

```bat
set BINANCE_SELECTION_MODE=scan
set BINANCE_STRATEGY_PROFILE=auto
set BINANCE_ADAPTIVE_MODE=paper
python -m app.binance
```

When `BINANCE_SELECTION_MODE` is `csv` or `scan`, the selected market is also classified into a conservative profile (`trend`, `range`, `volatile`, or `slow_liquid`) and that profile is applied before the bot starts. Use `BINANCE_STRATEGY_PROFILE=manual` to keep the base manual strategy settings, or set `BINANCE_STRATEGY_PROFILE=<profile>` to force one.

If you also set `BINANCE_ADAPTIVE_MODE=paper`, Binance will do a second conservative pass using recent OHLCV candles and ticker spread data, then layer one of the bounded adaptive policies on top of the selected market profile. That adaptive pass only runs in paper mode unless you explicitly set `BINANCE_ADAPTIVE_MODE=on`.

## Run Portfolio Foundation

The portfolio layer is a separate, conservative v1 allocator. It uses the existing Binance/Polymarket market scanners, but keeps execution in paper/report mode and maintains its own multi-position ledger.

```bat
set PORTFOLIO_VENUE=binance
set PORTFOLIO_SELECTION_MODE=scan
set PORTFOLIO_RUN_MODE=paper
python -m app.portfolio
```

Use `PORTFOLIO_RUN_MODE=report` for a zero-mutation dry run that only writes the allocation report. Use `PORTFOLIO_VENUE=polymarket` to point the same allocator at the Polymarket scan path.

The portfolio foundation adds:

- multiple tracked positions in portfolio state
- bounded allocation caps
- reserve cash handling
- explainable allocation decisions
- separate portfolio state and reports from the existing Binance runtime

Scan Polymarket YES outcomes using Gamma + live CLOB books and export ranked candidates to `data/market/polymarket_candidates.csv` plus report files:

```bat
python -m app.selection --venue polymarket --allowed-quotes USDC --min-quote-volume 5000 --min-trade-count 0 --max-spread-bps 800 --book-limit 25
```

Each scan now writes three artifacts by default:

- `data/market/<venue>_candidates.csv`
- `data/market/<venue>_candidates_report.txt`
- `data/market/<venue>_candidates_report.json`

The CLI also prints a `Why this market was chosen` summary for the selected market.

## Run Polymarket

Set the `POLYMARKET_*` and `PM_*` values in the same root `.env`, then run:

```bat
python -m app.polymarket
```

Optional runtime auto-pick modes:

- `BINANCE_SELECTION_MODE=csv` -> load the first accepted row from `data/market/binance_candidates.csv`
- `BINANCE_SELECTION_MODE=scan` -> rescan at startup, write `data/market/binance_candidates.csv`, and use the selected symbol and profile
- `BINANCE_STRATEGY_PROFILE=auto` -> apply the profile chosen from the selected market regime
- `BINANCE_STRATEGY_PROFILE=manual` -> keep the existing manual strategy values even when selection mode is `csv` or `scan`
- `BINANCE_STRATEGY_PROFILE=trend|range|volatile|slow_liquid` -> force a specific profile
- `BINANCE_ADAPTIVE_MODE=paper` -> apply the recent-history adaptive overlay only in paper mode
- `BINANCE_ADAPTIVE_MODE=on` -> apply the recent-history adaptive overlay in paper or live mode
- `PM_SELECTION_MODE=csv` -> load the first accepted row from `data/market/polymarket_candidates.csv`
- `PM_SELECTION_MODE=scan` -> rescan at startup, write `data/market/polymarket_candidates.csv`, and use the selected Polymarket token id

Optional conservative runtime rotation:

- `BINANCE_SELECTION_ROTATE_EVERY_LOOPS=<n>` -> every `n` bot loops, re-check selection while running
- `BINANCE_SELECTION_ROTATE_ONLY_WHEN_FLAT=true` -> only rotate when no position, no open orders, and no pending manual ticket
- `PM_SELECTION_ROTATE_EVERY_LOOPS=<n>` -> every `n` maker loops, re-check the market while running
- `PM_SELECTION_ROTATE_ONLY_WHEN_FLAT=true` -> only rotate when inventory is flat

Manual `SYMBOL` and `POLYMARKET_TOKEN_ID` still work as before when the selection mode stays `manual`. Rotation and profile auto-selection are off by default, so existing manual flows stay untouched.

The `polymarket_mm/` folder is docs plus config examples for that loop. It is not a Python package.

## Runtime Model

The Binance runtime is position/order driven instead of ticket driven:

- persistent state stores open position, open orders, daily PnL, cooldown, and last exchange sync
- manual execution logs update the same runtime state used by the bot
- live orders use persistent client order ids
- Binance symbol filters are validated before submit
- live startup reconciliation reloads balances, open orders, and recent trades
- live entries arm a protective stop-loss order after the entry fill

## Runtime Files

Defaults live under `data/`:

- `data/state/runtime_state.json`: Binance runtime position/order state
- `data/logs/trades.csv`: Binance paper trade log
- `data/logs/manual_tickets.csv`: Binance manual ticket journal
- `data/logs/decision_log.csv`: Binance approval / denial journal
- `data/logs/live_execution_log.csv`: Binance manual execution journal
- `data/backtests/backtest_trades.csv`: default Binance backtest output
- `data/market/binance_adaptive_report.txt`: latest Binance adaptive decision report
- `data/market/binance_adaptive_report.json`: machine-readable adaptive decision report
- `data/state/portfolio_state.json`: portfolio ledger state for the allocator/paper run
- `data/market/portfolio_allocation_report.txt`: latest portfolio allocation report
- `data/market/portfolio_allocation_report.json`: machine-readable portfolio allocation report
- `data/state/polymarket_state.json`: Polymarket state file
- `data/logs/polymarket_runs.csv`: Polymarket loop log
- `data/market/`: ad hoc market CSV snapshots and local samples

All of those paths can be overridden with env vars such as `BINANCE_STATE_PATH`, `BINANCE_TRADES_PATH`, `BINANCE_BACKTEST_OUTPUT_PATH`, `BINANCE_ADAPTIVE_REPORT_PATH`, `PORTFOLIO_STATE_PATH`, `PORTFOLIO_REPORT_PATH`, `PORTFOLIO_REPORT_JSON_PATH`, `PM_STATE_PATH`, and `PM_LOG_PATH`.

## Notes

- `app/common` is limited to actual shared plumbing.
- `app/utils/storage.py` centralizes repo-relative runtime paths.

## Important Limits

Still not a finished production platform:

- live fill truth still relies on REST reconciliation, not a Binance user-data websocket
- take-profit is software-managed; only stop-loss is armed as a live protective order
- there is no full monitoring/heartbeat layer yet
- the portfolio allocator is paper/report only in v1; live multi-position execution remains on the roadmap

Use `USE_TESTNET=true` first, keep size tiny, and rotate any webhook or API secret that may already have been exposed.
