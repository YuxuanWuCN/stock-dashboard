# 📘 Rainbow-FinGPT 板块实证复现与出版级研报修饰标准操作手册 (SOP)
### *—— 献给团队成员 B（黄金板块）与成员 C（绿电板块）的保姆级对齐指南*

> **📌 队长寄语**：
> 本项目存储板块（成员 A）已经完成了全流程出版级打磨（**4 幅高清实证大图 + 2 页出版级研报 PDF + 物理隔离回测 + pytest 门禁**）。
> 请两位同学以**存储超级周期**为黄金标准，分别对【黄金地缘避险】和【绿电公用事业】进行标准化对齐与修饰，确保全团队输出的成果风格一致、严谨可信、无懈可击！

---

## 🎯 一、 你的核心任务目标 (Core Deliverables)

每位成员负责一个独立板块，需确保交付以下 **4 项核心资产**：
1. src/analysis/<sector>_backtest_runner.py：支持 generate_and_save_artifacts() 并自动产出 4 幅实证图与 JSON 数据；
2. 
eports/figures/backtest_<sector>_2025q3_2026q3/：包含规范命名的 **4 幅出版级实证大图**；
3. 	ools/generate_isolated_<sector>_dossier_pdf.py：编译生成 **2 页出版级研报 PDF**（落盘至 
esearch-outputs/reports/）；
4. 	ests/test_<sector>_backtest_runner.py：编写并通过 pytest 自动化门禁测试（100% pass）。

---

## 📐 二、 4 幅实证大图规范 (The 4-Figure Standard)

所有图表均需使用 Matplotlib 生成（分辨率 dpi=220 以上，中文字体 Microsoft YaHei，专业配色）：

| 图号 | 文件标准命名 | 图表内容与设计规范 | 标杆参考 (存储板块) |
| :--- | :--- | :--- | :--- |
| **图 1** | ig1_cumulative_equity_and_drawdown.png | **净值走势与水下回撤对比图**（上下子图，比例 2.3:1）：<br>• 上半部：策略净值 vs 板块等权 vs 对应行业 ETF vs 沪深300<br>• 下半部：动态回撤曲线（深色高亮策略回撤，展示 C 浪拦截与回撤腰斩） | 对标芯片ETF (512760)<br>回撤由 -54.1% 压至 29.1% |
| **图 2** | ig2_asset_allocation_and_turnover.png | **动态资产配置与换手率图**（上下子图，比例 1.9:1）：<br>• 上半部：板块各标的持仓比例与闲置现金占比的面积堆叠图 (stackplot)<br>• 下半部：逐日调仓换手率柱状图 (ar) | 5 大存储股 + 1.8% 现金<br>展现牛市集中、熊市空仓 |
| **图 3** | ig3_zigzag_trend_gate_<sector>_defense.png | **龙头个股因果波浪与风控微观实证**：<br>• 核心代表个股 300 交易日真实收盘价 + MA20 均线<br>• 标注斐波那契 0.618 企稳加仓点 (绿色箭头)<br>• 阴影高亮 Trend Gate 触发 C 浪破位强制清仓区间 (红色箭头) | 佰维存储 (688525)<br>展示躲过单边暴跌的实战案例 |
| **图 4** | ig4_fama_macbeth_rolling_alpha.png | **Fama-MacBeth 滚动特质 Alpha 与显著性检验**（上下子图）：<br>• 上半部：剥离 MKT/SMB/HML/MOM 后的纯特质 Alpha 累计曲线<br>• 下半部：Newey-West HAC 稳健 $-statistic 显著性时序图（红虚线 =2.0$, 紫点线 =3.0$） | 累计 Alpha +68.2%<br>持续位于  \ge 2.0$ 门槛之上 |

---

## 📑 三、 2 页出版级研报 PDF 布局排版规范

PDF 统一基于 FPDF2 库排版，严格控制为 **2 页标准 A4 篇幅**（不可多也不可少）：

### 【第 1 页】宏观全景与对标基准
1. **页眉 (Header)**：深蓝细横条装饰，标明 Rainbow-FinGPT Autonomous Quant Agent | Physical Isolation Dossier；
2. **主标题与副标题**：黑体加粗 14pt，副标题注明样本外区间、摩擦成本与基准；
3. **5 大核心 KPI 网格**：实测样本区间、策略累积收益、年化夏普比率、最大动态回撤、卡尔玛比率（带淡蓝灰色背景框）；
4. **第 1 节 · 物理隔离协议**：说明仅使用 $\le t$ 历史数据，+1$ 真实撮合，买 0.125%、卖 0.175% 真实机构摩擦；
5. **第 2 节 · 绩效对比表**：策略 vs 板块等权 vs 行业 ETF vs 沪深 300（包含累计收益、年化、夏普、回撤、卡玛）；
6. **第 3 节 · 图 1 全宽大图**：嵌入 ig1_cumulative_equity_and_drawdown.png（宽度 180mm）。

