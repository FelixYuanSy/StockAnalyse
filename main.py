from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stock_analyse.ai_advisor import AiAdvisor, AiAdvisorError
from stock_analyse.analyzer import StockAnalyzer
from stock_analyse.data_provider import AkshareDataProvider, DataProviderError
from stock_analyse.html_report import generate_html_report
from stock_analyse.instrument_parser import asset_to_cli_value, is_instrument_text, parse_instrument_input
from stock_analyse.market import china_market_phase
from stock_analyse.models import AnalysisResult
from stock_analyse.news_searcher import WebNewsSearcher, WebNewsSearchError
from stock_analyse.professional import build_professional_context
from stock_analyse.report import format_follow_up_help, format_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stock, ETF and futures trend analysis CLI")
    parser.add_argument("symbol", nargs="?", help="Instrument code, for example 600519, 510300, 159915, RB0, AU0")
    parser.add_argument(
        "--asset",
        default="auto",
        choices=("auto", "stock", "etf", "futures"),
        help="Instrument type, default: auto",
    )
    parser.add_argument("--days", type=int, default=120, help="History window in trading days, default: 120")
    parser.add_argument("--once", action="store_true", help="Analyze once and exit")
    parser.add_argument("--no-ai", action="store_true", help="Diagnostics only: show local data/indicator report without AI")
    parser.add_argument("--show-raw", action="store_true", help="Also show the local data/indicator report used as AI evidence")
    parser.add_argument("--report", action="store_true", default=True, help="Generate an HTML report with chart and AI analysis")
    parser.add_argument("--no-report", action="store_false", dest="report", help="Do not generate an HTML report")
    parser.add_argument("--report-dir", default="reports", help="Directory for generated HTML reports")
    parser.add_argument(
        "--report-depth",
        default="专业详细",
        choices=("专业详细", "短线交易版", "保守投资版"),
        help="AI report style, default: 专业详细",
    )
    parser.add_argument(
        "--analysis-goal",
        default="",
        help="Optional goal for the full AI report, for example: 预测6月1日走势",
    )
    parser.add_argument(
        "--ai-provider",
        default="auto",
        choices=("auto", "openai", "gemini", "deepseek"),
        help="AI provider, default: auto",
    )
    parser.add_argument("--ai-model", default=None, help="AI model name. Defaults depend on provider.")
    parser.add_argument("--ai-timeout", type=float, default=120.0, help="AI request timeout in seconds")
    parser.add_argument(
        "--ai-reasoning",
        default="medium",
        choices=("none", "low", "medium", "high", "xhigh"),
        help="Reasoning effort for GPT advisor, default: medium",
    )
    parser.add_argument(
        "--use-system-proxy",
        action="store_true",
        help="Use HTTP_PROXY/HTTPS_PROXY from the current shell instead of bypassing proxies",
    )
    return parser.parse_args()


