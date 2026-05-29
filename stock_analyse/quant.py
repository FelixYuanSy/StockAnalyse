from __future__ import annotations

from statistics import median
from typing import Any

import pandas as pd

from .models import AssetType, StockQuote


HORIZONS = (1, 3, 5)


def build_quant_context(
    history: pd.DataFrame,
    quote: StockQuote,
    asset_type: AssetType,
    support_levels: tuple[float, float],
    resistance_levels: tuple[float, float],
    fundamental_data: dict | None = None,
) -> dict[str, Any]:
    """Build lightweight, explainable quant evidence for the AI report."""
    if history is None or history.empty or len(history) < 65:
        return {
            "available": False,
            "reason": "历史K线不足，无法生成量化因子和相似信号回测。",
        }

    data = history.copy().reset_index(drop=True)
    signal = classify_signal(data)
    factors = compute_factors(
        data=data,
        quote=quote,
        asset_type=asset_type,
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        fundamental_data=fundamental_data or {},
    )
    backtest = event_backtest(data, signal)
    score = _weighted_score(factors)

    return {
        "available": True,
        "version": "lightweight_quant_v1",
        "signal": signal,
        "factor_score": score,
        "confidence": _confidence(backtest, score),
        "factors": factors,
        "event_backtest": backtest,
        "usage_note": (
            "这是轻量事件型回测：只统计历史上类似技术信号出现后未来1/3/5日表现，"
            "不含交易成本、滑点、仓位管理和样本外验证。"
        ),
    }


def classify_signal(data: pd.DataFrame) -> dict[str, Any]:
    latest = data.iloc[-1]
    close = _float(latest.get("close"))
    ma20 = _float(latest.get("ma20"))
    ma60 = _float(latest.get("ma60"))
    rsi14 = _float(latest.get("rsi14"))
    macd_hist = _float(latest.get("macd_hist"))
    volume = _float(latest.get("volume"))
    volume_ma20 = _float(latest.get("volume_ma20"))

    if close is None or ma20 is None or ma60 is None:
        return {"name": "insufficient_indicator", "direction": 0, "label": "指标不足"}

    high_volume = volume is not None and volume_ma20 not in (None, 0) and volume > volume_ma20 * 1.25

    if close > ma20 > ma60 and (macd_hist or 0) > 0:
        name = "trend_long"
        label = "趋势多头"
        direction = 1
    elif close < ma20 < ma60 and (macd_hist or 0) < 0:
        name = "trend_short"
        label = "趋势空头"
        direction = -1
    elif rsi14 is not None and rsi14 < 35 and close < ma20:
        name = "oversold_weak"
        label = "弱势超跌"
        direction = 1
    elif rsi14 is not None and rsi14 > 70:
        name = "overheated"
        label = "高位过热"
        direction = -1
    elif close > ma20 and high_volume:
        name = "volume_breakout"
        label = "放量偏强"
        direction = 1
    else:
        name = "range_neutral"
        label = "震荡中性"
        direction = 0

    return {
        "name": name,
        "label": label,
        "direction": direction,
        "conditions": {
            "close": close,
            "ma20": ma20,
            "ma60": ma60,
            "rsi14": rsi14,
            "macd_hist": macd_hist,
            "high_volume": high_volume,
        },
    }


def compute_factors(
    data: pd.DataFrame,
    quote: StockQuote,
    asset_type: AssetType,
    support_levels: tuple[float, float],
    resistance_levels: tuple[float, float],
    fundamental_data: dict,
) -> list[dict[str, Any]]:
    latest = data.iloc[-1]
    previous_5 = data.iloc[-6] if len(data) >= 6 else data.iloc[0]
    previous_20 = data.iloc[-21] if len(data) >= 21 else data.iloc[0]

    factors = [
        _trend_factor(latest, previous_20),
        _momentum_factor(latest, previous_5, previous_20),
        _volatility_factor(data),
        _volume_factor(latest),
        _level_factor(float(quote.price), support_levels, resistance_levels),
    ]

    if asset_type == "futures":
        factors.extend(_futures_factors(fundamental_data))
    elif asset_type == "etf":
        factors.extend(_etf_factors(fundamental_data))

    return factors


