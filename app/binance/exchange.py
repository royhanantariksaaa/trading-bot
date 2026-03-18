from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

import ccxt
import pandas as pd

from .config import Config
from .models import AccountSnapshot, DustHolding, OrderState, WalletHolding


class ExchangeValidationError(ValueError):
    pass


DUST_NOTIONAL_BUFFER = 1.05


@dataclass
class SymbolRules:
    symbol: str
    base_asset: str
    quote_asset: str
    min_qty: float | None = None
    max_qty: float | None = None
    qty_step: float | None = None
    market_min_qty: float | None = None
    market_max_qty: float | None = None
    market_qty_step: float | None = None
    min_price: float | None = None
    max_price: float | None = None
    tick_size: float | None = None
    min_notional: float | None = None
    max_notional: float | None = None


def _to_float(value) -> float | None:
    if value in (None, "", "0E-8"):
        return None
    return float(value)


def _to_decimal(value: float | str) -> Decimal:
    return Decimal(str(value))


def _maybe_apply_base_url_override(exchange, config: Config) -> None:
    if not config.live_api_url:
        return
    base = config.live_api_url.rstrip("/")
    api_v3 = base if base.endswith("/api/v3") else f"{base}/api/v3"
    api_v1 = api_v3.replace("/api/v3", "/api/v1")
    exchange.urls["api"]["public"] = api_v3
    exchange.urls["api"]["private"] = api_v3
    exchange.urls["api"]["v1"] = api_v1


def _wallet_holdings_from_balance(balance: dict, *, quote_asset: str, base_asset: str) -> list[WalletHolding]:
    free = balance.get("free", {}) or {}
    used = balance.get("used", {}) or balance.get("locked", {}) or {}
    total = balance.get("total", {}) or {}
    assets = set()
    for payload in (free, used, total):
        if isinstance(payload, dict):
            assets.update(str(asset) for asset in payload.keys())
    ordered_assets = sorted(assets, key=lambda asset: (0 if asset in {quote_asset, base_asset} else 1, asset))
    holdings: list[WalletHolding] = []
    for asset in ordered_assets:
        asset_free = float(free.get(asset) or 0)
        asset_locked = float(used.get(asset) or 0)
        asset_total = float(total.get(asset) or (asset_free + asset_locked))
        if asset_free <= 0 and asset_locked <= 0 and asset_total <= 0:
            continue
        holdings.append(
            WalletHolding(
                asset=asset,
                free=asset_free,
                locked=asset_locked,
                total=asset_total,
            )
        )
    return holdings


def create_exchange(config: Config):
    exchange = ccxt.binance({
        "apiKey": config.api_key,
        "secret": config.api_secret,
        "enableRateLimit": True,
        "recvWindow": config.recv_window_ms,
        "options": {
            "defaultType": "spot",
            "newOrderRespType": {
                "market": "FULL",
                "limit": "FULL",
            },
        },
    })
    if config.use_testnet:
        exchange.set_sandbox_mode(True)
    _maybe_apply_base_url_override(exchange, config)
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
    from .strategy import add_indicators

    df = add_indicators(df, rsi_period=rsi_period)
    result = df[["timestamp", "rsi"]].copy()
    result = result.rename(columns={"rsi": f"htf_rsi_{timeframe}"})
    result[f"htf_pass_{timeframe}"] = result[f"htf_rsi_{timeframe}"] >= min_rsi
    return result