### 【第 2 页】微观风控、计量检验与学术归因
1. **第 4 节 · 图 2 全宽大图**：嵌入 ig2_asset_allocation_and_turnover.png（宽度 180mm）；
2. **第 5 节 · 图 3 与 图 4 并排对比图**：左侧嵌入 ig3_...（宽 88mm），右侧嵌入 ig4_...（宽 88mm）；
3. **第 6 节 · 经济学机理与结论归因框**：淡灰底色方框，阐述基本面 RAG 传导、Fama-MacBeth 显著性检验、Trend Gate C浪拦截三大论据。

---

## 🛠️ 四、 各成员具体操作执行流 (Step-by-Step)

### 👩‍💻 成员 B（黄金板块负责人）操作步骤：
1. **检查原始数据**：确认 data/raw/backtest_gold_2025q3_2026q3/ 包含 7 只黄金标的行情与因子；
2. **运行回测生成 4 图与 JSON**：
   `ash
   python -m src.analysis.gold_backtest_runner
   `
3. **编译 2 页出版级研报 PDF**：
   `ash
   python tools/generate_isolated_gold_dossier_pdf.py
   `
   *生成目标*：../research-outputs/reports/黄金地缘避险_物理隔绝真实交易实测研报.pdf
4. **运行自动化测试**：
   `ash
   python -m pytest tests/test_gold_backtest_runner.py
   `

---

### 👨‍💻 成员 C（绿电板块负责人）操作步骤：
1. **检查原始数据**：确认 data/raw/backtest_green_2025q3_2026q3/ 包含 6 只绿电标的行情与因子；
2. **运行回测生成 4 图与 JSON**：
   `ash
   python -m src.analysis.green_backtest_runner
   `
3. **编译 2 页出版级研报 PDF**：
   `ash
   python tools/generate_isolated_green_dossier_pdf.py
   `
   *生成目标*：../research-outputs/reports/绿电公用事业_物理隔绝真实交易实测研报.pdf
4. **运行自动化测试**：
   `ash
   python -m pytest tests/test_green_backtest_runner.py
   `

---

## 🛡️ 五、 Grill-Me 质量自检攻防清单 (Self-Audit Checklist)

在向队长提交代码或合并 GitHub 之前，请两位同学对照以下 **5 个尖锐问题进行自检（Grill Yourself）**：

- [ ] **Q1 (数据真实性)**：我的所有收益率和回撤数据，是否 100% 由本地 Runner 真实跑出？有没有任何硬编码假数据？
- [ ] **Q2 (未来函数隔离)**：我的回测代码在计算 $ 日决策时，是否只截取了 iloc[:t+1]？撮合收益是否在 +1$ 日？
- [ ] **Q3 (4 图对齐)**：我的 ig1 ~ ig4 命名、图表类型、配色与注释是否与存储板块完全一致？
- [ ] **Q4 (PDF 排版)**：生成的 PDF 是否恰好为 2 页？图片有没有被挤压变形？文字有没有重叠截断？
- [ ] **Q5 (测试全绿)**：运行 pytest 是否 100% 通过（无 error、无 failure）？

---

## 🚀 六、 双模并存体系：如何开启本地真实大模型长期长跑 (Live LLM Engine)

本项目支持**双模并存运行**，兼顾“大赛材料交付”与“本地活体长期投研”：

### 模式 A：比赛实证基准测试（离线秒级复现，用于 9月5日 网评材料提交）
- **特点**：无需配置 API Key，直接读取物理隔离历史数据，秒级生成用于大赛评审的 3 篇 2 页出版级研报 PDF；
- **运行方式**：
  ```powershell
  python -m src.analysis.green_backtest_runner
  python tools/generate_isolated_green_dossier_pdf.py
  ```

### 模式 B：全链路实时大模型投研与本地长跑（接上 API Key 开启真实 LLM 智能体）
- **特点**：接上你自己的 API Key（或启动本地 Ollama），每天自动抓取最新资讯、调用大模型进行 SCNU-RAG 事实抽取、动态更新因子库与个股深度研报并驱动策略调仓；
- **凭据配置（支持多种大模型后端）**：
  - 方式 1：在仓库根目录新建 `api-key.txt`，填入你的 DeepSeek / OpenAI / SiliconFlow 密钥；
  - 方式 2：启动本地 Ollama 离线大模型（如 `ollama run qwen2.5:7b`），系统将自动检测并连接 `http://localhost:11434`；
- **一键运行长跑**：
  ```powershell
  # 方式 1：执行单板块大模型实时投研
  python -m src.analysis.green_backtest_runner --live-llm

  # 方式 2：一键执行全流程每日长跑
  powershell tools/daily_live.ps1

  # 方式 3：一键注册 Windows 任务计划（每个交易日 15:30 自动静默运行）
  powershell tools/install_daily_scheduler.ps1
  ```
- **查看成果**：
  ```powershell
  python -m src.server
  ```
  在浏览器打开 `http://127.0.0.1:8000` 即可实时查看由你的大模型分析生成的最新个股研报与组合看板！