def event_backtest(data: pd.DataFrame, current_signal: dict[str, Any]) -> dict[str, Any]:
    name = current_signal.get("name")
    direction = int(current_signal.get("direction") or 0)
    if name in {"insufficient_indicator"}:
        return {"available": False, "reason": "当前信号无法分类。"}

    rows: list[int] = []
    for index in range(60, len(data) - max(HORIZONS)):
        window = data.iloc[: index + 1]
        if classify_signal(window).get("name") == name:
            rows.append(index)

    if not rows:
        return {
            "available": False,
            "signal_name": name,
            "signal_label": current_signal.get("label"),
            "sample_count": 0,
            "reason": "历史窗口内没有找到相似信号。",
        }

    horizon_stats = {}
    for horizon in HORIZONS:
        directional_returns: list[float] = []
        raw_returns: list[float] = []
        for index in rows:
            if index + horizon >= len(data):
                continue
            entry = _float(data.iloc[index].get("close"))
            future = _float(data.iloc[index + horizon].get("close"))
            if entry in (None, 0) or future is None:
                continue
            raw_return = future / entry - 1
            raw_returns.append(raw_return)
            if direction == 0:
                directional_returns.append(raw_return)
            else:
                directional_returns.append(raw_return * direction)

        horizon_stats[f"{horizon}d"] = _return_stats(directional_returns, raw_returns, direction)

    return {
        "available": True,
        "signal_name": name,
        "signal_label": current_signal.get("label"),
        "direction": direction,
        "sample_count": len(rows),
        "horizons": horizon_stats,
        "interpretation": _backtest_interpretation(horizon_stats, len(rows)),
    }


def _trend_factor(latest: pd.Series, previous_20: pd.Series) -> dict[str, Any]:
    close = _float(latest.get("close"))
    ma20 = _float(latest.get("ma20"))
    ma60 = _float(latest.get("ma60"))
    prev_ma20 = _float(previous_20.get("ma20"))
    score = 50
    evidence = []

    if close is not None and ma20 is not None:
        if close > ma20:
            score += 18
            evidence.append("价格高于MA20")
        else:
            score -= 18
            evidence.append("价格低于MA20")
    if ma20 is not None and ma60 is not None:
        if ma20 > ma60:
            score += 16
            evidence.append("MA20高于MA60")
        else:
            score -= 16
            evidence.append("MA20低于MA60")
    if ma20 is not None and prev_ma20 not in (None, 0):
        slope = ma20 / prev_ma20 - 1
        if slope > 0.01:
            score += 10
            evidence.append("MA20斜率向上")
        elif slope < -0.01:
            score -= 10
            evidence.append("MA20斜率向下")

    return _factor("trend", "趋势因子", score, evidence)


def _momentum_factor(latest: pd.Series, previous_5: pd.Series, previous_20: pd.Series) -> dict[str, Any]:
    close = _float(latest.get("close"))
    prev5 = _float(previous_5.get("close"))
    prev20 = _float(previous_20.get("close"))
    rsi14 = _float(latest.get("rsi14"))
    macd_hist = _float(latest.get("macd_hist"))
    score = 50
    evidence = []

    if close is not None and prev5 not in (None, 0):
        ret5 = close / prev5 - 1
        score += _clip(ret5 * 350, -18, 18)
        evidence.append(f"5日收益{ret5 * 100:.2f}%")
    if close is not None and prev20 not in (None, 0):
        ret20 = close / prev20 - 1
        score += _clip(ret20 * 180, -18, 18)
        evidence.append(f"20日收益{ret20 * 100:.2f}%")
    if macd_hist is not None:
        score += 12 if macd_hist > 0 else -12
        evidence.append("MACD柱为正" if macd_hist > 0 else "MACD柱为负")
    if rsi14 is not None:
        if 45 <= rsi14 <= 65:
            score += 8
            evidence.append("RSI处于健康区间")
        elif rsi14 > 75:
            score -= 12
            evidence.append("RSI过热")
        elif rsi14 < 35:
            score -= 6
            evidence.append("RSI偏弱/超跌")

    return _factor("momentum", "动量因子", score, evidence)


