from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .filters import SelectionFilters
from .models import MarketCandidate, MarketConstraints, MarketMetrics
from .scoring import ScoringConfig
from .selector import MarketSelectionConfig, MarketSelector, SelectionResult, select_markets


GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
CLOB_BASE_URL = "https://clob.polymarket.com"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_float(value: Any) -> float | None:
    if value in (None, "", "0E-8"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _http_get_json(url: str, *, user_agent: str = "trading-bot-selection/0.1") -> Any:
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


@dataclass(slots=True)
class PolymarketMarketRecord:
    market: dict[str, Any]
    outcome_name: str
    token_id: str
    outcome_price: float | None


class PolymarketPublicDataClient:
    def __init__(self, *, gamma_url: str = GAMMA_BASE_URL, clob_url: str = CLOB_BASE_URL) -> None:
        self.gamma_url = gamma_url.rstrip("/")
        self.clob_url = clob_url.rstrip("/")

    def list_markets(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        closed: bool = False,
        order: str = "volume24hr",
        ascending: bool = False,
    ) -> list[dict[str, Any]]:
        query = urlencode(
            {
                "limit": max(1, int(limit)),
                "offset": max(0, int(offset)),
                "closed": str(bool(closed)).lower(),
                "order": order,
                "ascending": str(bool(ascending)).lower(),
            }
        )
        payload = _http_get_json(f"{self.gamma_url}/markets?{query}", user_agent="trading-bot-selection-polymarket/0.1")
        return payload if isinstance(payload, list) else []

    def get_book(self, token_id: str) -> dict[str, Any]:
        query = urlencode({"token_id": token_id})
        payload = _http_get_json(f"{self.clob_url}/book?{query}", user_agent="trading-bot-selection-polymarket/0.1")
        return payload if isinstance(payload, dict) else {}


def _iter_outcomes(market: dict[str, Any], *, outcome_mode: str = "yes") -> list[PolymarketMarketRecord]:
    token_ids = [str(item) for item in _json_list(market.get("clobTokenIds")) if str(item)]
    outcome_names = [str(item) for item in _json_list(market.get("outcomes")) if str(item)]
    outcome_prices = _json_list(market.get("outcomePrices"))
    records: list[PolymarketMarketRecord] = []
    for index, token_id in enumerate(token_ids):
        outcome_name = outcome_names[index] if index < len(outcome_names) else f"OUTCOME_{index + 1}"
        normalized_name = outcome_name.strip().lower()
        if outcome_mode == "yes" and normalized_name != "yes":
            continue
        if outcome_mode == "no" and normalized_name != "no":
            continue
        price = _to_float(outcome_prices[index]) if index < len(outcome_prices) else None
        records.append(
            PolymarketMarketRecord(
                market=market,
                outcome_name=outcome_name,
                token_id=token_id,
                outcome_price=price,
            )
        )
    return records


def _book_metrics(book: dict[str, Any], fallback_last_price: float | None) -> tuple[MarketConstraints, MarketMetrics]:
    bids = book.get("bids") if isinstance(book.get("bids"), list) else []
    asks = book.get("asks") if isinstance(book.get("asks"), list) else []
    best_bid = _to_float(bids[0].get("price")) if bids else None
    best_ask = _to_float(asks[0].get("price")) if asks else None
    last_price = fallback_last_price
    if best_bid is not None and best_ask is not None:
        last_price = (best_bid + best_ask) / 2
    elif best_bid is not None:
        last_price = best_bid
    elif best_ask is not None:
        last_price = best_ask

    spread = None
    spread_bps = None
    if best_bid is not None and best_ask is not None and best_ask >= best_bid:
        spread = best_ask - best_bid
        midpoint = (best_bid + best_ask) / 2
        if midpoint > 0:
            spread_bps = (spread / midpoint) * 10_000

    min_qty = _to_float(book.get("min_order_size"))
    tick_size = _to_float(book.get("tick_size"))
    min_notional = (min_qty * last_price) if (min_qty is not None and last_price is not None) else None

    constraints = MarketConstraints(
        min_qty=min_qty,
        qty_step=tick_size,
        min_notional=min_notional,
        tick_size=tick_size,
    )
    metrics = MarketMetrics(
        last_price=last_price,
        bid=best_bid,
        ask=best_ask,
        spread=spread,
        spread_bps=spread_bps,
    )
    return constraints, metrics


def _normalize_market(record: PolymarketMarketRecord, book: dict[str, Any], scanned_at: str) -> MarketCandidate:
    market = record.market
    constraints, metrics = _book_metrics(book, record.outcome_price)
    volume_24h = _to_float(market.get("volume24hrClob") or market.get("volume24hr") or market.get("volumeNum") or market.get("volume"))
    liquidity = _to_float(market.get("liquidityClob") or market.get("liquidityNum") or market.get("liquidity"))
    one_day_change = _to_float(market.get("oneDayPriceChange"))
    last_trade_price = _to_float(market.get("lastTradePrice"))
    gamma_best_bid = _to_float(market.get("bestBid"))
    gamma_best_ask = _to_float(market.get("bestAsk"))
    gamma_spread = _to_float(market.get("spread"))
    if gamma_best_bid is not None and gamma_best_ask is not None and gamma_best_ask >= gamma_best_bid:
        gamma_mid = (gamma_best_bid + gamma_best_ask) / 2
        gamma_spread_bps = (gamma_spread / gamma_mid) * 10_000 if (gamma_spread is not None and gamma_mid > 0) else None
        if metrics.spread_bps is None or metrics.spread_bps > 5_000:
            metrics.bid = gamma_best_bid
            metrics.ask = gamma_best_ask
            metrics.spread = gamma_spread if gamma_spread is not None else gamma_best_ask - gamma_best_bid
            metrics.spread_bps = gamma_spread_bps
            metrics.last_price = last_trade_price or record.outcome_price or gamma_mid
    if metrics.last_price is None:
        metrics.last_price = last_trade_price or record.outcome_price
    metrics.volume_quote_24h = volume_24h
    metrics.volume_base_24h = volume_24h / metrics.last_price if (volume_24h is not None and metrics.last_price and metrics.last_price > 0) else None
    metrics.trade_count_24h = _to_int(market.get("commentCount")) or 0
    metrics.price_change_pct_24h = (one_day_change * 100.0) if one_day_change is not None else None
    metrics.range_pct_24h = abs(metrics.price_change_pct_24h or 0.0)
    metrics.high_24h = None
    metrics.low_24h = None

    slug = str(market.get("slug") or market.get("id") or record.token_id)
    symbol = f"{slug}:{record.outcome_name.upper()}"
    active = bool(market.get("active", True)) and not bool(market.get("closed", False))
    tradable = active and bool(market.get("acceptingOrders", True)) and bool(market.get("enableOrderBook", True))

    return MarketCandidate(
        venue="polymarket",
        symbol=symbol,
        market_id=record.token_id,
        base_asset=record.outcome_name.upper(),
        quote_asset="USDC",
        market_type="binary",
        status="ACTIVE" if active else "CLOSED",
        active=active,
        tradable=tradable,
        constraints=constraints,
        metrics=metrics,
        scanned_at=scanned_at,
        source="gamma+clob",
        raw={
            "market": market,
            "book": book,
            "question": market.get("question") or "",
            "outcome_name": record.outcome_name,
            "token_id": record.token_id,
            "slug": market.get("slug") or "",
            "liquidity": liquidity,
        },
    )


class PolymarketMarketScanner:
    venue = "polymarket"

    def __init__(
        self,
        *,
        client: PolymarketPublicDataClient | None = None,
        allowed_quotes: Sequence[str] = ("USDC",),
        outcome_mode: str = "yes",
        limit: int = 100,
        book_limit: int = 25,
    ) -> None:
        self.client = client or PolymarketPublicDataClient()
        self.allowed_quotes = tuple(quote.upper() for quote in allowed_quotes if quote)
        self.outcome_mode = outcome_mode.lower().strip() or "yes"
        self.limit = max(1, int(limit))
        self.book_limit = max(1, int(book_limit))

    def scan(self) -> list[MarketCandidate]:
        scanned_at = utc_now_iso()
        markets = self.client.list_markets(limit=self.limit, closed=False)
        records: list[PolymarketMarketRecord] = []
        for market in markets:
            if not isinstance(market, dict):
                continue
            if self.allowed_quotes and "USDC" not in self.allowed_quotes:
                continue
            records.extend(_iter_outcomes(market, outcome_mode=self.outcome_mode))

        candidates: list[MarketCandidate] = []
        for record in records[: self.book_limit]:
            try:
                book = self.client.get_book(record.token_id)
            except Exception:
                book = {}
            candidates.append(_normalize_market(record, book, scanned_at))
        return candidates


def polymarket_filters(max_entry_notional: float = 5.0, *, allowed_quotes: Sequence[str] = ("USDC",)) -> SelectionFilters:
    return SelectionFilters(
        allowed_quotes=tuple(allowed_quotes),
        require_active=True,
        require_tradable=True,
        require_spot=False,
        min_last_price=0.01,
        min_quote_volume_24h=5_000.0,
        min_trade_count_24h=0,
        max_spread_bps=800.0,
        max_entry_notional=max_entry_notional,
        excluded_base_suffixes=(),
    )


def polymarket_scoring() -> ScoringConfig:
    return ScoringConfig(
        volume_target_quote_24h=250_000.0,
        trade_count_target_24h=100.0,
        spread_cap_bps=800.0,
        movement_target_pct=10.0,
    )


def scan_polymarket_markets(
    *,
    filters: SelectionFilters | None = None,
    scoring: ScoringConfig | None = None,
    client: PolymarketPublicDataClient | None = None,
    allowed_quotes: Sequence[str] = ("USDC",),
    outcome_mode: str = "yes",
    limit: int = 100,
    book_limit: int = 25,
) -> SelectionResult:
    scanner = PolymarketMarketScanner(
        client=client,
        allowed_quotes=allowed_quotes,
        outcome_mode=outcome_mode,
        limit=limit,
        book_limit=book_limit,
    )
    selector = MarketSelector(
        MarketSelectionConfig(
            filters=filters or polymarket_filters(allowed_quotes=allowed_quotes),
            scoring=scoring or polymarket_scoring(),
        )
    )
    return select_markets(scanner.scan(), selector.config, venue=scanner.venue)
