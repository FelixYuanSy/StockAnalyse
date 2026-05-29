from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .models import AnalysisResult


def build_chart_html(result: AnalysisResult) -> str:
    rows = result.market_data.get("daily_kline_tail", [])
    if not rows:
        return "<p>暂无可绘制的 K 线数据。</p>"

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])

    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.52, 0.16, 0.16, 0.16],
        subplot_titles=("价格与均线", "成交量", "MACD", "RSI"),
    )

    fig.add_trace(
        go.Candlestick(
            x=df["date"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="K线",
            increasing_line_color="#d93025",
            decreasing_line_color="#188038",
        ),
        row=1,
        col=1,
    )

    for name, color in (("ma5", "#fbbc04"), ("ma10", "#4285f4"), ("ma20", "#a142f4"), ("ma60", "#5f6368")):
        if name in df.columns:
            fig.add_trace(go.Scatter(x=df["date"], y=df[name], mode="lines", name=name.upper(), line=dict(color=color, width=1.4)), row=1, col=1)

    for level, label, color in (
        (result.support_levels[0], "第一支撑", "#188038"),
        (result.support_levels[1], "第二支撑", "#0b8043"),
        (result.resistance_levels[0], "第一压力", "#d93025"),
        (result.resistance_levels[1], "第二压力", "#a50e0e"),
    ):
        fig.add_hline(y=level, line_width=1, line_dash="dot", line_color=color, annotation_text=f"{label} {level:.2f}", row=1, col=1)

    volume_colors = ["#d93025" if close >= open_ else "#188038" for open_, close in zip(df["open"], df["close"])]
    fig.add_trace(go.Bar(x=df["date"], y=df["volume"], name="成交量", marker_color=volume_colors), row=2, col=1)

    if {"macd", "macd_signal", "macd_hist"}.issubset(df.columns):
        hist_colors = ["#d93025" if value >= 0 else "#188038" for value in df["macd_hist"]]
        fig.add_trace(go.Bar(x=df["date"], y=df["macd_hist"], name="MACD柱", marker_color=hist_colors), row=3, col=1)
        fig.add_trace(go.Scatter(x=df["date"], y=df["macd"], mode="lines", name="DIF", line=dict(color="#4285f4")), row=3, col=1)
        fig.add_trace(go.Scatter(x=df["date"], y=df["macd_signal"], mode="lines", name="DEA", line=dict(color="#fbbc04")), row=3, col=1)

    if "rsi14" in df.columns:
        fig.add_trace(go.Scatter(x=df["date"], y=df["rsi14"], mode="lines", name="RSI14", line=dict(color="#a142f4")), row=4, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#d93025", row=4, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#188038", row=4, col=1)

    fig.update_layout(
        height=980,
        template="plotly_white",
        margin=dict(l=48, r=32, t=72, b=36),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="量", row=2, col=1)
    fig.update_yaxes(title_text="MACD", row=3, col=1)
    fig.update_yaxes(title_text="RSI", row=4, col=1, range=[0, 100])

    return fig.to_html(full_html=False, include_plotlyjs="cdn")


def write_html(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def build_today_prediction_html(result: AnalysisResult) -> str:
    """Build a visual intraday scenario forecast from the current evidence pack.

    This is not a tick-level quant model. It gives a scenario path based on the
    current quote, recent daily volatility, local score, and support/resistance.
    """
    daily_rows = result.market_data.get("daily_kline_tail", [])
    if not daily_rows:
        return "<p>暂无可用于预测走势图的数据。</p>"

    daily = pd.DataFrame(daily_rows)
    for column in ("open", "high", "low", "close"):
        daily[column] = pd.to_numeric(daily[column], errors="coerce")
    daily = daily.dropna(subset=["close"])
    if daily.empty:
        return "<p>暂无可用于预测走势图的数据。</p>"

    current_price = float(result.quote.price)
    latest = daily.iloc[-1]
    volatility = _recent_volatility(daily)
    drift = _directional_drift(result, latest, volatility)

    actual_x, actual_y = _actual_intraday_points(result, current_price)
    start_time = actual_x[-1] if actual_x else datetime.now()
    start_price = actual_y[-1] if actual_y else current_price
    future_x = _future_times(start_time)

    baseline = _scenario_path(start_price, future_x, drift, wave=0.12)
    optimistic = _scenario_path(start_price, future_x, drift + volatility * 0.65, wave=0.18)
    pessimistic = _scenario_path(start_price, future_x, drift - volatility * 0.65, wave=-0.16)

    fig = go.Figure()
    if actual_x:
        fig.add_trace(
            go.Scatter(
                x=actual_x,
                y=actual_y,
                mode="lines+markers",
                name="已发生走势",
                line=dict(color="#2f6fed", width=2.4),
            )
        )

    fig.add_trace(
        go.Scatter(
            x=future_x,
            y=baseline,
            mode="lines",
            name="基准预测",
            line=dict(color="#111827", width=2.6),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=future_x,
            y=optimistic,
            mode="lines",
            name="乐观路径",
            line=dict(color="#d93025", width=1.8, dash="dot"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=future_x,
            y=pessimistic,
            mode="lines",
            name="悲观路径",
            line=dict(color="#188038", width=1.8, dash="dot"),
        )
    )

    fig.add_hline(
        y=result.support_levels[0],
        line_color="#188038",
        line_dash="dash",
        annotation_text=f"支撑 {result.support_levels[0]:.2f}",
    )
    fig.add_hline(
        y=result.resistance_levels[0],
        line_color="#d93025",
        line_dash="dash",
        annotation_text=f"压力 {result.resistance_levels[0]:.2f}",
    )
    fig.add_hline(
        y=current_price,
        line_color="#6b7280",
        line_dash="dot",
        annotation_text=f"当前 {current_price:.2f}",
    )

    fig.update_layout(
        height=520,
        template="plotly_white",
        title=f"{result.quote.name} ({result.quote.symbol}) 今日走势情景预测",
        margin=dict(l=48, r=32, t=64, b=36),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="x unified",
    )
    fig.update_xaxes(title_text="时间")
    fig.update_yaxes(title_text="价格")
    return fig.to_html(full_html=False, include_plotlyjs="cdn")


def should_show_today_prediction(question: str) -> bool:
    text = (question or "").lower()
    keywords = (
        "走势图",
        "画图",
        "图",
        "今天走势",
        "今日走势",
        "盘中",
        "预测今天",
        "预测今日",
        "trend chart",
        "intraday",
    )
    return any(keyword in text for keyword in keywords)


def _recent_volatility(daily: pd.DataFrame) -> float:
    returns = daily["close"].pct_change().dropna().tail(20)
    if returns.empty:
        return 0.008
    value = float(returns.std())
    return max(0.003, min(0.035, value if value == value else 0.008))


def _directional_drift(result: AnalysisResult, latest: pd.Series, volatility: float) -> float:
    score_bias = (float(result.score) - 50.0) / 50.0
    change_bias = max(-1.0, min(1.0, float(result.quote.change_pct) / 3.0))
    macd_bias = 0.0
    if "macd_hist" in latest and pd.notna(latest["macd_hist"]):
        macd_bias = 0.18 if float(latest["macd_hist"]) > 0 else -0.18
    return (score_bias * 0.65 + change_bias * 0.25 + macd_bias * 0.10) * volatility


def _actual_intraday_points(result: AnalysisResult, fallback_price: float) -> tuple[list[datetime], list[float]]:
    rows = result.market_data.get("intraday_kline_tail", [])
    if not rows:
        return [], []
    df = pd.DataFrame(rows)
    if "datetime" not in df.columns or "close" not in df.columns:
        return [], []
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["datetime", "close"]).tail(48)
    if df.empty:
        return [], []
    return list(df["datetime"].dt.to_pydatetime()), [float(value) for value in df["close"]]


def _future_times(start_time: datetime) -> list[datetime]:
    close_time = datetime.combine(start_time.date(), time(15, 0))
    if start_time >= close_time:
        start_time = datetime.combine(start_time.date(), time(9, 30))
        close_time = datetime.combine(start_time.date(), time(15, 0))

    points: list[datetime] = []
    cursor = start_time
    step = timedelta(minutes=30)
    while cursor <= close_time:
        if time(11, 30) < cursor.time() < time(13, 0):
            cursor = datetime.combine(cursor.date(), time(13, 0))
        points.append(cursor)
        cursor += step
    if points[-1] < close_time:
        points.append(close_time)
    return points[:14]


def _scenario_path(start_price: float, times: list[datetime], drift: float, wave: float) -> list[float]:
    if not times:
        return []
    values: list[float] = []
    total = max(1, len(times) - 1)
    for index, _ in enumerate(times):
        progress = index / total
        curve = progress * drift
        intraday_wave = wave * progress * (1 - progress) * abs(drift if drift else 0.006)
        values.append(round(start_price * (1 + curve + intraday_wave), 4))
    return values
