# Supervised Trading Bot

This is a Binance Spot **paper/supervised manual** bot.

## What it does
- Pulls market candles from Binance
- Uses EMA 9 / EMA 21 crossover
- Can require RSI confirmation
- Can require up to **2 higher-timeframe RSI filters**
- Uses **closed-candle** signals by default
- Sends Discord alerts through a webhook URL
- Creates **manual execution tickets** instead of placing real orders
- Tracks ticket lifecycle states: `pending`, `approved`, `denied`, `expired`, `executed`, `closed`, `skipped`
- Uses separate **BUY** and **SELL** ticket formatting
- Tracks daily realized PnL guardrails in local state
- Sends a richer **daily summary** message to Discord on first startup/check each day
- Logs clearer condition gates like `ema_cross_up`, `rsi_entry_ok`, and `htf_ok`
- Uses prettier Discord status formatting for operator readability
- Adds market-rule warnings when suggested notional/qty may be below Binance spot minimums
- Runs in paper/supervised mode only

## Strategy baseline
Suggested baseline:
- `SYMBOL=SOL/USDT`
- `TIMEFRAME=15m`
- `USE_RSI_FILTER=true`
- `RSI_BUY_MIN=52`
- `RSI_SELL_MAX=48`
- `RSI_PERIOD=14`
- `SIGNAL_ON_CLOSED_CANDLE=true`

## Optional 2-layer HTF filter
You can enable up to 2 higher-timeframe RSI filters.

Example:
```env
USE_HTF_FILTER=true
HTF_1_TIMEFRAME=4h
HTF_1_RSI_MIN=50
HTF_1_RSI_PERIOD=14
HTF_2_ENABLED=false
HTF_2_TIMEFRAME=1d
HTF_2_RSI_MIN=50
HTF_2_RSI_PERIOD=14
```

The bot then allows 15m **buy** signals only if the enabled HTF filters pass.
Exits still follow the main timeframe logic.

## Safety / supervision settings
- `EXECUTION_MODE=manual`
- `APPROVAL_MODE=discord`
- `MAX_TRADE_USD=5`
- `MAX_DAILY_LOSS_USD=1`
- `ENABLE_LIVE_TRADING=false`

## Install

```bat
python -m pip install -r requirements.txt
```

## Configure
Copy `.env.example` to `.env` and edit values if needed.

```bat
copy .env.example .env
```

## Run bot

```bat
python main.py
```

## Preview UX instantly
You can send fake preview messages without waiting for market conditions:

```bat
python preview_messages.py
```

If you also want preview tickets written into `manual_tickets.csv` so you can test lifecycle scripts end-to-end:

```bat
python preview_messages.py --persist-tickets
```

This prints and optionally sends:
- startup message
- fake BUY ticket
- fake SELL ticket
- fake NO TRADE message
- fake STATUS message
- fake DAILY SUMMARY

## Ticket lifecycle tracking
Tickets now support these lifecycle states:
- `pending`
- `approved`
- `denied`
- `expired`
- `executed`
- `closed`
- `skipped`

Current build writes lifecycle state into `manual_tickets.csv`.
Decision logging still writes to `decision_log.csv`.

## Update ticket status manually
Use:

```bat
python update_ticket.py --ticket abc12345 --status approved
python update_ticket.py --ticket abc12345 --status denied
python update_ticket.py --ticket abc12345 --status executed
python update_ticket.py --ticket abc12345 --status closed
```

Optional note:

```bat
python update_ticket.py --ticket abc12345 --status approved --note "approved from Discord"
```

## Log manual live executions
Use:

```bat
python log_execution.py --ticket abc12345 --action BUY --symbol SOL/USDT --type entry --price 94.30 --qty 0.053 --fee 0.01 --note "manual Binance fill"
python log_execution.py --ticket abc12345 --action SELL --symbol SOL/USDT --type exit --price 96.10 --qty 0.053 --fee 0.01 --note "manual Binance exit"
```

This writes to:
- `live_execution_log.csv`

It also updates ticket status automatically:
- `entry` -> `executed`
- `exit` -> `closed`

## Review the day
Use:

```bat
python review_day.py
```

This prints:
- tickets today
- decision count
- execution log count
- ticket status counts
- decision counts
- execution counts
- last ticket
- gross notional logged
- fees logged

## Market-rule warnings
The bot checks Binance market metadata and can warn when a generated ticket looks too small for practical spot execution.
That warning is included in the ticket message when applicable.

## Discord/operator output
- Tickets are formatted for Discord readability
- Status messages are more compact and operator-friendly
- No-trade messages are now prettier too
- Ticket messages can include minimum-notional / minimum-amount warnings

## Files it writes
- `trades.csv` — paper trade history
- `manual_tickets.csv` — generated manual tickets + status
- `decision_log.csv` — approval/deny logs when logged locally
- `live_execution_log.csv` — manual real execution journal
- `runtime_state.json` — pending ticket id + daily realized PnL state

## Terminal decision logging
If you set:

```env
APPROVAL_MODE=terminal
```

then when a ticket appears, the bot prompts you to type:
- `approve <ticket_id>`
- `deny <ticket_id>`

It logs that decision to `decision_log.csv`, updates ticket lifecycle state, and mirrors a decision log message to Discord.
Execution is still manual.

## Backtest examples

Plain baseline:
```bat
python backtest.py --symbol SOL/USDT --timeframe 15m --candles 1000 --use-rsi-filter --rsi-buy-min 52 --rsi-sell-max 48
```

With one HTF filter:
```bat
python backtest.py --symbol SOL/USDT --timeframe 15m --candles 1000 --use-rsi-filter --rsi-buy-min 52 --rsi-sell-max 48 --use-htf-filter --htf-1-timeframe 4h --htf-1-rsi-min 50
```

With two HTF filters:
```bat
python backtest.py --symbol SOL/USDT --timeframe 15m --candles 1000 --use-rsi-filter --rsi-buy-min 52 --rsi-sell-max 48 --use-htf-filter --htf-1-timeframe 1h --htf-1-rsi-min 50 --htf-2-enabled --htf-2-timeframe 4h --htf-2-rsi-min 50
```

## Notes
- This build does **not** place real orders.
- `BOT_MODE=live` remains blocked.
- Rotate/regenerate your Discord webhook if it was exposed publicly.
