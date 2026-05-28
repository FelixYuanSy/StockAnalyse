# 代码逐文件讲解

这份文档专门给 Python 基础一般、但想真正看懂项目的人准备。它不会假设你已经熟悉正式项目结构，会尽量用普通语言解释“这段代码为什么存在、负责什么、上下游是谁”。

建议你打开两个窗口：左边打开代码文件，右边打开这份文档。按顺序读，不要急着背语法，先理解数据怎么流动。

## 0. 项目主线

一次完整分析大概是这样：

```text
输入代码
  -> 识别股票 / ETF / 期货
  -> 获取行情、K线、新闻、基本面或期货数据
  -> 计算技术指标
  -> 整理专业投研上下文
  -> 交给 AI 生成报告
  -> 网页展示，并生成 HTML 报告
```

对应代码：

```text
web_app.py / main.py
  -> instrument_parser.py
  -> data_provider.py + news_searcher.py
  -> analyzer.py + indicators.py
  -> professional.py
  -> ai_advisor.py
  -> charting.py + html_report.py + report.py
```

## 1. `main.py`

`main.py` 是 CLI 入口，也是通用分析流程的核心。你可以把它理解成“项目导演”：它自己不负责具体数据接口，也不负责画图，而是把所有模块按顺序串起来。

### import 区域

文件开头导入的模块，基本就是项目地图：

- `argparse`：解析命令行参数。
- `sys`：让程序可以用 `sys.exit()` 返回退出码。
- `Path`：处理文件路径。
- `AiAdvisor`：调用 AI。
- `StockAnalyzer`：计算指标和分析底稿。
- `AkshareDataProvider`：获取行情数据。
- `generate_html_report`：生成 HTML 报告。
- `parse_instrument_input`：识别输入代码。
- `china_market_phase`：判断盘中、盘后、休市。

### `parse_args()`

这个函数负责读取命令行参数。例如：

```powershell
.\.venv\Scripts\python main.py futures:LC2609 --ai-provider gemini --days 120
```

它会把命令整理成程序能用的配置：

- `symbol`：标的代码。
- `--asset`：资产类型。
- `--days`：历史 K 线天数。
- `--once`：分析一次后退出。
- `--no-ai`：不调用 AI。
- `--report` / `--no-report`：是否生成 HTML 报告。
- `--ai-provider`：选择 Gemini、DeepSeek 或 OpenAI。

新手理解：它只负责“把命令行文字变成配置对象”。

### `analyze_symbol()`

这是最重要的函数之一。它完成一次标的分析的数据准备。

大致步骤：

1. 用 `parse_instrument_input(symbol)` 解析输入，例如 `futures:LC2609`。
2. 用 `provider.resolve_asset_type()` 确认资产类型。
3. 用 `provider.get_daily_history()` 获取历史 K 线。
4. 用 `china_market_phase()` 判断盘中、盘后或休市。
5. 尝试获取实时行情。
6. 如果实时行情失败，就用最新日线数据兜底。
7. 盘中时尝试获取分钟线。
8. 获取 AKShare 新闻。
9. 使用 `WebNewsSearcher` 搜索网页新闻。
10. 获取股票基本面或期货现货、基差、持仓数据。
11. 调用 `build_professional_context()` 生成专业上下文。
12. 盘后获取全球市场新闻。
13. 调用 `analyzer.analyze()` 生成 `AnalysisResult`。

你可以把它理解成：

```text
analyze_symbol = 一次分析的数据流水线
```

### `interactive_loop()`

这是 CLI 连续问答模式。它解决的问题是：分析完一个标的后，用户还能继续输入新代码或追问。

逻辑：

1. 没有当前代码时，让用户输入。
2. 输入 `q` 就退出。
3. 输入像新标的，就重新分析。
4. 输入普通问题，就把问题和当前分析结果一起发给 AI。

### `_build_advisor()`

创建 AI 对象。如果用户用了 `--no-ai`，它返回 `None`。否则创建 `AiAdvisor`。如果没有配置 key，就打印提示。

### `_merge_news()`

把两组新闻合并，并去重。去重规则：

