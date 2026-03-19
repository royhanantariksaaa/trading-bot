from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app.binance.outlook import (
    MarketOutlookReport,
    OutlookHorizon,
    _adjusted_confidence_from_horizons,
    _consensus_rationale,
    _append_outlook_history,
)


class OutlookTest(unittest.TestCase):
    def test_adjusted_confidence_penalizes_disagreement(self) -> None:
        horizons = (
            OutlookHorizon(label="6h", timeframe="15m", candles=24, bias="bullish", confidence="medium", score=4.5, regime="trend"),
            OutlookHorizon(label="24h", timeframe="1h", candles=24, bias="bearish", confidence="medium", score=-4.0, regime="volatile"),
            OutlookHorizon(label="3d", timeframe="4h", candles=18, bias="neutral", confidence="low", score=0.5, regime="range"),
        )
        self.assertEqual(_adjusted_confidence_from_horizons(3.2, horizons), "low")

    def test_consensus_rationale_mentions_weighting(self) -> None:
        horizons = (
            OutlookHorizon(label="6h", timeframe="15m", candles=24, bias="bullish", confidence="low", score=1.0, regime="range"),
            OutlookHorizon(label="24h", timeframe="1h", candles=24, bias="bearish", confidence="medium", score=-3.0, regime="trend"),
            OutlookHorizon(label="3d", timeframe="4h", candles=18, bias="bearish", confidence="medium", score=-2.2, regime="trend"),
        )
        rationale = _consensus_rationale(horizons, -2.11)
        self.assertTrue(any("24h=0.5" in line for line in rationale))
        self.assertTrue(any("bearish" in line.lower() for line in rationale))

    def test_append_outlook_history_writes_jsonl(self) -> None:
        report = MarketOutlookReport(
            symbol="XRP/USDC",
            generated_at="2026-03-19T08:00:00+00:00",
            summary_bias="bearish",
            summary_confidence="low",
            summary_score=-1.9,
            summary_rationale=("Weighted consensus score=-1.90",),
            horizons=(
                OutlookHorizon(
                    label="24h",
                    timeframe="1h",
                    candles=24,
                    bias="bearish",
                    confidence="medium",
                    score=-3.8,
                    regime="trend",
                    metrics={"rsi": 42.1},
                ),
            ),
        )
        path = Path(__file__).resolve().parent / ".tmp_outlook_history.jsonl"
        try:
            _append_outlook_history(report, path)
            rows = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(rows), 1)
            payload = json.loads(rows[0])
            self.assertEqual(payload["symbol"], "XRP/USDC")
            self.assertEqual(payload["summary_bias"], "bearish")
            self.assertEqual(payload["horizons"][0]["label"], "24h")
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
