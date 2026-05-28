from __future__ import annotations

from datetime import datetime
from html import escape
import json
from pathlib import Path
from urllib.parse import urlparse

from .charting import build_chart_html, write_html
from .models import AnalysisResult, NewsItem


def generate_html_report(result: AnalysisResult, ai_text: str, output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{result.quote.symbol}_{timestamp}.html"
    path = output_dir / filename
    chart_html = build_chart_html(result)
    fundamental_json = json.dumps(result.fundamental_data, ensure_ascii=False, indent=2, default=str)
    news_html = _news_links_html(result)

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(result.quote.name)} {escape(result.quote.symbol)} 投资决策报告</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f7f8fa; color: #202124; }}
    header {{ padding: 28px 36px 18px; background: #fff; border-bottom: 1px solid #e8eaed; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 10px; font-size: 28px; }}
    h2 {{ margin: 26px 0 12px; font-size: 20px; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 10px; color: #5f6368; }}
    .pill {{ background: #eef2f7; border-radius: 6px; padding: 6px 10px; }}
    .panel {{ background: #fff; border: 1px solid #e8eaed; border-radius: 8px; padding: 20px; margin-bottom: 18px; }}
    .ai {{ white-space: pre-wrap; line-height: 1.68; font-size: 15px; }}
    .raw {{ white-space: pre-wrap; overflow: auto; max-height: 420px; background: #0f172a; color: #e5e7eb; border-radius: 6px; padding: 14px; font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .metric {{ background: #fafafa; border: 1px solid #edf0f2; border-radius: 6px; padding: 12px; }}
    .metric b {{ display: block; font-size: 18px; margin-top: 4px; }}
    .news-list {{ display: grid; gap: 12px; }}
    .news-item {{ border: 1px solid #edf0f2; border-radius: 6px; padding: 14px; background: #fafafa; }}
    .news-title {{ font-weight: 700; margin-bottom: 6px; }}
    .news-meta {{ color: #5f6368; font-size: 13px; margin-bottom: 8px; }}
    .news-summary {{ color: #3c4043; line-height: 1.6; margin-bottom: 8px; }}
    .news-link {{ color: #1558d6; text-decoration: none; font-weight: 600; }}
    .news-link:hover {{ text-decoration: underline; }}
    footer {{ color: #5f6368; font-size: 13px; padding: 0 24px 28px; max-width: 1180px; margin: 0 auto; }}
  </style>
</head>
<body>
  <header>
    <h1>{escape(result.quote.name)} ({escape(result.quote.symbol)}) 投资决策报告</h1>
    <div class="meta">
      <span class="pill">类型: {escape(result.quote.asset_type)}</span>
      <span class="pill">数据来源: {escape(result.data_source)}</span>
      <span class="pill">市场状态: {escape(result.market_phase)}</span>
      <span class="pill">生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</span>
    </div>
  </header>
  <main>
    <section class="panel">
      <div class="grid">
        <div class="metric">当前价格<b>{result.quote.price:.2f}</b></div>
        <div class="metric">涨跌幅<b>{result.quote.change_pct:.2f}%</b></div>
        <div class="metric">支撑位<b>{result.support_levels[0]:.2f} / {result.support_levels[1]:.2f}</b></div>
        <div class="metric">压力位<b>{result.resistance_levels[0]:.2f} / {result.resistance_levels[1]:.2f}</b></div>
      </div>
    </section>
    <section class="panel">
      <h2>AI 投资决策</h2>
      <div class="ai">{escape(ai_text)}</div>
    </section>
    <section class="panel">
      <h2>新闻与来源链接</h2>
      {news_html}
    </section>
    <section class="panel">
      <h2>图表详解</h2>
      {chart_html}
    </section>
    <section class="panel">
      <h2>基本面/期货底稿</h2>
      <pre class="raw">{escape(fundamental_json)}</pre>
    </section>
  </main>
  <footer>本报告仅用于研究辅助，不构成收益承诺或直接投资指令。</footer>
</body>
</html>
"""
    return write_html(path, html)


def _news_links_html(result: AnalysisResult) -> str:
    grouped = _collect_news_groups(result)
    if not any(grouped.values()):
        return "<p>本次未获取到可展示链接的新闻。</p>"

    sections = []
    labels = (
        ("strong_related", "强相关新闻"),
        ("weak_related", "弱相关/背景新闻"),
        ("market_background", "市场背景新闻"),
    )
    for key, label in labels:
        items = grouped.get(key, [])
        if not items:
            continue
        cards = [_news_card(item) for item in items]
        sections.append(f"<h3>{escape(label)}</h3><div class=\"news-list\">" + "\n".join(cards) + "</div>")
    return "\n".join(sections)


def _news_card(item: NewsItem) -> str:
        title = escape(item.title)
        source = escape(item.source or _domain(item.url) or "未知来源")
        published = escape(item.published_at or "时间未知")
        summary = escape(item.summary[:260]) if item.summary else ""
        link = _link_html(item.url)
        return f"""
            <article class="news-item">
              <div class="news-title">{title}</div>
              <div class="news-meta">{source} · {published}</div>
              <div class="news-summary">{summary}</div>
              {link}
            </article>
            """


def _collect_news_groups(result: AnalysisResult) -> dict[str, list[NewsItem]]:
    groups: dict[str, list[NewsItem]] = {
        "strong_related": [],
        "weak_related": [],
        "market_background": [],
    }
    seen: set[str] = set()

    def add(group: str, item: NewsItem) -> None:
        key = (item.url or item.title).strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        groups[group].append(item)

    relevance = result.fundamental_data.get("professional_context", {}).get("news_relevance", {})
    for group_key, source_key in (
        ("strong_related", "strong_related"),
        ("weak_related", "weak_related"),
    ):
        for raw in relevance.get(source_key, []):
            add(group_key, _news_item_from_dict(raw))

    for raw in result.fundamental_data.get("web_news", []):
        add("weak_related", _news_item_from_dict(raw))

    for item in result.stock_news:
        add("weak_related", item)
    for item in result.global_news:
        add("market_background", item)

    return {key: value[:8] for key, value in groups.items()}


def _news_item_from_dict(raw: dict) -> NewsItem:
    return NewsItem(
        title=str(raw.get("title") or ""),
        source=str(raw.get("source") or ""),
        published_at=str(raw.get("published_at") or ""),
        summary=str(raw.get("summary") or ""),
        url=str(raw.get("url") or ""),
    )


def _link_html(url: str) -> str:
    if not url:
        return '<span class="news-meta">暂无原文链接</span>'
    safe_url = escape(url, quote=True)
    domain = escape(_domain(url) or "打开原文")
    return f'<a class="news-link" href="{safe_url}" target="_blank" rel="noopener noreferrer">打开原文：{domain}</a>'


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except ValueError:
        return ""
