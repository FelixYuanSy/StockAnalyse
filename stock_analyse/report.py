from __future__ import annotations

from .models import AnalysisResult, NewsItem


def format_report(result: AnalysisResult) -> str:
    quote = result.quote
    volume = _format_optional(quote.volume, "{:,.0f}")
    turnover = _format_optional(quote.turnover_rate, "{:.2f}%")
    asset_name = _asset_name(quote.asset_type)

    lines = [
        "",
        f"{quote.name} ({quote.symbol})",
        "-" * 42,
        f"标的类型: {asset_name}",
        f"当前价格: {quote.price:.2f}",
        f"今日涨跌幅: {quote.change_pct:.2f}%",
        f"成交量: {volume}",
        f"换手率: {turnover}",
        f"数据来源: {result.data_source}",
        f"市场状态: {result.market_phase}",
        "",
        f"趋势判断: {result.trend}",
        f"综合评分: {result.score}/100",
        f"风险等级: {result.risk_level}",
        f"操作建议: {result.action}",
        f"支撑位: {result.support_levels[0]:.2f} / {result.support_levels[1]:.2f}",
        f"压力位: {result.resistance_levels[0]:.2f} / {result.resistance_levels[1]:.2f}",
        "",
        f"{result.prediction.horizon}预测: {result.prediction.bias}",
        f"预测置信度: {result.prediction.confidence}/100",
        f"预测摘要: {result.prediction.summary}",
        f"执行建议: {result.prediction.strategy}",
        f"失效条件: {result.prediction.invalidation}",
        "",
        "预测依据:",
    ]

    lines.extend(f"- {item}" for item in result.prediction.evidence)
    lines.append("")
    lines.extend(
        [
            "关键观察位:",
        ]
    )
    lines.extend(f"- {level}" for level in result.prediction.watch_levels)
    lines.extend(
        [
            "",
            "分析理由:",
        ]
    )

    lines.extend(f"- {reason}" for reason in result.reasons)

    if result.stock_news:
        lines.append("")
        lines.append("个股新闻:")
        lines.extend(_format_news(result.stock_news[:3]))

    if result.global_news and result.market_phase != "盘中":
        lines.append("")
        lines.append("全球/市场新闻:")
        lines.extend(_format_news(result.global_news[:5]))

    if result.warnings:
        lines.append("")
        lines.append("风险提示:")
        lines.extend(f"- {warning}" for warning in result.warnings)

    lines.extend(
        [
            "",
            "声明: 本报告仅用于研究辅助，不构成收益承诺或直接投资指令。",
        ]
    )

    return "\n".join(lines)


def format_follow_up_help() -> str:
    return "\n".join(
        [
            "",
            "你可以继续输入问题，例如:",
            "- 明天怎么操作",
            "- 为什么这么判断",
            "- 风险在哪里",
            "- 支撑压力是多少",
            "- 新闻有什么影响",
            "- 300750",
            "- 510300",
            "- RB0",
            "输入 q 退出。",
        ]
    )


def format_follow_up_answer(question: str, result: AnalysisResult) -> str:
    text = question.strip()
    prediction = result.prediction

    if any(word in text for word in ("明天", "下一交易日", "明日")):
        return "\n".join(
            [
                "",
                f"明日核心建议: {prediction.strategy}",
                f"方向判断: {prediction.bias}，置信度 {prediction.confidence}/100。",
                f"看错条件: {prediction.invalidation}",
            ]
        )

    if any(word in text.lower() for word in ("为什么", "依据", "根据", "原因", "逻辑", "判断", "why", "reason")):
        return "\n".join(["", "主要依据:", *[f"- {item}" for item in prediction.evidence]])

    if any(word in text for word in ("风险", "止损", "跌破")):
        warnings = result.warnings or ("当前没有额外风险提示，但仍需控制仓位。",)
        return "\n".join(["", "风险和防守点:", *[f"- {item}" for item in warnings], f"- {prediction.invalidation}"])

    if any(word in text for word in ("支撑", "压力", "位置", "价位")):
        return "\n".join(["", "关键价位:", *[f"- {item}" for item in prediction.watch_levels]])

    if any(word in text for word in ("新闻", "消息", "全球")):
        lines = ["", "消息面摘要:"]
        if result.stock_news:
            lines.append("个股新闻:")
            lines.extend(_format_news(result.stock_news[:3]))
        if result.global_news:
            lines.append("全球/市场新闻:")
            lines.extend(_format_news(result.global_news[:5]))
        if len(lines) == 2:
            lines.append("- 暂未获取到新闻。")
        return "\n".join(lines)

    return "\n".join(
        [
            "",
            f"当前结论: {result.trend}，{prediction.horizon}判断为{prediction.bias}。",
            f"建议: {prediction.strategy}",
            "你也可以继续问“为什么”“风险”“支撑压力”“新闻影响”。",
        ]
    )


def _format_news(items: tuple[NewsItem, ...]) -> list[str]:
    lines = []
    for item in items:
        timestamp = f" [{item.published_at}]" if item.published_at else ""
        source = f"({item.source})" if item.source else ""
        lines.append(f"- {item.title}{source}{timestamp}")
    return lines

def _format_optional(value: float | None, pattern: str) -> str:
    if value is None:
        return "N/A"
    return pattern.format(value)


def _asset_name(asset_type: str) -> str:
    return {"stock": "股票", "etf": "ETF", "futures": "期货"}.get(asset_type, asset_type)
