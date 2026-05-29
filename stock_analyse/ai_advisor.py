from __future__ import annotations

import json
import os
import re
import time
from datetime import date
from urllib.parse import urlparse
from typing import Literal

from .models import AnalysisResult


Provider = Literal["auto", "openai", "gemini", "deepseek"]

DEFAULT_MODELS = {
    "openai": "gpt-5.5",
    "gemini": "gemini-2.5-flash",
    "deepseek": "deepseek-chat",
}

GEMINI_FALLBACK_MODELS = ("gemini-2.5-flash", "gemini-2.0-flash")


class AiAdvisorError(RuntimeError):
    """Raised when the AI advisor cannot produce a response."""


class AiAdvisor:
    def __init__(
        self,
        provider: Provider = "auto",
        model: str | None = None,
        reasoning_effort: str = "medium",
        timeout: float = 120.0,
    ) -> None:
        try:
            from openai import OpenAI
            import httpx
            import requests
        except ImportError as exc:
            raise AiAdvisorError("缺少 openai 依赖。请运行: pip install -r requirements.txt") from exc

        resolved_provider = self._resolve_provider(provider)
        api_key = self._api_key_for(resolved_provider)
        if not api_key:
            raise AiAdvisorError(
                "没有找到可用 AI API key。请设置 OPENAI_API_KEY、GEMINI_API_KEY 或 DEEPSEEK_API_KEY。"
            )

        base_url = self._base_url_for(resolved_provider)
        http_client = self._build_http_client(httpx, timeout)
        client_kwargs = {"api_key": api_key, "base_url": base_url, "timeout": timeout}
        if http_client is not None:
            client_kwargs["http_client"] = http_client
        self._client = OpenAI(**client_kwargs)
        self._provider = resolved_provider
        self._model = model or DEFAULT_MODELS[resolved_provider]
        self._reasoning_effort = reasoning_effort
        self._timeout = timeout
        self._api_key = api_key
        self._requests = requests

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    def advise(
        self,
        result: AnalysisResult,
        user_question: str | None = None,
        report_depth: str = "专业详细",
        enable_web_search: bool | None = None,
        analysis_goal: str | None = None,
    ) -> str:
        payload = _analysis_payload(result)
        analysis_goal = (analysis_goal or "").strip()
        missing_search = _missing_data_search_instruction(result)
        goal_needs_search = _text_requests_search(analysis_goal)
        use_gemini_search = (
            self._provider == "gemini"
            and (bool(user_question) or missing_search["should_search"] or goal_needs_search)
            and _should_enable_gemini_search_grounding()
            if enable_web_search is None
            else self._provider == "gemini" and bool(enable_web_search)
        )
        prompt = {
            "task": "你是主分析模型。请基于程序收集到的股票、ETF或期货行情、K线、指标、新闻，独立给出下一阶段趋势预测和投资建议。",
            "analysis_goal": analysis_goal or "请给出完整投资分析。",
            "target_date_instruction": _target_date_instruction(analysis_goal),
            "user_question": user_question or "",
            "report_depth": report_depth,
            "analysis_payload": payload,
            "interactive_search_instruction": _interactive_search_instruction(use_gemini_search),
            "missing_data_search_instruction": missing_search,
            "asset_specific_framework": _asset_specific_framework(result.quote.asset_type),
            "etf_data_requirements": [
                "如果标的类型是 ETF，且 analysis_payload.fundamental_data.realtime_detail 存在，必须引用 IOPV实时估值、基金折价率、成交额、换手率、最新份额、流通市值/总市值、资金流向等字段。",
                "如果引用ETF资金流向，必须明确列出主力/超大单/大单净额或净占比，并说明资金流只是短线情绪指标，不能单独决定买卖。",
                "如果 analysis_payload.fundamental_data.top_holdings 存在，必须说明最近一期前十大或前十五大持仓、权重集中度和主要成分股风险。",
                "如果 analysis_payload.fundamental_data.industry_allocation 存在，必须说明行业配置、第一大行业占比和行业集中风险。",
                "只有在对应字段确实缺失时，才提示 ETF 持仓、IOPV、折溢价缺失；不要在字段已经存在时继续说暂未接入。",
            ],
            "quant_requirements": [
                "如果 analysis_payload.fundamental_data.quant_context.available 为 true，必须增加“量化因子与历史相似信号”章节。",
                "必须引用 quant_context.signal.label、factor_score、confidence、factors 和 event_backtest。",
                "必须说明未来1日/3日/5日相似信号回测的样本数、胜率、平均收益、最大亏损；样本数不足时要降低结论权重。",
                "如果 quant_context.strategy_backtest.available 为 true，必须引用策略型回测：入场规则、止损止盈、交易次数、胜率、平均收益、最大回撤、盈亏比和退出原因。",
                "如果是股票或ETF的看空信号，策略型回测中的 short 方向只能解释为回避/减仓/对冲参考，不得直接建议普通用户裸做空。",
                "必须用普通投资者能听懂的语言解释因子综合分、胜率、平均收益、盈亏比、最大回撤分别是什么意思，不要只罗列数字。",
                "不能把轻量回测说成确定预测；必须说明该回测已扣除简化交易成本，但不含真实滑点、盘口冲击、样本外验证和组合仓位管理。",
                "最终仓位建议必须同时考虑AI判断、本地技术结构、量化因子分和回测胜率。",
            ],
            "output_requirements": [
                "必须使用中文，结构清晰，像一位优秀投资者给普通投资者解释。",
                "如果 analysis_goal 不为空，报告必须围绕 analysis_goal 展开；不要默认写成“今天走势”，也不要机械复用通用模板。",
                "如果 analysis_goal 或 target_date_instruction 包含目标日期，必须在一句话结论、操作计划和数据说明中明确该目标日期；今天/当前只允许作为数据截面，不是报告主题。",
                "如果目标日期在未来，请基于当前可得数据预测该日期前后的情景、触发条件和风控计划，不要假装已经知道未来真实行情。",
                "如果 user_question 要求你搜索、查找、核实、补充仓单/库存/仓储/现货/基差/新闻等最新信息，且 interactive_search_instruction 显示搜索工具已启用，你必须先使用搜索工具，而不是只说原始底稿缺失。",
                "如果 missing_data_search_instruction.should_search 为 true，且 interactive_search_instruction 显示搜索工具已启用，你必须先尝试用搜索工具补齐这些缺失数据，再生成完整报告。",
                "如果缺失项属于分钟线/实时盘口等搜索工具无法可靠替代的数据，可以明确说明不能用网页搜索替代，不要编造。",
                "搜索后必须说明你搜索/核实到了什么、来源链接是什么、数据时间是什么、可信度如何，以及它如何改变或不改变原分析。",
                "必须先给一句话结论，再给操作计划。",
                "必须按以下标题输出：一句话结论、当前趋势结构、关键支撑/压力、风险收益比、仓位建议、不同投资者方案、看错条件、下一阶段观察清单。",
                "如果是股票，必须增加“股票100分质量评分”章节，按盈利能力20分、成长能力20分、现金流质量15分、估值水平20分、财务安全10分、行业与竞争10分、技术面与市场情绪5分分别打分，并给出总分。",
                "股票评分必须综合基本面、估值、现金流、行业和风险，不得只看K线；如果某项数据缺失，要扣除可信度并明确说明缺失项。",
                "股票最终必须输出：总分、投资建议（买入/持有/观察/回避）、核心理由、主要风险、适合的投资周期、建议仓位、触发买入条件、触发卖出或止损条件、一句话总结。",
                "如果是期货，不要套用股票财务评分；必须增加“期货驱动因素评分”章节，覆盖趋势动量、成交/持仓、现货基差、库存仓单、产业新闻、宏观政策、期限结构、杠杆风险。",
                "如果 payload 中有 professional_context，必须优先使用其中的 news_relevance、position_summary、basis_summary、level_plan 和 data_time_warning。",
                "期货新闻必须按 strong_related、weak_related、excluded_or_background 分层；只有 strong_related 可以作为核心交易依据，无关新闻不得用于方向判断。",
                "期货持仓必须看前N合计、净持仓和增减仓，不得把单个期货公司席位直接解释为该公司的自营观点。",
                "期货交易计划必须数字化：写出入场区间、止损位、目标位、风险点数、收益点数、赔率；如果胜率不足，要明确说即使赔率可看也不建议重仓。",
                "支撑压力必须分层：日内/短线观察位、波段关键位、极端风险位，不要只给一个很远的支撑位。",
                "如果 quote_price 与 latest_kline_close 不在同一时间截面，必须在结论前半部分明确提醒，避免把实时价和日线指标混用。",
                "如果 market_phase 是 盘中 或 午间休市，不得写“技术指标和K线数据截至今日收盘”；应写“截至当前可获取的盘中快照/日线快照”。只有 market_phase 是 盘后 或 休市，才可以说日线收盘数据。",
                "如果是ETF，不要套用股票财务评分；必须增加“ETF质量与交易评分”章节，覆盖跟踪指数趋势、行业/风格景气、流动性、折溢价/IOPV可用性、成分风险、技术面。",
                "不要照抄本地规则结论；本地评分只能作为参考，必须自己综合K线、指标、量能、新闻和关键价位判断。",
                "必须给出看错条件和风险控制。",
                "必须说明你参考了哪些数据，哪些数据缺失或实时性不足。",
                "新闻必须区分时间：当天/近三日新闻可以作为短线驱动，较旧新闻只能作为背景，不得当作最新利多或利空。",
                "使用网页搜索新闻时，必须在分析中说明新闻来源、发布时间和可验证链接；没有来源或时间的消息只能低权重参考。",
                "仓位建议要保守，使用区间表达，例如 0-2 成、2-3 成，不要建议满仓。",
                "如果是期货，必须强调杠杆、隔夜风险、持仓量/成交量和结算价；如果是ETF，必须说明跟踪标的方向和折溢价/IOPV数据可用性；如果是股票，必须说明财报/估值/行业数据是否缺失。",
                "不要承诺收益，不要使用绝对化措辞。",
                "如果数据来源是最新日线而非实时行情，需要明确说明实时性限制。",
            ],
        }
        if user_question:
            prompt = _follow_up_prompt(
                result=result,
                user_question=user_question,
                report_depth=report_depth,
                enable_search=use_gemini_search,
            )
        prompt_text = json.dumps(prompt, ensure_ascii=False)

        try:
            if self._provider == "gemini":
                text = self._gemini_rest_api(prompt_text, enable_google_search=use_gemini_search)
            elif self._provider == "openai":
                text = self._responses_api(prompt_text)
            else:
                text = self._chat_completions_api(prompt_text)
        except Exception as exc:
            raise AiAdvisorError(_friendly_ai_error(exc, self._provider)) from exc

        if not text:
            raise AiAdvisorError("AI 返回为空。Gemini 已响应但没有文本内容，建议用 --ai-reasoning none 或 --ai-model gemini-2.5-flash 重试。")
        return text.strip()

    def _responses_api(self, prompt_text: str) -> str:
        response = self._client.responses.create(
            model=self._model,
            reasoning={"effort": self._reasoning_effort},
            instructions=_system_prompt(),
            input=prompt_text,
        )
        return getattr(response, "output_text", "") or ""

    def _chat_completions_api(self, prompt_text: str) -> str:
        kwargs = {}

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": prompt_text},
            ],
            **kwargs,
        )
        if not response.choices:
            return ""

        message = response.choices[0].message
        content = message.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(getattr(item, "text", "") or getattr(item, "content", "") or ""))
            return "\n".join(part for part in parts if part)
        return str(content or "")

    def _gemini_rest_api(self, prompt_text: str, enable_google_search: bool = False) -> str:
        payload = {
            "systemInstruction": {
                "parts": [{"text": _system_prompt()}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt_text}],
                }
            ],
            "generationConfig": {
                "temperature": 0.35,
                "topP": 0.9,
            },
        }
        if enable_google_search:
            payload["tools"] = [{"google_search": {}}]

        models = (self._model,)
        if self._model == "gemini-2.5-flash":
            models = GEMINI_FALLBACK_MODELS

        last_error = ""
        for model in models:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/{model}:generateContent"
            )
            network_error = False
            for attempt in range(3):
                try:
                    response = self._requests.post(
                        url,
                        params={"key": self._api_key},
                        json=payload,
                        proxies=_requests_proxies(),
                        timeout=self._timeout,
                    )
                except Exception as exc:
                    network_error = True
                    last_error = _redact_sensitive_text(str(exc))
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if response.status_code < 400:
                    data = response.json()
                    return _gemini_response_text(data)

                last_error = _safe_http_error(response)
                if response.status_code not in {429, 500, 502, 503, 504}:
                    break
                time.sleep(1.5 * (attempt + 1))

            if network_error and _should_try_gemini_direct_fallback():
                direct_error = self._try_gemini_direct(url, payload)
                if direct_error.startswith("__OK__:"):
                    return direct_error.removeprefix("__OK__:")
                last_error = direct_error

        raise AiAdvisorError(f"GEMINI API 请求失败: {last_error}")

    def _try_gemini_direct(self, url: str, payload: dict) -> str:
        last_error = ""
        for attempt in range(2):
            try:
                response = self._requests.post(
                    url,
                    params={"key": self._api_key},
                    json=payload,
                    proxies={"http": "", "https": ""},
                    timeout=min(self._timeout, 60),
                )
            except Exception as exc:
                last_error = _redact_sensitive_text(str(exc))
                time.sleep(1.5 * (attempt + 1))
                continue

            if response.status_code < 400:
                data = response.json()
                return "__OK__:" + _gemini_response_text(data)

            last_error = _safe_http_error(response)
            if response.status_code not in {429, 500, 502, 503, 504}:
                break
        return f"代理连接失败后尝试直连也失败: {last_error}"

    @staticmethod
    def _resolve_provider(provider: Provider) -> Literal["openai", "gemini", "deepseek"]:
        if provider != "auto":
            return provider
        if os.getenv("GEMINI_API_KEY"):
            return "gemini"
        if os.getenv("DEEPSEEK_API_KEY"):
            return "deepseek"
        if os.getenv("OPENAI_API_KEY"):
            return "openai"
        raise AiAdvisorError(
            "没有找到可用 AI API key。请设置 OPENAI_API_KEY、GEMINI_API_KEY 或 DEEPSEEK_API_KEY。"
        )

    @staticmethod
    def _api_key_for(provider: str) -> str | None:
        if provider == "openai":
            return os.getenv("OPENAI_API_KEY")
        if provider == "gemini":
            return os.getenv("GEMINI_API_KEY")
        if provider == "deepseek":
            return os.getenv("DEEPSEEK_API_KEY")
        return None

    @staticmethod
    def _base_url_for(provider: str) -> str | None:
        if provider == "gemini":
            return "https://generativelanguage.googleapis.com/v1beta/openai/"
        if provider == "deepseek":
            return "https://api.deepseek.com"
        return None

    @staticmethod
    def _build_http_client(httpx_module, timeout: float):
        ai_proxy = os.getenv("AI_PROXY")
        if ai_proxy:
            return httpx_module.Client(proxy=ai_proxy, timeout=timeout, trust_env=False)

        use_system_proxy = os.getenv("AI_USE_SYSTEM_PROXY", "true").strip().lower()
        if use_system_proxy in {"0", "false", "no", "off"}:
            return httpx_module.Client(timeout=timeout, trust_env=False)

        return None


