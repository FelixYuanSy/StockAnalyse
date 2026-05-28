# StockAnalyse

本项目是一个本地运行的 AI 投资分析工具，面向中国 A 股、ETF 和期货。当前阶段的定位是：

```text
公开数据底稿 + 技术指标 + 新闻检索 + AI 主导投研报告
```

它会通过 AKShare 和公开网页新闻获取行情、K 线、部分基本面、期货现货/基差、持仓排名和新闻链接，再交给 Gemini、DeepSeek 或 OpenAI 生成投资决策报告。日常使用推荐打开本地网页，不需要每次在 PowerShell 里输入复杂命令。

> 风险声明：本项目只用于研究和学习，不构成收益承诺，也不能替代持牌投顾意见。真实交易前必须自己复核数据、仓位和风险。

## 当前能力

- 支持 A 股：例如 `600519`、`000001`。
- 支持 ETF：例如 `510300`、`159915`。
- 支持期货：例如 `LC2609`、`RB0`、`AU0`。
- 支持显式输入：`stock:600519`、`etf:510300`、`futures:LC2609`。
- 默认使用 Gemini 生成 AI 投资报告，也可切换 DeepSeek/OpenAI。
- 自动生成 HTML 图文报告，包含 K 线、均线、成交量、MACD、RSI、支撑压力和新闻链接。
- 对期货额外关注现货价格、基差、持仓排名、产业新闻和杠杆风险。

## 快速启动

第一次使用：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

在 `.env` 中填写你的 AI key，例如：

```text
GEMINI_API_KEY=your_gemini_api_key_here
```

日常使用直接双击项目根目录里的：

```text
启动投资分析.bat
```

它会启动本地网页，通常地址是：

```text
http://localhost:8501
```

## CLI 备用入口

网页打不开时，可以使用命令行：

```powershell
.\.venv\Scripts\python main.py stock:600519 --ai-provider gemini
.\.venv\Scripts\python main.py etf:510300 --ai-provider gemini
.\.venv\Scripts\python main.py futures:LC2609 --ai-provider gemini
```

只看数据底稿，不调用 AI：

```powershell
.\.venv\Scripts\python main.py futures:LC2609 --no-ai
```

## 推荐阅读顺序

如果你今天要把文档和代码都看完，建议按这个顺序：

1. [用户使用指南](docs/USER_GUIDE.md)
2. [项目当前状态](docs/PROJECT_STATUS.md)
3. [系统架构说明](docs/ARCHITECTURE.md)
4. [数据源说明](docs/DATA_SOURCES.md)
5. [代码学习指南](docs/CODE_LEARNING_GUIDE.md)
6. [常见问题排查](docs/TROUBLESHOOTING.md)
7. [量化升级路线](docs/QUANT_UPGRADE_PLAN.md)

## 代码结构

```text
main.py                         CLI 入口和通用分析流程
web_app.py                      Streamlit 本地网页入口
stock_analyse/
  data_provider.py              AKShare 数据获取和字段标准化
  news_searcher.py              免费网页新闻搜索
  analyzer.py                   技术指标、评分、预测底稿
  professional.py               专业投研上下文：基差、持仓、风险收益比
  ai_advisor.py                 Gemini/DeepSeek/OpenAI 调用和 Prompt
  charting.py                   Plotly 图表
  html_report.py                HTML 图文报告
  models.py                     数据结构
  instrument_parser.py          标的类型识别
tests/
  test_analyzer.py              基础单元测试
```

## 安全说明

- 真实 API key 只放在 `.env`，不要写入 README、代码、截图或聊天记录。
- `.env` 已被 `.gitignore` 忽略，不会正常提交到 Git。
- 如果某个 key 曾经暴露过，请去对应平台控制台立即轮换。

## 下一阶段方向

当前工具是 AI-first 投研助手。下一阶段会向“轻量专业量化模型”升级：新增量化因子、历史回测、当前信号评分和 AI 解释层，让报告从“AI 判断”升级为“历史验证 + 当前信号 + AI 解读”。