def get_market_rules(exchange, symbol: str) -> SymbolRules:
    exchange.load_markets()
    market = exchange.market(symbol)
    filters = {row.get("filterType"): row for row in market.get("info", {}).get("filters", [])}
    lot_size = filters.get("LOT_SIZE", {})
    market_lot_size = filters.get("MARKET_LOT_SIZE", {})
    price_filter = filters.get("PRICE_FILTER", {})
    min_notional = filters.get("MIN_NOTIONAL", {})
    notional = filters.get("NOTIONAL", {})
    return SymbolRules(
        symbol=symbol,
        base_asset=market.get("base", ""),
        quote_asset=market.get("quote", ""),
        min_qty=_to_float(lot_size.get("minQty")),
        max_qty=_to_float(lot_size.get("maxQty")),
        qty_step=_to_float(lot_size.get("stepSize")),
        market_min_qty=_to_float(market_lot_size.get("minQty")),
        market_max_qty=_to_float(market_lot_size.get("maxQty")),
        market_qty_step=_to_float(market_lot_size.get("stepSize")),
        min_price=_to_float(price_filter.get("minPrice")),
        max_price=_to_float(price_filter.get("maxPrice")),
        tick_size=_to_float(price_filter.get("tickSize")),
        min_notional=_to_float(notional.get("minNotional") or min_notional.get("minNotional")),
        max_notional=_to_float(notional.get("maxNotional")),
    )


def round_price(price: float, rules: SymbolRules) -> float:
    if rules.tick_size in (None, 0):
        return float(price)
    tick = _to_decimal(rules.tick_size)
    return float((_to_decimal(price) / tick).to_integral_value(rounding=ROUND_DOWN) * tick)


def round_quantity(quantity: float, rules: SymbolRules, *, market_order: bool = True) -> float:
    step_size = rules.market_qty_step if market_order and rules.market_qty_step else rules.qty_step
    if step_size in (None, 0):
        return float(quantity)
    step = _to_decimal(step_size)
    return float((_to_decimal(quantity) / step).to_integral_value(rounding=ROUND_DOWN) * step)


def validate_market_quote_budget(quote_budget: float, signal_price: float, rules: SymbolRules) -> float:
    rounded_budget = float(_to_decimal(quote_budget).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN))
    if rounded_budget <= 0:
        raise ExchangeValidationError("Quote budget must be > 0")
    estimated_qty = round_quantity(rounded_budget / signal_price, rules, market_order=True)
    if estimated_qty <= 0:
        raise ExchangeValidationError("Quote budget becomes 0 quantity after MARKET_LOT_SIZE rounding")
    if rules.market_min_qty is not None and estimated_qty < rules.market_min_qty:
        raise ExchangeValidationError(f"Estimated qty {estimated_qty:.8f} is below market min qty {rules.market_min_qty:.8f}")
    if rules.min_notional is not None and rounded_budget < rules.min_notional:
        raise ExchangeValidationError(f"Quote budget {rounded_budget:.8f} is below min notional {rules.min_notional:.8f}")
    if rules.max_notional is not None and rounded_budget > rules.max_notional:
        raise ExchangeValidationError(f"Quote budget {rounded_budget:.8f} is above max notional {rules.max_notional:.8f}")
    return rounded_budget


def validate_market_sell_quantity(quantity: float, price: float, rules: SymbolRules) -> float:
    rounded_qty = round_quantity(quantity, rules, market_order=True)
    if rounded_qty <= 0:
        raise ExchangeValidationError("Sell quantity becomes 0 after rounding")
    min_qty = rules.market_min_qty if rules.market_min_qty is not None else rules.min_qty
    max_qty = rules.market_max_qty if rules.market_max_qty is not None else rules.max_qty
    if min_qty is not None and rounded_qty < min_qty:
        raise ExchangeValidationError(f"Sell quantity {rounded_qty:.8f} is below min qty {min_qty:.8f}")
    if max_qty is not None and rounded_qty > max_qty:
        raise ExchangeValidationError(f"Sell quantity {rounded_qty:.8f} is above max qty {max_qty:.8f}")
    notional = rounded_qty * price
    if rules.min_notional is not None and notional < rules.min_notional:
        raise ExchangeValidationError(f"Sell notional {notional:.8f} is below min notional {rules.min_notional:.8f}")
    if rules.max_notional is not None and notional > rules.max_notional:
        raise ExchangeValidationError(f"Sell notional {notional:.8f} is above max notional {rules.max_notional:.8f}")
    return rounded_qty