def _system_prompt() -> str:
    return (
        "你是一个谨慎、专业、重视风险收益比的股票、ETF和期货投研助手。"
        "你的目标不是预测神准，而是帮助用户建立优秀投资者的决策流程。"
        "你可以给出概率化趋势判断、仓位建议和交易计划，但不能承诺收益，也不能把建议包装成确定性指令。"
    )


def _asset_specific_framework(asset_type: str) -> dict:
    if asset_type == "stock":
        return {
            "name": "股票100分质量评分",
            "dimensions": [
                {"name": "盈利能力", "points": 20, "focus": "毛利率、净利率、ROE、ROA，判断赚钱能力是否稳定。"},
                {"name": "成长能力", "points": 20, "focus": "营收增长率、净利润增长率、扣非净利润增长率、EPS增长率，判断增长质量。"},
                {"name": "现金流质量", "points": 15, "focus": "经营现金流、自由现金流、经营现金流/净利润、应收账款和存货变化，判断利润是否真实。"},
                {"name": "估值水平", "points": 20, "focus": "PE、PB、PS、PEG、股息率、历史估值分位和同行估值，判断价格是否合理。"},
                {"name": "财务安全", "points": 10, "focus": "资产负债率、有息负债、现金短债比、利息保障倍数，判断财务风险。"},
                {"name": "行业与竞争", "points": 10, "focus": "行业景气度、竞争格局、公司市场地位、政策风险和周期位置。"},
                {"name": "技术面与市场情绪", "points": 5, "focus": "均线趋势、成交量、相对强弱、波动率、资金流向，辅助判断买卖时机。"},
            ],
        }
    if asset_type == "futures":
        return {
            "name": "期货驱动因素评分",
            "dimensions": [
                "趋势动量和关键价位",
                "成交量与持仓量变化",
                "现货价格与基差",
                "库存、仓单和产业供需",
                "产业新闻与政策变化",
                "期限结构和主力合约切换",
                "杠杆、保证金、隔夜跳空风险",
            ],
        }
    return {
        "name": "ETF质量与交易评分",
        "dimensions": [
            "跟踪指数方向与市场风格",
            "成分行业景气度",
            "成交额与流动性",
            "折溢价/IOPV可用性",
            "集中度和成分风险",
            "技术面与资金情绪",
        ],
    }


