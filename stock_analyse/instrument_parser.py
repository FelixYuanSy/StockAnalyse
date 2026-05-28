from __future__ import annotations

import re
from dataclasses import dataclass

from .models import AssetType


ASSET_ALIASES: dict[str, AssetType] = {
    "stock": "stock",
    "a": "stock",
    "a股": "stock",
    "股票": "stock",
    "etf": "etf",
    "fund": "etf",
    "基金": "etf",
    "futures": "futures",
    "future": "futures",
    "期货": "futures",
    "qh": "futures",
}


@dataclass(frozen=True)
class InstrumentInput:
    symbol: str
    asset: AssetType | None = None


def parse_instrument_input(raw: str) -> InstrumentInput:
    text = raw.strip()
    if ":" in text:
        prefix, symbol = text.split(":", 1)
        asset = ASSET_ALIASES.get(prefix.strip().lower())
        if asset and symbol.strip():
            return InstrumentInput(symbol=symbol.strip(), asset=asset)
    return InstrumentInput(symbol=text)


def is_instrument_text(raw: str) -> bool:
    parsed = parse_instrument_input(raw)
    text = parsed.symbol.strip()
    return bool(
        re.fullmatch(r"\d{6}", text)
        or re.fullmatch(r"(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_]{2,12}", text)
    )


def asset_to_cli_value(asset: AssetType | None, fallback: str = "auto") -> str:
    return asset if asset else fallback
