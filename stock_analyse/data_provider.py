from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import date, timedelta
import io
import os
from typing import Any

import pandas as pd

from .models import AssetType, NewsItem, StockQuote


class DataProviderError(RuntimeError):
    """Raised when market data cannot be fetched or normalized."""


class AkshareDataProvider:
    FUTURES_NEWS_KEYWORDS = {
        "LC": ("碳酸锂", "锂", "锂矿", "盐湖", "锂电池", "新能源车", "电池级碳酸锂"),
        "SI": ("工业硅", "多晶硅", "光伏", "硅料"),
        "RB": ("螺纹钢", "钢材", "地产", "基建", "铁矿"),
        "I": ("铁矿", "钢厂", "港口库存", "澳洲矿"),
        "CU": ("铜", "电解铜", "库存", "有色"),
        "AL": ("铝", "电解铝", "氧化铝", "有色"),
        "AU": ("黄金", "贵金属", "美元", "美债"),
        "AG": ("白银", "贵金属", "美元", "美债"),
        "SC": ("原油", "OPEC", "石油", "库存"),
    }

    FUTURES_NEWS_CATEGORY = {
        "LC": "小金属",
        "SI": "小金属",
        "CU": "铜",
        "AL": "铝",
        "AU": "贵金属",
        "AG": "贵金属",
    }

    def __init__(self, use_system_proxy: bool = False) -> None:
        try:
            import akshare as ak
        except ImportError as exc:
            raise DataProviderError(
                "缺少 AKShare 依赖。请先运行: pip install -r requirements.txt"
            ) from exc

        self._ak = ak
        self._use_system_proxy = use_system_proxy

    def resolve_asset_type(self, symbol: str, asset_type: str = "auto") -> AssetType:
        if asset_type in {"stock", "etf", "futures"}:
            return asset_type  # type: ignore[return-value]

        code = symbol.strip().lower()
        if any(char.isalpha() for char in code):
            return "futures"
        if self._looks_like_etf(code):
            return "etf"
        return "stock"

    def get_realtime_quote(self, symbol: str, asset_type: AssetType = "stock") -> StockQuote:
        code = self._normalize_symbol(symbol, asset_type)

        try:
            with self._network_context():
                if asset_type == "etf":
                    spot = self._ak.fund_etf_spot_em()
                elif asset_type == "futures":
                    return self._get_futures_realtime_quote(code)
                else:
                    spot = self._ak.stock_zh_a_spot_em()
        except Exception as exc:
            raise DataProviderError(f"无法获取 {self._asset_name(asset_type)} 实时行情: {exc}") from exc

        row = spot.loc[spot["代码"].astype(str) == code]
        if row.empty:
            raise DataProviderError(f"实时行情中找不到 {self._asset_name(asset_type)} 代码 {code}")

        item = row.iloc[0]
        return StockQuote(
            symbol=code,
            name=str(item.get("名称", code)),
            asset_type=asset_type,
            price=self._to_float(item.get("最新价")),
            change_pct=self._to_float(item.get("涨跌幅")),
            volume=self._optional_float(item.get("成交量")),
            turnover_rate=self._optional_float(item.get("换手率")),
        )

    def get_daily_history(self, symbol: str, days: int = 120, asset_type: AssetType = "stock") -> pd.DataFrame:
        code = self._normalize_symbol(symbol, asset_type)
        end = date.today()
        start = end - timedelta(days=max(days * 2, 180))

        errors: list[str] = []
        try:
            with self._network_context():
                df = self._history_primary(code, start, end, asset_type)
        except Exception as exc:
            errors.append(f"主日线接口失败: {exc}")
            try:
                with self._network_context():
                    df = self._history_fallback(code, start, end, asset_type)
            except Exception as fallback_exc:
                errors.append(f"备用日线接口失败: {fallback_exc}")
                raise DataProviderError(f"无法获取 {code} 历史 K 线: {'; '.join(errors)}") from fallback_exc

        if df.empty:
            raise DataProviderError(f"历史 K 线为空: {code}")

        normalized = df.rename(
            columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
                "振幅": "amplitude",
                "涨跌幅": "change_pct",
                "涨跌额": "change",
                "换手率": "turnover_rate",
                "turnover": "turnover_rate",
                "开盘价": "open",
                "收盘价": "close",
                "最高价": "high",
                "最低价": "low",
                "动态结算价": "settle",
            }
        )

        required = ["date", "open", "close", "high", "low", "volume"]
        missing = [column for column in required if column not in normalized.columns]
        if missing:
            raise DataProviderError(f"历史数据缺少字段: {', '.join(missing)}")

        normalized = normalized.tail(days).copy()
        normalized["date"] = pd.to_datetime(normalized["date"])
        for column in ["open", "close", "high", "low", "volume"]:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

        if "change_pct" not in normalized.columns:
            normalized["change_pct"] = normalized["close"].pct_change() * 100
        if "turnover_rate" in normalized.columns and normalized["turnover_rate"].max() <= 1:
            normalized["turnover_rate"] = normalized["turnover_rate"] * 100

        normalized = normalized.dropna(subset=["open", "close", "high", "low", "volume"])
        if len(normalized) < 60:
            raise DataProviderError(f"有效历史数据不足 60 条，当前只有 {len(normalized)} 条")

        return normalized.reset_index(drop=True)

    def get_intraday_history(
        self,
        symbol: str,
        period: str = "5",
        asset_type: AssetType = "stock",
    ) -> pd.DataFrame:
        code = self._normalize_symbol(symbol, asset_type)
        errors: list[str] = []

        try:
            with self._network_context():
                if asset_type == "futures":
                    df = self._call_with_retries(
                        lambda: self._ak.futures_zh_minute_sina(symbol=code.upper(), period=period)
                    )
                elif asset_type == "etf":
                    df = self._call_with_retries(
                        lambda: self._ak.fund_etf_hist_min_em(symbol=code, period=period, adjust="")
                    )
                else:
                    df = self._call_with_retries(
                        lambda: self._ak.stock_zh_a_minute(
                            symbol=self._market_prefixed_symbol(code),
                            period=period,
                            adjust="",
                        )
                    )
        except Exception as exc:
            errors.append(f"Sina 分钟线接口失败: {exc}")
            try:
                with self._network_context():
                    if asset_type == "futures":
                        raise DataProviderError("期货暂无备用分钟线接口")
                    if asset_type == "etf":
                        df = self._call_with_retries(
                            lambda: self._ak.fund_etf_hist_min_em(symbol=code, period=period, adjust="")
                        )
                    else:
                        df = self._call_with_retries(
                            lambda: self._ak.stock_zh_a_hist_min_em(symbol=code, period=period, adjust="")
                        )
            except Exception as fallback_exc:
                errors.append(f"东方财富分钟线接口失败: {fallback_exc}")
                raise DataProviderError(f"无法获取 {code} 分钟线: {'; '.join(errors)}") from fallback_exc

        normalized = self._normalize_intraday_frame(df, code)

        required = ["datetime", "open", "close", "high", "low", "volume"]
        missing = [column for column in required if column not in normalized.columns]
        if missing and asset_type in {"stock", "etf"}:
            try:
                with self._network_context():
                    df = self._call_with_retries(
                        lambda: self._ak.stock_zh_a_minute(
                            symbol=self._market_prefixed_symbol(code),
                            period=period,
                            adjust="",
                        )
                    )
                normalized = self._normalize_intraday_frame(df, code)
                missing = [column for column in required if column not in normalized.columns]
            except Exception as fallback_exc:
                errors.append(f"Sina通用分钟线接口失败: {fallback_exc}")
        if missing:
            raise DataProviderError(f"分钟线缺少字段: {', '.join(missing)}")

        normalized["datetime"] = pd.to_datetime(normalized["datetime"])
        for column in ["open", "close", "high", "low", "volume"]:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

        normalized = normalized.dropna(subset=required).tail(96)
        if len(normalized) < 12:
            raise DataProviderError(f"有效分钟线不足 12 条，当前只有 {len(normalized)} 条")

        return normalized.reset_index(drop=True)

    def _normalize_intraday_frame(self, df: pd.DataFrame, code: str) -> pd.DataFrame:
        if df.empty:
            raise DataProviderError(f"分钟线为空: {code}")

        return df.rename(
            columns={
                "day": "datetime",
                "date": "datetime",
                "日期": "datetime",
                "时间": "datetime",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
            }
        ).copy()

    @staticmethod
    def _call_with_retries(func, attempts: int = 3):
        last_exc: Exception | None = None
        for _ in range(attempts):
            try:
                return func()
            except Exception as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        raise DataProviderError("接口重试失败")

    def get_global_news(self, limit: int = 8) -> tuple[NewsItem, ...]:
        try:
            with self._network_context():
                df = self._ak.stock_info_global_em()
        except Exception as exc:
            raise DataProviderError(f"无法获取全球财经新闻: {exc}") from exc

        return tuple(self._news_from_rows(df.head(limit), source_default="东方财富"))

    def get_stock_news(
        self,
        symbol: str,
        limit: int = 5,
        asset_type: AssetType = "stock",
    ) -> tuple[NewsItem, ...]:
        code = self._normalize_symbol(symbol, asset_type)

        if asset_type == "futures":
            return self._get_futures_news(code, limit=limit)
        if asset_type == "etf":
            return self._get_market_news(limit=limit, keywords=(code, "ETF", "指数基金"))

        try:
            with self._network_context():
                df = self._ak.stock_news_em(symbol=code)
        except Exception as exc:
            try:
                keywords = self._stock_news_keywords(code)
                fallback = self._get_filtered_market_news(limit=limit, keywords=keywords)
                if fallback:
                    return fallback
            except Exception:
                pass
            raise DataProviderError(f"无法获取 {code} 个股新闻: {exc}") from exc

        return tuple(self._news_from_rows(df.head(limit), source_default="东方财富"))

    def get_fundamental_data(self, symbol: str, asset_type: AssetType = "stock") -> dict:
        code = self._normalize_symbol(symbol, asset_type)
        if asset_type == "stock":
            return self._get_stock_fundamental_data(code)
        if asset_type == "futures":
            return self._get_futures_fundamental_data(code)
        return self._get_etf_fundamental_data(code)

    def _get_stock_fundamental_data(self, code: str) -> dict:
        data: dict[str, Any] = {
            "framework": "stock_100_score",
            "notes": [
                "股票报告应优先按盈利能力、成长能力、现金流质量、估值水平、财务安全、行业竞争、技术面情绪七项评分。",
            ],
        }

        errors: list[str] = []
        fetches = (
            ("profile", lambda: self._ak.stock_individual_info_em(symbol=code)),
            ("financial_abstract", lambda: self._ak.stock_financial_abstract(symbol=code)),
            ("financial_indicators", lambda: self._ak.stock_financial_analysis_indicator(symbol=code, start_year="2020")),
            ("valuation_pe_ttm", lambda: self._ak.stock_zh_valuation_baidu(symbol=code, indicator="市盈率(TTM)", period="近一年")),
            ("valuation_pb", lambda: self._ak.stock_zh_valuation_baidu(symbol=code, indicator="市净率", period="近一年")),
            ("peer_valuation", lambda: self._ak.stock_zh_valuation_comparison_em(symbol=self._market_prefixed_symbol(code).upper())),
        )

        for key, fetch in fetches:
            try:
                with self._network_context():
                    df = fetch()
                data[key] = self._frame_tail_records(df, rows=8)
            except Exception as exc:
                errors.append(f"{key}: {exc}")

        if errors:
            data["missing_or_failed"] = errors
        return data

    def _get_futures_fundamental_data(self, code: str) -> dict:
        root = self._futures_root(code)
        data: dict[str, Any] = {
            "framework": "futures_driver_score",
            "contract_root": root,
            "industry_keywords": self.FUTURES_NEWS_KEYWORDS.get(root, (root,)),
            "notes": [
                "期货报告应重点看现货价格、基差、持仓量、成交量、库存、仓单、产业新闻、期限结构和隔夜风险。",
            ],
        }

        errors: list[str] = []
        try:
            data["spot_basis"] = self._get_recent_futures_spot_basis(root)
        except Exception as exc:
            errors.append(f"spot_basis: {exc}")

        try:
            data["settlement"] = self._get_recent_futures_settlement(code)
        except Exception as exc:
            errors.append(f"settlement: {exc}")

        for key, rank_type in (
            ("volume_rank", "成交量"),
            ("long_position_rank", "多单持仓"),
            ("short_position_rank", "空单持仓"),
        ):
            try:
                data[key] = self._get_recent_futures_hold_rank(code, rank_type)
            except Exception as exc:
                errors.append(f"{key}: {exc}")

        if errors:
            data["missing_or_failed"] = errors
        return data

    def _get_recent_futures_spot_basis(self, root: str, lookback_days: int = 10) -> list[dict]:
        errors: list[str] = []
        for day in self._recent_date_strings(lookback_days):
            try:
                with self._network_context():
                    df = self._ak.futures_spot_price(date=day, vars_list=[root])
                if not df.empty:
                    records = self._frame_tail_records(df, rows=5)
                    for record in records:
                        record["data_date"] = day
                    return records
                errors.append(f"{day}: empty")
            except Exception as exc:
                errors.append(f"{day}: {exc}")
        raise DataProviderError(f"最近 {lookback_days} 天无 {root} 现货/基差数据: {'; '.join(errors[-3:])}")

    def _get_recent_futures_settlement(self, code: str, lookback_days: int = 10) -> list[dict]:
        errors: list[str] = []
        normalized_code = code.lower()
        for day in self._recent_date_strings(lookback_days):
            try:
                with self._network_context():
                    df = self._ak.futures_settle(date=day, market="GFEX")
                if df.empty or "symbol" not in df.columns:
                    errors.append(f"{day}: empty")
                    continue
                filtered = df.loc[df["symbol"].astype(str).str.lower() == normalized_code]
                if not filtered.empty:
                    records = self._frame_tail_records(filtered, rows=3)
                    for record in records:
                        record["data_date"] = day
                    return records
                errors.append(f"{day}: {code} not found")
            except Exception as exc:
                errors.append(f"{day}: {exc}")
        raise DataProviderError(f"最近 {lookback_days} 天无 {code} 结算参数: {'; '.join(errors[-3:])}")

    def _get_recent_futures_hold_rank(self, code: str, rank_type: str, lookback_days: int = 10) -> list[dict]:
        errors: list[str] = []
        for day in self._recent_date_strings(lookback_days):
            try:
                with self._network_context():
                    df = self._ak.futures_hold_pos_sina(symbol=rank_type, contract=code, date=day)
                if not df.empty:
                    records = self._frame_head_records(df, rows=10)
                    for record in records:
                        record["data_date"] = day
                    return records
                errors.append(f"{day}: empty")
            except Exception as exc:
                errors.append(f"{day}: {exc}")
        raise DataProviderError(f"最近 {lookback_days} 天无 {code} {rank_type}排名: {'; '.join(errors[-3:])}")

    def _get_etf_fundamental_data(self, code: str) -> dict:
        data: dict[str, Any] = {
            "framework": "etf_tracking_score",
            "notes": [
                "ETF报告应重点看跟踪指数方向、成分行业、成交额、流动性、折溢价/IOPV、持仓集中度和市场风格。",
            ],
            "missing_or_failed": [],
        }

        try:
            with self._network_context():
                spot = self._ak.fund_etf_spot_em()
            row = spot.loc[spot["代码"].astype(str) == code]
            if row.empty:
                data["missing_or_failed"].append(f"ETF实时扩展行情中未找到 {code}")
            else:
                data["realtime_detail"] = self._frame_records(row.head(1))[0]
        except Exception as exc:
            data["missing_or_failed"].append(f"ETF实时扩展行情获取失败: {exc}")

        try:
            with self._network_context():
                nav = self._ak.fund_etf_fund_info_em(fund=code)
            data["nav_history_tail"] = self._frame_tail_records(nav, rows=8)
        except Exception as exc:
            data["missing_or_failed"].append(f"ETF净值历史获取失败: {exc}")

        try:
            data["top_holdings"] = self._get_recent_fund_portfolio_hold(code)
        except DataProviderError as exc:
            data["missing_or_failed"].append(str(exc))

        try:
            data["industry_allocation"] = self._get_recent_fund_industry_allocation(code)
        except DataProviderError as exc:
            data["missing_or_failed"].append(str(exc))

        if not data["missing_or_failed"]:
            data["missing_or_failed"] = []
        return data

    def _get_recent_fund_portfolio_hold(self, code: str, lookback_years: int = 3) -> dict:
        errors: list[str] = []
        for year in range(date.today().year, date.today().year - lookback_years, -1):
            try:
                with self._network_context():
                    df = self._ak.fund_portfolio_hold_em(symbol=code, date=str(year))
                if df.empty:
                    errors.append(f"{year}: empty")
                    continue
                latest_period = str(df.iloc[0].get("季度", year)) if "季度" in df.columns else str(year)
                if "季度" in df.columns:
                    df = df.loc[df["季度"].astype(str) == latest_period]
                return {
                    "data_year": year,
                    "latest_period": latest_period,
                    "records": self._frame_head_records(df, rows=15),
                    "source": "天天基金-基金持仓",
                }
            except Exception as exc:
                errors.append(f"{year}: {exc}")
        raise DataProviderError(f"最近 {lookback_years} 年无 {code} ETF持仓数据: {'; '.join(errors[-3:])}")

    def _get_recent_fund_industry_allocation(self, code: str, lookback_years: int = 3) -> dict:
        errors: list[str] = []
        for year in range(date.today().year, date.today().year - lookback_years, -1):
            try:
                with self._network_context():
                    df = self._ak.fund_portfolio_industry_allocation_em(symbol=code, date=str(year))
                if df.empty:
                    errors.append(f"{year}: empty")
                    continue
                latest_date = str(df.iloc[0].get("截止时间", year)) if "截止时间" in df.columns else str(year)
                if "截止时间" in df.columns:
                    df = df.loc[df["截止时间"].astype(str) == latest_date]
                return {
                    "data_year": year,
                    "latest_date": latest_date,
                    "records": self._frame_head_records(df, rows=12),
                    "source": "天天基金-行业配置",
                }
            except Exception as exc:
                errors.append(f"{year}: {exc}")
        raise DataProviderError(f"最近 {lookback_years} 年无 {code} ETF行业配置数据: {'; '.join(errors[-3:])}")

    def _get_futures_news(self, code: str, limit: int = 5) -> tuple[NewsItem, ...]:
        root = self._futures_root(code)
        category = self.FUTURES_NEWS_CATEGORY.get(root, "全部")
        keywords = self.FUTURES_NEWS_KEYWORDS.get(root, (root,))
        items: list[NewsItem] = []
        errors: list[str] = []

        for query in dict.fromkeys((category, "要闻", "财经", "全部")):
            try:
                with self._network_context():
                    df = self._ak.futures_news_shmet(symbol=query)
                items.extend(self._news_from_rows(df.head(80), source_default="上海金属网"))
            except Exception as exc:
                errors.append(f"{query}: {exc}")

        filtered = self._filter_news(items, keywords)
        if filtered:
            return tuple(self._sort_news(filtered)[:limit])
        if items:
            return tuple(self._sort_news(items)[:limit])
        raise DataProviderError(f"无法获取 {code} 期货产业新闻: {'; '.join(errors)}")

    def _get_market_news(self, limit: int, keywords: tuple[str, ...]) -> tuple[NewsItem, ...]:
        try:
            with self._network_context():
                df = self._ak.stock_info_global_em()
        except Exception as exc:
            raise DataProviderError(f"无法获取市场新闻: {exc}") from exc

        items = self._news_from_rows(df.head(60), source_default="东方财富")
        filtered = self._filter_news(items, keywords)
        return tuple(self._sort_news(filtered or items)[:limit])

    def _get_filtered_market_news(self, limit: int, keywords: tuple[str, ...]) -> tuple[NewsItem, ...]:
        try:
            with self._network_context():
                df = self._ak.stock_info_global_em()
        except Exception as exc:
            raise DataProviderError(f"无法获取市场新闻: {exc}") from exc

        items = self._news_from_rows(df.head(100), source_default="东方财富")
        return tuple(self._sort_news(self._filter_news(items, keywords))[:limit])

    def _stock_news_keywords(self, code: str) -> tuple[str, ...]:
        keywords = [code]
        try:
            with self._network_context():
                info = self._ak.stock_individual_info_em(symbol=code)
            for record in self._frame_tail_records(info, rows=20):
                for value in record.values():
                    text = str(value).strip()
                    if 2 <= len(text) <= 12 and not text.isdigit():
                        keywords.append(text)
        except Exception:
            pass
        return tuple(dict.fromkeys(keywords))

    def _history_primary(self, code: str, start: date, end: date, asset_type: AssetType) -> pd.DataFrame:
        if asset_type == "etf":
            return self._ak.fund_etf_hist_em(
                symbol=code,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="qfq",
            )
        if asset_type == "futures":
            return self._ak.futures_zh_daily_sina(symbol=code.upper())
        return self._ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq",
        )

    def _history_fallback(self, code: str, start: date, end: date, asset_type: AssetType) -> pd.DataFrame:
        if asset_type == "etf":
            return self._ak.fund_etf_hist_sina(symbol=self._market_prefixed_symbol(code))
        if asset_type == "futures":
            return self._ak.futures_main_sina(
                symbol=code.upper(),
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        return self._ak.stock_zh_a_daily(
            symbol=self._market_prefixed_symbol(code),
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq",
        )

    def quote_from_history(
        self,
        symbol: str,
        history: pd.DataFrame,
        asset_type: AssetType = "stock",
    ) -> StockQuote:
        code = self._normalize_symbol(symbol, asset_type)
        latest = history.iloc[-1]
        return StockQuote(
            symbol=code,
            name=code,
            asset_type=asset_type,
            price=self._to_float(latest["close"]),
            change_pct=self._optional_float(latest.get("change_pct")) or 0.0,
            volume=self._optional_float(latest.get("volume")),
            turnover_rate=self._optional_float(latest.get("turnover_rate")),
        )

    def _get_futures_realtime_quote(self, code: str) -> StockQuote:
        df = self._ak.futures_zh_spot(symbol=code.upper(), market="CF", adjust="0")
        if df.empty:
            raise DataProviderError(f"实时行情中找不到期货代码 {code}")
        item = df.iloc[0]
        price = self._to_float(item.get("current_price"))
        settle = self._optional_float(item.get("last_settle_price"))
        change_pct = ((price / settle - 1) * 100) if settle else 0.0
        return StockQuote(
            symbol=code.upper(),
            name=str(item.get("symbol") or code.upper()),
            asset_type="futures",
            price=price,
            change_pct=change_pct,
            volume=self._optional_float(item.get("volume")),
            turnover_rate=None,
        )

    @classmethod
    def _futures_root(cls, code: str) -> str:
        return "".join(char for char in code.upper() if char.isalpha())

    @classmethod
    def _filter_news(cls, items: list[NewsItem], keywords: tuple[str, ...]) -> list[NewsItem]:
        filtered: list[NewsItem] = []
        for item in items:
            text = f"{item.title} {item.summary}"
            if any(keyword and keyword in text for keyword in keywords):
                filtered.append(item)
        return filtered

    @staticmethod
    def _sort_news(items: list[NewsItem]) -> list[NewsItem]:
        def key(item: NewsItem):
            parsed = pd.to_datetime(item.published_at, errors="coerce", utc=True)
            if pd.isna(parsed):
                return pd.Timestamp.min
            return parsed.tz_convert(None)

        return sorted(items, key=key, reverse=True)

    @staticmethod
    def _recent_date_strings(lookback_days: int) -> list[str]:
        return [
            (date.today() - timedelta(days=offset)).strftime("%Y%m%d")
            for offset in range(lookback_days)
        ]

    @staticmethod
    def _first_value(row: pd.Series, names: tuple[str, ...]) -> Any:
        for name in names:
            if name in row:
                value = row.get(name)
                if pd.notna(value):
                    return value
        return ""

    @classmethod
    def _frame_tail_records(cls, df: pd.DataFrame, rows: int = 8) -> list[dict]:
        if df is None or df.empty:
            return []
        tail = df.tail(rows).copy()
        return cls._frame_records(tail)

    @classmethod
    def _frame_head_records(cls, df: pd.DataFrame, rows: int = 8) -> list[dict]:
        if df is None or df.empty:
            return []
        head = df.head(rows).copy()
        return cls._frame_records(head)

    @staticmethod
    def _frame_records(df: pd.DataFrame) -> list[dict]:
        records: list[dict] = []
        for raw in df.to_dict(orient="records"):
            record = {}
            for key, value in raw.items():
                if value is None:
                    record[str(key)] = None
                elif isinstance(value, (list, tuple, dict)):
                    record[str(key)] = value
                elif pd.isna(value):
                    record[str(key)] = None
                elif hasattr(value, "isoformat"):
                    record[str(key)] = value.isoformat()
                else:
                    record[str(key)] = value
            records.append(record)
        return records

    @staticmethod
    def _news_from_rows(df: pd.DataFrame, source_default: str) -> list[NewsItem]:
        items: list[NewsItem] = []
        for _, row in df.iterrows():
            title = str(
                AkshareDataProvider._first_value(row, ("标题", "新闻标题", "title", "content", "内容", "快讯内容"))
            ).strip()
            if not title:
                continue

            items.append(
                NewsItem(
                    title=title,
                    source=str(
                        AkshareDataProvider._first_value(row, ("文章来源", "信息来源", "来源", "source")) or source_default
                    ),
                    published_at=str(
                        AkshareDataProvider._first_value(row, ("发布时间", "发布日期", "时间", "date", "datetime"))
                    ),
                    summary=str(
                        AkshareDataProvider._first_value(row, ("摘要", "新闻内容", "内容", "summary", "快讯内容"))
                    ),
                    url=str(AkshareDataProvider._first_value(row, ("链接", "新闻链接", "url"))),
                )
            )
        return items

    @staticmethod
    def _normalize_symbol(symbol: str, asset_type: AssetType) -> str:
        code = symbol.strip().lower()
        if "." in code:
            code = code.split(".", 1)[0]

        if asset_type in {"stock", "etf"}:
            if not code.isdigit() or len(code) != 6:
                raise DataProviderError(f"{AkshareDataProvider._asset_name(asset_type)}代码应为 6 位数字，例如 600519、510300、159915")
            return code

        if not code.replace("_", "").isalnum():
            raise DataProviderError("期货代码应为字母和数字组合，例如 RB0、AU0、IF0")
        return code.upper()

    @staticmethod
    def _looks_like_etf(code: str) -> bool:
        return code.isdigit() and len(code) == 6 and code.startswith(
            ("159", "510", "511", "512", "513", "515", "516", "517", "518", "560", "561", "562", "563", "588", "589")
        )

    @staticmethod
    def _asset_name(asset_type: AssetType) -> str:
        return {"stock": "股票", "etf": "ETF", "futures": "期货"}[asset_type]

    @staticmethod
    def _market_prefixed_symbol(code: str) -> str:
        if code.startswith(("5", "6", "9")):
            return f"sh{code}"
        if code.startswith(("0", "1", "2", "3")):
            return f"sz{code}"
        if code.startswith(("4", "8")):
            return f"bj{code}"
        return code

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise DataProviderError(f"行情字段无法转换为数字: {value}") from exc

    @classmethod
    def _optional_float(cls, value: Any) -> float | None:
        try:
            return cls._to_float(value)
        except DataProviderError:
            return None

    @contextmanager
    def _network_context(self):
        if self._use_system_proxy:
            with self._quiet_akshare_output():
                yield
            return

        original = {key: os.environ.get(key) for key in self._proxy_keys()}
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            os.environ.pop(key, None)
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        try:
            with self._quiet_akshare_output():
                yield
        finally:
            for key in self._proxy_keys():
                value = original.get(key)
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    @staticmethod
    @contextmanager
    def _quiet_akshare_output():
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            yield

    @staticmethod
    def _proxy_keys() -> tuple[str, ...]:
        return (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "NO_PROXY",
            "no_proxy",
        )
