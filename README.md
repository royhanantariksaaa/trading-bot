# Trading Bot

This repo now supports three execution styles for a single-symbol, spot, long-only strategy:

- `BOT_MODE=paper` + `EXECUTION_MODE=auto` for autonomous paper trading
- `BOT_MODE=live` + `EXECUTION_MODE=manual` for supervised live tickets
- `BOT_MODE=live` + `EXECUTION_MODE=auto` for real Binance Spot execution

The runtime is now position/order driven instead of ticket driven:

- persistent `runtime_state.json` stores open position, open orders, daily PnL, cooldown, and last exchange sync
- manual execution logs update the same runtime state used by the bot
- live orders use persistent client order ids
- Binance symbol filters are validated before submit
- live startup reconciliation reloads balances, open orders, and recent trades
- live entries arm a protective stop-loss order after the entry fill

## Install

```bat
python -m pip install -r requirements.txt
```

## Configure

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

## Run

```bat
python main.py
```

## Manual workflow helpers

Update ticket status:

```bat
python update_ticket.py --ticket abc12345 --status approved
python update_ticket.py --ticket abc12345 --status denied
```

Log manual executions and sync runtime state:

```bat
python log_execution.py --ticket abc12345 --action BUY --symbol SOL/USDT --type entry --price 94.30 --qty 0.053 --fee 0.01 --note "manual Binance fill"
python log_execution.py --ticket abc12345 --action SELL --symbol SOL/USDT --type exit --price 96.10 --qty 0.053 --fee 0.01 --note "manual Binance exit"
```

## Backtest

```bat
python backtest.py --symbol SOL/USDT --timeframe 15m --candles 1000 --use-rsi-filter --rsi-buy-min 52 --rsi-sell-max 48
```

## Files

- `runtime_state.json`: persistent runtime position/order state
- `trades.csv`: paper trade log
- `manual_tickets.csv`: manual ticket journal
- `decision_log.csv`: approval / denial journal
- `live_execution_log.csv`: manual execution journal

## Important limits

This refactor closes the biggest gaps from the docs, but it is still not a finished production platform. In particular:

- live fill truth still relies on REST reconciliation, not a Binance user-data websocket
- take-profit is software-managed; only stop-loss is armed as a live protective order
- there is no full monitoring/heartbeat layer yet

Use `USE_TESTNET=true` first, keep size tiny, and rotate any webhook or API secret that may already have been exposed.