def actionable_notional_threshold(price: float, rules: SymbolRules, *, buffer: float = DUST_NOTIONAL_BUFFER) -> float:
    thresholds = []
    if rules.min_notional is not None:
        thresholds.append(float(rules.min_notional) * max(buffer, 1.0))
    min_amount = rules.market_min_qty if rules.market_min_qty is not None else rules.min_qty
    if min_amount is not None and price > 0:
        thresholds.append(float(min_amount) * price)
    return max(thresholds) if thresholds else 0.0


def assess_dust_holding(*, asset: str, free: float, locked: float, total: float, price: float, rules: SymbolRules, symbol: str = "") -> DustHolding | None:
    if total <= 0:
        return None
    rounded_qty = round_quantity(total, rules, market_order=True)
    min_amount = rules.market_min_qty if rules.market_min_qty is not None else rules.min_qty
    notional = total * price
    threshold = actionable_notional_threshold(price, rules)
    reasons = []
    if rounded_qty <= 0:
        reasons.append("rounds to zero after market lot-size step")
    elif min_amount is not None and rounded_qty < float(min_amount):
        reasons.append(f"market qty {rounded_qty:.8f} < min qty {float(min_amount):.8f}")
    if threshold > 0 and notional < threshold:
        reasons.append(f"notional {notional:.8f} < actionable threshold {threshold:.8f}")
    if not reasons:
        return None
    return DustHolding(
        asset=asset,
        free=free,
        locked=locked,
        total=total,
        symbol=symbol,
        notional=notional,
        actionable_threshold=threshold,
        reason="; ".join(reasons),
    )


def build_min_notional_warning(symbol: str, qty: float, price: float, market_rules: SymbolRules) -> str:
    notional = qty * price
    parts = []
    min_cost = market_rules.min_notional
    min_amount = market_rules.market_min_qty if market_rules.market_min_qty is not None else market_rules.min_qty
    if min_cost is not None and notional < float(min_cost):
        parts.append(f"notional ${notional:.4f} < min_notional ${float(min_cost):.4f}")
    if min_amount is not None and qty < float(min_amount):
        parts.append(f"qty {qty:.8f} < min_qty {float(min_amount):.8f}")
    if not parts:
        return ""
    return f"Market warning for {symbol}: " + "; ".join(parts)


def _millis_to_iso(value) -> str:
    if value in (None, ""):
        return ""
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return str(value)
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def order_average_price(order: dict) -> float:
    average = order.get("average")
    if average not in (None, 0):
        return float(average)
    filled = float(order.get("filled") or 0)
    cost = float(order.get("cost") or 0)
    if filled > 0 and cost > 0:
        return cost / filled
    info = order.get("info", {}) or {}
    executed_qty = float(info.get("executedQty") or 0)
    quote_executed = float(info.get("cummulativeQuoteQty") or 0)
    if executed_qty > 0 and quote_executed > 0:
        return quote_executed / executed_qty
    return float(order.get("price") or info.get("price") or 0)


def ccxt_order_to_state(order: dict) -> OrderState:
    info = order.get("info", {}) or {}
    timestamp = order.get("timestamp") or info.get("transactTime")
    updated_at = order.get("lastTradeTimestamp") or timestamp
    return OrderState(
        symbol=order.get("symbol") or info.get("symbol") or "",
        side=(order.get("side") or info.get("side") or "").upper(),
        order_type=(order.get("type") or info.get("type") or "").upper(),
        order_id=str(order.get("id") or info.get("orderId") or ""),
        client_order_id=order.get("clientOrderId") or info.get("clientOrderId") or info.get("origClientOrderId") or "",
        status=(order.get("status") or info.get("status") or "").upper(),
        qty=float(order.get("amount") or info.get("origQty") or 0),
        executed_qty=float(order.get("filled") or info.get("executedQty") or 0),
        quote_order_qty=float(info.get("quoteOrderQty") or 0),
        quote_executed=float(order.get("cost") or info.get("cummulativeQuoteQty") or 0),
        price=float(order.get("price") or info.get("price") or 0),
        stop_price=float(order.get("stopPrice") or info.get("stopPrice") or 0),
        submitted_at=_millis_to_iso(timestamp),
        updated_at=_millis_to_iso(updated_at),
    )


