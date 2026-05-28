from __future__ import annotations

import json
import os
import time
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
    ) -> str:
        payload = _analysis_payload(result)
        prompt = {
            "task": "你是主分析模型。请基于程序收集到的股票、ETF或期货行情、K线、指标、新闻，独立给出下一阶段趋势预测和投资建议。",
            "user_question": user_question or "请给出完整投资分析。",
            "report_depth": report_depth,
            "analysis_payload": payload,
            "asset_specific_framework": _asset_specific_framework(result.quote.asset_type),
            "output_requirements": [
                "必须使用中文，结构清晰，像一位优秀投资者给普通投资者解释。",
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
        prompt_text = json.dumps(prompt, ensure_ascii=False)

        try:
            if self._provider == "gemini":
                text = self._gemini_rest_api(prompt_text)
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

    def _gemini_rest_api(self, prompt_text: str) -> str:
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

        models = (self._model,)
        if self._model == "gemini-2.5-flash":
            models = GEMINI_FALLBACK_MODELS

        last_error = ""
        for model in models:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/{model}:generateContent"
            )
            for attempt in range(3):
                response = self._requests.post(
                    url,
                    params={"key": self._api_key},
                    json=payload,
                    proxies=_requests_proxies(),
                    timeout=self._timeout,
                )
                if response.status_code < 400:
                    data = response.json()
                    parts: list[str] = []
                    for candidate in data.get("candidates", []):
                        content = candidate.get("content") or {}
                        for part in content.get("parts", []):
                            text = part.get("text")
                            if text:
                                parts.append(text)
                    return "\n".join(parts)

                last_error = _safe_http_error(response)
                if response.status_code not in {429, 500, 502, 503, 504}:
                    break
                time.sleep(1.5 * (attempt + 1))

        raise AiAdvisorError(f"GEMINI API 请求失败: {last_error}")

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
    message = str(exc)
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


def _requests_proxies() -> dict[str, str] | None:
    ai_proxy = os.getenv("AI_PROXY")
    if ai_proxy:
        return {"http": ai_proxy, "https": ai_proxy}

    use_system_proxy = os.getenv("AI_USE_SYSTEM_PROXY", "true").strip().lower()
    if use_system_proxy in {"0", "false", "no", "off"}:
        return {"http": "", "https": ""}
    return None


def _safe_http_error(response) -> str:
    try:
        payload = response.json()
        message = payload.get("error", {}).get("message") or payload
    except ValueError:
        message = response.text[:500]
    return f"HTTP {response.status_code}: {message}"


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
