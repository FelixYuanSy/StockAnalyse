from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
import streamlit.components.v1 as components

from main import _load_dotenv, analyze_symbol
from stock_analyse.ai_advisor import AiAdvisor, AiAdvisorError
from stock_analyse.analyzer import StockAnalyzer
from stock_analyse.charting import build_chart_html, build_today_prediction_html, should_show_today_prediction
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

REPORT_DEPTH_OPTIONS = ["专业详细", "短线交易版", "保守投资版"]


def main() -> None:
    _load_dotenv()
    _init_session_state()

    st.set_page_config(page_title="AI 投资分析助手", layout="wide")
    st.title("AI 投资分析助手")

    with st.sidebar:
        st.header("分析设置")
        symbol = st.text_input(
            "代码",
            value="LC2609",
            help="例如 600519、510300、LC2609，也支持 futures:LC2609",
        )
        asset = st.selectbox(
            "标的类型",
            options=list(ASSET_LABELS),
            format_func=lambda key: ASSET_LABELS[key],
        )
        ai_provider = st.selectbox("AI Provider", options=["auto", "gemini", "deepseek", "openai"], index=1)
        report_depth = st.selectbox("报告深度", options=REPORT_DEPTH_OPTIONS, index=0)
        days = st.slider("历史K线天数", min_value=80, max_value=260, value=120, step=20)
        show_raw = st.checkbox("显示本地数据底稿", value=False)
        generate_file = st.checkbox("生成 HTML 报告文件", value=True)
        run = st.button("生成分析", type="primary", use_container_width=True)

        if st.session_state.latest_result is not None:
            if st.button("清空当前分析", use_container_width=True):
                _clear_analysis_state()
                st.rerun()

    if run:
        _run_analysis(
            symbol=symbol,
            asset=asset,
            ai_provider=ai_provider,
            report_depth=report_depth,
            days=days,
            generate_file=generate_file,
        )

    result = st.session_state.latest_result
    ai_text = st.session_state.latest_ai_text

    if result is None:
        st.info("输入代码后点击“生成分析”。建议先试 LC2609、510300 或 600519。")
        return

    _render_summary(result)

    st.subheader("AI 投资决策")
    st.markdown(ai_text or "AI 报告为空，请重新生成分析。")

    _render_quant_context(result)

    _render_follow_up(result, ai_provider=ai_provider, report_depth=report_depth)

    st.subheader("新闻与来源链接")
    _render_news_links(result)

    st.subheader("图表详解")
    components.html(build_chart_html(result), height=1050, scrolling=True)

    _render_download()

    if show_raw:
        st.subheader("本地数据底稿")
        st.code(format_report(result), language="text")