def fetch_account_snapshot(exchange, rules: SymbolRules) -> AccountSnapshot:
    balance = exchange.fetch_balance()
    quote = balance.get(rules.quote_asset, {}) or {}
    base = balance.get(rules.base_asset, {}) or {}
    info = balance.get("info", {}) or {}
    maker_fee = _to_float(info.get("makerCommission"))
    taker_fee = _to_float(info.get("takerCommission"))
    if maker_fee is not None:
        maker_fee /= 10000
    if taker_fee is not None:
        taker_fee /= 10000
    return AccountSnapshot(
        quote_asset=rules.quote_asset,
        quote_free=float(quote.get("free") or 0),
        quote_locked=float(quote.get("used") or quote.get("locked") or 0),
        base_asset=rules.base_asset,
        base_free=float(base.get("free") or 0),
        base_locked=float(base.get("used") or base.get("locked") or 0),
        holdings=_wallet_holdings_from_balance(balance, quote_asset=rules.quote_asset, base_asset=rules.base_asset),
        maker_fee=maker_fee,
        taker_fee=taker_fee,
        captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def fetch_open_orders(exchange, symbol: str) -> list[OrderState]:
    return [ccxt_order_to_state(order) for order in exchange.fetch_open_orders(symbol)]


def fetch_order_by_client_id(exchange, symbol: str, client_order_id: str) -> OrderState:
    market = exchange.market(symbol)
    payload = exchange.privateGetOrder({"symbol": market["id"], "origClientOrderId": client_order_id})
    return ccxt_order_to_state(exchange.parse_order(payload, market))


def fetch_recent_trades(exchange, symbol: str, limit: int = 100) -> list[dict]:
    return exchange.fetch_my_trades(symbol, limit=limit)


def validate_market_buy_order(exchange, symbol: str, quote_order_qty: float, signal_price: float, client_order_id: str) -> None:
    amount = quote_order_qty / max(signal_price, 1e-12)
    exchange.create_order(
        symbol,
        "market",
        "buy",
        amount,
        None,
        {"quoteOrderQty": quote_order_qty, "clientOrderId": client_order_id, "test": True},
    )


def submit_market_buy(exchange, symbol: str, quote_order_qty: float, signal_price: float, client_order_id: str) -> OrderState:
    amount = quote_order_qty / max(signal_price, 1e-12)
    order = exchange.create_order(
        symbol,
        "market",
        "buy",
        amount,
        None,
        {"quoteOrderQty": quote_order_qty, "clientOrderId": client_order_id},
    )
    return ccxt_order_to_state(order)


def validate_market_sell_order(exchange, symbol: str, quantity: float, client_order_id: str) -> None:
    exchange.create_order(symbol, "market", "sell", quantity, None, {"clientOrderId": client_order_id, "test": True})


def submit_market_sell(exchange, symbol: str, quantity: float, client_order_id: str) -> OrderState:
    order = exchange.create_order(symbol, "market", "sell", quantity, None, {"clientOrderId": client_order_id})
    return ccxt_order_to_state(order)


def validate_stop_loss_sell_order(exchange, symbol: str, quantity: float, stop_price: float, client_order_id: str) -> None:
    exchange.create_order(
        symbol,
        "market",
        "sell",
        quantity,
        None,
        {"clientOrderId": client_order_id, "stopLossPrice": stop_price, "test": True},
    )


def submit_stop_loss_sell(exchange, symbol: str, quantity: float, stop_price: float, client_order_id: str) -> OrderState:
    order = exchange.create_order(
        symbol,
        "market",
        "sell",
        quantity,
        None,
        {"clientOrderId": client_order_id, "stopLossPrice": stop_price},
    )
    return ccxt_order_to_state(order)


def cancel_order_by_client_id(exchange, symbol: str, client_order_id: str) -> OrderState:
    market = exchange.market(symbol)
    payload = exchange.privateDeleteOrder({"symbol": market["id"], "origClientOrderId": client_order_id})
    return ccxt_order_to_state(exchange.parse_order(payload, market))
