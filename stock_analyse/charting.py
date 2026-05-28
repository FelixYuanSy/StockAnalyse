from __future__ import annotations

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
