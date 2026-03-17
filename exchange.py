from __future__ import annotations

import ccxt
import pandas as pd

from config import Config


def create_exchange(config: Config):
    exchange = ccxt.binance({
        "apiKey": config.api_key,
        "secret": config.api_secret,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    return exchange


def fetch_ohlcv_df(exchange, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    candles = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(
        candles,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


def prepare_htf_rsi_filter(
    exchange,
    symbol: str,
    timeframe: str,
    rsi_period: int,
    min_rsi: float,
    limit: int = 300,
) -> pd.DataFrame:
    df = fetch_ohlcv_df(exchange, symbol, timeframe, limit=limit)
    from strategy import add_indicators

    df = add_indicators(df, rsi_period=rsi_period)
    result = df[["timestamp", "rsi"]].copy()
    result = result.rename(columns={"rsi": f"htf_rsi_{timeframe}"})
    result[f"htf_pass_{timeframe}"] = result[f"htf_rsi_{timeframe}"] >= min_rsi
    return result


def get_market_rules(exchange, symbol: str) -> dict:
    exchange.load_markets()
    market = exchange.market(symbol)
    limits = market.get("limits", {}) or {}
    amount_limits = limits.get("amount", {}) or {}
    cost_limits = limits.get("cost", {}) or {}
    precision = market.get("precision", {}) or {}
    return {
        "min_amount": amount_limits.get("min"),
        "min_cost": cost_limits.get("min"),
        "amount_precision": precision.get("amount"),
        "price_precision": precision.get("price"),
    }


def build_min_notional_warning(symbol: str, qty: float, price: float, market_rules: dict) -> str:
    notional = qty * price
    parts = []
    min_cost = market_rules.get("min_cost")
    min_amount = market_rules.get("min_amount")
    if min_cost is not None and notional < float(min_cost):
        parts.append(f"notional ${notional:.4f} < min_cost ${float(min_cost):.4f}")
    if min_amount is not None and qty < float(min_amount):
        parts.append(f"qty {qty:.8f} < min_amount {float(min_amount):.8f}")
    if not parts:
        return ""
    return f"Market warning for {symbol}: " + "; ".join(parts)
