from __future__ import annotations

import json
from urllib import request, error


class DiscordNotifier:
    def __init__(self, webhook_url: str = "") -> None:
        cleaned = webhook_url.strip().strip('"').strip("'")
        self.webhook_url = cleaned

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def masked_url(self) -> str:
        if not self.enabled:
            return "<disabled>"
        if "/api/webhooks/" not in self.webhook_url:
            return "<invalid-format>"
        prefix, token = self.webhook_url.rsplit("/", 1)
        return f"{prefix}/{token[:6]}..."

    def send(self, content: str) -> None:
        if not self.enabled:
            return
        payload = json.dumps({"content": content}).encode("utf-8")
        req = request.Request(
            self.webhook_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "KlauTradingBot/0.1 (+paper-mode)",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=10) as response:
                response.read()
        except error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            print(
                f"[WARN] Discord alert failed: HTTP {exc.code} | webhook={self.masked_url()} | body={body}",
                flush=True,
            )
        except error.URLError as exc:
            print(f"[WARN] Discord alert failed: {exc} | webhook={self.masked_url()}", flush=True)
