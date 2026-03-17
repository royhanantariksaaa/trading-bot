from __future__ import annotations

import pandas as pd


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def add_indicators(df: pd.DataFrame, fast: int = 9, slow: int = 21, rsi_period: int = 14) -> pd.DataFrame:
    data = df.copy()
    data["ema_fast"] = data["close"].ewm(span=fast, adjust=False).mean()
    data["ema_slow"] = data["close"].ewm(span=slow, adjust=False).mean()
    data["rsi"] = compute_rsi(data["close"], period=rsi_period)
    return data


def gate_status_for_index(
    df: pd.DataFrame,
    index: int,
    use_rsi_filter: bool = False,
    rsi_buy_min: float = 50.0,
    rsi_sell_max: float = 50.0,
) -> dict:
    if index < 1 or len(df) < 3:
        return {
            "crossed_up": False,
            "crossed_down": False,
            "rsi_buy_ok": False,
            "rsi_sell_ok": False,
            "buy_ready": False,
            "sell_ready": False,
        }

    prev = df.iloc[index - 1]
    curr = df.iloc[index]

    crossed_up = prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"]
    crossed_down = prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"]
    rsi_value = float(curr["rsi"])

    rsi_buy_ok = (not use_rsi_filter) or rsi_value >= rsi_buy_min
    rsi_sell_ok = (not use_rsi_filter) or rsi_value <= rsi_sell_max

    return {
        "crossed_up": bool(crossed_up),
        "crossed_down": bool(crossed_down),
        "rsi_buy_ok": bool(rsi_buy_ok),
        "rsi_sell_ok": bool(rsi_sell_ok),
        "buy_ready": bool(crossed_up and rsi_buy_ok),
        "sell_ready": bool(crossed_down and rsi_sell_ok),
    }


def signal_for_index(
    df: pd.DataFrame,
    index: int,
    use_rsi_filter: bool = False,
    rsi_buy_min: float = 50.0,
    rsi_sell_max: float = 50.0,
) -> str:
    gates = gate_status_for_index(df, index, use_rsi_filter, rsi_buy_min, rsi_sell_max)
    if gates["buy_ready"]:
        return "buy"
    if gates["sell_ready"]:
        return "sell"
    return "hold"


def latest_signal(
    df: pd.DataFrame,
    use_rsi_filter: bool = False,
    rsi_buy_min: float = 50.0,
    rsi_sell_max: float = 50.0,
) -> str:
    return signal_for_index(df, len(df) - 1, use_rsi_filter, rsi_buy_min, rsi_sell_max)
