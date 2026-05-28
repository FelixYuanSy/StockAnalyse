from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


AssetType = Literal["stock", "etf", "futures"]
Action = Literal["买入观察", "谨慎持有", "观望", "减仓防守", "规避"]
RiskLevel = Literal["低", "中", "高"]
TrendLabel = Literal["强势上涨", "温和上涨", "震荡", "偏弱下跌", "明显下跌"]
MarketPhase = Literal["盘中", "盘后", "休市"]


@dataclass(frozen=True)
class NewsItem:
    title: str
    source: str
    published_at: str
    summary: str = ""
    url: str = ""


@dataclass(frozen=True)
class Prediction:
    horizon: str
    bias: str
    confidence: int
    summary: str
    strategy: str
    evidence: tuple[str, ...]
    invalidation: str
    watch_levels: tuple[str, ...]


@dataclass(frozen=True)
class StockQuote:
    symbol: str
    name: str
    asset_type: AssetType
    price: float
    change_pct: float
    volume: float | None = None
    turnover_rate: float | None = None


@dataclass(frozen=True)
class AnalysisResult:
    quote: StockQuote
    data_source: str
    market_phase: MarketPhase
    trend: TrendLabel
    risk_level: RiskLevel
    action: Action
    score: int
    support_levels: tuple[float, float]
    resistance_levels: tuple[float, float]
    prediction: Prediction
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    stock_news: tuple[NewsItem, ...] = ()
    global_news: tuple[NewsItem, ...] = ()
    market_data: dict = field(default_factory=dict)
    fundamental_data: dict = field(default_factory=dict)