def _init_session_state() -> None:
    defaults = {
        "latest_result": None,
        "latest_ai_text": "",
        "latest_report_path": "",
        "chat_history": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _clear_analysis_state() -> None:
    st.session_state.latest_result = None
    st.session_state.latest_ai_text = ""
    st.session_state.latest_report_path = ""
    st.session_state.chat_history = []


def _run_analysis(
    symbol: str,
    asset: str,
    ai_provider: str,
    report_depth: str,
    days: int,
    generate_file: bool,
) -> None:
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

    report_path = ""
    if generate_file:
        path = generate_html_report(result, ai_text, Path("reports"))
        report_path = str(path)
        st.success(f"HTML 报告已生成: {path.resolve()}")

    st.session_state.latest_result = result
    st.session_state.latest_ai_text = ai_text
    st.session_state.latest_report_path = report_path
    st.session_state.chat_history = []


def _render_summary(result) -> None:
    st.subheader(f"{result.quote.name} ({result.quote.symbol})")
    cols = st.columns(4)
    cols[0].metric("类型", result.quote.asset_type)
    cols[1].metric("当前价格", f"{result.quote.price:.2f}", f"{result.quote.change_pct:.2f}%")
    cols[2].metric("第一支撑", f"{result.support_levels[0]:.2f}")
    cols[3].metric("第一压力", f"{result.resistance_levels[0]:.2f}")


def _render_quant_context(result) -> None:
    quant = result.fundamental_data.get("quant_context") or {}
    if not quant:
        return

    st.subheader("量化因子与历史相似信号")
    if not quant.get("available"):
        st.caption(quant.get("reason") or "量化上下文暂不可用。")
        return

    signal = quant.get("signal") or {}
    cols = st.columns(3)
    cols[0].metric("当前量化信号", signal.get("label", "N/A"))
    cols[1].metric("因子综合分", f"{quant.get('factor_score', 'N/A')}/100")
    cols[2].metric("量化置信度", f"{quant.get('confidence', 'N/A')}/100")

    factors = quant.get("factors") or []
    if factors:
        st.dataframe(
            [
                {
                    "因子": item.get("name"),
                    "分数": item.get("score"),
                    "状态": item.get("label"),
                    "依据": "；".join(item.get("evidence") or []),
                }
                for item in factors
            ],
            use_container_width=True,
            hide_index=True,
        )

    backtest = quant.get("event_backtest") or {}
    if not backtest.get("available"):
        st.caption(backtest.get("reason") or "历史相似信号样本不足。")
        return

    rows = []
    for horizon, stats in (backtest.get("horizons") or {}).items():
        if not stats.get("available"):
            continue
        rows.append(
            {
                "周期": horizon,
                "样本数": stats.get("sample_count"),
                "胜率": f"{stats.get('win_rate')}%",
                "平均收益": f"{stats.get('avg_return')}%",
                "方向收益": f"{stats.get('directional_avg_return')}%",
                "最大收益": f"{stats.get('max_gain')}%",
                "最大亏损": f"{stats.get('max_loss')}%",
                "盈亏比": stats.get("profit_factor") or "N/A",
            }
        )
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(quant.get("usage_note") or "")


def _render_follow_up(result, ai_provider: str, report_depth: str) -> None:
    st.subheader("继续追问")
    st.caption("这里会基于当前这份数据底稿继续回答。你也可以在侧边栏输入新代码并重新生成分析。")

    examples = st.columns(4)
    examples[0].caption("例：明天怎么操作")
    examples[1].caption("例：为什么这么判断")
    examples[2].caption("例：风险在哪里")
    examples[3].caption("例：如果我已持仓怎么办")

    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("show_today_prediction"):
                components.html(build_today_prediction_html(result), height=580, scrolling=True)

    question = st.chat_input("继续提问，例如：明天怎么操作？风险在哪里？")
    if not question:
        return

    show_today_prediction = should_show_today_prediction(question)
    st.session_state.chat_history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    try:
        advisor = AiAdvisor(provider=ai_provider)
        with st.status("AI 正在基于当前数据继续分析...", expanded=False):
            answer = advisor.advise(result, user_question=question, report_depth=report_depth)
    except AiAdvisorError as exc:
        answer = _local_follow_up_fallback(result, question, exc)

    st.session_state.chat_history.append(
        {
            "role": "assistant",
            "content": answer,
            "show_today_prediction": show_today_prediction,
        }
    )
    with st.chat_message("assistant"):
        st.markdown(answer)
        if show_today_prediction:
            st.caption("下图是基于当前数据底稿生成的情景预测，不是确定走势。")
            components.html(build_today_prediction_html(result), height=580, scrolling=True)


def _render_download() -> None:
    report_path = st.session_state.latest_report_path
    if not report_path:
        return

    path = Path(report_path)
    if not path.exists():
        st.warning("HTML 报告文件路径已记录，但文件当前不存在。请重新生成分析。")
        return

    st.download_button(
        "下载 HTML 报告",
        data=path.read_bytes(),
        file_name=path.name,
        mime="text/html",
        use_container_width=True,
    )


def _local_follow_up_fallback(result, question: str, exc: Exception) -> str:
    latest_rows = result.market_data.get("daily_kline_tail", [])
    latest = latest_rows[-1] if latest_rows else {}
    ma20 = latest.get("ma20", "N/A")
    ma60 = latest.get("ma60", "N/A")
    macd_hist = latest.get("macd_hist", "N/A")
    rsi14 = latest.get("rsi14", "N/A")

    lines = [
        f"AI 追问暂时失败：{exc}",
        "",
        "先给你一个本地兜底判断，避免这次追问完全中断：",
        f"- 标的：{result.quote.name} ({result.quote.symbol})，类型：{result.quote.asset_type}",
        f"- 当前价格：{result.quote.price:.2f}，涨跌幅：{result.quote.change_pct:.2f}%",
        f"- 本地趋势：{result.trend}，评分：{result.score}/100，风险等级：{result.risk_level}",
        f"- 第一支撑：{result.support_levels[0]:.2f}，第一压力：{result.resistance_levels[0]:.2f}",
        f"- MA20：{_fmt_value(ma20)}，MA60：{_fmt_value(ma60)}，MACD柱：{_fmt_value(macd_hist)}，RSI14：{_fmt_value(rsi14)}",
        f"- 本地预测：{result.prediction.bias}，置信度：{result.prediction.confidence}/100",
        "",
        "操作上先按支撑/压力做情景处理：没有有效站上压力前不要追高；跌破第一支撑后优先控制仓位。下面如果你要求画走势图，图表仍会正常显示。",
    ]
    return "\n".join(lines)


def _fmt_value(value) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


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
            st.caption(f"{item['source'] or _domain(item['url']) or '未知来源'} | {item['published_at'] or '时间未知'}")
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
