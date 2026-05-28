from __future__ import annotations

from numbers import Number

import pandas as pd

from .indicators import add_indicators
from .models import (
    Action,
    AnalysisResult,
    MarketPhase,
    NewsItem,
    Prediction,
    RiskLevel,
    StockQuote,
    TrendLabel,
)


class StockAnalyzer:
    def analyze(
        self,
        quote: StockQuote,
        history: pd.DataFrame,
        market_phase: MarketPhase,
        intraday: pd.DataFrame | None = None,
        stock_news: tuple[NewsItem, ...] = (),
        global_news: tuple[NewsItem, ...] = (),
        data_warnings: tuple[str, ...] = (),
        fundamental_data: dict | None = None,
    ) -> AnalysisResult:
        data = add_indicators(history)
        latest = data.iloc[-1]
        previous = data.iloc[-2]

        score = 45
        reasons: list[str] = ["45 分为中性基准，随后按趋势、动能、量能、波动和消息面加减分。"]
        warnings: list[str] = []

        score += self._trend_score(latest, reasons)
        score += self._momentum_score(latest, previous, reasons, warnings)
        score += self._volume_score(latest, reasons, warnings)
        score += self._bollinger_score(latest, reasons, warnings)

        stock_news_score, stock_news_reason = self._news_score(stock_news)
        global_news_score, global_news_reason = self._news_score(global_news)
        if stock_news_reason:
            reasons.append(f"个股消息面: {stock_news_reason}")
            score += stock_news_score
        if market_phase != "盘中" and global_news_reason:
            reasons.append(f"全球消息面: {global_news_reason}")
            score += max(-8, min(8, global_news_score))

        recent_20 = data.tail(20)
        recent_60 = data.tail(60)
        support_levels = (
            round(float(recent_20["low"].min()), 2),
            round(float(recent_60["low"].min()), 2),
        )
        resistance_levels = (
            round(float(recent_20["high"].max()), 2),
            round(float(recent_60["high"].max()), 2),
        )

        score = max(0, min(100, score))
        trend = self._trend_label(score)
        risk_level = self._risk_level(score, latest, warnings)
        action = self._action(score, risk_level)
        prediction = self._prediction(
            score=score,
            latest=latest,
            previous=previous,
            market_phase=market_phase,
            intraday=intraday,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            stock_news_score=stock_news_score,
            global_news_score=global_news_score,
        )

        if latest["close"] < latest["ma20"]:
            warnings.append("收盘价低于 MA20，短线结构仍需防守。")
        if quote.price < support_levels[0]:
            warnings.append("价格跌破 20 日支撑区，短线止损纪律优先。")

        return AnalysisResult(
            quote=quote,
            data_source="实时行情" if not data_warnings else "最新日线",
            market_phase=market_phase,
            trend=trend,
            risk_level=risk_level,
            action=action,
            score=score,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            prediction=prediction,
            reasons=tuple(reasons),
            warnings=tuple(dict.fromkeys((*data_warnings, *warnings))),
            stock_news=stock_news,
            global_news=global_news,
            market_data={
                "daily_kline_tail": self._records(data.tail(30), "date"),
                "intraday_kline_tail": self._records(intraday.tail(24), "datetime") if intraday is not None else [],
            },
            fundamental_data=fundamental_data or {},
        )

    @staticmethod
    def _trend_score(latest: pd.Series, reasons: list[str]) -> int:
        close = latest["close"]
        ma5 = latest["ma5"]
        ma10 = latest["ma10"]
        ma20 = latest["ma20"]
        ma60 = latest["ma60"]

        if close > ma5 > ma10 > ma20 > ma60:
            reasons.append("价格站上 MA5/10/20/60，均线呈多头排列，趋势分 +22。")
            return 22
        if close > ma20 > ma60:
            reasons.append("价格位于 MA20 和 MA60 上方，中期趋势偏强，趋势分 +15。")
            return 15
        if close > ma20:
            reasons.append("价格位于 MA20 上方，但均线未完全多头，趋势分 +8。")
            return 8
        if close < ma20 < ma60:
            reasons.append("价格低于 MA20 且 MA20 低于 MA60，趋势分 -18。")
            return -18

        reasons.append("均线结构没有形成明确方向，趋势分 -3。")
        return -3

    @staticmethod
    def _momentum_score(
        latest: pd.Series,
        previous: pd.Series,
        reasons: list[str],
        warnings: list[str],
    ) -> int:
        score = 0

        if latest["macd_hist"] > 0 and latest["macd_hist"] > previous["macd_hist"]:
            reasons.append("MACD 柱体为正且继续扩大，短线动能分 +12。")
            score += 12
        elif latest["macd_hist"] > 0:
            reasons.append("MACD 仍在零轴上方，但扩张不明显，动能分 +6。")
            score += 6
        else:
            warnings.append("MACD 柱体为负，短线动能偏弱。")
            score -= 8

        rsi = latest["rsi14"]
        if 45 <= rsi <= 65:
            reasons.append("RSI 处于健康区间，未明显过热，动能分 +8。")
            score += 8
        elif 65 < rsi <= 75:
            reasons.append("RSI 偏强，趋势有延续性，动能分 +5。")
            score += 5
            warnings.append("RSI 接近高位，追涨需要降低仓位。")
        elif rsi > 75:
            warnings.append("RSI 超买，短线回撤风险较高。")
            score -= 10
        elif rsi < 35:
            warnings.append("RSI 偏低，弱势延续和超跌反弹都可能出现。")
            score -= 5

        return score

    @staticmethod
    def _volume_score(latest: pd.Series, reasons: list[str], warnings: list[str]) -> int:
        volume = latest["volume"]
        volume_ma5 = latest["volume_ma5"]
        volume_ma20 = latest["volume_ma20"]

        if volume > volume_ma20 * 1.5 and latest["close"] > latest["open"]:
            reasons.append("成交量显著高于 20 日均量且收阳，量能分 +10。")
            return 10
        if volume > volume_ma20 * 1.5 and latest["close"] < latest["open"]:
            warnings.append("放量下跌，说明分歧或抛压较重。")
            return -10
        if volume_ma5 > volume_ma20:
            reasons.append("5 日均量高于 20 日均量，近期活跃度提升，量能分 +5。")
            return 5

        warnings.append("成交量未明显放大，趋势确认度一般。")
        return -2

    @staticmethod
    def _bollinger_score(latest: pd.Series, reasons: list[str], warnings: list[str]) -> int:
        close = latest["close"]
        upper = latest["boll_upper"]
        lower = latest["boll_lower"]
        middle = latest["boll_mid"]

        if close > upper:
            reasons.append("价格突破布林上轨，短线强势，波动分 +5。")
            warnings.append("突破上轨后波动会放大，需要防止冲高回落。")
            return 5
        if close > middle:
            reasons.append("价格位于布林中轨上方，结构偏积极，波动分 +5。")
            return 5
        if close < lower:
            warnings.append("价格跌破布林下轨，短线风险释放但趋势较弱。")
            return -7

        return 0

    def _prediction(
        self,
        score: int,
        latest: pd.Series,
        previous: pd.Series,
        market_phase: MarketPhase,
        intraday: pd.DataFrame | None,
        support_levels: tuple[float, float],
        resistance_levels: tuple[float, float],
        stock_news_score: int,
        global_news_score: int,
    ) -> Prediction:
        evidence = [
            f"日线评分 {score}/100，MA20={latest['ma20']:.2f}，MA60={latest['ma60']:.2f}。",
            f"最近一日 K 线: 开 {latest['open']:.2f}，收 {latest['close']:.2f}，高 {latest['high']:.2f}，低 {latest['low']:.2f}。",
            f"MACD 柱体 {latest['macd_hist']:.2f}，RSI14={latest['rsi14']:.1f}。",
        ]

        intraday_score = 0
        if market_phase == "盘中" and intraday is not None and len(intraday) >= 12:
            intraday_score, intraday_reason = self._intraday_score(intraday)
            evidence.append(intraday_reason)

        combined = score + intraday_score + stock_news_score + (0 if market_phase == "盘中" else global_news_score)
        confidence = max(35, min(85, 45 + abs(combined - 50) // 2))

        if combined >= 68:
            bias = "偏多"
            summary = "短线更可能延续反弹或震荡上行，但接近压力位时不宜追高。"
            strategy = (
                f"可等待回踩不破 {support_levels[0]:.2f} 后小仓试探；"
                f"若放量突破 {resistance_levels[0]:.2f}，再考虑顺势加仓。"
            )
        elif combined >= 52:
            bias = "震荡偏多"
            summary = "下一阶段更可能在支撑和压力之间震荡，方向需要成交量确认。"
            strategy = (
                f"低吸位置优先看 {support_levels[0]:.2f} 附近，"
                f"接近 {resistance_levels[0]:.2f} 先看承接，不追涨。"
            )
        elif combined >= 38:
            bias = "震荡偏弱"
            summary = "短线反弹力度不足，下一阶段更可能弱震荡或继续测试支撑。"
            strategy = (
                f"已有仓位以防守为主，跌破 {support_levels[0]:.2f} 需要降仓；"
                f"未持仓等待重新站回 MA20 后再评估。"
            )
        else:
            bias = "偏空"
            summary = "趋势和动能暂时不支持主动进攻，下一阶段优先防止继续走弱。"
            strategy = (
                f"不建议抄底追反弹；若不能快速收回 {support_levels[0]:.2f}，"
                "以规避或轻仓观察为主。"
            )

        horizon = "盘中未来 30-60 分钟" if market_phase == "盘中" else "下一交易日"
        invalidation = (
            f"若价格有效跌破 {support_levels[0]:.2f}，当前预测失效并转为防守。"
            if bias in {"偏多", "震荡偏多"}
            else f"若放量站上 {resistance_levels[0]:.2f}，偏弱判断需要重新评估。"
        )

        evidence.append(
            f"消息面评分: 个股 {stock_news_score:+d}，全球 {global_news_score:+d}。"
        )
        evidence.append(
            f"前一交易日收盘变化: {latest['close'] - previous['close']:+.2f}。"
        )

        return Prediction(
            horizon=horizon,
            bias=bias,
            confidence=int(confidence),
            summary=summary,
            strategy=strategy,
            evidence=tuple(evidence),
            invalidation=invalidation,
            watch_levels=(
                f"第一支撑 {support_levels[0]:.2f}",
                f"第二支撑 {support_levels[1]:.2f}",
                f"第一压力 {resistance_levels[0]:.2f}",
                f"第二压力 {resistance_levels[1]:.2f}",
            ),
        )

    @staticmethod
    def _intraday_score(intraday: pd.DataFrame) -> tuple[int, str]:
        recent = intraday.tail(12)
        first_close = float(recent.iloc[0]["close"])
        last_close = float(recent.iloc[-1]["close"])
        change_pct = (last_close / first_close - 1) * 100
        vwap = float((recent["close"] * recent["volume"]).sum() / recent["volume"].sum())
        volume_now = float(recent.tail(3)["volume"].mean())
        volume_base = float(recent.head(9)["volume"].mean())

        score = 0
        if change_pct > 0.4:
            score += 6
        elif change_pct < -0.4:
            score -= 6

        if last_close > vwap:
            score += 4
        else:
            score -= 4

        if volume_base > 0 and volume_now > volume_base * 1.3:
            score += 3 if last_close >= first_close else -3

        reason = (
            f"分钟线依据: 近 12 根 5 分钟 K 线涨跌 {change_pct:+.2f}%，"
            f"最新价 {'高于' if last_close > vwap else '低于'}短线 VWAP {vwap:.2f}。"
        )
        return score, reason

    @staticmethod
    def _news_score(news: tuple[NewsItem, ...]) -> tuple[int, str]:
        if not news:
            return 0, ""

        positive_words = ("上涨", "增长", "买入", "增持", "利好", "上调", "获批", "回购", "盈利")
        negative_words = (
            "下跌",
            "下降",
            "减持",
            "亏损",
            "风险",
            "处罚",
            "爆雷",
            "违约",
            "终止",
            "下调",
            "军事",
            "战争",
            "停火",
            "冲突",
            "制裁",
            "霍尔木兹",
            "禁止驶入",
        )

        score = 0
        hits: list[str] = []
        for item in news[:5]:
            text = f"{item.title} {item.summary}"
            local = 0
            if any(word in text for word in positive_words):
                local += 2
            if any(word in text for word in negative_words):
                local -= 2
            if local:
                hits.append(item.title[:30])
            score += local

        score = max(-10, min(10, score))
        if score > 0:
            tone = "偏利好"
        elif score < 0:
            tone = "偏利空"
        else:
            tone = "中性"

        sample = f"，代表标题: {'；'.join(hits[:2])}" if hits else ""
        return score, f"{tone}，样本 {len(news[:5])} 条{sample}。"

    @staticmethod
    def _trend_label(score: int) -> TrendLabel:
        if score >= 75:
            return "强势上涨"
        if score >= 58:
            return "温和上涨"
        if score >= 42:
            return "震荡"
        if score >= 25:
            return "偏弱下跌"
        return "明显下跌"

    @staticmethod
    def _risk_level(score: int, latest: pd.Series, warnings: list[str]) -> RiskLevel:
        if latest["rsi14"] > 75 or latest["close"] < latest["ma60"] or score < 35:
            return "高"
        if score < 55 or len(warnings) >= 2:
            return "中"
        return "低"

    @staticmethod
    def _action(score: int, risk_level: RiskLevel) -> Action:
        if risk_level == "高":
            return "减仓防守" if score >= 35 else "规避"
        if score >= 75:
            return "谨慎持有"
        if score >= 58:
            return "买入观察"
        if score >= 42:
            return "观望"
        return "减仓防守"

    @staticmethod
    def _records(data: pd.DataFrame, date_column: str) -> list[dict]:
        columns = [
            column
            for column in (
                date_column,
                "open",
                "high",
                "low",
                "close",
                "volume",
                "ma5",
                "ma10",
                "ma20",
                "ma60",
                "rsi14",
                "macd",
                "macd_signal",
                "macd_hist",
                "boll_upper",
                "boll_mid",
                "boll_lower",
            )
            if column in data.columns
        ]
        rows: list[dict] = []
        for raw in data[columns].to_dict(orient="records"):
            row = {}
            for key, value in raw.items():
                if pd.isna(value):
                    row[key] = None
                elif hasattr(value, "isoformat"):
                    row[key] = value.isoformat()
                elif isinstance(value, Number):
                    row[key] = round(value, 4)
                else:
                    row[key] = value
            rows.append(row)
        return rows
