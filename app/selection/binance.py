from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

import ccxt

from .filters import SelectionFilters
from .models import MarketCandidate, MarketConstraints, MarketMetrics
from .scoring import ScoringConfig
from .selector import MarketSelectionConfig, MarketSelector, SelectionResult, select_markets


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_float(value) -> float | None:
    if value in (None, "", "0E-8"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _step_from_precision(value) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, int):
        if value < 0:
            return None
        return 10.0 ** (-value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def create_public_binance_exchange(*, use_testnet: bool = False):
    exchange = ccxt.binance(
        {
            "enableRateLimit": True,
            "options": {
                "defaultType": "spot",
            },
        }
    )
    if use_testnet:
        exchange.set_sandbox_mode(True)
    return exchange


def _market_constraints(market: dict[str, Any]) -> MarketConstraints:
    info = market.get("info", {}) or {}
    filters = {row.get("filterType"): row for row in info.get("filters", []) if isinstance(row, dict)}
    lot_size = filters.get("LOT_SIZE", {})
    market_lot_size = filters.get("MARKET_LOT_SIZE", {})
    price_filter = filters.get("PRICE_FILTER", {})
    notional_filter = filters.get("NOTIONAL", {})
    min_notional_filter = filters.get("MIN_NOTIONAL", {})
    limits = market.get("limits", {}) or {}
    precision = market.get("precision", {}) or {}

    min_qty = _to_float(market_lot_size.get("minQty") or lot_size.get("minQty") or limits.get("amount", {}).get("min"))
    max_qty = _to_float(market_lot_size.get("maxQty") or lot_size.get("maxQty") or limits.get("amount", {}).get("max"))
    qty_step = _to_float(market_lot_size.get("stepSize") or lot_size.get("stepSize") or _step_from_precision(precision.get("amount")))
    min_notional = _to_float(notional_filter.get("minNotional") or min_notional_filter.get("minNotional") or limits.get("cost", {}).get("min"))
    max_notional = _to_float(notional_filter.get("maxNotional") or limits.get("cost", {}).get("max"))
    tick_size = _to_float(price_filter.get("tickSize") or _step_from_precision(precision.get("price")))
    return MarketConstraints(
        min_qty=min_qty,
        max_qty=max_qty,
        qty_step=qty_step,
        min_notional=min_notional,
        max_notional=max_notional,
        tick_size=tick_size,
    )


def _market_metrics(ticker: dict[str, Any]) -> MarketMetrics:
    last_price = _to_float(ticker.get("last") or ticker.get("close"))
    bid = _to_float(ticker.get("bid"))
    ask = _to_float(ticker.get("ask"))
    spread = None
    spread_bps = None
    if bid is not None and ask is not None and ask >= bid:
        spread = ask - bid
        midpoint = (ask + bid) / 2
        if midpoint > 0:
            spread_bps = (spread / midpoint) * 10_000

    high_24h = _to_float(ticker.get("high"))
    low_24h = _to_float(ticker.get("low"))
    range_pct_24h = None
    if last_price is not None and last_price > 0 and high_24h is not None and low_24h is not None and high_24h >= low_24h:
        range_pct_24h = ((high_24h - low_24h) / last_price) * 100.0

    info = ticker.get("info", {}) or {}
    trade_count = _to_int(info.get("count") or info.get("tradeCount") or info.get("trades"))
    price_change_pct = _to_float(ticker.get("percentage"))

    return MarketMetrics(
        last_price=last_price,
        bid=bid,
        ask=ask,
        spread=spread,
        spread_bps=spread_bps,
        volume_base_24h=_to_float(ticker.get("baseVolume")),
        volume_quote_24h=_to_float(ticker.get("quoteVolume")),
        trade_count_24h=trade_count,
        price_change_pct_24h=price_change_pct,
        range_pct_24h=range_pct_24h,
        high_24h=high_24h,
        low_24h=low_24h,
    )


def _normalize_market(market: dict[str, Any], ticker: dict[str, Any], scanned_at: str) -> MarketCandidate:
    symbol = str(market.get("symbol") or ticker.get("symbol") or market.get("id") or "")
    base_asset = str(market.get("base") or "")
    quote_asset = str(market.get("quote") or "")
    active = bool(market.get("active", True))
    status = str(market.get("status") or market.get("info", {}).get("status") or ("TRADING" if active else "INACTIVE")).upper()
    market_type = str(market.get("type") or ("spot" if market.get("spot") else "spot")).lower()
    tradable = active and market_type == "spot"

    return MarketCandidate(
        venue="binance",
        symbol=symbol,
        market_id=str(market.get("id") or ""),
        base_asset=base_asset,
        quote_asset=quote_asset,
        market_type=market_type,
        status=status,
        active=active,
        tradable=tradable,
        constraints=_market_constraints(market),
        metrics=_market_metrics(ticker),
        scanned_at=scanned_at,
        source="ccxt.binance",
        raw={"market": market, "ticker": ticker},
    )


class BinanceMarketScanner:
    venue = "binance"

    def __init__(
        self,
        *,
        exchange: Any | None = None,
        allowed_quotes: Sequence[str] = ("USDT", "USDC"),
        use_testnet: bool = False,
    ) -> None:
        self.exchange = exchange or create_public_binance_exchange(use_testnet=use_testnet)
        self.allowed_quotes = tuple(quote.upper() for quote in allowed_quotes if quote)

    def scan(self) -> list[MarketCandidate]:
        scanned_at = utc_now_iso()
        exchange = self.exchange
        markets = exchange.load_markets()
        market_values = list(markets.values()) if isinstance(markets, dict) else list(getattr(exchange, "markets", {}).values())
        try:
            tickers = exchange.fetch_tickers()
        except Exception:
            tickers = {}

        candidates: list[MarketCandidate] = []
        for market in market_values:
            if not isinstance(market, dict):
                continue
            if market.get("contract") or market.get("swap") or market.get("future"):
                continue
            if market.get("spot") is False and str(market.get("type") or "").lower() != "spot":
                continue
            if self.allowed_quotes and str(market.get("quote") or "").upper() not in self.allowed_quotes:
                continue
            symbol = str(market.get("symbol") or "")
            ticker = tickers.get(symbol) or tickers.get(str(market.get("id") or "")) or {}
            if not ticker and symbol:
                try:
                    ticker = exchange.fetch_ticker(symbol)
                except Exception:
                    ticker = {}
            candidates.append(_normalize_market(market, ticker if isinstance(ticker, dict) else {}, scanned_at))
        return candidates


def scan_binance_markets(
    *,
    filters: SelectionFilters | None = None,
    scoring: ScoringConfig | None = None,
    exchange: Any | None = None,
    allowed_quotes: Sequence[str] = ("USDT", "USDC"),
    use_testnet: bool = False,
) -> SelectionResult:
    scanner = BinanceMarketScanner(exchange=exchange, allowed_quotes=allowed_quotes, use_testnet=use_testnet)
    selector = MarketSelector(MarketSelectionConfig(filters=filters or SelectionFilters(), scoring=scoring or ScoringConfig()))
    return select_markets(scanner.scan(), selector.config, venue=scanner.venue)
