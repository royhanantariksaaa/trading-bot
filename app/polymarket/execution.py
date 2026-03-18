from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol


@dataclass(slots=True)
class PolymarketLiveCredentials:
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""
    private_key: str = ""
    funder: str = ""
    chain_id: int = 137
    signature_type: int = 0

    @property
    def configured(self) -> bool:
        return all(
            [
                self.api_key.strip(),
                self.api_secret.strip(),
                self.api_passphrase.strip(),
                self.private_key.strip(),
                self.funder.strip(),
            ]
        )


@dataclass(slots=True)
class AccountSnapshot:
    cash_usdc: float = 0.0
    locked_usdc: float = 0.0
    positions: list[dict] = field(default_factory=list)
    open_orders: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class OrderRequest:
    token_id: str
    side: str
    price: float
    size: float
    order_type: str = "GTC"
    client_order_id: str = ""


class ExecutionGateway(Protocol):
    def validate_ready(self) -> None: ...
    def get_account_snapshot(self) -> AccountSnapshot: ...
    def place_order(self, request: OrderRequest) -> dict: ...
    def cancel_order(self, order_id: str) -> dict: ...
    def sync_fills(self, *, since: str = "") -> list[dict]: ...


class UnimplementedLiveGateway:
    """Fail-closed placeholder for real Polymarket live trading support.

    This intentionally does not fake live trading. It exists to document the shape
    of the missing execution layer so the rest of the bot can be wired honestly.
    """

    def __init__(self, credentials: PolymarketLiveCredentials) -> None:
        self.credentials = credentials

    def validate_ready(self) -> None:
        if not self.credentials.configured:
            raise NotImplementedError(
                "Polymarket live trading is not ready: missing PM_CLOB_API_KEY/SECRET/PASSPHRASE, PM_PRIVATE_KEY, or PM_FUNDER. "
                "Even with credentials present, a real signed execution client is still not implemented in this repo."
            )
        raise NotImplementedError(
            "Polymarket live trading scaffold only: signed auth, order placement/cancel, balances/positions, and fill sync still need a verified implementation."
        )

    def get_account_snapshot(self) -> AccountSnapshot:
        self.validate_ready()
        raise AssertionError("unreachable")

    def place_order(self, request: OrderRequest) -> dict:
        self.validate_ready()
        raise AssertionError("unreachable")

    def cancel_order(self, order_id: str) -> dict:
        self.validate_ready()
        raise AssertionError("unreachable")

    def sync_fills(self, *, since: str = "") -> list[dict]:
        self.validate_ready()
        raise AssertionError("unreachable")