- 优先用 URL。
- 没有 URL 时用标题。
- 最多保留 `limit` 条。

### `_get_ai_advice()`

真正调用 AI：

```python
advisor.advise(result, user_question=question, report_depth=report_depth)
```

如果 AI 调用失败，它不会让程序直接崩掉，而是返回一段“已获取数据底稿”的错误说明。

### `_write_report()`

调用 `generate_html_report()` 生成 HTML 报告。

### `_load_dotenv()`

读取 `.env` 文件，让程序拿到 Gemini、DeepSeek、OpenAI key 和代理配置。

### `main()`

CLI 真正入口。它负责：

1. 读取 `.env`。
2. 解析参数。
3. 创建数据提供者。
4. 创建分析器。
5. 创建 AI advisor。
6. 如果是 `--once`，只分析一次。
7. 否则进入连续问答模式。

## 2. `web_app.py`

`web_app.py` 是网页入口，使用 Streamlit。它让你不用每次在 PowerShell 里敲命令。

### `ASSET_LABELS`

把程序内部英文值显示成中文：

```python
"auto" -> "自动识别"
"stock" -> "股票"
"etf" -> "ETF"
"futures" -> "期货"
```

### `main()`

网页主函数。它做这些事：

1. 读取 `.env`。
2. 设置页面标题和布局。
3. 在侧边栏显示输入控件。
4. 等用户点击“生成分析”。
5. 校验代码格式。
6. 创建 `AkshareDataProvider` 和 `StockAnalyzer`。
7. 调用 `analyze_symbol()` 获取分析结果。
8. 创建 `AiAdvisor`。
9. 调用 AI 生成报告。
10. 展示指标卡片、AI 报告、新闻链接、图表。
11. 生成 HTML 报告并提供下载。

重点理解：网页层只负责“收集用户输入 + 展示结果”，不应该塞太多投资逻辑。

### `_render_news_links()`

把新闻展示到网页上。它从两个地方拿新闻：

- `result.fundamental_data["web_news"]`
- `result.stock_news` 和 `result.global_news`

然后去重，显示标题、来源、时间、摘要和原文按钮。

### `_domain()`

从 URL 中提取域名，例如把 `https://finance.sina.com.cn/...` 提取成 `finance.sina.com.cn`。

## 3. `stock_analyse/models.py`

这个文件定义核心数据结构。所有模块都围绕这些对象传数据。

### `AssetType`

资产类型只能是：

- `stock`
- `etf`
- `futures`

这样可以减少拼写错误。

### `NewsItem`

新闻对象，包含：

- `title`：标题。
- `source`：来源。
- `published_at`：发布时间。
- `summary`：摘要。
- `url`：链接。

### `Prediction`

预测对象，包含：

- `horizon`：预测周期。
- `bias`：偏多、偏空、震荡。
- `confidence`：置信度。
- `summary`：摘要。
- `strategy`：执行建议。
- `evidence`：依据。
- `invalidation`：失效条件。
- `watch_levels`：观察位。

### `StockQuote`

行情快照，包含代码、名称、资产类型、价格、涨跌幅、成交量、换手率。

虽然名字叫 `StockQuote`，但当前也用于 ETF 和期货。

### `AnalysisResult`

一次完整分析的结果。它包含：

- 行情 `quote`
- 数据来源 `data_source`
- 市场状态 `market_phase`
- 趋势 `trend`
- 风险等级 `risk_level`
- 操作建议 `action`
- 综合评分 `score`
- 支撑压力
- 预测对象 `prediction`
- 分析理由
- 风险提示
- 新闻
- K 线和指标底稿 `market_data`
- 基本面或期货专业数据 `fundamental_data`

你读其他文件时，只要看到 `result`，大概率就是 `AnalysisResult`。

## 4. `stock_analyse/instrument_parser.py`

这个文件负责识别用户输入。

### `ASSET_ALIASES`

资产类型别名字典。例如 `stock`、`a`、`etf`、`futures`、`qh` 等最终会映射到标准资产类型。

### `InstrumentInput`

一个小数据结构：

