from __future__ import annotations

import pandas as pd


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()

    for window in (5, 10, 20, 60):
        data[f"ma{window}"] = data["close"].rolling(window=window).mean()

    data["volume_ma5"] = data["volume"].rolling(window=5).mean()
    data["volume_ma20"] = data["volume"].rolling(window=20).mean()
    data["rsi14"] = rsi(data["close"], period=14)

    macd_line, signal_line, histogram = macd(data["close"])
    data["macd"] = macd_line
    data["macd_signal"] = signal_line
    data["macd_hist"] = histogram

    middle = data["close"].rolling(window=20).mean()
    std = data["close"].rolling(window=20).std()
    data["boll_mid"] = middle
    data["boll_upper"] = middle + 2 * std
    data["boll_lower"] = middle - 2 * std

    return data


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    values = 100 - (100 / (1 + rs))
    values = values.mask(avg_loss == 0, 100)
    values = values.mask((avg_gain == 0) & (avg_loss == 0), 50)
    return values


def macd(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = (macd_line - signal_line) * 2
    return macd_line, signal_line, histogram
