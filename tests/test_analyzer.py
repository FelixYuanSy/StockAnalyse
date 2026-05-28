from __future__ import annotations

import unittest
import json
from pathlib import Path
import tempfile

import pandas as pd

from stock_analyse.ai_advisor import _analysis_payload
from stock_analyse.analyzer import StockAnalyzer
from stock_analyse.html_report import generate_html_report
from stock_analyse.instrument_parser import is_instrument_text, parse_instrument_input
from stock_analyse.models import StockQuote


class StockAnalyzerTest(unittest.TestCase):
    def test_parse_instrument_prefixes(self) -> None:
        self.assertEqual(parse_instrument_input("stock:600519").asset, "stock")
        self.assertEqual(parse_instrument_input("etf:510300").asset, "etf")
        self.assertEqual(parse_instrument_input("futures:LC2609").asset, "futures")
        self.assertTrue(is_instrument_text("600519"))
        self.assertTrue(is_instrument_text("510300"))
        self.assertTrue(is_instrument_text("LC2609"))
        self.assertTrue(is_instrument_text("futures:LC2609"))

    def test_analyze_generates_report_fields(self) -> None:
        rows = []
        price = 10.0
        for index in range(90):
            price += 0.08
            rows.append(
                {
                    "date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=index),
                    "open": price - 0.05,
                    "close": price,
                    "high": price + 0.1,
                    "low": price - 0.2,
                    "volume": 1_000_000 + index * 2_000,
                    "change_pct": 0.8,
                    "turnover_rate": 1.2,
                }
            )

        quote = StockQuote(symbol="000001", name="平安银行", asset_type="stock", price=price, change_pct=0.8)
        result = StockAnalyzer().analyze(quote=quote, history=pd.DataFrame(rows), market_phase="盘后")

        self.assertEqual(result.quote.symbol, "000001")
        self.assertGreaterEqual(result.score, 0)
        self.assertLessEqual(result.score, 100)
        self.assertTrue(result.reasons)
        self.assertTrue(result.prediction.evidence)
        self.assertTrue(result.market_data["daily_kline_tail"])
        self.assertIsInstance(result.fundamental_data, dict)
        json.dumps(_analysis_payload(result), ensure_ascii=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = generate_html_report(result, "AI analysis text", Path(tmpdir))
            self.assertTrue(report_path.exists())
            self.assertIn("AI analysis text", report_path.read_text(encoding="utf-8"))
        self.assertEqual(len(result.support_levels), 2)
        self.assertEqual(len(result.resistance_levels), 2)


if __name__ == "__main__":
    unittest.main()