def analyze_symbol(
    provider: AkshareDataProvider,
    analyzer: StockAnalyzer,
    symbol: str,
    days: int,
    asset: str = "auto",
) -> AnalysisResult:
    parsed = parse_instrument_input(symbol)
    symbol_code = parsed.symbol
    asset_hint = asset_to_cli_value(parsed.asset, asset)
    asset_type = provider.resolve_asset_type(symbol_code, asset_hint)
    history = provider.get_daily_history(symbol_code, days=days, asset_type=asset_type)
    phase = china_market_phase()
    data_warnings: list[str] = []
    intraday = None

    try:
        quote = provider.get_realtime_quote(symbol_code, asset_type=asset_type)
    except DataProviderError as exc:
        quote = provider.quote_from_history(symbol_code, history, asset_type=asset_type)
        data_warnings.append(f"实时行情获取失败，已使用最新日线收盘数据代替: {exc}")

    if phase in {"盘中", "午间休市"}:
        try:
            intraday = provider.get_intraday_history(symbol_code, asset_type=asset_type)
        except DataProviderError as exc:
            data_warnings.append(f"分钟线获取失败，盘中预测降级为日线预测: {exc}")

    try:
        web_news = ()
        stock_news = provider.get_stock_news(symbol_code, asset_type=asset_type)
    except DataProviderError as exc:
        stock_news = ()
        data_warnings.append(str(exc))

    try:
        web_news = WebNewsSearcher().search(
            symbol=symbol_code,
            name=quote.name,
            asset_type=asset_type,
            limit=8,
        )
        stock_news = _merge_news(web_news, stock_news, limit=10)
    except WebNewsSearchError as exc:
        web_news = ()
        data_warnings.append(f"网页新闻搜索失败: {exc}")

    try:
        fundamental_data = provider.get_fundamental_data(symbol_code, asset_type=asset_type)
    except DataProviderError as exc:
        fundamental_data = {"missing_or_failed": [str(exc)]}
        data_warnings.append(str(exc))
    if web_news:
        fundamental_data["web_news"] = [
            {
                "title": item.title,
                "source": item.source,
                "published_at": item.published_at,
                "url": item.url,
                "summary": item.summary,
            }
            for item in web_news
        ]
    fundamental_data["professional_context"] = build_professional_context(
        quote=quote,
        history=history,
        asset_type=asset_type,
        fundamental_data=fundamental_data,
        news=stock_news,
    )

    if phase in {"盘中", "午间休市"}:
        global_news = ()
    else:
        try:
            global_news = provider.get_global_news()
        except DataProviderError as exc:
            global_news = ()
            data_warnings.append(str(exc))

    return analyzer.analyze(
        quote=quote,
        history=history,
        market_phase=phase,
        intraday=intraday,
        stock_news=stock_news,
        global_news=global_news,
        data_warnings=tuple(data_warnings),
        fundamental_data=fundamental_data,
    )


def interactive_loop(
    provider: AkshareDataProvider,
    analyzer: StockAnalyzer,
    days: int,
    initial_symbol: str | None,
    advisor: AiAdvisor | None,
    asset: str,
    show_raw: bool,
    report: bool,
    report_dir: Path,
    report_depth: str,
    analysis_goal: str = "",
) -> int:
    result: AnalysisResult | None = None
    current_symbol = initial_symbol

    while True:
        if not current_symbol:
            current_symbol = input("请输入股票/ETF/期货代码: ").strip()

        if current_symbol.lower() in {"q", "quit", "exit"}:
            return 0

        if not is_instrument_text(current_symbol):
            print("代码格式不正确。例如股票 600519、ETF 510300、期货 RB0/AU0/IF0。")
            current_symbol = None
            continue

        try:
            result = analyze_symbol(provider, analyzer, current_symbol, days, asset="auto")
        except DataProviderError as exc:
            print(f"数据获取失败: {exc}")
            current_symbol = None
            continue
        except Exception as exc:
            print(f"分析失败: {exc}")
            current_symbol = None
            continue

        if advisor:
            ai_text = _get_ai_advice(
                advisor,
                result,
                report_depth=report_depth,
                analysis_goal=analysis_goal,
            )
            print(_format_ai_output(advisor, ai_text))
            if report and ai_text:
                print(_write_report(result, ai_text, report_dir, analysis_goal=analysis_goal))
        if advisor is None or show_raw:
            print(format_report(result))
        print(format_follow_up_help())

        while True:
            command = input("\n继续提问或输入新股票代码: ").strip()
            if command.lower() in {"q", "quit", "exit"}:
                return 0
            if not command:
                continue
            if is_instrument_text(command):
                current_symbol = command
                break
            if result and any(word in command for word in ("刷新", "重新", "再分析", "更新")):
                current_symbol = result.quote.symbol
                break
            if result:
                if advisor:
                    ai_text = _get_ai_advice(advisor, result, command, report_depth=report_depth)
                    print(_format_ai_output(advisor, ai_text))
                else:
                    print("当前是 --no-ai 诊断模式，追问不会调用 AI。请去掉 --no-ai 后重新运行。")


def _build_advisor(args: argparse.Namespace) -> AiAdvisor | None:
    if args.no_ai:
        return None
    try:
        return AiAdvisor(
            provider=args.ai_provider,
            model=args.ai_model,
            reasoning_effort=args.ai_reasoning,
            timeout=args.ai_timeout,
        )
    except AiAdvisorError as exc:
        print(f"AI 分析未启用: {exc}")
        print("如需启用 AI，请设置 OPENAI_API_KEY、GEMINI_API_KEY 或 DEEPSEEK_API_KEY。")
        return None