- `symbol`：代码。
- `asset`：资产类型，可以为空。

例如 `futures:LC2609` 会解析成：

```text
symbol = LC2609
asset = futures
```

### `parse_instrument_input()`

如果输入里有冒号，就尝试按“资产类型:代码”解析；如果没有冒号，就只返回代码。

### `is_instrument_text()`

检查输入是否像一个有效标的。它允许：

- 6 位数字，例如 `600519`
- 字母和数字组合，例如 `LC2609`

### `asset_to_cli_value()`

如果用户输入里已经带了资产类型，就优先使用用户输入的类型；否则使用默认值。

## 5. `stock_analyse/market.py`

这个文件判断当前中国市场状态。

### `china_market_phase()`

逻辑：

- 周六周日：休市。
- 9:30 到 11:30：盘中。
- 13:00 到 15:00：盘中。
- 15:00 后：盘后。
- 其他时间：休市。

这个结果会影响是否获取分钟线，以及 AI 报告偏“盘中下一段”还是“明日建议”。

## 6. `stock_analyse/indicators.py`

这个文件计算技术指标，是最适合新手练习的文件之一。

### `add_indicators()`

输入是一张 K 线表 `df`，输出是加了指标的新表。它会计算：

- `ma5`
- `ma10`
- `ma20`
- `ma60`
- `volume_ma5`
- `volume_ma20`
- `rsi14`
- `macd`
- `macd_signal`
- `macd_hist`
- `boll_mid`
- `boll_upper`
- `boll_lower`

关键点：

```python
data = df.copy()
```

意思是复制一份数据，避免直接修改原始 K 线。

### `rsi()`

RSI 是强弱指标。基本思路：

1. 计算每天涨跌变化。
2. 涨的部分叫 `gain`。
3. 跌的部分叫 `loss`。
4. 计算平均涨幅和平均跌幅。
5. 转换成 0 到 100 的 RSI。

一般理解：

- RSI 太高：可能过热。
- RSI 太低：可能超跌，但不代表一定反弹。

### `macd()`

MACD 用指数均线计算动量。它返回：

- `macd_line`
- `signal_line`
- `histogram`

项目里主要看 `macd_hist`：大于 0 偏强，小于 0 偏弱。

## 7. `stock_analyse/data_provider.py`

这是项目最复杂的文件，因为它负责所有外部数据。不要一次读完，建议按函数块读。

### `DataProviderError`

自定义错误类型。数据获取失败时抛出它，上层可以捕获并给用户友好提示。

### `AkshareDataProvider.__init__()`

初始化时导入 AKShare。如果没安装，就提示安装依赖。

### `resolve_asset_type()`

判断资产类型：

- 用户明确传 `stock/etf/futures`，就直接用。
- 代码里有字母，大概率是期货。
- 代码像 ETF，就判断为 ETF。
- 其他 6 位数字默认股票。

### `get_realtime_quote()`

获取实时行情。不同资产走不同接口：

- 股票：`stock_zh_a_spot_em`
- ETF：`fund_etf_spot_em`
- 期货：`_get_futures_realtime_quote`

拿到数据后整理成统一的 `StockQuote`。

### `get_daily_history()`

获取历史日线。重点逻辑：

1. 优先调用主接口 `_history_primary()`。
2. 如果失败，调用备用接口 `_history_fallback()`。
3. 把不同接口字段统一成 `date/open/close/high/low/volume`。
4. 检查字段是否齐全。
5. 转成数字。
6. 少于 60 条有效数据就报错。

统一字段很重要，因为后面的分析器不想关心数据来自股票、ETF 还是期货。

### `get_intraday_history()`

获取分钟线。盘中分析时更有价值。如果分钟线失败，程序会降级为日线分析。

### `get_global_news()`

获取全球财经新闻，用于盘后或休市时作为市场背景。

### `get_stock_news()`

根据资产类型获取新闻：

- 期货：走 `_get_futures_news()`。
- ETF：走市场新闻。
- 股票：走个股新闻接口。

### `get_fundamental_data()`

根据资产类型获取增强数据：

