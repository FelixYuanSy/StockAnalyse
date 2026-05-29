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
    data_quality_html = _data_quality_html(result)
    level_html = _level_context_html(result)
    etf_html = _etf_context_html(result)
    quant_html = _quant_context_html(result)

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
    .note {{ background: #fff7e6; border: 1px solid #ffe2a8; border-radius: 6px; padding: 12px 14px; line-height: 1.7; }}
    .muted {{ color: #5f6368; line-height: 1.7; }}
    table {{ width: 100%; border-collapse: collapse; margin: 10px 0 16px; font-size: 14px; }}
    th, td {{ border: 1px solid #e8eaed; padding: 9px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f1f3f4; }}
    .small {{ font-size: 13px; }}
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
      <h2>数据质量与缺失提示</h2>
      {data_quality_html}
    </section>
    <section class="panel">
      <h2>关键价位分层</h2>
      {level_html}
    </section>
    {etf_html}
    <section class="panel">
      <h2>量化因子与回测说明</h2>
      {quant_html}
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


def _data_quality_html(result: AnalysisResult) -> str:
    warnings = list(result.warnings)
    professional = result.fundamental_data.get("professional_context", {})
    data_warning = professional.get("data_time_warning") or {}
    lines = []
    if data_warning:
        gap = data_warning.get("price_gap_pct")
        latest_date = data_warning.get("latest_kline_date") or "未知"
        if gap is not None:
            lines.append(
                f"实时/指示价格与最新日线收盘价的差异约 {gap:+.2f}%，日线指标对应日期为 {escape(str(latest_date))}。"
            )
    if warnings:
        lines.extend(escape(item) for item in warnings[:8])
    if result.quote.asset_type == "etf":
        lines.append("ETF 持仓和行业配置通常来自季报，可能滞后于当前市场；IOPV/折溢价更适合判断交易价格是否偏离净值。")
    if result.quote.asset_type == "futures":
        lines.append("期货数据需要同时看现货、基差、持仓、成交和杠杆风险；单一指标不能直接决定交易。")
    if not lines:
        lines.append("本次没有明显的数据缺失提示，但仍建议交易前复核行情源和新闻链接。")
    return "<div class=\"note\">" + "<br>".join(lines) + "</div>"


def _level_context_html(result: AnalysisResult) -> str:
    context = result.market_data.get("level_context") or result.fundamental_data.get("professional_context", {}).get("level_plan") or {}
    if not context:
        return "<p class=\"muted\">暂无分层价位底稿。</p>"

    groups = [
        ("short_term_supports", "短线支撑", "今天/明天最先观察，跌破后短线计划要收缩。"),
        ("short_term_resistances", "短线压力", "反弹或突破首先要面对的位置，靠近时不适合盲目追高。"),
        ("swing_supports", "波段支撑", "趋势是否还能维持的中期位置。"),
        ("swing_resistances", "波段压力", "趋势继续向上需要放量突破的位置。"),
        ("extreme_supports", "极端风险支撑", "更偏最坏情景，不应直接当成短线止损。"),
        ("extreme_resistances", "极端压力", "更偏远端目标或强压力，不应作为短线必达目标。"),
    ]
    rows = []
    for key, label, meaning in groups:
        values = context.get(key) or []
        if not values:
            continue
        text = "；".join(_format_level(item) for item in values[:5])
        rows.append(f"<tr><td>{escape(label)}</td><td>{escape(text)}</td><td>{escape(meaning)}</td></tr>")

    rr = context.get("long_risk_reward") or {}
    rr_text = ""
    if rr.get("available"):
        rr_text = (
            f"<p class=\"muted\">多头赔率参考：入场 {rr.get('entry')}，止损 {rr.get('stop')}，"
            f"目标 {rr.get('target')}，赔率 {rr.get('reward_risk_ratio')}。"
            "赔率低于 1 通常说明潜在收益不足以覆盖风险。</p>"
        )

    return (
        "<table><thead><tr><th>层级</th><th>价位</th><th>怎么理解</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
        + rr_text
    )


def _etf_context_html(result: AnalysisResult) -> str:
    if result.quote.asset_type != "etf":
        return ""
    data = result.fundamental_data
    detail = data.get("realtime_detail") or {}
    holdings = (data.get("top_holdings") or {}).get("records") or []
    industries = (data.get("industry_allocation") or {}).get("records") or []
    if not detail and not holdings and not industries:
        return '<section class="panel"><h2>ETF 专属信息</h2><p class="muted">本次未获取到 ETF IOPV、持仓或行业配置扩展数据。</p></section>'

    metric_rows = []
    for label, key, meaning in (
        ("IOPV实时估值", "IOPV实时估值", "ETF盘中参考净值，用来判断成交价是否偏离净值。"),
        ("基金折价率", "基金折价率", "正值通常表示溢价，负值通常表示折价；绝对值越大，交易偏离风险越高。"),
        ("成交额", "成交额", "成交额越大，买卖冲击成本通常越低。"),
        ("换手率", "换手率", "反映当日交易活跃度，过高也可能意味着短线拥挤。"),
        ("最新份额", "最新份额", "份额变化可辅助观察资金申赎方向。"),
        ("流通市值", "流通市值", "规模越大通常流动性和稳定性越好。"),
    ):
        if key in detail:
            metric_rows.append(f"<tr><td>{escape(label)}</td><td>{escape(str(detail.get(key)))}</td><td>{escape(meaning)}</td></tr>")
    flow_rows = _fund_flow_rows(detail)

    holding_rows = []
    for item in holdings[:10]:
        name = item.get("股票名称") or item.get("持仓名称") or item.get("名称") or ""
        weight = item.get("占净值比例") or item.get("持仓占比") or ""
        holding_rows.append(f"<tr><td>{escape(str(name))}</td><td>{escape(str(weight))}</td></tr>")

    industry_rows = []
    for item in industries[:8]:
        industry = item.get("行业类别") or item.get("行业名称") or item.get("名称") or ""
        weight = item.get("占净值比例") or item.get("占比") or ""
        industry_rows.append(f"<tr><td>{escape(str(industry))}</td><td>{escape(str(weight))}</td></tr>")

    html = [
        '<section class="panel"><h2>ETF 专属信息</h2>',
        '<p class="muted">ETF 不是单家公司，核心要看跟踪方向、流动性、IOPV折溢价、份额变化和成分集中度。持仓/行业数据通常来自季报，存在滞后。</p>',
    ]
    if metric_rows:
        html.append("<h3>交易与净值指标</h3><table><thead><tr><th>指标</th><th>数值</th><th>含义</th></tr></thead><tbody>")
        html.append("".join(metric_rows))
        html.append("</tbody></table>")
    if flow_rows:
        html.append("<h3>资金流向</h3><p class=\"muted\">资金流用于观察短线情绪。净流入为负代表该类资金当日偏卖出，不能单独作为买卖信号。</p>")
        html.append("<table><thead><tr><th>类别</th><th>净额</th><th>净占比</th></tr></thead><tbody>")
        html.append("".join(flow_rows))
        html.append("</tbody></table>")
    if holding_rows:
        html.append("<h3>最近一期主要持仓</h3><table><thead><tr><th>成分</th><th>权重/比例</th></tr></thead><tbody>")
        html.append("".join(holding_rows))
        html.append("</tbody></table>")
    if industry_rows:
        html.append("<h3>行业配置</h3><table><thead><tr><th>行业</th><th>权重/比例</th></tr></thead><tbody>")
        html.append("".join(industry_rows))
        html.append("</tbody></table>")
    html.append("</section>")
    return "".join(html)


def _fund_flow_rows(detail: dict) -> list[str]:
    rows = []
    for label, amount_key, ratio_key in (
        ("主力", "主力净流入-净额", "主力净流入-净占比"),
        ("超大单", "超大单净流入-净额", "超大单净流入-净占比"),
        ("大单", "大单净流入-净额", "大单净流入-净占比"),
        ("中单", "中单净流入-净额", "中单净流入-净占比"),
        ("小单", "小单净流入-净额", "小单净流入-净占比"),
    ):
        if amount_key not in detail and ratio_key not in detail:
            continue
        amount = _format_money(detail.get(amount_key))
        ratio = _format_percent(detail.get(ratio_key))
        rows.append(f"<tr><td>{escape(label)}</td><td>{escape(amount)}</td><td>{escape(ratio)}</td></tr>")
    return rows


def _format_money(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "N/A")
    unit = "亿" if abs(number) >= 100_000_000 else "万"
    divisor = 100_000_000 if unit == "亿" else 10_000
    return f"{number / divisor:.2f}{unit}"


def _format_percent(value) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return str(value or "N/A")


def _quant_context_html(result: AnalysisResult) -> str:
    quant = result.fundamental_data.get("quant_context") or {}
    if not quant:
        return "<p class=\"muted\">暂无量化底稿。</p>"
    if not quant.get("available"):
        return f"<p class=\"muted\">{escape(str(quant.get('reason') or '量化上下文暂不可用。'))}</p>"

    metric_guide = quant.get("metric_guide") or {}
    factor_guide = quant.get("factor_guide") or {}
    signal = quant.get("signal") or {}
    intro = (
        f"<div class=\"note\">当前量化信号：{escape(str(signal.get('label', 'N/A')))}；"
        f"因子综合分：{escape(str(quant.get('factor_score', 'N/A')))} / 100；"
        f"量化置信度：{escape(str(quant.get('confidence', 'N/A')))} / 100。<br>"
        f"{escape(str(metric_guide.get('factor_score', '因子综合分用于辅助判断，不是买卖指令。')))}</div>"
    )

    factor_rows = []
    for item in quant.get("factors") or []:
        key = str(item.get("key") or "")
        evidence = "；".join(item.get("evidence") or [])
        factor_rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('name')))}</td>"
            f"<td>{escape(str(item.get('score')))}</td>"
            f"<td>{escape(str(item.get('label')))}</td>"
            f"<td>{escape(evidence)}</td>"
            f"<td>{escape(str(factor_guide.get(key, '该因子用于辅助判断当前结构。')))}</td>"
            "</tr>"
        )
    factor_table = ""
    if factor_rows:
        factor_table = (
            "<h3>因子表</h3><table><thead><tr><th>因子</th><th>分数</th><th>状态</th><th>依据</th><th>怎么看</th></tr></thead><tbody>"
            + "".join(factor_rows)
            + "</tbody></table>"
        )

    event_table = _event_backtest_html(quant)
    strategy_table = _strategy_backtest_html(quant)
    guide_rows = "".join(
        f"<tr><td>{escape(key)}</td><td>{escape(value)}</td></tr>"
        for key, value in metric_guide.items()
    )
    guide_table = (
        "<h3>指标词典</h3><table><thead><tr><th>指标</th><th>意思</th></tr></thead><tbody>"
        + guide_rows
        + "</tbody></table>"
        if guide_rows
        else ""
    )

    usage = escape(str(quant.get("usage_note") or ""))
    return intro + factor_table + event_table + strategy_table + guide_table + f"<p class=\"muted small\">{usage}</p>"


def _event_backtest_html(quant: dict) -> str:
    backtest = quant.get("event_backtest") or {}
    if not backtest.get("available"):
        return f"<p class=\"muted\">历史相似信号：{escape(str(backtest.get('reason') or '样本不足。'))}</p>"
    rows = []
    for horizon, stats in (backtest.get("horizons") or {}).items():
        if not stats.get("available"):
            continue
        rows.append(
            "<tr>"
            f"<td>{escape(str(horizon))}</td>"
            f"<td>{escape(str(stats.get('sample_count')))}</td>"
            f"<td>{escape(str(stats.get('win_rate')))}%</td>"
            f"<td>{escape(str(stats.get('avg_return')))}%</td>"
            f"<td>{escape(str(stats.get('directional_avg_return')))}%</td>"
            f"<td>{escape(str(stats.get('max_gain')))}%</td>"
            f"<td>{escape(str(stats.get('max_loss')))}%</td>"
            f"<td>{escape(str(stats.get('profit_factor') or 'N/A'))}</td>"
            "</tr>"
        )
    if not rows:
        return ""
    return (
        "<h3>历史相似信号</h3><p class=\"muted\">它回答的是：过去出现类似形态后，未来1/3/5日通常怎么走。样本少时只能低权重参考。</p>"
        "<table><thead><tr><th>周期</th><th>样本数</th><th>胜率</th><th>平均收益</th><th>方向收益</th><th>最大收益</th><th>最大亏损</th><th>盈亏比</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
        + f"<p class=\"muted\">{escape(str(backtest.get('interpretation') or ''))}</p>"
    )


def _strategy_backtest_html(quant: dict) -> str:
    strategy = quant.get("strategy_backtest") or {}
    if not strategy.get("available"):
        return f"<p class=\"muted\">策略型回测：{escape(str(strategy.get('reason') or '暂不可用。'))}</p>"
    rule = strategy.get("rule") or {}
    metric_rows = [
        ("交易次数", strategy.get("trade_count"), "历史上按同样规则模拟交易的次数。"),
        ("胜率", f"{strategy.get('win_rate')}%", "赚钱交易占比，不能单独看，要结合平均收益和最大亏损。"),
        ("平均收益", f"{strategy.get('avg_return')}%", "每笔模拟交易的平均结果，已扣除简化往返成本。"),
        ("最大回撤", f"{strategy.get('max_drawdown')}%", "策略过程中曾经最难熬的累计回撤。"),
        ("盈亏比", strategy.get("profit_factor") or "N/A", "盈利总额除以亏损总额，大于1更健康。"),
        ("平均持有天数", strategy.get("avg_holding_days"), "模拟交易平均持有多久。"),
    ]
    rows = "".join(f"<tr><td>{escape(str(a))}</td><td>{escape(str(b))}</td><td>{escape(str(c))}</td></tr>" for a, b, c in metric_rows)
    recent_rows = []
    for trade in strategy.get("recent_trades") or []:
        recent_rows.append(
            "<tr>"
            f"<td>{escape(str(trade.get('entry_date')))}</td>"
            f"<td>{escape(str(trade.get('direction')))}</td>"
            f"<td>{escape(str(trade.get('entry')))}</td>"
            f"<td>{escape(str(trade.get('exit')))}</td>"
            f"<td>{escape(str(trade.get('return_pct')))}%</td>"
            f"<td>{escape(str(trade.get('exit_reason')))}</td>"
            "</tr>"
        )
    recent_table = ""
    if recent_rows:
        recent_table = (
            "<h4>最近模拟交易</h4><table><thead><tr><th>入场日</th><th>方向</th><th>入场</th><th>离场</th><th>收益</th><th>退出原因</th></tr></thead><tbody>"
            + "".join(recent_rows)
            + "</tbody></table>"
        )
    rule_text = (
        f"规则：{rule.get('entry', 'N/A')}；{rule.get('stop_loss', 'N/A')}；"
        f"{rule.get('take_profit', 'N/A')}；最多持有 {rule.get('max_holding_days', 'N/A')} 日；"
        f"往返成本 {rule.get('round_trip_cost_bps', 'N/A')} bps。"
    )
    return (
        "<h3>策略型回测</h3>"
        f"<p class=\"muted\">{escape(rule_text)}</p>"
        "<table><thead><tr><th>指标</th><th>数值</th><th>怎么理解</th></tr></thead><tbody>"
        + rows
        + "</tbody></table>"
        + recent_table
        + f"<p class=\"muted\">{escape(str(strategy.get('interpretation') or ''))}</p>"
    )


def _format_level(item) -> str:
    if isinstance(item, dict):
        label = item.get("label") or ""
        price = item.get("price")
        distance = item.get("distance_pct")
        suffix = f"{distance:+.2f}%" if isinstance(distance, (int, float)) else ""
        return f"{label} {price} ({suffix})"
    return str(item)


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