def _merge_news(primary, secondary, limit: int):
    seen: set[str] = set()
    merged = []
    for item in (*primary, *secondary):
        key = (item.url or item.title).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= limit:
            break
    return tuple(merged)
    try:
        return AiAdvisor(
            provider=args.ai_provider,
            model=args.ai_model,
            reasoning_effort=args.ai_reasoning,
            timeout=args.ai_timeout,
        )
    except AiAdvisorError as exc:
        print(f"AI 分析未启用: {exc}")
        print("如需启用 AI，请设置 OPENAI_API_KEY、GEMINI_API_KEY 或 DEEPSEEK_API_KEY。")
        return None


def _get_ai_advice(
    advisor: AiAdvisor | None,
    result: AnalysisResult,
    question: str | None = None,
    report_depth: str = "专业详细",
    analysis_goal: str = "",
) -> str:
    if advisor is None:
        return ""
    try:
        advice = advisor.advise(
            result,
            user_question=question,
            report_depth=report_depth,
            analysis_goal=analysis_goal,
        )
    except AiAdvisorError as exc:
        return "\n".join(
            [
                f"AI 分析未完成: {exc}",
                "已获取到的数据摘要:",
                f"- 标的: {result.quote.name} ({result.quote.symbol}) / {result.quote.asset_type}",
                f"- 价格: {result.quote.price:.2f}, 涨跌幅: {result.quote.change_pct:.2f}%",
                f"- 数据来源: {result.data_source}, 市场状态: {result.market_phase}",
                f"- K线数量: {len(result.market_data.get('daily_kline_tail', []))} 条尾部样本",
                f"- 本地关键位: 支撑 {result.support_levels[0]:.2f}/{result.support_levels[1]:.2f}, 压力 {result.resistance_levels[0]:.2f}/{result.resistance_levels[1]:.2f}",
            ]
        )
    return advice


def _format_ai_output(advisor: AiAdvisor, ai_text: str) -> str:
    return f"\nAI 模型分析 ({advisor.provider}/{advisor.model}):\n{ai_text}"


def _write_report(result: AnalysisResult, ai_text: str, report_dir: Path, analysis_goal: str = "") -> str:
    path = generate_html_report(result, ai_text, report_dir, analysis_goal=analysis_goal)
    return f"\nHTML 图文报告已生成: {path.resolve()}"


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    load_dotenv(dotenv_path=Path(__file__).with_name(".env"))


def main() -> int:
    _load_dotenv()
    args = parse_args()
    provider = AkshareDataProvider(use_system_proxy=args.use_system_proxy)
    analyzer = StockAnalyzer()
    advisor = _build_advisor(args)
    if advisor is None and not args.no_ai:
        return 1

    if args.once:
        symbol = args.symbol or input("请输入股票/ETF/期货代码: ").strip()
        if not is_instrument_text(symbol):
            print("代码格式不正确。例如股票 600519、ETF 510300、期货 RB0/AU0/IF0。")
            return 2
        try:
            result = analyze_symbol(provider, analyzer, symbol, args.days, asset=args.asset)
            if advisor:
                ai_text = _get_ai_advice(
                    advisor,
                    result,
                    report_depth=args.report_depth,
                    analysis_goal=args.analysis_goal,
                )
                print(_format_ai_output(advisor, ai_text))
                if args.report and ai_text:
                    print(_write_report(result, ai_text, Path(args.report_dir), analysis_goal=args.analysis_goal))
            if args.no_ai or args.show_raw:
                print(format_report(result))
        except DataProviderError as exc:
            print(f"数据获取失败: {exc}")
            return 1
        return 0

    return interactive_loop(
        provider,
        analyzer,
        args.days,
        args.symbol,
        advisor,
        args.asset,
        args.show_raw,
        args.report,
        Path(args.report_dir),
        args.report_depth,
        args.analysis_goal,
    )


if __name__ == "__main__":
    sys.exit(main())