- 股票：财务、估值、同行。
- ETF：ETF 相关基础数据。
- 期货：现货、基差、结算、持仓排名。

### `_get_stock_fundamental_data()`

股票基本面数据，包括公司信息、财务摘要、财务指标、历史估值、同行估值。

### `_get_futures_fundamental_data()`

期货增强数据，包括现货/基差、结算数据、成交排名、多单排名、空单排名。

### `_get_recent_futures_spot_basis()`

向前查最近几天的现货和基差数据。因为当天数据可能还没更新，所以需要向前找。

### `_get_recent_futures_settlement()`

获取最近结算数据，并过滤到当前合约，例如 `LC2609`。

### `_get_recent_futures_hold_rank()`

获取期货持仓排名。注意：席位排名不等于某家公司自己的观点，只能作为线索。

### `_history_primary()` 和 `_history_fallback()`

主接口和备用接口。外部接口不稳定，所以要准备 fallback。

### `quote_from_history()`

实时行情失败时，用最新一根日线生成行情快照，让程序至少还能给出兜底分析。

### `_normalize_symbol()`

把用户输入整理成接口需要的格式。例如期货通常转大写。

### `_network_context()`

处理代理环境，避免 AKShare 请求被不合适的代理影响。

## 8. `stock_analyse/news_searcher.py`

这个文件负责免费网页新闻搜索。

### `WebNewsSearchError`

新闻搜索失败时使用的自定义错误。

### `WebNewsSearcher.__init__()`

设置请求超时时间。默认超时短一些，是为了避免新闻搜索卡太久。

### `search()`

主搜索函数。步骤：

1. 根据代码、名称和资产类型生成关键词。
2. 生成搜索 query。
3. 请求多个免费新闻源。
4. 收集新闻。
5. 去重、过滤、排序。
6. 返回 `NewsItem` 列表。

### `_bing_news_rss()` / `_google_news_rss()`

从 Bing News RSS 或 Google News RSS 读取新闻。RSS 可以理解成网站提供的“机器可读新闻列表”。

### `_gdelt_news()`

从 GDELT 免费公开新闻数据源搜索新闻。

### `_keywords()`

根据资产类型生成关键词。例如期货 `LC2609` 会关注碳酸锂、锂矿、锂电池、新能源车、广期所等。

### `_filter_and_rank()`

过滤和排序新闻，减少重复、过旧、弱相关的新闻。

## 9. `stock_analyse/analyzer.py`

这个文件把行情和 K 线整理成本地分析结果。

### `StockAnalyzer.analyze()`

核心函数。流程：

1. 调用 `add_indicators(history)` 增加技术指标。
2. 取最新一根 K 线和前一根 K 线。
3. 从 45 分中性基准开始评分。
4. 加上趋势评分。
5. 加上动量评分。
6. 加上成交量评分。
7. 加上布林带评分。
8. 加上新闻评分。
9. 计算支撑位和压力位。
10. 生成趋势标签、风险等级、操作建议。
11. 生成下一阶段预测。
12. 打包成 `AnalysisResult`。

### `_trend_score()`

根据均线判断趋势。多头排列加分，跌破 MA20 且 MA20 低于 MA60 扣分。

### `_momentum_score()`

根据 MACD 和 RSI 判断动量。MACD 柱体为正偏强，为负偏弱；RSI 过高提示追高风险，过低提示弱势和反弹都可能出现。

### `_volume_score()`

看成交量是否支持价格变化。放量上涨加分，放量下跌扣分，量能不足提示趋势确认度一般。

### `_bollinger_score()`

用布林带判断价格位置和波动。突破上轨短线强但风险也变大；跌破下轨说明风险释放但趋势弱。

### `_prediction()`

生成下一阶段预测。它综合评分、分钟线、新闻、支撑压力，输出偏多/偏空、置信度、策略和失效条件。

### `_intraday_score()`

盘中使用，根据分钟线判断短线动量。

### `_news_score()`

简单新闻情绪评分。它不是深度 NLP，只是本地规则辅助。

### `_trend_label()` / `_risk_level()` / `_action()`

