from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"

from .models import BookSnapshot, QuoteLevel


class PolymarketPublicClient:
    def __init__(self, host: str, gamma_host: str = GAMMA_MARKETS_URL) -> None:
        self.host = host.rstrip("/")
        self.gamma_host = gamma_host.rstrip("/")

    def get_book(self, token_id: str) -> BookSnapshot:
        query = urlencode({"token_id": token_id})
        req = Request(f"{self.host}/book?{query}", headers={"User-Agent": "openclaw-polymarket-mvp/0.1"})
        with urlopen(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        bids = [QuoteLevel(price=float(level["price"]), size=float(level["size"])) for level in payload.get("bids", [])]
        asks = [QuoteLevel(price=float(level["price"]), size=float(level["size"])) for level in payload.get("asks", [])]
        if not bids or not asks:
            raise ValueError("Orderbook is missing bids or asks")
        return BookSnapshot(
            token_id=str(payload.get("asset_id") or token_id),
            tick_size=float(payload.get("tick_size") or 0.01),
            min_order_size=float(payload.get("min_order_size") or 5),
            best_bid=bids[0].price,
            best_ask=asks[0].price,
            bids=bids,
            asks=asks,
            timestamp=str(payload.get("timestamp") or ""),
            book_hash=str(payload.get("hash") or ""),
        )

    def get_market_metadata(self, token_id: str) -> dict:
        query = urlencode({"limit": 200, "closed": "false"})
        req = Request(f"{self.gamma_host}?{query}", headers={"User-Agent": "openclaw-polymarket-mvp/0.1"})
        with urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            return {}
        for market in payload:
            token_ids = market.get("clobTokenIds")
            if isinstance(token_ids, str):
                try:
                    token_ids = json.loads(token_ids)
                except json.JSONDecodeError:
                    token_ids = []
            if isinstance(token_ids, list) and str(token_id) in {str(item) for item in token_ids}:
                return market if isinstance(market, dict) else {}
        return {}
