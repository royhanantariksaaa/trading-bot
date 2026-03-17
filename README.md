# Trading Bot

Multi-venue repo with package-first entrypoints.

## Venues

- `trading_bot.binance`: single-symbol spot bot for paper, supervised manual, or live auto execution
- `trading_bot.polymarket`: paper-first Polymarket market-maker MVP

Legacy top-level Python wrappers are gone on purpose. Run the package modules directly.

## Install

```bat
python -m pip install -r requirements.txt
```

## Configure Binance

Copy `.env.example` to `.env` and edit it.

```bat
copy .env.example .env
```

Recommended first automated live setup:

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

## Run Binance bot

Default package entrypoint:

```bat
python -m trading_bot
```

Explicit Binance entrypoint:

```bat
python -m trading_bot.binance
```

Direct helper modules:

```bat
python -m trading_bot.binance.backtest --symbol SOL/USDT --timeframe 15m --candles 1000 --use-rsi-filter --rsi-buy-min 52 --rsi-sell-max 48
python -m trading_bot.binance.update_ticket --ticket abc12345 --status approved
python -m trading_bot.binance.log_execution --ticket abc12345 --action BUY --symbol SOL/USDT --type entry --price 94.30 --qty 0.053 --fee 0.01 --note "manual Binance fill"
python -m trading_bot.binance.preview_messages
python -m trading_bot.binance.review_day
python -m trading_bot.binance.test_webhook
```

## Run Polymarket market-maker

Copy env file:

```bat
copy polymarket_mm\.env.example polymarket_mm\.env
```

Then run:

```bat
python -m trading_bot.polymarket
```

## Runtime model

The Binance runtime is position/order driven instead of ticket driven:

- persistent `runtime_state.json` stores open position, open orders, daily PnL, cooldown, and last exchange sync
- manual execution logs update the same runtime state used by the bot
- live orders use persistent client order ids
- Binance symbol filters are validated before submit
- live startup reconciliation reloads balances, open orders, and recent trades
- live entries arm a protective stop-loss order after the entry fill

## Output files

- `runtime_state.json`: persistent Binance runtime position/order state
- `trades.csv`: paper trade log
- `manual_tickets.csv`: manual ticket journal
- `decision_log.csv`: approval / denial journal
- `live_execution_log.csv`: manual execution journal
- `polymarket_mm/state.json`: default Polymarket state file
- `polymarket_mm/runs.csv`: default Polymarket loop log

## Notes

- `trading_bot.common` exists only for genuinely shared plumbing. Right now that's just env loading/parsing; no fake abstraction zoo.
- `polymarket_mm/` is now just config/data/docs territory, not a second Python package.

## Important limits

Still not a finished production platform:

- live fill truth still relies on REST reconciliation, not a Binance user-data websocket
- take-profit is software-managed; only stop-loss is armed as a live protective order
- there is no full monitoring/heartbeat layer yet

Use `USE_TESTNET=true` first, keep size tiny, and rotate any webhook or API secret that may already have been exposed.
