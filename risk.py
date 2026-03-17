from __future__ import annotations


def calc_position_size(balance_usdt: float, risk_per_trade: float, entry_price: float, stop_loss_pct: float) -> float:
    risk_budget = balance_usdt * risk_per_trade
    stop_distance = entry_price * stop_loss_pct
    if stop_distance <= 0:
        return 0.0
    qty = risk_budget / stop_distance
    max_affordable_qty = balance_usdt / entry_price
    return max(0.0, min(qty, max_affordable_qty))
