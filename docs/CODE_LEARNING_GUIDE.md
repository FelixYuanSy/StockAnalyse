# 代码学习指南

这份文档的目标不是让你一次性记住所有代码，而是让你能按顺序看懂项目：先知道流程，再知道每个文件负责什么，最后知道以后怎么改。

## 1. 今天建议怎么读

建议用四轮阅读法：

1. 第一轮只看数据流，不纠结语法。
2. 第二轮看每个文件的职责。
3. 第三轮挑一个功能追踪完整调用链。
4. 第四轮尝试改一个小地方，比如 AI prompt 或报告标题。

不要一上来从第一行读到最后一行。真实项目代码不是小说，适合按问题去追。

## 2. 项目整体地图

```text
main.py
web_app.py
stock_analyse/
  instrument_parser.py
  data_provider.py
  news_searcher.py
  indicators.py
  analyzer.py
  professional.py
  ai_advisor.py
  charting.py
  html_report.py
  models.py
tests/
  test_analyzer.py
```

最重要的阅读顺序：

1. `main.py`
2. `web_app.py`
3. `stock_analyse/models.py`
4. `stock_analyse/instrument_parser.py`
5. `stock_analyse/data_provider.py`
6. `stock_analyse/analyzer.py`
7. `stock_analyse/professional.py`
8. `stock_analyse/ai_advisor.py`
9. `stock_analyse/html_report.py`

如果你想按文件逐个理解每段代码的意思，请继续看：

```text
docs/CODE_WALKTHROUGH.md
```

那份文档会更细，适合一边打开代码一边对照阅读。

## 3. 一次分析是怎么跑完的

以 `futures:LC2609` 为例：

1. 用户在网页输入 `LC2609`。
2. `web_app.py` 收到输入。
3. `instrument_parser.py` 判断它是期货。
4. `main.py` 调用 `AkshareDataProvider`。
5. `data_provider.py` 获取实时行情、日线、新闻、现货/基差、持仓排名。
6. `news_searcher.py` 用关键词补充网页新闻。
7. `analyzer.py` 计算 MA、MACD、RSI、支撑压力和本地评分。
8. `professional.py` 生成专业上下文，例如基差、持仓聚合、多空计划。
9. `ai_advisor.py` 把这些数据整理成 prompt，发给 Gemini。
10. Gemini 返回 AI 投资报告。
11. `charting.py` 画图。
12. `html_report.py` 生成 HTML 报告。
13. `web_app.py` 在网页展示结果。

## 4. 每个核心文件怎么看

### `main.py`

先找这些函数：

- `_load_dotenv()`：读取 `.env`。
- `_build_advisor()`：创建 AI 顾问对象。
- `analyze_symbol()`：完整分析流程的核心。
- `main()`：CLI 参数入口。

学习重点：它像“导演”，自己不负责取数据和算指标，而是把各个模块串起来。

### `web_app.py`

这是网页层。重点看：

- 页面输入控件。
- 点击按钮后调用了哪个函数。
- 图表和报告怎么展示。
- 新闻链接怎么展示。

学习重点：它负责用户体验，不应该塞太多投资逻辑。

### `models.py`

这里定义数据结构。比如：

- `StockQuote`：行情快照。
- `AnalysisResult`：一次完整分析的结果。
- `NewsItem`：新闻条目。

学习重点：`dataclass` 就像“数据表单”，让不同模块传数据时字段更清楚。

### `instrument_parser.py`

这里负责资产类型识别。它解决的问题是：

- `600519` 应该走股票接口。
- `510300` 应该走 ETF 接口。
- `LC2609` 应该走期货接口。
- `futures:LC2609` 应该强制走期货接口。

学习重点：输入越明确，系统越不容易误判。

### `data_provider.py`

这是最大也最复杂的文件。建议分块看：

- 股票行情函数。
- ETF 行情函数。
- 期货行情函数。
- 新闻函数。
- 基本面/现货/持仓函数。
- 字段标准化函数。

学习重点：外部数据永远不稳定，所以这里会有很多 `try/except` 和备用接口。

### `news_searcher.py`

这里负责免费网页新闻搜索。重点看：

- 怎么根据资产类型生成关键词。
- 怎么解析新闻标题、来源、时间、链接。
- 怎么去重和过滤。

学习重点：新闻是辅助证据，不是绝对事实。代码要保留来源链接，方便人工复核。

### `indicators.py`

这是技术指标工具文件。适合新手练习新增功能。

你可以从这里学习：

- 如何用 pandas 计算均线。
- 如何计算 RSI。
- 如何计算 MACD。

### `analyzer.py`

它会把 K 线和行情整理成 AI 可读的数据底稿。

重点看：

