from __future__ import annotations

import argparse
from pathlib import Path

from config import Config
from exchange import create_exchange, fetch_ohlcv_df, prepare_htf_rsi_filter
from logger import fmt_pct, log_event
from paper_wallet import PaperWallet
from risk import calc_position_size
from strategy import add_indicators, signal_for_index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a historical backtest for the EMA strategy.")
    parser.add_argument("--symbol", help="Trading pair like ETH/USDT or SOL/USDT")
    parser.add_argument("--timeframe", help="Timeframe like 5m, 15m, 1h")
    parser.add_argument("--candles", type=int, default=500, help="Number of historical candles to fetch")
    parser.add_argument("--balance", type=float, help="Override starting balance in USDT")
    parser.add_argument("--risk", type=float, help="Override risk per trade, e.g. 0.01 for 1%%")
    parser.add_argument("--stop-loss", dest="stop_loss", type=float, help="Override stop loss percent, e.g. 0.02")
    parser.add_argument("--take-profit", dest="take_profit", type=float, help="Override take profit percent, e.g. 0.03")
    parser.add_argument("--cooldown", type=int, help="Override cooldown candles after exit")
    parser.add_argument("--use-rsi-filter", action="store_true", help="Require RSI confirmation on EMA signals")
    parser.add_argument("--rsi-buy-min", type=float, help="Minimum RSI needed to allow a buy signal")
    parser.add_argument("--rsi-sell-max", type=float, help="Maximum RSI needed to allow a sell signal")
    parser.add_argument("--rsi-period", type=int, help="RSI period length")
    parser.add_argument("--use-htf-filter", action="store_true", help="Enable higher timeframe RSI filter")
    parser.add_argument("--htf-1-timeframe", type=str, help="First HTF timeframe, e.g. 1h or 4h")
    parser.add_argument("--htf-1-rsi-min", type=float, help="Minimum RSI for HTF layer 1")
    parser.add_argument("--htf-1-rsi-period", type=int, help="RSI period for HTF layer 1")
    parser.add_argument("--htf-2-enabled", action="store_true", help="Enable second HTF RSI filter")
    parser.add_argument("--htf-2-timeframe", type=str, help="Second HTF timeframe, e.g. 4h or 1d")
    parser.add_argument("--htf-2-rsi-min", type=float, help="Minimum RSI for HTF layer 2")
    parser.add_argument("--htf-2-rsi-period", type=int, help="RSI period for HTF layer 2")
    parser.add_argument("--output", default="backtest_trades.csv", help="Trade log CSV output path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = Config()
    config.validate()

    if args.symbol:
        config.symbol = args.symbol
    if args.timeframe:
        config.timeframe = args.timeframe
    if args.balance is not None:
        config.starting_balance = args.balance
    if args.risk is not None:
        config.risk_per_trade = args.risk
    if args.stop_loss is not None:
        config.stop_loss_pct = args.stop_loss
    if args.take_profit is not None:
        config.take_profit_pct = args.take_profit
    if args.cooldown is not None:
        config.cooldown_candles = args.cooldown
    if args.use_rsi_filter:
        config.use_rsi_filter = True
    if args.rsi_buy_min is not None:
        config.rsi_buy_min = args.rsi_buy_min
    if args.rsi_sell_max is not None:
        config.rsi_sell_max = args.rsi_sell_max
    if args.rsi_period is not None:
        config.rsi_period = args.rsi_period
    if args.use_htf_filter:
        config.use_htf_filter = True
    if args.htf_1_timeframe is not None:
        config.htf_1_timeframe = args.htf_1_timeframe
    if args.htf_1_rsi_min is not None:
        config.htf_1_rsi_min = args.htf_1_rsi_min
    if args.htf_1_rsi_period is not None:
        config.htf_1_rsi_period = args.htf_1_rsi_period
    if args.htf_2_enabled:
        config.htf_2_enabled = True
    if args.htf_2_timeframe is not None:
        config.htf_2_timeframe = args.htf_2_timeframe
    if args.htf_2_rsi_min is not None:
        config.htf_2_rsi_min = args.htf_2_rsi_min
    if args.htf_2_rsi_period is not None:
        config.htf_2_rsi_period = args.htf_2_rsi_period

    config.validate()

    exchange = create_exchange(config)
    df = fetch_ohlcv_df(exchange, config.symbol, config.timeframe, limit=args.candles)
    df = add_indicators(df, rsi_period=config.rsi_period)

    htf_columns = []
    if config.use_htf_filter:
        htf1 = prepare_htf_rsi_filter(exchange, config.symbol, config.htf_1_timeframe, config.htf_1_rsi_period, config.htf_1_rsi_min)
        df = df.merge(htf1, on="timestamp", how="left")
        df[f"htf_pass_{config.htf_1_timeframe}"] = df[f"htf_pass_{config.htf_1_timeframe}"].ffill().fillna(False)
        htf_columns.append((config.htf_1_timeframe, config.htf_1_rsi_min))
        if config.htf_2_enabled:
            htf2 = prepare_htf_rsi_filter(exchange, config.symbol, config.htf_2_timeframe, config.htf_2_rsi_period, config.htf_2_rsi_min)
            df = df.merge(htf2, on="timestamp", how="left")
            df[f"htf_pass_{config.htf_2_timeframe}"] = df[f"htf_pass_{config.htf_2_timeframe}"].ffill().fillna(False)
            htf_columns.append((config.htf_2_timeframe, config.htf_2_rsi_min))

    wallet = PaperWallet(
        balance_usdt=config.starting_balance,
        trades_path=Path(args.output),
    )

    trade_count = 0
    win_count = 0
    loss_count = 0
    realized_pnl = 0.0
    peak_balance = wallet.balance_usdt
    max_drawdown_pct = 0.0

    strategy_label = "EMA 9/21"
    if config.use_rsi_filter:
        strategy_label += f" + RSI({config.rsi_period}) buy>={config.rsi_buy_min:.1f} sell<={config.rsi_sell_max:.1f}"
    if config.use_htf_filter:
        for tf, min_rsi in htf_columns:
            strategy_label += f" + HTF[{tf}] RSI>={min_rsi:.1f}"

    log_event(
        "INFO",
        f"Starting backtest | symbol={config.symbol} tf={config.timeframe} candles={len(df)} balance={config.starting_balance:.2f} risk={fmt_pct(config.risk_per_trade)} sl={fmt_pct(config.stop_loss_pct)} tp={fmt_pct(config.take_profit_pct)} cooldown={config.cooldown_candles} strategy={strategy_label}",
    )

    for i in range(21, len(df)):
        row = df.iloc[i]
        price = float(row["close"])
        signal = signal_for_index(
            df,
            i,
            use_rsi_filter=config.use_rsi_filter,
            rsi_buy_min=config.rsi_buy_min,
            rsi_sell_max=config.rsi_sell_max,
        )

        htf_ok = True
        if config.use_htf_filter:
            htf_ok = bool(row.get(f"htf_pass_{config.htf_1_timeframe}", False))
            if config.htf_2_enabled:
                htf_ok = htf_ok and bool(row.get(f"htf_pass_{config.htf_2_timeframe}", False))

        if wallet.position is not None:
            if price <= wallet.position.stop_loss:
                pnl = wallet.exit_long(price, i, note="stop_loss")
                trade_count += 1
                realized_pnl += pnl
                win_count += 1 if pnl > 0 else 0
                loss_count += 1 if pnl <= 0 else 0
            elif price >= wallet.position.take_profit:
                pnl = wallet.exit_long(price, i, note="take_profit")
                trade_count += 1
                realized_pnl += pnl
                win_count += 1 if pnl > 0 else 0
                loss_count += 1 if pnl <= 0 else 0
            elif signal == "sell":
                pnl = wallet.exit_long(price, i, note="ema_cross_down")
                trade_count += 1
                realized_pnl += pnl
                win_count += 1 if pnl > 0 else 0
                loss_count += 1 if pnl <= 0 else 0
        else:
            if signal == "buy" and htf_ok and wallet.can_enter(i, config.cooldown_candles):
                qty = calc_position_size(
                    wallet.balance_usdt,
                    config.risk_per_trade,
                    price,
                    config.stop_loss_pct,
                )
                stop_loss = price * (1 - config.stop_loss_pct)
                take_profit = price * (1 + config.take_profit_pct)
                wallet.enter_long(price, qty, stop_loss, take_profit)

        equity = wallet.balance_usdt
        if wallet.position is not None:
            equity += wallet.position.qty * price

        peak_balance = max(peak_balance, equity)
        if peak_balance > 0:
            drawdown_pct = (peak_balance - equity) / peak_balance
            max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

    last_price = float(df.iloc[-1]["close"])
    if wallet.position is not None:
        pnl = wallet.exit_long(last_price, len(df) - 1, note="forced_end_of_backtest")
        trade_count += 1
        realized_pnl += pnl
        win_count += 1 if pnl > 0 else 0
        loss_count += 1 if pnl <= 0 else 0

    final_balance = wallet.balance_usdt
    total_return_pct = (final_balance - config.starting_balance) / config.starting_balance if config.starting_balance else 0.0
    win_rate = (win_count / trade_count) if trade_count else 0.0

    print()
    print("=== BACKTEST SUMMARY ===")
    print(f"Symbol: {config.symbol}")
    print(f"Timeframe: {config.timeframe}")
    print(f"Strategy: {strategy_label}")
    print(f"Candles: {len(df)}")
    print(f"Trades: {trade_count}")
    print(f"Wins: {win_count}")
    print(f"Losses: {loss_count}")
    print(f"Win rate: {win_rate * 100:.2f}%")
    print(f"Start balance: {config.starting_balance:.4f} USDT")
    print(f"Final balance: {final_balance:.4f} USDT")
    print(f"Realized PnL: {realized_pnl:.4f} USDT")
    print(f"Return: {total_return_pct * 100:.2f}%")
    print(f"Max drawdown: {max_drawdown_pct * 100:.2f}%")
    print(f"Trade log: {args.output}")


if __name__ == "__main__":
    main()
