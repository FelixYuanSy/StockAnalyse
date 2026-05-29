from __future__ import annotations

from statistics import median
from typing import Any

import pandas as pd

from .models import AssetType, StockQuote


HORIZONS = (1, 3, 5)

FACTOR_GUIDE = {
    "trend": "趋势因子：看价格和MA20、MA60的关系。分数高说明趋势更顺，分数低说明价格在均线下方或均线走弱。",
    "momentum": "动量因子：看近5日/20日涨跌、MACD和RSI。分数高说明上涨动能更强，过热时也会扣分。",
    "volatility": "波动风险因子：看最近波动率和单日最大跌幅。分数低不是一定会跌，而是说明持仓过程更容易大幅波动。",
    "volume": "量能因子：看成交量是否放大，以及放量时价格是上涨还是下跌。放量上涨偏积极，放量下跌偏风险。",
    "level": "位置/盈亏比因子：看当前价离支撑和压力有多近。离支撑近且止损清楚，赔率通常更好；靠近压力追涨风险更高。",
    "basis": "期货基差因子：看期货与现货的价差。基差异常说明期现结构可能不稳定，需要结合交割、仓单和产业预期。",
    "position": "期货持仓因子：看多空席位合计和增减仓。它反映资金结构变化，但不能等同于某个期货公司的自营观点。",
    "etf_liquidity_discount": "ETF流动性/折溢价因子：看成交额、换手率和IOPV折溢价。流动性好、折溢价小，交易成本和跟踪偏离风险更低。",
    "etf_concentration": "ETF持仓集中度因子：看前十大持仓权重。集中度高代表弹性更强，但成分股单一风险也更大。",
}

