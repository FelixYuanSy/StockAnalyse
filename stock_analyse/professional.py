from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from .indicators import add_indicators
from .models import AssetType, NewsItem, StockQuote


FUTURES_STRONG_KEYWORDS = {
    "LC": ("碳酸锂", "电池级碳酸锂", "锂矿", "盐湖", "锂电池", "新能源车", "广期所", "仓单", "基差"),
    "SI": ("工业硅", "多晶硅", "硅料", "光伏", "广期所", "仓单", "基差"),
    "RB": ("螺纹钢", "钢材", "铁矿", "地产", "基建", "库存", "基差"),
    "I": ("铁矿", "港口库存", "钢厂", "澳洲矿", "基差"),
    "CU": ("铜", "电解铜", "有色", "库存", "基差"),
    "AL": ("铝", "电解铝", "氧化铝", "有色", "库存", "基差"),
}

FUTURES_WEAK_KEYWORDS = {
    "LC": ("有色", "商品", "宏观", "美元", "利率", "新能源汽车", "电池"),
    "SI": ("有色", "商品", "宏观", "新能源", "光伏"),
}


def build_professional_context(
    quote: StockQuote,
    history: pd.DataFrame,
    asset_type: AssetType,
    fundamental_data: dict,
    news: tuple[NewsItem, ...],
) -> dict:
    context: dict[str, Any] = {
        "purpose": "给 AI 的专业投研底稿，用于减少模板化判断和新闻误读。",
        "data_time_warning": _data_time_warning(quote, history),
        "news_relevance": _news_relevance(quote.symbol, asset_type, news),
    }

    if asset_type == "futures":
        context.update(
            {
                "basis_summary": _basis_summary(fundamental_data),
                "position_summary": _position_summary(fundamental_data),
                "level_plan": _level_plan(quote, history),
            }
        )

    return context


def _data_time_warning(quote: StockQuote, history: pd.DataFrame) -> dict:
    latest = history.iloc[-1]
    last_close = _float(latest.get("close"))
    price_gap = quote.price - last_close if last_close is not None else None
    price_gap_pct = (price_gap / last_close * 100) if price_gap is not None and last_close else None
    return {
        "quote_price": quote.price,
        "latest_kline_close": last_close,
        "latest_kline_date": str(latest.get("date", "")),
        "price_gap": round(price_gap, 4) if price_gap is not None else None,
        "price_gap_pct": round(price_gap_pct, 4) if price_gap_pct is not None else None,
        "instruction": "若 quote_price 与 latest_kline_close 差异较大，必须明确说明实时价/指示价和日线收盘价不在同一时间截面。",
    }


def _basis_summary(fundamental_data: dict) -> dict:
    rows = fundamental_data.get("spot_basis") or []
    if not rows:
        return {"available": False, "instruction": "现货/基差缺失时不得强行判断期现结构。"}

    row = rows[0]
    return {
        "available": True,
        "data_date": row.get("data_date") or row.get("date"),
        "spot_price": row.get("spot_price"),
        "dominant_contract": row.get("dominant_contract"),
        "dominant_contract_price": row.get("dominant_contract_price"),
        "dominant_basis": row.get("dom_basis"),
        "dominant_basis_rate": row.get("dom_basis_rate"),
        "interpretation_hint": "基差为负通常表示期货低于现货；需要结合交割、仓单、预期和流动性判断，不可单独作为买卖信号。",
    }


def _position_summary(fundamental_data: dict) -> dict:
    longs = fundamental_data.get("long_position_rank") or []
    shorts = fundamental_data.get("short_position_rank") or []
    volumes = fundamental_data.get("volume_rank") or []

    long_total = _sum_field(longs, "多单持仓")
    short_total = _sum_field(shorts, "空单持仓")
    long_change = _sum_field(longs, "比上交易增减")
    short_change = _sum_field(shorts, "比上交易增减")

    return {
        "top_long_total": long_total,
        "top_short_total": short_total,
        "net_short": short_total - long_total if long_total is not None and short_total is not None else None,
        "top_long_change": long_change,
        "top_short_change": short_change,
        "top_volume_total": _sum_field(volumes, "成交量"),
        "data_date": _first_non_empty(longs, "data_date") or _first_non_empty(shorts, "data_date"),
        "interpretation_warning": "席位数据代表会员客户汇总，不等于期货公司自营观点；重点看前N合计、净持仓和增减仓方向，不要只解读单个席位。",
    }