def _volatility_factor(data: pd.DataFrame) -> dict[str, Any]:
    returns = pd.to_numeric(data["close"], errors="coerce").pct_change().dropna().tail(20)
    score = 70
    evidence = []
    if not returns.empty:
        vol = float(returns.std()) * 100
        max_loss = float(returns.min()) * 100
        if vol > 3:
            score -= 25
        elif vol > 1.8:
            score -= 12
        else:
            score += 6
        if max_loss < -4:
            score -= 10
        evidence.append(f"20日波动率约{vol:.2f}%")
        evidence.append(f"单日最大跌幅约{max_loss:.2f}%")
    return _factor("volatility", "波动风险因子", score, evidence)


def _volume_factor(latest: pd.Series) -> dict[str, Any]:
    volume = _float(latest.get("volume"))
    volume_ma5 = _float(latest.get("volume_ma5"))
    volume_ma20 = _float(latest.get("volume_ma20"))
    close = _float(latest.get("close"))
    open_ = _float(latest.get("open"))
    score = 50
    evidence = []

    if volume is not None and volume_ma20 not in (None, 0):
        ratio = volume / volume_ma20
        evidence.append(f"成交量/20日均量={ratio:.2f}")
        if ratio > 1.4 and close is not None and open_ is not None and close >= open_:
            score += 22
            evidence.append("放量上涨")
        elif ratio > 1.4 and close is not None and open_ is not None and close < open_:
            score -= 22
            evidence.append("放量下跌")
        elif volume_ma5 not in (None, 0) and volume_ma5 > volume_ma20:
            score += 8
            evidence.append("5日均量高于20日均量")
    return _factor("volume", "量能因子", score, evidence)


def _level_factor(price: float, support_levels: tuple[float, float], resistance_levels: tuple[float, float]) -> dict[str, Any]:
    support = support_levels[0]
    resistance = resistance_levels[0]
    score = 50
    evidence = []

    if support and resistance and resistance > support:
        position = (price - support) / (resistance - support)
        evidence.append(f"价格处于支撑压力区间{position * 100:.1f}%位置")
        if position < 0.25:
            score += 8
            evidence.append("靠近支撑，潜在盈亏比改善")
        elif position > 0.8:
            score -= 12
            evidence.append("靠近压力，追高风险增加")
        else:
            score += 2

    return _factor("level", "位置/盈亏比因子", score, evidence)


def _futures_factors(fundamental_data: dict) -> list[dict[str, Any]]:
    factors = []
    spot_basis = fundamental_data.get("spot_basis") or []
    if spot_basis:
        latest = spot_basis[0]
        basis_rate = _float(latest.get("dom_basis_rate") or latest.get("basis_rate"))
        score = 50
        evidence = []
        if basis_rate is not None:
            if abs(basis_rate) > 4:
                score -= 12
            elif basis_rate < -1:
                score += 4
            evidence.append(f"主力基差率{basis_rate:.2f}%")
        factors.append(_factor("basis", "期货基差因子", score, evidence))

    long_rows = fundamental_data.get("long_rank") or []
    short_rows = fundamental_data.get("short_rank") or []
    if long_rows or short_rows:
        long_sum = _sum_number(long_rows, "持买单量")
        short_sum = _sum_number(short_rows, "持卖单量")
        score = 50
        evidence = []
        if long_sum and short_sum:
            net = long_sum - short_sum
            score += _clip(net / max(long_sum, short_sum) * 30, -20, 20)
            evidence.append(f"前列席位多空差{net:.0f}")
        factors.append(_factor("position", "期货持仓因子", score, evidence))
    return factors