- 技术指标怎么加入结果。
- 支撑压力怎么计算。
- 风险提示怎么生成。
- AI payload 怎么组织。

学习重点：这里是“数据整理员”，不是最终投资顾问。

### `professional.py`

这是专业投研增强层。重点看：

- 怎么判断新闻强弱相关。
- 怎么解读期货基差。
- 怎么聚合持仓排名。
- 怎么计算入场、止损、目标和风险收益比。

学习重点：优秀投资建议必须落到计划，不能只有“看多/看空”。

### `ai_advisor.py`

这是 AI 层。重点看：

- `_system_prompt()`：告诉 AI 扮演什么角色。
- prompt 里的输出结构。
- Gemini/DeepSeek/OpenAI 的调用方式。
- 错误处理和超时处理。

学习重点：AI 输出质量很大程度取决于输入数据和提示词结构。

### `charting.py`

负责画图。重点看：

- K 线图。
- 成交量。
- MACD。
- RSI。
- 支撑压力线。

### `html_report.py`

负责生成 HTML 报告。重点看：

- AI 文本怎么放进 HTML。
- 图表怎么嵌入。
- 新闻链接怎么渲染。
- 原始数据怎么展示。

## 5. Python 概念解释

### `class` 是什么

`class` 可以理解为“工具箱模板”。例如 `AkshareDataProvider` 是一个数据工具箱，里面有获取行情、K 线、新闻的方法。

### `dataclass` 是什么

`dataclass` 是专门用来装数据的类。它可以减少重复代码，让你少写很多初始化函数。

示意：

```python
@dataclass
class StockQuote:
    symbol: str
    name: str
    price: float
```

意思是：一个行情对象至少有代码、名称和价格。

### `dict` 是什么

`dict` 是键值对：

```python
{"price": 175960, "asset_type": "futures"}
```

项目里经常用它装灵活的数据，例如 `fundamental_data`。

### `list` 是什么

`list` 是列表：

```python
["LC2609", "600519", "510300"]
```

项目里新闻、K 线行、风险提示通常都是列表。

### `tuple` 是什么

`tuple` 是不可变列表：

```python
(172080, 140000)
```

适合表示固定的一组值。

### 类型标注怎么看

```python
def get_history(symbol: str, days: int) -> pd.DataFrame:
```

意思是：

- `symbol` 应该是字符串。
- `days` 应该是整数。
- 函数返回 pandas 的 `DataFrame`。

类型标注不一定强制执行，但能帮助你读代码。

### `try/except` 是什么

外部接口可能失败，所以代码会写：

```python
try:
    data = get_realtime_data()
except Exception:
    data = get_daily_data()
```

意思是：先试实时数据，失败就用日线兜底。

## 6. 常见维护任务

### 修改 AI 报告结构

改：

```text
stock_analyse/ai_advisor.py
```

重点找：

- `_system_prompt()`
- 输出要求
- 股票/ETF/期货不同资产的分析框架

### 新增一个技术指标

一般步骤：

1. 在 `indicators.py` 写计算函数。
2. 在 `analyzer.py` 调用它。
3. 把结果放进 AI payload。
4. 在 `html_report.py` 或 `charting.py` 展示。
5. 写一个测试。

### 新增一个数据源

一般步骤：

1. 在 `data_provider.py` 写获取函数。
2. 标准化字段名。
3. 失败时加错误提示。
4. 把数据放入 `fundamental_data` 或 `AnalysisResult`。
5. 在 `ai_advisor.py` prompt 中说明 AI 如何使用。

### 调整网页

改：

```text
web_app.py
```

适合调整：

- 输入框。
- 下拉框。
- 按钮。
- 页面展示顺序。
- 报告下载。

### 调整 HTML 报告

改：

```text
stock_analyse/html_report.py
```

适合调整：

- 标题。
- 样式。
- 新闻链接。
- 数据底稿展示。

## 7. 建议你今天做的小练习

1. 打开 `main.py`，找到 `analyze_symbol()`。
2. 在 `analyze_symbol()` 里找到 `get_quote`、`get_history`、`get_news`。
3. 打开 `data_provider.py`，找到期货相关函数。
4. 打开 `ai_advisor.py`，找到期货 prompt。
5. 打开 `professional.py`，看基差和持仓是怎么整理的。
6. 打开一个 HTML 报告，对照代码看新闻链接和图表是怎么生成的。

## 8. 你真正需要先理解的核心思想

这个项目不是一个“预测神器”。它目前做的是：

```text
把分散的数据收集起来
把指标和新闻整理成底稿
让 AI 按投资框架输出报告
```

下一阶段要变专业，就要加入：

```text
量化因子
历史回测
信号胜率
风险收益统计
```

也就是说，未来的重点不是让 AI 说得更像专家，而是让 AI 引用经过历史验证的数据。