def _level_plan(quote: StockQuote, history: pd.DataFrame) -> dict:
    data = add_indicators(history)
    latest = data.iloc[-1]
    recent_20 = data.tail(20)
    recent_60 = data.tail(60)

    supports = _sorted_levels(
        quote.price,
        (
            latest.get("low"),
            latest.get("ma60"),
            recent_20["low"].min(),
            recent_60["low"].min(),
            latest.get("boll_lower"),
        ),
        below=True,
    )
    resistances = _sorted_levels(
        quote.price,
        (
            latest.get("ma5"),
            latest.get("ma10"),
            latest.get("ma20"),
            recent_20["high"].max(),
            recent_60["high"].max(),
        ),
        below=False,
    )

    long_plan = _risk_reward(entry=quote.price, stop=supports[0] if supports else None, target=resistances[1] if len(resistances) > 1 else (resistances[0] if resistances else None), direction="long")
    short_plan = _risk_reward(entry=quote.price, stop=resistances[0] if resistances else None, target=supports[1] if len(supports) > 1 else (supports[0] if supports else None), direction="short")

    return {
        "intraday_supports": supports[:3],
        "intraday_resistances": resistances[:3],
        "swing_supports": supports,
        "swing_resistances": resistances,
        "long_risk_reward": long_plan,
        "short_risk_reward": short_plan,
        "instruction": "报告必须用这些价位给出入场、止损、目标和赔率；如果胜率不足，即使赔率看似合适也应降低仓位或观望。",
    }


def _news_relevance(symbol: str, asset_type: AssetType, news: tuple[NewsItem, ...]) -> dict:
    root = "".join(char for char in symbol.upper() if char.isalpha())
    strong = FUTURES_STRONG_KEYWORDS.get(root, (symbol,)) if asset_type == "futures" else (symbol,)
    weak = FUTURES_WEAK_KEYWORDS.get(root, ()) if asset_type == "futures" else ()

    strong_items = []
    weak_items = []
    unrelated_items = []
    for item in news:
        text = f"{item.title} {item.summary}"
        row = asdict(item)
        if any(keyword and keyword in text for keyword in strong):
            strong_items.append(row)
        elif any(keyword and keyword in text for keyword in weak):
            weak_items.append(row)
        else:
            unrelated_items.append(row)

    return {
        "strong_related": strong_items[:8],
        "weak_related": weak_items[:6],
        "excluded_or_background": unrelated_items[:8],
        "instruction": "强相关新闻才能作为核心依据；弱相关新闻只能辅助；无关新闻不得用于方向判断。",
    }


def _risk_reward(entry: float, stop: float | None, target: float | None, direction: str) -> dict:
    if stop is None or target is None:
        return {"available": False}
    if direction == "long":
        risk = entry - stop
        reward = target - entry
    else:
        risk = stop - entry
        reward = entry - target
    ratio = reward / risk if risk and risk > 0 else None
    return {
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "risk_points": round(risk, 2) if risk is not None else None,
        "reward_points": round(reward, 2) if reward is not None else None,
        "reward_risk_ratio": round(ratio, 2) if ratio is not None else None,
    }


def _sorted_levels(price: float, values, below: bool) -> list[float]:
    levels = []
    for value in values:
        number = _float(value)
        if number is None:
            continue
        if below and number < price:
            levels.append(round(number, 2))
        if not below and number > price:
            levels.append(round(number, 2))
    return sorted(set(levels), reverse=below)


def _sum_field(rows: list[dict], field: str) -> float | None:
    values = [_float(row.get(field)) for row in rows]
    values = [value for value in values if value is not None]
    return round(sum(values), 4) if values else None


def _first_non_empty(rows: list[dict], field: str):
    for row in rows:
        value = row.get(field)
        if value not in (None, ""):
            return value
    return None


def _float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
