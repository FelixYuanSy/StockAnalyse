from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
import os
import re
from typing import Iterable
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

from .models import AssetType, NewsItem


class WebNewsSearchError(RuntimeError):
    """Raised when public web news search cannot complete."""


class WebNewsSearcher:
    """Search public news pages without paid data API keys.

    It tries several no-key public endpoints because any single search page may
    be blocked, redirected, or temporarily return HTML instead of feed data.
    """

    FUTURES_KEYWORDS = {
        "LC": ("碳酸锂", "电池级碳酸锂", "锂矿", "盐湖提锂", "锂电池", "新能源车", "广期所 碳酸锂"),
        "SI": ("工业硅", "多晶硅", "硅料", "光伏", "广期所 工业硅"),
        "RB": ("螺纹钢", "钢材", "地产", "基建", "铁矿石"),
        "I": ("铁矿石", "港口库存", "钢厂", "澳洲铁矿"),
        "CU": ("铜", "电解铜", "铜库存", "有色金属"),
        "AL": ("铝", "电解铝", "氧化铝", "有色金属"),
        "AU": ("黄金", "贵金属", "美元", "美债收益率"),
        "AG": ("白银", "贵金属", "美元", "美债收益率"),
        "SC": ("原油", "OPEC", "石油库存", "地缘风险"),
    }

    SOURCE_HINTS = (
        "东方财富",
        "财联社",
        "证券时报",
        "上海有色",
        "SMM",
        "Mysteel",
        "生意社",
        "广期所",
        "交易所",
    )

    def __init__(self, timeout: float = 6.0) -> None:
        try:
            import requests
        except ImportError as exc:
            raise WebNewsSearchError("缺少 requests 依赖。请运行: pip install -r requirements.txt") from exc

        self._requests = requests
        self._timeout = timeout

    def search(
        self,
        symbol: str,
        name: str,
        asset_type: AssetType,
        limit: int = 8,
        max_age_days: int = 30,
    ) -> tuple[NewsItem, ...]:
        keywords = self._keywords(symbol, name, asset_type)
        queries = self._queries(symbol, name, asset_type, keywords)
        items: list[NewsItem] = []
        errors: list[str] = []

        tasks = []
        for query in queries:
            tasks.extend(
                (
                    ("google", query, self._google_news_rss),
                    ("bing", query, self._bing_news_rss),
                    ("gdelt", query, self._gdelt_news),
                )
            )

        max_workers = min(8, max(2, len(tasks)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(fetch, query): (source, query)
                for source, query, fetch in tasks
            }
            for future in as_completed(future_map):
                source, query = future_map[future]
                try:
                    items.extend(future.result())
                except Exception as exc:
                    errors.append(f"{source}:{query}: {exc}")

        if not items and errors:
            raise WebNewsSearchError("; ".join(errors[:3]))

        filtered = self._filter_and_rank(items, keywords, max_age_days=max_age_days)
        return tuple(filtered[:limit])

    def _bing_news_rss(self, query: str) -> list[NewsItem]:
        url = (
            "https://www.bing.com/news/search"
            f"?q={quote_plus(query)}&format=rss&setlang=zh-CN&cc=CN"
        )
        return self._rss_items(url)

    def _google_news_rss(self, query: str) -> list[NewsItem]:
        url = (
            "https://news.google.com/rss/search"
            f"?q={quote_plus(query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
        )
        return self._rss_items(url)

    def _rss_items(self, url: str) -> list[NewsItem]:
        response = self._requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
                )
            },
            proxies=self._proxies(),
            timeout=self._timeout,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        head = response.content[:100].lstrip().lower()
        if b"<rss" not in head and b"<?xml" not in head and "xml" not in content_type:
            raise WebNewsSearchError("search endpoint returned non-RSS content")

        root = ET.fromstring(response.content)
        parsed: list[NewsItem] = []
        for item in root.findall("./channel/item"):
            title = self._text(item, "title")
            if not title:
                continue
            parsed.append(
                NewsItem(
                    title=title,
                    source=self._source(item),
                    published_at=self._text(item, "pubDate"),
                    summary=self._clean_html(self._text(item, "description")),
                    url=self._text(item, "link"),
                )
            )
        return parsed

    def _gdelt_news(self, query: str) -> list[NewsItem]:
        url = (
            "https://api.gdeltproject.org/api/v2/doc/doc"
            f"?query={quote_plus(query)}&mode=ArtList&format=json&maxrecords=20&sort=HybridRel"
        )
        response = self._requests.get(
            url,
            headers={"User-Agent": "StockAnalyse/1.0"},
            proxies=self._proxies(),
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()

        items: list[NewsItem] = []
        for article in payload.get("articles", []):
            title = str(article.get("title") or "").strip()
            if not title:
                continue
            items.append(
                NewsItem(
                    title=title,
                    source=str(article.get("sourceCommonName") or article.get("domain") or "GDELT"),
                    published_at=str(article.get("seendate") or ""),
                    summary=str(article.get("socialimage") or ""),
                    url=str(article.get("url") or ""),
                )
            )
        return items

    def _proxies(self) -> dict[str, str] | None:
        explicit = os.getenv("NEWS_SEARCH_PROXY") or os.getenv("AI_PROXY")
        if explicit:
            return {"http": explicit, "https": explicit}

        use_system_proxy = os.getenv("NEWS_SEARCH_USE_SYSTEM_PROXY", "false").strip().lower()
        if use_system_proxy in {"0", "false", "no", "off"}:
            return {"http": "", "https": ""}
        return None

    @classmethod
    def _keywords(cls, symbol: str, name: str, asset_type: AssetType) -> tuple[str, ...]:
        code = symbol.upper()
        keywords = [code]
        if name and name.upper() != code:
            keywords.append(name)

        if asset_type == "futures":
            root = "".join(char for char in code if char.isalpha())
            keywords.extend(cls.FUTURES_KEYWORDS.get(root, (root, f"{root} 期货")))
        elif asset_type == "etf":
            keywords.extend(("ETF", "指数基金", "基金净值", "IOPV", "折溢价"))
        else:
            keywords.extend(("股票", "业绩", "财报", "公告", "机构评级"))

        return tuple(dict.fromkeys(item for item in keywords if item))

    @classmethod
    def _queries(
        cls,
        symbol: str,
        name: str,
        asset_type: AssetType,
        keywords: tuple[str, ...],
    ) -> tuple[str, ...]:
        code = symbol.upper()
        if asset_type == "futures":
            root_terms = " ".join(keywords[1:4])
            return tuple(
                dict.fromkeys(
                    (
                        f"{code} {root_terms}",
                        f"{root_terms} 期货 最新",
                        f"{root_terms} 现货价格 基差",
                        f"{root_terms} 库存 仓单 供需",
                        f"SMM {root_terms}",
                        f"生意社 {root_terms}",
                    )
                )
            )
        if asset_type == "etf":
            return tuple(dict.fromkeys((f"{code} {name} ETF", f"{name} 指数 ETF", f"{code} 折溢价 IOPV")))
        return tuple(dict.fromkeys((f"{code} {name}", f"{name} 财报 业绩", f"{name} 公告 机构评级")))

    @classmethod
    def _filter_and_rank(
        cls,
        items: Iterable[NewsItem],
        keywords: tuple[str, ...],
        max_age_days: int,
    ) -> list[NewsItem]:
        seen: set[str] = set()
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=max_age_days)
        ranked: list[tuple[int, datetime, NewsItem]] = []

        for item in items:
            title_key = cls._normalize_title(item.title)
            url_key = item.url.strip().lower()
            identity = url_key or title_key
            if not identity or identity in seen or title_key in seen:
                continue
            seen.add(identity)
            seen.add(title_key)

            published = cls._parse_date(item.published_at)
            if published and published < cutoff:
                continue

            text = f"{item.title} {item.summary}"
            relevance = sum(2 if keyword in item.title else 1 for keyword in keywords if keyword and keyword in text)
            if relevance <= 0:
                continue
            if any(source in f"{item.source} {item.title}" for source in cls.SOURCE_HINTS):
                relevance += 2

            ranked.append((relevance, published or datetime.min.replace(tzinfo=timezone.utc), item))

        ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return [item for _, _, item in ranked]

    @staticmethod
    def _normalize_title(title: str) -> str:
        title = re.sub(r"\s+", "", title)
        title = re.sub(r"[-_｜|].{2,12}$", "", title)
        return title.lower()

    @staticmethod
    def _parse_date(value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass

        for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    @staticmethod
    def _source(item: ET.Element) -> str:
        source = item.find("source")
        if source is not None and source.text:
            return source.text.strip()
        return "Bing News"

    @staticmethod
    def _text(item: ET.Element, tag: str) -> str:
        child = item.find(tag)
        return unescape((child.text or "").strip()) if child is not None else ""

    @staticmethod
    def _clean_html(value: str) -> str:
        text = re.sub(r"<[^>]+>", " ", value)
        return re.sub(r"\s+", " ", unescape(text)).strip()
