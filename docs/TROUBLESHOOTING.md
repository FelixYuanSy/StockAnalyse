# 常见问题排查

## 1. 双击 bat 窗口闪退

常见原因：

- 没有创建 `.venv`。
- 依赖没有安装完整。
- 当前目录不是项目目录。
- Streamlit 启动时报错但窗口太快关闭。

建议先用 PowerShell 手动启动一次，看完整报错：

```powershell
cd D:\felixvedio\新建文件夹\StockAnalyse
.\.venv\Scripts\python.exe -m streamlit run web_app.py --server.port 8501
```

如果提示没有 streamlit，重新安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. Gemini 连接失败

页面可能显示：

```text
GEMINI API 请求失败: Connection error.
```

这通常是网络或代理问题，不一定是 key 错误。

如果你使用代理软件，在 `.env` 中配置：

```text
AI_PROXY=http://127.0.0.1:7890
```

端口以你的代理软件为准，常见端口有：

```text
7890
7897
10808
10809
```

如果你不想让 AI 请求读取系统代理，可以设置：

```text
AI_USE_SYSTEM_PROXY=false
```

如果错误里出现 `ProxyError`、`Remote end closed connection without response`，通常说明代理软件虽然端口存在，但当前节点或规则没有成功转发 Gemini 请求。可以尝试：

- 确认代理软件正在运行。
- 确认 `.env` 中 `AI_PROXY` 是实际可用端口，例如 `http://127.0.0.1:7890`。
- 在代理软件中确认 Google/Gemini 域名走代理。
- 换一个代理节点后重试。
- 临时切换 `AI Provider` 到 DeepSeek。

程序会对错误信息里的 API key 做脱敏。如果你曾经在截图、日志或聊天里暴露过真实 key，请立即到对应平台控制台轮换。

## 3. Gemini 返回为空

可能原因：

- 模型暂时无响应。
- 网络中断。
- 请求内容过大。
- Gemini 某个模型临时不可用。

可以尝试：

```powershell
.\.venv\Scripts\python main.py futures:LC2609 --ai-provider gemini --ai-model gemini-2.0-flash
```

也可以换 DeepSeek：

```powershell
.\.venv\Scripts\python main.py futures:LC2609 --ai-provider deepseek
```

## 4. API key 无效或额度不足

如果出现 quota、billing、insufficient quota，说明当前 provider 账号没有可用 API 额度。ChatGPT Plus 和 OpenAI API 是两套计费体系，Plus 不等于 API 免费额度。

检查 `.env`：

```text
GEMINI_API_KEY=你的GeminiKey
DEEPSEEK_API_KEY=你的DeepSeekKey
OPENAI_API_KEY=你的OpenAIKey
```

不要把真实 key 粘贴到文档、代码、截图或聊天记录。如果已经暴露，请去平台控制台轮换。

## 5. AKShare 行情接口失败

常见原因：

- 上游接口临时不可用。
- 网络或代理影响访问。
- 输入合约不存在或不活跃。
- A 股非交易时段实时行情不更新。

先检查数据底稿：

```powershell
.\.venv\Scripts\python main.py futures:LC2609 --no-ai
```

如果实时行情失败但日线成功，程序会用最新日线兜底，并在报告中提示“数据来源：最新日线”。

## 6. 期货现货价格没有

可能原因：

- AKShare 当天没有返回该品种现货数据。
- 当前日期不是有效交易日。
- 现货接口更新晚于期货行情。
- 品种名称和合约代码映射不完整。

程序会向前查找最近可用日期。如果仍然没有，AI 必须说明“现货/基差缺失”，不能编造现货价。

## 7. 新闻没有或新闻不相关

原因可能是：

- 免费新闻 RSS 源没有返回结果。
- 关键词过窄。
- 新闻源被网络环境拦截。
- 新闻时间太旧，被程序过滤。
- 系统代理端口失效，例如系统里残留 `ALL_PROXY=http://127.0.0.1:7897`，但实际代理软件使用 `7890`。

当前程序会同时使用 AKShare 新闻和网页新闻搜索。HTML 报告会显示新闻标题、来源、时间和链接。遇到新闻缺失时，建议手动打开财经网站核对。

如果新闻搜索报错里出现 `Unable to connect to proxy`，请在 `.env` 中设置：

```text
NEWS_SEARCH_PROXY=http://127.0.0.1:7890
```

如果你已经设置了：

```text
AI_PROXY=http://127.0.0.1:7890
```

新闻搜索会自动复用 `AI_PROXY`。只有当你的系统代理变量确定正确时，才建议设置：

```text
NEWS_SEARCH_USE_SYSTEM_PROXY=true
```

## 8. 报告里的价格和你看到的软件不同

可能原因：

- 数据源不同。
- 实时行情和日线数据更新时间不同。
- 期货主力合约和指定合约不是同一个。
- 交易软件显示的是最新 tick，本项目取到的是接口返回时刻。

真实交易以前，以交易软件和交易所数据为准。

## 9. GitHub 上传失败

常见原因：

- 没有配置 remote。
- 没有权限。
- SSH key 没加载。
- GitHub 仓库不存在。

检查远端：

```powershell
git remote -v
```

如果没有输出，需要添加：

```powershell
git remote add origin git@github.com:你的用户名/仓库名.git
```

然后推送：

```powershell
git push -u origin master
```