def _friendly_ai_error(exc: Exception, provider: str) -> str:
    message = _redact_sensitive_text(str(exc))
    name = provider.upper()
    proxy_names = ("AI_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
    has_proxy = any(os.getenv(item) for item in proxy_names)
    if "insufficient_quota" in message:
        return f"{name} API 额度不足或账单未启用。请检查控制台 Billing/Usage。"
    if "rate_limit" in message or "Error code: 429" in message:
        return f"{name} API 触发限流或额度限制。请稍后重试，或换模型/项目/API key。"
    if "timed out" in message.lower() or "timeout" in message.lower():
        return f"{name} API 请求超时。可以尝试 --ai-timeout 300，或检查代理/网络。"
    if "401" in message or "invalid_api_key" in message or "API key not valid" in message:
        return f"{name} API key 无效。请重新设置对应环境变量。"
    if "Connection error" in message or "ConnectError" in message or "EOF occurred" in message:
        hint = (
            "检测到本机配置了代理环境变量。请确认代理软件已启动、端口正确；"
            "也可以在 .env 中设置 AI_PROXY=http://127.0.0.1:你的端口，"
            "或设置 AI_USE_SYSTEM_PROXY=false 尝试直连。"
            if has_proxy
            else "请检查网络是否能访问 Gemini/OpenAI/DeepSeek API 域名；如需要代理，请在 .env 中设置 AI_PROXY。"
        )
        return f"{name} API 连接失败。{hint} 原始错误: {message}"
    if "ProxyError" in message or "ConnectTimeout" in message:
        proxy = os.getenv("AI_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or ""
        parsed = urlparse(proxy)
        proxy_hint = f"当前代理: {parsed.hostname}:{parsed.port}" if parsed.hostname else "当前未识别到代理地址"
        return f"{name} API 代理连接失败。{proxy_hint}。请确认代理软件已启动并允许访问 Google/Gemini。原始错误: {message}"
    return f"{name} API 请求失败: {message}"


def _redact_sensitive_text(value: str) -> str:
    text = value or ""
    text = re.sub(r"([?&]key=)[^&\s)'\"]+", r"\1***", text)
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9._\-]+", r"\1***", text)
    text = re.sub(r"sk-[A-Za-z0-9_\-]{12,}", "sk-***", text)
    text = re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "AIza***", text)

    for env_name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY"):
        secret = os.getenv(env_name)
        if secret:
            text = text.replace(secret, f"{env_name}=***")
    return text