把分数转换成中文结论：趋势判断、风险等级、操作建议。

## 10. `stock_analyse/professional.py`

这是专业投研增强层，让 AI 不只是看 K 线。

### `build_professional_context()`

主函数。通用内容包括数据时间警告、新闻相关性；期货额外包括基差总结、持仓总结、多空交易计划。

### `_data_time_warning()`

检查实时价格和最新 K 线收盘价是否差异较大。如果差异大，AI 需要提醒数据可能来自不同时间点。

### `_basis_summary()`

整理期货现货和基差。基差大致是：

```text
期货价格 - 现货价格
```

它能帮助判断市场预期和期限结构。

### `_position_summary()`

聚合持仓排名，包括成交、多单、空单、净多或净空倾向。

### `_level_plan()`

生成多空计划，包括入场价、止损价、目标价、风险点数、收益点数和风险收益比。

### `_news_relevance()`

把新闻分成强相关、弱相关、背景新闻，避免 AI 硬套无关新闻。

### `_risk_reward()`

计算风险收益比。做多时：

```text
风险 = 入场价 - 止损价
收益 = 目标价 - 入场价
```

## 11. `stock_analyse/ai_advisor.py`

这个文件负责调用 AI，也是报告质量最关键的文件之一。

### `AiAdvisorError`

AI 调用失败时使用的错误类型。

### `AiAdvisor.__init__()`

初始化 AI 顾问，决定 provider、模型、API key、base URL 和超时时间。

### `provider` 和 `model`

属性方法，让外部可以读取当前使用的 AI provider 和模型。

### `advise()`

调用 AI 的主函数。它会：

1. 把 `AnalysisResult` 转成 payload。
2. 加上用户追问。
3. 加上报告深度。
4. 加上系统提示词。
5. 根据 provider 调用不同 API。
6. 返回 AI 文本。

### `_responses_api()`

OpenAI Responses API 调用方式。

### `_chat_completions_api()`

OpenAI-compatible API 调用方式，DeepSeek 主要走这种形式。

### `_gemini_rest_api()`

Gemini 官方 REST API 调用方式。它比 Gemini OpenAI-compatible 接口更稳定。

### `_resolve_provider()`

如果用户选择 `auto`，它会按可用 key 自动选择 provider。

### `_api_key_for()`

根据 provider 读取对应环境变量：

- Gemini：`GEMINI_API_KEY`
- DeepSeek：`DEEPSEEK_API_KEY`
- OpenAI：`OPENAI_API_KEY`

### `_system_prompt()`

系统提示词。它告诉 AI 必须基于数据、说明依据、不能承诺收益，并且不同资产要用不同分析框架。

以后想改变 AI 风格，重点改这里。

### `_asset_specific_framework()`

按资产类型提供不同分析框架：

- 股票看基本面、估值、现金流、行业。
- ETF 看指数、流动性、板块和技术面。
- 期货看趋势、基差、持仓、产业新闻和杠杆风险。

### `_friendly_ai_error()`

把底层错误变成用户能看懂的错误提示，例如 quota 不足、key 错误、连接失败、代理问题。

### `_analysis_payload()`

把 `AnalysisResult` 转成 AI 能读的字典。它包括标的基础信息、技术指标、新闻、基本面数据、专业上下文、支撑压力和风险提示。

## 12. `stock_analyse/charting.py`

这个文件负责生成图表。

### `build_chart_html()`

用 Plotly 生成：

- K 线。
- 均线。
- 成交量。
- MACD。
- RSI。
- 支撑压力。

最后返回 HTML 字符串，网页和报告都可以嵌入。

### `write_html()`

把 HTML 字符串写入文件。

## 13. `stock_analyse/html_report.py`

这个文件生成最终 HTML 报告。

### `generate_html_report()`

主函数。它会：

1. 创建报告目录。
2. 根据标的和时间生成文件名。
3. 调用 `build_chart_html()` 生成图表。
4. 把 AI 文本、图表、新闻链接、数据底稿组合成 HTML。
5. 写入文件并返回路径。

### `_news_links_html()`