METRIC_GUIDE = {
    "factor_score": "因子综合分：把趋势、动量、波动、量能、位置等因子加权后的0-100分。越高越偏积极，但不是买入指令。",
    "confidence": "量化置信度：样本数、因子强弱和策略回测共同决定。置信度低时，AI结论也应更保守。",
    "sample_count": "样本数：历史上出现类似信号的次数。少于8次通常只能弱参考。",
    "win_rate": "胜率：历史相似信号里，按当前方向赚钱的比例。胜率高也要看平均收益和最大亏损。",
    "avg_return": "平均收益：样本未来表现的平均值，容易被极端值影响，所以要和中位数一起看。",
    "directional_avg_return": "方向收益：按当前看多/看空方向调整后的收益。看空信号下，价格下跌才算方向收益为正。",
    "profit_factor": "盈亏比：盈利样本总收益/亏损样本总亏损。大于1代表历史盈利总额高于亏损总额。",
    "max_drawdown": "最大回撤：策略历史权益曲线从高点到低点的最大跌幅，用来衡量最难熬的亏损阶段。",
    "strategy_backtest": "策略型回测：用固定入场、ATR止损止盈、最多持有天数和交易成本模拟交易。它比事件统计更接近交易计划，但仍不是实盘保证。",
}


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
    strategy = strategy_backtest(data, signal, asset_type=asset_type)
    score = _weighted_score(factors)

    return {
        "available": True,
        "version": "lightweight_quant_v2",
        "signal": signal,
        "factor_score": score,
        "confidence": _confidence(backtest, score, strategy),
        "factors": factors,
        "event_backtest": backtest,
        "strategy_backtest": strategy,
        "factor_guide": FACTOR_GUIDE,
        "metric_guide": METRIC_GUIDE,
        "usage_note": (
            "这是轻量量化回测：包含相似信号事件统计和简化策略回测。"
            "策略回测使用下一交易日开盘入场、ATR止损止盈、最多持有5日，并扣除简化交易成本；"
            "仍不含真实滑点、盘口冲击、样本外验证和组合仓位管理。"
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


def strategy_backtest(
    data: pd.DataFrame,
    current_signal: dict[str, Any],
    asset_type: AssetType,
    max_holding_days: int = 5,
) -> dict[str, Any]:
    name = current_signal.get("name")
    direction = int(current_signal.get("direction") or 0)
    if direction == 0:
        return {
            "available": False,
            "reason": "当前信号方向为中性，不适合生成策略型回测。",
            "signal_name": name,
        }

    trades = []
    cost_rate = _round_trip_cost_rate(asset_type)
    for index in range(60, len(data) - max_holding_days - 1):
        window = data.iloc[: index + 1]
        if classify_signal(window).get("name") != name:
            continue
        trade = _simulate_trade(
            data=data,
            signal_index=index,
            direction=direction,
            max_holding_days=max_holding_days,
            cost_rate=cost_rate,
        )
        if trade:
            trades.append(trade)

    if not trades:
        return {
            "available": False,
            "reason": "历史窗口内没有足够信号可进行策略型回测。",
            "signal_name": name,
            "direction": direction,
        }

    returns = [trade["return_pct"] / 100 for trade in trades]
    wins = [item for item in returns if item > 0]
    losses = [item for item in returns if item <= 0]
    gain_sum = sum(wins)
    loss_sum = abs(sum(losses))
    equity_curve = _equity_curve(returns)

    return {
        "available": True,
        "signal_name": name,
        "signal_label": current_signal.get("label"),
        "direction": direction,
        "rule": {
            "entry": "信号出现后的下一交易日开盘价",
            "stop_loss": "基于ATR的动态止损",
            "take_profit": "约1.8倍止损距离的动态止盈",
            "max_holding_days": max_holding_days,
            "round_trip_cost_bps": round(cost_rate * 10000, 2),
            "same_day_stop_take_priority": "同日同时触发止损和止盈时，保守按止损成交",
        },
        "trade_count": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 2),
        "avg_return": round(sum(returns) / len(returns) * 100, 2),
        "median_return": round(median(returns) * 100, 2),
        "max_gain": round(max(returns) * 100, 2),
        "max_loss": round(min(returns) * 100, 2),
        "profit_factor": round(gain_sum / loss_sum, 2) if loss_sum else None,
        "max_drawdown": round(_max_drawdown(equity_curve) * 100, 2),
        "avg_holding_days": round(sum(trade["holding_days"] for trade in trades) / len(trades), 2),
        "exit_reasons": _exit_reason_counts(trades),
        "recent_trades": trades[-8:],
        "interpretation": _strategy_interpretation(trades, returns),
    }


def _simulate_trade(
    data: pd.DataFrame,
    signal_index: int,
    direction: int,
    max_holding_days: int,
    cost_rate: float,
) -> dict[str, Any] | None:
    entry_index = signal_index + 1
    if entry_index >= len(data):
        return None

    entry_row = data.iloc[entry_index]
    entry = _float(entry_row.get("open")) or _float(entry_row.get("close"))
    if entry in (None, 0):
        return None

    atr_ratio = _atr_ratio(data.iloc[: signal_index + 1])
    stop_pct = _clip(atr_ratio * 1.2, 0.008, 0.06)
    take_pct = _clip(stop_pct * 1.8, 0.012, 0.12)
    stop_price = entry * (1 - direction * stop_pct)
    take_price = entry * (1 + direction * take_pct)

    exit_price = None
    exit_reason = "time_exit"
    exit_index = min(entry_index + max_holding_days - 1, len(data) - 1)

    for index in range(entry_index, min(entry_index + max_holding_days, len(data))):
        row = data.iloc[index]
        high = _float(row.get("high"))
        low = _float(row.get("low"))
        close = _float(row.get("close"))
        if high is None or low is None or close is None:
            continue

        if direction > 0:
            hit_stop = low <= stop_price
            hit_take = high >= take_price
        else:
            hit_stop = high >= stop_price
            hit_take = low <= take_price

        if hit_stop:
            exit_price = stop_price
            exit_reason = "stop_loss"
            exit_index = index
            break
        if hit_take:
            exit_price = take_price
            exit_reason = "take_profit"
            exit_index = index
            break

        exit_price = close
        exit_index = index

    if exit_price is None:
        return None

    raw_return = (exit_price / entry - 1) * direction
    net_return = raw_return - cost_rate
    return {
        "signal_date": _date_value(data.iloc[signal_index].get("date")),
        "entry_date": _date_value(data.iloc[entry_index].get("date")),
        "exit_date": _date_value(data.iloc[exit_index].get("date")),
        "direction": "long" if direction > 0 else "short",
        "entry": round(entry, 4),
        "exit": round(exit_price, 4),
        "stop": round(stop_price, 4),
        "take_profit": round(take_price, 4),
        "return_pct": round(net_return * 100, 2),
        "holding_days": int(exit_index - entry_index + 1),
        "exit_reason": exit_reason,
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


def _strategy_interpretation(trades: list[dict[str, Any]], returns: list[float]) -> str:
    if len(trades) < 8:
        return "策略回测样本偏少，只能作为弱参考。"
    wins = [item for item in returns if item > 0]
    win_rate = len(wins) / len(returns) * 100
    avg_return = sum(returns) / len(returns) * 100
    drawdown = _max_drawdown(_equity_curve(returns)) * 100
    if win_rate >= 55 and avg_return > 0 and drawdown < 12:
        return "简化策略回测表现偏正向，可作为提高计划置信度的辅助证据。"
    if win_rate < 45 or avg_return <= 0:
        return "简化策略回测不占优，应降低仓位或等待更强确认信号。"
    return "简化策略回测表现中性，需要结合实时结构、风险收益比和新闻驱动。"


def _atr_ratio(data: pd.DataFrame, period: int = 14) -> float:
    if len(data) < 2:
        return 0.015
    recent = data.tail(period + 1).copy()
    highs = pd.to_numeric(recent["high"], errors="coerce")
    lows = pd.to_numeric(recent["low"], errors="coerce")
    closes = pd.to_numeric(recent["close"], errors="coerce")
    prev_close = closes.shift(1)
    true_range = pd.concat(
        [
            highs - lows,
            (highs - prev_close).abs(),
            (lows - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(true_range.dropna().tail(period).mean()) if not true_range.dropna().empty else 0
    close = _float(data.iloc[-1].get("close"))
    if close in (None, 0) or atr <= 0:
        return 0.015
    return _clip(atr / close, 0.005, 0.05)


def _round_trip_cost_rate(asset_type: AssetType) -> float:
    if asset_type == "futures":
        return 0.0004
    if asset_type == "etf":
        return 0.0006
    return 0.0012


def _equity_curve(returns: list[float]) -> list[float]:
    equity = 1.0
    curve = [equity]
    for value in returns:
        equity *= 1 + value
        curve.append(equity)
    return curve


def _max_drawdown(curve: list[float]) -> float:
    peak = curve[0] if curve else 1.0
    max_dd = 0.0
    for value in curve:
        peak = max(peak, value)
        if peak:
            max_dd = max(max_dd, (peak - value) / peak)
    return max_dd


def _exit_reason_counts(trades: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for trade in trades:
        reason = str(trade.get("exit_reason") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _date_value(value: Any) -> str:
    if hasattr(value, "date"):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _weighted_score(factors: list[dict[str, Any]]) -> int:
    if not factors:
        return 50
    total_weight = sum(float(item.get("weight", 1.0)) for item in factors)
    if total_weight <= 0:
        return 50
    score = sum(float(item.get("score", 50)) * float(item.get("weight", 1.0)) for item in factors) / total_weight
    return int(round(_clip(score, 0, 100)))


def _confidence(backtest: dict[str, Any], score: int, strategy: dict[str, Any] | None = None) -> int:
    base = 45 + abs(score - 50) * 0.35
    if backtest.get("available"):
        sample_count = int(backtest.get("sample_count") or 0)
        base += min(20, sample_count * 1.2)
    if strategy and strategy.get("available"):
        trade_count = int(strategy.get("trade_count") or 0)
        base += min(10, trade_count * 0.5)
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