def _etf_factors(fundamental_data: dict) -> list[dict[str, Any]]:
    detail = fundamental_data.get("realtime_detail") or {}
    factors = []
    if detail:
        amount = _float(detail.get("成交额"))
        turnover = _float(detail.get("换手率"))
        discount = _float(detail.get("基金折价率"))
        score = 55
        evidence = []
        if amount is not None:
            if amount >= 100_000_000:
                score += 16
            elif amount < 20_000_000:
                score -= 18
            evidence.append(f"成交额{amount:.0f}")
        if turnover is not None:
            evidence.append(f"换手率{turnover:.2f}%")
        if discount is not None:
            if abs(discount) <= 0.2:
                score += 8
            elif abs(discount) > 1:
                score -= 16
            evidence.append(f"折价率{discount:.2f}%")
        factors.append(_factor("etf_liquidity_discount", "ETF流动性/折溢价因子", score, evidence))

    holdings = (fundamental_data.get("top_holdings") or {}).get("records") or []
    if holdings:
        top_weights = [_float(row.get("占净值比例")) for row in holdings[:10]]
        top_weights = [item for item in top_weights if item is not None]
        score = 55
        evidence = []
        if top_weights:
            concentration = sum(top_weights)
            if concentration > 45:
                score -= 10
            elif concentration < 30:
                score += 6
            evidence.append(f"前十大持仓合计约{concentration:.2f}%")
        factors.append(_factor("etf_concentration", "ETF持仓集中度因子", score, evidence))
    return factors


def _return_stats(directional_returns: list[float], raw_returns: list[float], direction: int) -> dict[str, Any]:
    if not directional_returns:
        return {"available": False, "sample_count": 0}

    wins = [item for item in directional_returns if item > 0]
    losses = [item for item in directional_returns if item <= 0]
    gain_sum = sum(wins)
    loss_sum = abs(sum(losses))
    return {
        "available": True,
        "sample_count": len(directional_returns),
        "win_rate": round(len(wins) / len(directional_returns) * 100, 2),
        "avg_return": round(sum(raw_returns) / len(raw_returns) * 100, 2),
        "median_return": round(median(raw_returns) * 100, 2),
        "max_gain": round(max(raw_returns) * 100, 2),
        "max_loss": round(min(raw_returns) * 100, 2),
        "directional_avg_return": round(sum(directional_returns) / len(directional_returns) * 100, 2),
        "profit_factor": round(gain_sum / loss_sum, 2) if loss_sum else None,
        "direction_note": "按看空方向统计胜率" if direction < 0 else "按看多方向统计胜率" if direction > 0 else "按原始涨跌统计",
    }


def _backtest_interpretation(horizon_stats: dict[str, Any], sample_count: int) -> str:
    focus = horizon_stats.get("3d") or horizon_stats.get("1d") or {}
    if not focus.get("available"):
        return "样本不足，不能形成有效统计倾向。"
    win_rate = focus.get("win_rate", 0)
    avg_return = focus.get("directional_avg_return", 0)
    if sample_count < 8:
        return "样本数偏少，只能作为弱参考。"
    if win_rate >= 58 and avg_return > 0:
        return "历史相似信号表现偏正向，可作为提高置信度的辅助证据。"
    if win_rate <= 45 or avg_return < 0:
        return "历史相似信号表现不占优，应降低进攻仓位或等待确认。"
    return "历史相似信号表现中性，需要结合关键价位和风险收益比。"


def _weighted_score(factors: list[dict[str, Any]]) -> int:
    if not factors:
        return 50
    total_weight = sum(float(item.get("weight", 1.0)) for item in factors)
    if total_weight <= 0:
        return 50
    score = sum(float(item.get("score", 50)) * float(item.get("weight", 1.0)) for item in factors) / total_weight
    return int(round(_clip(score, 0, 100)))


def _confidence(backtest: dict[str, Any], score: int) -> int:
    base = 45 + abs(score - 50) * 0.35
    if backtest.get("available"):
        sample_count = int(backtest.get("sample_count") or 0)
        base += min(20, sample_count * 1.2)
    return int(round(_clip(base, 30, 85)))


def _factor(key: str, name: str, score: float, evidence: list[str], weight: float = 1.0) -> dict[str, Any]:
    score = _clip(score, 0, 100)
    if score >= 70:
        label = "偏强"
    elif score >= 55:
        label = "略强"
    elif score >= 45:
        label = "中性"
    elif score >= 30:
        label = "偏弱"
    else:
        label = "较弱"
    return {
        "key": key,
        "name": name,
        "score": int(round(score)),
        "label": label,
        "evidence": evidence,
        "weight": weight,
    }


def _sum_number(rows: list[dict], field: str) -> float | None:
    values = [_float(row.get(field)) for row in rows]
    values = [value for value in values if value is not None]
    return sum(values) if values else None


def _float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