生成新闻链接区域。

### `_news_card()`

把一条新闻变成 HTML 卡片，包含标题、来源、时间、摘要和原文链接。

### `_collect_news_groups()`

把新闻分组为强相关新闻、弱相关/背景新闻、市场背景新闻。

### `_link_html()` 和 `_domain()`

生成安全的链接 HTML，并显示域名。

## 14. `stock_analyse/report.py`

这个文件负责 CLI 文本报告。

### `format_report()`

把 `AnalysisResult` 转成命令行可读文本。

### `format_follow_up_help()`

输出追问提示，例如“明天怎么操作”“为什么这么判断”“风险在哪里”。

### `format_follow_up_answer()`

没有 AI 时，用本地规则回答简单追问。

## 15. `tests/test_analyzer.py`

测试文件。它的作用是确认改代码后没有把基础功能弄坏。

当前测试重点：

- 资产类型识别。
- 分析器能否生成结果。
- AI payload 是否包含关键字段。
- HTML 报告是否能生成。

运行测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## 16. `.env.example`

环境变量模板。它不会放真实 key，只告诉你需要哪些配置。真实配置放 `.env`，`.env` 不提交到 GitHub。

## 17. `requirements.txt`

依赖列表。主要依赖：

- `akshare`：获取公开金融数据。
- `pandas`：处理表格数据。
- `numpy`：数值计算。
- `openai`：OpenAI/DeepSeek 兼容调用。
- `python-dotenv`：读取 `.env`。
- `plotly`：画图。
- `streamlit`：本地网页。
- `requests`：HTTP 请求。

## 18. `启动投资分析.bat`

Windows 双击启动脚本。它会切换到项目目录、启动 Streamlit、打开本地网页。

## 19. 新手最容易混淆的点

### `provider` 不一定是 AI provider

项目里有两个 provider：

- `AkshareDataProvider`：数据 provider，负责行情。
- `AiAdvisor(provider="gemini")`：AI provider，负责模型。

### `AnalysisResult` 是核心结果包

很多函数最后都围绕它工作。你看代码时遇到 `result`，大概率就是 `AnalysisResult`。

### `fundamental_data` 不只是股票基本面

期货里也用它装现货/基差、结算数据、持仓排名、网页新闻和专业上下文。

### 本地评分不是最终建议

`analyzer.py` 的分数只是底稿。最终建议由 AI 综合数据、新闻、专业上下文生成。

### 免费数据源一定要复核

代码会尽量抓数据，但不能保证完全准确。报告里的链接就是给你复核用的。

## 20. 推荐读代码路线

第一天：

```text
main.py
web_app.py
models.py
```

目标：知道程序怎么启动、结果怎么包装。

第二天：

```text
instrument_parser.py
market.py
indicators.py
```

目标：理解输入识别、市场状态、技术指标。

第三天：

```text
data_provider.py
news_searcher.py
```

目标：知道数据从哪里来。

第四天：

```text
analyzer.py
professional.py
```

目标：理解分析底稿怎么形成。

第五天：

```text
ai_advisor.py
```

目标：理解 AI prompt 和 provider 调用。

第六天：

```text
charting.py
html_report.py
report.py
```

目标：理解报告怎么展示。

第七天：

```text
tests/test_analyzer.py
```

目标：理解怎么验证代码没坏。

## 21. 最适合新手的改代码练习

### 练习 1：改 AI 输出格式

改：

```text
stock_analyse/ai_advisor.py
```

找 `_system_prompt()` 或资产分析框架。

### 练习 2：新增一个指标

改：

```text
stock_analyse/indicators.py
stock_analyse/analyzer.py
```

例如新增 ATR。

### 练习 3：调整 HTML 报告样式

改：

```text
stock_analyse/html_report.py
```

例如改标题、颜色、新闻区块顺序。

## 22. 最重要的一句话

这个项目不是一堆散乱代码，而是一条流水线。每个文件只负责流水线中的一段。

只要你能说清楚“数据从哪里来、经过哪里处理、最后到哪里展示”，你就已经看懂了这个项目的骨架。
