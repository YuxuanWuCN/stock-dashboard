# 🏠 家庭股票自动看板

> **一句话说明**：每个交易日晚上自动抓取自选股票/基金数据，生成含 K 线、成交量、均线和涨跌摘要的可视化网页，自动发布到公网固定网址，父母手机随时可看。

---

## 目录

- [快速开始（从零配置，图文级教程）](#快速开始从零配置图文级教程)
- [本地运行测试](#本地运行测试)
- [如何修改自选股列表](#如何修改自选股列表)
- [故障排查](#故障排查)
- [常见问题 FAQ](#常见问题-faq)

---

## 快速开始（从零配置，图文级教程）

本教程面向不熟悉编程的维护者（子女），每一步都有说明。全过程只需做一次，此后全自动运行。

### 第 1 步：注册 GitHub 账号

访问 [github.com](https://github.com) → 点击右上角 **Sign up** → 按提示注册一个免费账号。

> 💡 建议用常用邮箱注册，后续失败提醒会发到这个邮箱。

### 第 2 步：创建仓库

1. 登录 GitHub，点击右上角头像旁的 **+** → **New repository**。
2. Repository name 填 `stock-dashboard`（建议这个名字，与脚本配套）。
3. 选择 **Public**（公开仓库可免费使用 GitHub Pages；若选 Private，需要在 Settings → Pages 里确认权限）。
4. **不要**勾选 "Add a README file"（我们会上传自己的）。
5. 点击 **Create repository**。

### 第 3 步：上传项目文件

**方法 A（推荐，不需要装 git）——网页上传：**

1. 在新建的仓库页面，点击 **uploading an existing file** 链接。
2. 将本项目所有文件/文件夹拖拽到上传区域。
3. 在下方 Commit message 里写 `初始化项目`，点 **Commit changes**。

**方法 B——用 git 命令：**

```bash
git clone https://github.com/<你的用户名>/stock-dashboard.git
cd stock-dashboard

# 把本项目所有文件复制到这个目录，然后：
git add .
git commit -m "初始化项目"
git push
```

### 第 4 步：开启 GitHub Pages（获得公网网址）

1. 在仓库页面，点击顶部 **Settings**。
2. 左侧菜单点击 **Pages**。
3. Source 选择 **Deploy from a branch**。
4. Branch 选择 `main`，目录选择 `/docs`，点击 **Save**。
5. 等待 1~2 分钟，页面顶部会出现绿色的提示框，里面写着 **"Your site is live at https://..."**。
6. **把这个网址记下来**，这就是父母看的网址。

> 💡 如果显示不出来，回到 Pages 设置页，确认分支选的是 `main`（不是 `master`）。

### 第 5 步：确认 Actions 权限

1. 在仓库 **Settings → Actions → General**。
2. 往下滚动到 **Workflow permissions**。
3. 选择 **Read and write permissions**。
4. 点击 **Save**。

> 这个权限让自动任务能够把数据提交到仓库，从而更新网站内容。

### 第 6 步：确认邮件通知已开启

1. 点击 GitHub 右上角头像 → **Settings**。
2. 左侧菜单点击 **Notifications**。
3. 往下滚动到 **System** 区域，找到 **Actions**。
4. 确认 **"Failed workflows"** 的邮件通知开关是打开的。

> 这样如果某天数据抓取完全失败，GitHub 会自动发邮件提醒你来看一眼。

### 第 7 步：手动测试一次

1. 在仓库页面，点击顶部 **Actions** 标签。
2. 左侧点击 **Daily Stock Data Update**。
3. 右侧点击 **Run workflow** 下拉按钮 → 再点绿色的 **Run workflow**。
4. 等待约 2~5 分钟，任务完成后会显示绿色 ✓。
5. 打开第 4 步记下的网址，应该能看到看板页面了。

🎉 **配置完成！** 之后每个交易日下午 6:30 左右，系统会自动更新数据，你什么都不用管。

### 第 8 步：把网址发给父母

把第 4 步得到的网址发给父母，教他们：

- **iPhone（Safari）**：打开网址 → 底部中间分享按钮 → **添加到主屏幕** → 以后像 App 一样点开。
- **Android（Chrome）**：打开网址 → 右上角三个点 → **添加到主屏幕** → 以后像 App 一样点开。
- 也可以直接存成浏览器书签。

---

## 本地运行测试

如果想在本地电脑上打开完整网页或测试数据抓取脚本：

### 环境要求

- Python 3.11 或更高版本
- 能访问互联网（akshare 需要联网抓数据）

### 安装步骤

```bash
# 1. 进入项目目录
cd stock-dashboard

# 2. 安装依赖（推荐先创建虚拟环境）
python -m venv venv
# Windows: venv\Scripts\activate
# Mac/Linux: source venv/bin/activate

pip install -r requirements.txt
```

### 一键打开完整网页（推荐）

Windows 用户直接双击项目根目录下的 `start_local.bat`。也可以在终端运行：

```bash
python start_local.py
```

启动器会同时启动：

- 网页：<http://127.0.0.1:8001/>
- 股票查询 API：<http://127.0.0.1:5000/api/health>

浏览器会自动打开网页。不要关闭启动窗口；使用完毕后在启动窗口按 `Ctrl+C`，前后端会一起停止。如果提示端口 `5000` 或 `8001` 已被占用，请先关闭旧的本地看板进程后再运行。

### 只更新本地股票数据

```bash

# 3. 运行脚本
python src/fetch_data.py
```

### 运行成功标志

- 控制台输出日志，显示每只标的的抓取结果（✓/✗）。
- `docs/data/kline/` 下出现各只标的的 `.json` 文件。
- `docs/data/summary.json` 和 `docs/data/meta.json` 已生成。

---

## FinGPT 风格流程 + DeepSeek V4 Flash

本项目已经接入的是“FinGPT 方法论流程 + DeepSeek API 推理”：

1. 从现有规则引擎读取技术、风险、行业和基本面评分，模型不得修改这些数值。
2. 按 FinGPT 的采样思路对新闻做批量情感分析，同一批新闻只调用一次 API。
3. 用 RAG 检索新闻和公告证据，并由程序绑定来源、日期和原文片段。
4. 排行榜的详情和排名 JSON 落盘后，主流程自动调度前 5 名的报告；模型固定为
   `deepseek-v4-flash`，不接受环境变量静默切换。
5. 没有可用 DeepSeek 密钥或显式关闭时，主流程安全跳过报告阶段，不抓新闻也不覆盖
   已有深度报告；实际 API 调用失败时，核心流程拒绝保存模板降级产物或市场反馈，
   但不会中断排行榜。手动独立运行仍可使用模板降级路径。
6. 保存 `pipeline/backend/model/mode/fallback_reason` 等非敏感元数据，便于核对实际运行路径。

这里没有把 FinGPT 的 LoRA/QLoRA 权重上传给 DeepSeek。DeepSeek API 不能直接加载本地
FinGPT 权重；本项目复用的是 FinGPT 的数据、RAG、情感和市场反馈方法。以后若需要运行
真实 FinGPT 权重，应单独部署带 GPU 的本地推理服务。

### 本地密钥配置

推荐在项目根目录创建 `api-key.txt`，文件只放一行 DeepSeek API Key：

```text
sk-你的密钥
```

该文件和 `.env` 已被 `.gitignore` 排除。程序优先读取环境变量
`DEEPSEEK_API_KEY`，没有时才读取本地 `api-key.txt`；任何报告和日志都不会保存密钥。
完整配置占位见 `.env.example`。

运行 `python -m src.build_ranking` 时，核心分析会在写完排行榜后自动处理前 5 名。
可在 `.env` 或运行环境中调整：

```text
LLM_REPORTS_ENABLED=true
LLM_REPORTS_TOP_K=5
LLM_REPORTS_SKIP_EXISTING=true
```

手动补跑当前排行榜前 5 名的研究报告：

```bash
python -m src.llm.generate_reports --top-k 5
```

强制离线、不读取密钥也不调用 API：

```bash
python -m src.llm.generate_reports --top-k 5 --no-llm --no-news
```

在 GitHub Actions 中，请到仓库 `Settings → Secrets and variables → Actions` 新建
`DEEPSEEK_API_KEY`。工作流只运行核心排行榜命令；模型固定和报告异常隔离由核心代码
保证，不会重复调用报告流程。

---

## 如何修改自选股列表

自选股列表存储在 `watchlist.csv` 文件中，用 Excel 或记事本都能编辑。

### 从查询结果加入自选股

1. 在页面顶部输入 6 位股票代码并点击“查询对比”。
2. 查询成功后点击“加到自选股”，选择分类并确认。
3. 本地运行时会直接更新项目根目录的 `watchlist.csv`，刷新页面后仍然保留。
4. 在线网页会先保存到当前浏览器并立即显示。要让新股票参与每天 17:30 的风险收益排行榜，请在“编辑列表”中下载新的 `watchlist.csv`，再更新到 GitHub 仓库根目录。

### 用网页修改（最简单）

1. 在 GitHub 仓库页面，点击 `watchlist.csv` 文件。
2. 点击右上角的 **✏️ 编辑**（铅笔图标）。
3. 按格式增删行，改完后点 **Commit changes**。
4. 修改会在下一个交易日自动生效（手动运行一次 Actions 可立即生效）。

### 文件格式

```
code,name,type
600519,贵州茅台,stock
000001,平安银行,stock
510300,沪深300ETF,etf
```

> **规则**：
> - 第一行表头不能改。
> - `code` = 6 位数字代码（上交所 6 开头，深交所 0/3 开头，ETF 5/1 开头）。
> - `name` = 显示名称，自己起，中文即可。
> - `type` = `stock`（股票）或 `etf`（场内基金/ETF）。
> - 以 `#` 开头的行会被忽略（可用于写注释）。
> - 空行自动跳过。

---

## 故障排查

| 现象 | 可能原因 | 解决办法 |
|---|---|---|
| Actions 任务一直转圈不结束 | GitHub 排队中 | 等 10~15 分钟再刷新 |
| Actions 显示红色 ✗ | 所有标的抓取都失败了 | 检查是否收到邮件，尝试手动重新运行；若持续失败检查网络/接口 |
| 网页显示"暂无数据" | 数据文件未生成或路径错误 | 确认 Actions 最近一次是绿的，确认 `docs/data/` 下有 JSON 文件 |
| 手机打开网页字太小 | 浏览器缩放 | 双指放大，或竖屏查看自适应布局 |
| 某只股票显示灰色/stale | 该只上次抓取失败用了旧数据 | 一般下次会自动恢复；持续失败的检查代码是否变更 |
| 节假日/周末 Actions 运行了 | 正常，脚本会自动识别 | 节假日无新数据不会报错，保留上次数据 |
| 邮件设置在哪 | GitHub 通知设置 | 右上角头像 → Settings → Notifications → Actions 区域 |

---

## 常见问题 FAQ

**Q：需要花钱吗？**
A：基础看板、GitHub Pages 和公开数据流程可以免费运行；启用 DeepSeek 研究报告时，
API 费用以你的 DeepSeek 账户计费规则为准。项目通过批量情感、Top-K 和每进程调用上限控制成本。

**Q：能不能加港股/美股？**
A：当前版本只支持 A 股和场内基金。港股/美股是计划中的扩展项。

**Q：如果某天数据抓取失败了怎么办？**
A：网页会继续显示上一次成功的数据，不会空白。同时你会收到 GitHub 的邮件通知，提醒你去排查。

**Q：GitHub 被墙了怎么办？**
A：GitHub 在国内有间歇性访问问题。如果父母打不开，可以考虑用 Cloudflare Pages 等国内访问更快的替代方案（需要额外配置，本期不做）。

**Q：能加 MACD/KDJ 等指标吗？**
A：按需求方要求，本期只做 K 线 + 均线 + 成交量，复杂指标放在未来迭代。

---

## 项目结构

```
stock-dashboard/
├── README.md                   项目总说明（从零配置教程）
├── AGENTS.md                   质量门禁规则
├── QUALITY_WORKFLOW.md         质量工作流入口（完整规则见 WORKFLOW.md）
├── WORKFLOW.md                 质量门禁完整规则
├── 项目背书.md                   项目立项背书
├── requirements.txt            Python 依赖
├── render.yaml                 Render 云端部署配置（备用）
├── start_local.bat / start_local.py   本地一键启动
├── watchlist.csv               自选股/基金列表（可自行编辑）
├── strategy_pool.csv           策略扩展股票池
├── .env.example                密钥配置模板（真实密钥放 .env，勿提交）
├── src/                        后端源码
│   ├── fetch_data.py           抓取行情（A股/港股/美股/韩股/ETF/基金）
│   ├── build_ranking.py        排行榜构建
│   ├── server.py               Flask API 服务
│   ├── config.py / utils.py / proxy.py / market_feedback.py
│   ├── analysis/               技术指标、行业、评分（规则引擎）
│   ├── llm/                    FinGPT 风格 LLM 分析管线（DeepSeek V4 Flash）
│   └── strategies/             策略选股引擎（KHunter 合并）、明日关注
├── tools/                      自动化与工具
│   ├── daily_local.ps1         每日本地自动任务（抓取→排行→策略→模拟盘→推送）
│   ├── paper_portfolio.py      模拟盘对决记录（稳健 vs 激进）
│   ├── aggressive_scan.py      全库激进扫描
│   └── run_quality.ps1 / quality_gate.py   质量门禁
├── tests/                      pytest 测试
├── config/strategy_params.json 策略参数
├── docs/                       GitHub Pages 发布目录（data/ 勿手动修改）
│   ├── index.html / assets/
│   └── data/                   程序自动生成（kline/analysis/llm/strategy/paper/fundamental）
├── 项目规划/                    项目规划文档（01-05）+ 人工需求idea/
├── 测试记录/版本/                各版本测试记录
├── reports/                    研究报告（assumptions.md、单股分析 data/）
├── bug合集/                     质量门禁 bug 归档
└── .github/workflows/          云端自动化（已停用，现由本地计划任务代替）
```

---

## 2.1 新增：短线风险收益排行榜

### 评分口径

系统每交易日 17:30 为每只自选股计算风险收益评分，产出排行榜。

**风险分数 (risk_score)** 范围 0–100，越高风险越大：

| 因子 | 权重 |
|---|---:|
| 20 日年化波动率 | 30% |
| 60 日最大回撤 | 25% |
| ATR 百分比 | 20% |
| 量价异常与流动性 | 10% |
| 行业波动和行业弱势 | 15% |

各因子先转换为 0–100 子分，再加权。阈值：
- 0–35：**低风险**（绿色）
- 36–65：**中等风险**（黄色）
- 66–100：**高风险**（红色）

**风险调整后评分：**
- 机会分 = 35% × 预期收益百分位 + 25% × 上涨样本比例 + 20% × 技术分 + 20% × 行业分
- 最终评分 = 机会分 × (1 - 0.5 × 风险分/100)，范围 0–100

**三个排行榜视图：**
1. 风险收益榜 — 按风险调整后评分降序
2. 收益预估榜 — 按 5 日预期收益降序
3. 低风险榜 — 按风险分升序

### 数据源

- **行情数据**：AkShare（东财），前复权日线
- **行业板块**：AkShare 东财行业板块接口，失败时降级到市场指数
- **历史深度**：5 年日线，用于相似走势匹配

### 故障排查

| 现象 | 可能原因 | 解决办法 |
|---|---|---|
| 分析任务失败 | 行业接口不可用或数据不足 | 查看 Actions 日志，上次成功数据会自动保留 |
| 某只数据显示样本不足 | 历史数据不够或停牌过多 | 正常现象，预测值显示为 null 不影响排行 |
| 排行榜未更新 | 节假日无交易数据 | 脚本自动识别，不报错 |

### 免责声明

基于历史日线的统计分析，仅用于学习和研究，不构成投资建议或收益保证。系统不自动交易、不连接证券账户。所有预期收益均为历史相似样本的统计值，不代表未来表现。

## 2.5 新增：策略选股引擎（KHunter 合并）

本版将参考项目 KHunter 的核心能力合并进看板，新增 **选股策略引擎、策略回测、狩猎场、市场温度** 四大模块。

### 运行方式

```bash
# 策略选股（自选股 + 扩展股票池）
python -m src.strategies.run_strategies

# 综合研究：选股 → 狩猎场 → 市场温度（+ 可选回测）
python -m src.strategies.main --backtest

# 指定范围
python -m src.strategies.run_strategies --scope watchlist   # 只跑自选股
python -m src.strategies.run_strategies --scope pool        # 只跑扩展池
```

### 四个模块

| 模块 | 说明 |
|---|---|
| 策略引擎 | `src/strategies/`：BaseStrategy 基类 + 注册表（自动扫描），3 个内置策略（多金叉共振/涨停回马枪/启明星），参数在 `config/strategy_params.json` 可调 |
| 策略回测 | 事件驱动回测：T+1、手续费（佣金/印花税/过户费）、止盈止损、移动止损、亏损冷却；输出收益/回撤/夏普/胜率等指标 |
| 狩猎场 | 选股结果 → 支撑位计算（ma20/关键收盘/关键开盘）→ 买点判断（0~3% 买入区间）→ 跟踪 |
| 市场温度 | 四维度（涨跌比 35%/跌停 35%/涨停表现 20%/成交额 10%）计算市场状态与仓位系数 |

### 扩展股票池

`strategy_pool.csv`（格式同 `watchlist.csv`）定义了策略扫描的扩展股票池（默认 20 只关注股）。策略只在 **自选股 + 扩展池** 范围内选股，不做全市场扫描（受免费数据源与 Actions 额度限制）。

### 输出文件

策略结果写入 `docs/data/strategy/`：

| 文件 | 内容 |
|---|---|
| `selection.json` | 各策略选股结果 |
| `hunting_ground.json` | 狩猎场（支撑位/买点判断） |
| `market_temperature.json` | 市场温度与仓位系数 |
| `backtest.json` | 策略回测绩效（--backtest 时生成） |

### 项目边界（与 KHunter 的差异）

- 不引入 SQLite，结果沿用 JSON 文件体系（`配置一次，长期自动运行`）
- 不移植 PTrade 实盘交易（项目红线：不自动交易）
- 不移植依赖 tushare 积分的资金面/事件数据（免费源不稳定）
- 策略信号是研究参考，不是买卖指令

## 致维护者

这个项目的设计理念是 **"配置一次，长期自动运行"**。你不需要每天登录检查，只有在收到失败邮件时才需要看一下。父母需要做的就是打开手机浏览器点一下链接 —— 和打开任何一个 App 一样简单。

如果遇到问题，首先看 [故障排查](#故障排查)；如果解决不了，可以打开 GitHub Actions 页面查看最后一次运行的日志（点击红色 ✗ → 点击 `fetch-and-publish` → 展开 `运行数据抓取脚本` 看日志输出）。