def _requests_proxies() -> dict[str, str] | None:
    ai_proxy = os.getenv("AI_PROXY")
    if ai_proxy:
        return {"http": ai_proxy, "https": ai_proxy}

    use_system_proxy = os.getenv("AI_USE_SYSTEM_PROXY", "true").strip().lower()
    if use_system_proxy in {"0", "false", "no", "off"}:
        return {"http": "", "https": ""}
    return None


def _should_try_gemini_direct_fallback() -> bool:
    value = os.getenv("GEMINI_DIRECT_FALLBACK", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _text_requests_search(text: str | None) -> bool:
    if not text:
        return False
    keywords = (
        "搜索",
        "查",
        "查询",
        "核实",
        "最新",
        "新闻",
        "仓单",
        "库存",
        "仓储",
        "现货",
        "基差",
        "持仓",
        "6.1",
        "6月1",
    )
    return any(keyword in text for keyword in keywords)


def _target_date_instruction(text: str | None) -> dict:
    value = (text or "").strip()
    if not value:
        return {"has_target_date": False}

    current_year = date.today().year
    patterns = (
        r"(?P<year>20\d{2})[./年-]\s*(?P<month>\d{1,2})[./月-]\s*(?P<day>\d{1,2})\s*(?:日)?",
        r"(?P<month>\d{1,2})[./月-]\s*(?P<day>\d{1,2})\s*(?:日)?",
    )
    for pattern in patterns:
        match = re.search(pattern, value)
        if not match:
            continue
        year = int(match.groupdict().get("year") or current_year)
        month = int(match.group("month"))
        day = int(match.group("day"))
        try:
            target = date(year, month, day)
        except ValueError:
            continue
        return {
            "has_target_date": True,
            "target_date": target.isoformat(),
            "raw_text": match.group(0),
            "instruction": (
                "本次报告主题必须围绕该目标日期预测。"
                "当前行情和K线只代表数据截面，不能把报告主题写成今天。"
            ),
        }
    return {"has_target_date": False}


def _should_enable_gemini_search_grounding() -> bool:
    value = os.getenv("GEMINI_SEARCH_GROUNDING", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _interactive_search_instruction(enabled: bool) -> dict:
    if enabled:
        return {
            "enabled": True,
            "tool": "Gemini Grounding with Google Search",
            "instruction": (
                "本次追问已启用 Gemini 内置 Google Search 工具。"
                "当用户要求搜索、核实、补充最新库存/仓单/仓储量/现货/基差/新闻时，"
                "你应自己调用搜索工具，并基于搜索来源回答。"
            ),
            "preferred_sources_for_china_futures": [
                "广期所/交易所公告",
                "SMM上海有色",
                "Mysteel",
                "生意社",
                "东方财富期货资讯",
                "期货公司研报",
            ],
        }
    return {
        "enabled": False,
        "instruction": "本次未启用模型搜索工具，只能基于 analysis_payload 中已有数据回答。",
    }


def _missing_data_search_instruction(result: AnalysisResult) -> dict:
    items = _collect_missing_items(result)
    searchable = [item for item in items if _is_searchable_missing_item(item)]
    non_searchable = [item for item in items if item not in searchable]
    queries = _missing_data_queries(result, searchable)
    return {
        "should_search": bool(searchable),
        "searchable_missing_items": searchable[:8],
        "non_searchable_missing_items": non_searchable[:6],
        "suggested_queries": queries[:8],
        "instruction": (
            "这些缺失项适合用 Gemini Google Search grounding 补充。"
            "请优先搜索官方交易所、SMM、Mysteel、生意社、东方财富、财联社、期货公司研报等来源，"
            "并说明搜索结果是否足以补齐底稿。"
            if searchable
            else "本次没有发现适合用网页搜索自动补齐的关键缺失项。"
        ),
    }


def _collect_missing_items(result: AnalysisResult) -> list[str]:
    items: list[str] = []
    fundamental = result.fundamental_data or {}

    def add(value) -> None:
        if value is None:
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                add(item)
            return
        text = str(value).strip()
        if text:
            items.append(text)

    add(fundamental.get("missing_or_failed"))
    for key in ("professional_context",):
        context = fundamental.get(key) or {}
        if isinstance(context, dict):
            basis = context.get("basis_summary") or {}
            if isinstance(basis, dict) and basis.get("available") is False:
                add(basis.get("instruction"))
    for warning in result.warnings:
        add(warning)

    deduped = []
    seen = set()
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _is_searchable_missing_item(item: str) -> bool:
    text = item.lower()
    positive = (
        "仓单",
        "库存",
        "仓储",
        "现货",
        "基差",
        "升贴水",
        "产业",
        "供需",
        "新闻",
        "公告",
        "研报",
        "持仓排名",
        "席位",
        "etf持仓",
        "行业配置",
        "iopv",
        "折溢价",
    )
    negative = (
        "分钟线",
        "实时行情获取失败",
        "盘中预测降级",
        "api",
        "connection",
        "remote disconnected",
        "timeout",
    )
    return any(word in text for word in positive) and not any(word in text for word in negative)


def _missing_data_queries(result: AnalysisResult, searchable_items: list[str]) -> list[str]:
    if not searchable_items:
        return []
    symbol = result.quote.symbol
    name = result.quote.name
    asset_type = result.quote.asset_type
    queries = []
    if asset_type == "futures":
        root = "".join(char for char in symbol.upper() if char.isalpha())
        base = f"{symbol} {name}".strip()
        queries.extend(
            [
                f"{base} 仓单 库存 最新",
                f"{base} 现货 基差 最新",
                f"{root} 期货 仓单 库存 广期所",
                f"SMM {name} 库存",
                f"Mysteel {name} 库存",
            ]
        )
    elif asset_type == "etf":
        queries.extend([f"{symbol} {name} IOPV 折溢价", f"{symbol} {name} 持仓 行业配置"])
    else:
        queries.extend([f"{symbol} {name} 财报 估值 现金流", f"{symbol} {name} 最新公告 新闻"])

    for item in searchable_items[:3]:
        queries.append(f"{symbol} {name} {item[:24]}")
    return list(dict.fromkeys(query for query in queries if query.strip()))


def _gemini_response_text(data: dict) -> str:
    parts: list[str] = []
    grounding_chunks: list[dict] = []
    search_queries: list[str] = []

    for candidate in data.get("candidates", []):
        content = candidate.get("content") or {}
        for part in content.get("parts", []):
            text = part.get("text")
            if text:
                parts.append(text)

        metadata = candidate.get("groundingMetadata") or candidate.get("grounding_metadata") or {}
        search_queries.extend(str(item) for item in metadata.get("webSearchQueries", []) if item)
        grounding_chunks.extend(metadata.get("groundingChunks", []) or [])

    summary = _grounding_summary(search_queries, grounding_chunks)
    if summary:
        parts.append(summary)
    return "\n".join(parts)


def _grounding_summary(search_queries: list[str], grounding_chunks: list[dict]) -> str:
    unique_queries = list(dict.fromkeys(query.strip() for query in search_queries if query.strip()))
    sources = []
    seen_urls: set[str] = set()
    for chunk in grounding_chunks:
        web = chunk.get("web") or {}
        url = str(web.get("uri") or "").strip()
        title = str(web.get("title") or url or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        sources.append((title, url))
        if len(sources) >= 8:
            break

    if not unique_queries and not sources:
        return ""

    lines = ["", "---", "搜索依据（Gemini Google Search）:"]
    if unique_queries:
        lines.append("搜索词:")
        lines.extend(f"- {query}" for query in unique_queries[:8])
    if sources:
        lines.append("来源:")
        lines.extend(f"- [{title}]({url})" for title, url in sources)
    return "\n".join(lines)


def _safe_http_error(response) -> str:
    try:
        payload = response.json()
        message = payload.get("error", {}).get("message") or payload
    except ValueError:
        message = response.text[:500]
    return _redact_sensitive_text(f"HTTP {response.status_code}: {message}")


def _analysis_payload(result: AnalysisResult) -> dict:
    return {
        "symbol": result.quote.symbol,
        "name": result.quote.name,
        "asset_type": result.quote.asset_type,
        "price": result.quote.price,
        "change_pct": result.quote.change_pct,
        "data_source": result.data_source,
        "market_phase": result.market_phase,
        "trend": result.trend,
        "risk_level": result.risk_level,
        "rule_action": result.action,
        "score": result.score,
        "support_levels": result.support_levels,
        "resistance_levels": result.resistance_levels,
        "rule_prediction": {
            "horizon": result.prediction.horizon,
            "bias": result.prediction.bias,
            "confidence": result.prediction.confidence,
            "summary": result.prediction.summary,
            "strategy": result.prediction.strategy,
            "evidence": result.prediction.evidence,
            "invalidation": result.prediction.invalidation,
            "watch_levels": result.prediction.watch_levels,
        },
        "reasons": result.reasons,
        "warnings": result.warnings,
        "market_data": result.market_data,
        "fundamental_data": result.fundamental_data,
        "stock_news": [
            {
                "title": item.title,
                "source": item.source,
                "published_at": item.published_at,
                "summary": item.summary,
            }
            for item in result.stock_news[:5]
        ],
        "global_news": [
            {
                "title": item.title,
                "source": item.source,
                "published_at": item.published_at,
                "summary": item.summary,
            }
            for item in result.global_news[:8]
        ],
    }


def _follow_up_prompt(
    result: AnalysisResult,
    user_question: str,
    report_depth: str,
    enable_search: bool,
) -> dict:
    return {
        "task": "这是用户在完整报告之后的继续追问。请直接解决用户的新问题，不要重新套完整投资报告模板。",
        "user_question": user_question,
        "target_date_instruction": _target_date_instruction(user_question),
        "report_depth": report_depth,
        "interactive_search_instruction": _interactive_search_instruction(enable_search),
        "current_context": _compact_follow_up_context(result),
        "answer_rules": [
            "优先回答用户这次问的具体问题，不要机械输出“一句话结论/趋势结构/仓位建议”等完整报告模板，除非用户明确要求重新完整分析。",
            "如果用户要求你搜索、查找、核实、补充仓单/库存/仓储量/现货/基差/新闻等最新信息，且搜索工具已启用，你必须自己使用搜索工具核实。",
            "搜索后必须写清楚：你搜索到的数据是什么、数据日期是什么、来源链接是什么、来源可信度如何。",
            "如果搜索结果之间冲突，不要强行给唯一答案；请列出不同来源并说明哪个更可信。",
            "如果搜索后仍找不到可靠数据，要说明你搜索了哪些方向，并给出下一步应该查的官方或专业来源。",
            "回答要像专业投资助手：先给结论，再给证据，再说对原交易判断的影响。",
            "不要说“输入数据缺失所以无法分析”就结束；如果搜索工具可用，应先尝试搜索。",
            "不要承诺收益，不要把搜索结果当成单一买卖信号。",
        ],
    }


def _compact_follow_up_context(result: AnalysisResult) -> dict:
    fundamental = result.fundamental_data or {}
    professional = fundamental.get("professional_context") or {}
    quant = fundamental.get("quant_context") or {}
    signal = quant.get("signal") or {}
    return {
        "symbol": result.quote.symbol,
        "name": result.quote.name,
        "asset_type": result.quote.asset_type,
        "price": result.quote.price,
        "change_pct": result.quote.change_pct,
        "market_phase": result.market_phase,
        "data_source": result.data_source,
        "trend": result.trend,
        "risk_level": result.risk_level,
        "score": result.score,
        "support_levels": result.support_levels,
        "resistance_levels": result.resistance_levels,
        "prediction": {
            "horizon": result.prediction.horizon,
            "bias": result.prediction.bias,
            "confidence": result.prediction.confidence,
            "strategy": result.prediction.strategy,
            "invalidation": result.prediction.invalidation,
        },
        "warnings": result.warnings,
        "known_missing_or_failed": fundamental.get("missing_or_failed", []),
        "futures_basis_summary": professional.get("basis_summary"),
        "futures_position_summary": professional.get("position_summary"),
        "professional_level_plan": professional.get("level_plan"),
        "quant_summary": {
            "available": quant.get("available"),
            "signal": signal.get("label"),
            "factor_score": quant.get("factor_score"),
            "confidence": quant.get("confidence"),
            "event_backtest_interpretation": (quant.get("event_backtest") or {}).get("interpretation"),
            "strategy_backtest_interpretation": (quant.get("strategy_backtest") or {}).get("interpretation"),
        },
        "recent_news": [
            {
                "title": item.title,
                "source": item.source,
                "published_at": item.published_at,
                "url": item.url,
            }
            for item in result.stock_news[:5]
        ],
    }
