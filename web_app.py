from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
import streamlit.components.v1 as components

from main import analyze_symbol, _load_dotenv
from stock_analyse.ai_advisor import AiAdvisor, AiAdvisorError
from stock_analyse.analyzer import StockAnalyzer
from stock_analyse.charting import build_chart_html
from stock_analyse.data_provider import AkshareDataProvider, DataProviderError
from stock_analyse.html_report import generate_html_report
from stock_analyse.instrument_parser import is_instrument_text
from stock_analyse.report import format_report


ASSET_LABELS = {
    "auto": "自动识别",
    "stock": "股票",
    "etf": "ETF",
    "futures": "期货",
}


def main() -> None:
    _load_dotenv()
    st.set_page_config(page_title="AI 投资分析助手", layout="wide")
    st.title("AI 投资分析助手")

    with st.sidebar:
        st.header("分析设置")
        symbol = st.text_input("代码", value="LC2609", help="例如 600519、510300、LC2609，也支持 futures:LC2609")
        asset = st.selectbox("标的类型", options=list(ASSET_LABELS), format_func=lambda key: ASSET_LABELS[key])
        ai_provider = st.selectbox("AI Provider", options=["auto", "gemini", "deepseek", "openai"], index=1)
        report_depth = st.selectbox("报告深度", options=["专业详细", "短线交易版", "保守投资版"], index=0)
        days = st.slider("历史K线天数", min_value=80, max_value=260, value=120, step=20)
        show_raw = st.checkbox("显示本地数据底稿", value=False)
        generate_file = st.checkbox("生成 HTML 报告文件", value=True)
        run = st.button("生成分析", type="primary", use_container_width=True)

    if not run:
        st.info("输入代码后点击“生成分析”。建议先试 LC2609、510300 或 600519。")
        return

    if not is_instrument_text(symbol):
        st.error("代码格式不正确。例如股票 600519、ETF 510300、期货 LC2609。")
        return

    provider = AkshareDataProvider()
    analyzer = StockAnalyzer()

    with st.status("正在获取行情、K线和新闻...", expanded=False):
        try:
            result = analyze_symbol(provider, analyzer, symbol, days, asset=asset)
        except DataProviderError as exc:
            st.error(f"数据获取失败: {exc}")
            return

    try:
        advisor = AiAdvisor(provider=ai_provider)
    except AiAdvisorError as exc:
        st.error(f"AI 分析未启用: {exc}")
        st.caption("请检查 .env 中是否设置 GEMINI_API_KEY、DEEPSEEK_API_KEY 或 OPENAI_API_KEY。")
        return

    with st.status("AI 正在生成专业投资决策报告...", expanded=False):
        try:
            ai_text = advisor.advise(result, report_depth=report_depth)
        except AiAdvisorError as exc:
            st.error(f"AI 分析未完成: {exc}")
            st.subheader("已获取到的数据底稿")
            st.code(format_report(result), language="text")
            return

    st.subheader(f"{result.quote.name} ({result.quote.symbol})")
    cols = st.columns(4)
    cols[0].metric("类型", result.quote.asset_type)
    cols[1].metric("当前价格", f"{result.quote.price:.2f}", f"{result.quote.change_pct:.2f}%")
    cols[2].metric("第一支撑", f"{result.support_levels[0]:.2f}")
    cols[3].metric("第一压力", f"{result.resistance_levels[0]:.2f}")

    st.subheader("AI 投资决策")
    st.markdown(ai_text)

    st.subheader("新闻与来源链接")
    _render_news_links(result)

    st.subheader("图表详解")
    components.html(build_chart_html(result), height=1050, scrolling=True)

    if generate_file:
        report_path = generate_html_report(result, ai_text, Path("reports"))
        st.success(f"HTML 报告已生成: {report_path.resolve()}")
        st.download_button(
            "下载 HTML 报告",
            data=report_path.read_bytes(),
            file_name=report_path.name,
            mime="text/html",
            use_container_width=True,
        )

    if show_raw:
        st.subheader("本地数据底稿")
        st.code(format_report(result), language="text")


def _render_news_links(result) -> None:
    items = []
    seen = set()

    def add(title: str, source: str, published_at: str, summary: str, url: str) -> None:
        key = (url or title).strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        items.append(
            {
                "title": title,
                "source": source,
                "published_at": published_at,
                "summary": summary,
                "url": url,
            }
        )

    for raw in result.fundamental_data.get("web_news", []):
        add(
            str(raw.get("title") or ""),
            str(raw.get("source") or ""),
            str(raw.get("published_at") or ""),
            str(raw.get("summary") or ""),
            str(raw.get("url") or ""),
        )

    for item in (*result.stock_news, *result.global_news):
        add(item.title, item.source, item.published_at, item.summary, item.url)

    if not items:
        st.caption("本次未获取到可展示链接的新闻。")
        return

    for item in items[:16]:
        with st.container(border=True):
            st.markdown(f"**{item['title']}**")
            st.caption(f"{item['source'] or _domain(item['url']) or '未知来源'} · {item['published_at'] or '时间未知'}")
            if item["summary"]:
                st.write(item["summary"][:260])
            if item["url"]:
                st.link_button("打开原文", item["url"])
            else:
                st.caption("暂无原文链接")


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except ValueError:
        return ""


if __name__ == "__main__":
    main()
