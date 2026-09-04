<div align="center">

# 🌈 Rainbow-FinGPT v2.0
### *新一代全自动 A股 智能量化投研终端 & AI-Copilot*

[![Python 3.12](https://img.shields.io/badge/Python-3.12%2B-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![LLM Backend](https://img.shields.io/badge/LLM-DeepSeek--V4--Flash-6366f1.svg?style=for-the-badge&logo=openai&logoColor=white)](https://deepseek.com/)
[![Framework](https://img.shields.io/badge/Pipeline-FinGPT--RAG-8b5cf6.svg?style=for-the-badge)](https://github.com/AI4Finance-Foundation/FinGPT)
[![Live Demo](https://img.shields.io/badge/在线看板-已上线-10b981.svg?style=for-the-badge&logo=vercel&logoColor=white)](https://yuxuanwucn.github.io/stock-dashboard/)
[![License](https://img.shields.io/badge/License-MIT-amber.svg?style=for-the-badge)](LICENSE)

**全自动交易日日落投研平台。**  
融合 **Fama-MacBeth 四因子 Alpha 截面回归**、**多因子 Trend Gate 趋势门禁（C浪排斥）**、**确定性 KNN 相似形态预测** 与 **DeepSeek 可溯源金融大模型研报系统**。

[🚀 在线体验 Web 看板](https://yuxuanwucn.github.io/stock-dashboard/) · [📖 English Documentation (README)](README.md) · [📄 完整学术论文](本人研究成果/Rainbow_FinGPT_v2_Paper.docx) · [⚡ 快速上手](#-快速上手)

---

<img src="本人研究成果/figures/arch_framework.png" alt="Rainbow-FinGPT 系统架构" width="90%">

</div>

---

## 🌟 核心亮点

- 🤖 **FinGPT 范式 RAG 研报引擎**：交易日 18:00 自动抓取上市公司公告、新闻与财报，调用 DeepSeek 生成**带精确证据溯源（Citation-Grounded）**的机构级投研简报。
- 🛡️ **数学级 Trend Gate™ 趋势门禁**：通过 **MA20 均线排列、MACD 动量多头、艾略特 C 浪下跌排斥** 三重逻辑硬门禁，有效阻断大盘杀跌与单边下行风险。
- 📐 **经典资产定价模型**：实现 **Fama-MacBeth 两阶段截面回归**与 Newey-West HAC 异方差自相关稳健协方差估计，剥离市场（MKT）、市值（SMB）、价值（HML）与动量（MOM）因子，提取真正统计显著的个股 Alpha。
- 📈 **标准化 KNN 历史相似形态回测**：基于 5 年滚动数据（1200+ 交易日），快速计算未来 3 日 / 5 日条件上涨概率与盈亏比期望。
- 💼 **多策略模拟盘实盘对决**：实时追踪 6 大量化组合（*激进成长、妖股弹性、防御保守、科技主题、蓝筹价值、全球配置*），盘后自动调仓并计算累计净值。
- 🎨 **年轻化 FinTech 极简设计看板**：纯静态 Web 架构，支持毛玻璃轻奢风、ECharts 高刷图表交互与移动端完美适配。

---

## 📊 回测验证与抗风险实证

### 🔬 封箱回测：极端行情的抗跌实证

在严格的 T+1 封箱回测中，**Trend Gate 趋势门禁**成功将组合在极端单边阴跌行情中的最大回撤由 **-46.3% 大幅压降至 -16.9%**，同时完整保留了右侧主升浪的超额收益：

<div align="center">
  <img src="本人研究成果/figures/001258_sealed_box.png" alt="Trend Gate 回测 001258" width="48%">
  <img src="本人研究成果/figures/MU_sealed_box.png" alt="Trend Gate 回测 MU" width="48%">
  <p><em>图：趋势门禁前后最大回撤抑制与 Alpha 捕捉效果（严格遵循封箱交易者测试协议）</em></p>
</div>

---

## 🛡️ 研发质量铁律与版本迭代门禁 (Data & Code Evolution Mandate)

> [!IMPORTANT]
> **代码编写与数据覆盖铁律（必须严格执行）**：
> 1. **代码修改后必须先跑全量数据端测试**：每次编写或修改完代码之后，**必须首先运行全量数据层回测与量化指标测试**（包括但不限于多因子定价检验、物理隔离实证回测、Sharpe 比率与最大回撤评估等）。
> 2. **对比前一版本确认“质的提升”**：必须将新产出的量化数据与核心指标同上一个版本进行严格横向对比。**只有在明确确认新版本相比前一版本具有显著、实质性的“质的提升”（如夏普比率实质提升、回撤大幅收敛、因子统计显著性增强或系统吞吐大幅跃升），才允许覆盖并提交前一个版本的数据文件与产物！**
> 3. **未见质变坚决禁止覆盖**：若新测试结果未见质的提升、或指标存在停滞衰退，坚决不覆盖原有稳定基准与实盘历史数据，保留前一版本并深入排查算法根因。

---

## ⚡ 快速上手

### 1. 克隆代码与虚拟环境

```bash
git clone https://github.com/YuxuanWuCN/stock-dashboard.git
cd stock-dashboard/Rainbow_FinGPTv2

# 创建并激活虚拟环境 (推荐 Python 3.12+)
python -m venv .venv
.venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置 API Key

在项目根目录下创建 `.env` 文件：

```env
DEEPSEEK_API_KEY="你的DeepSeek-API-Key"
STOCK_PROXY="direct"
LLM_DAILY_CALL_LIMIT="800"
```

### 3. 一键跑通全流程并启动 Web 看板

```powershell
# 1. 运行每日投研全流程（抓取行情 -> 打分 -> DeepSeek研报 -> 调仓结算）
powershell -ExecutionPolicy Bypass -File tools\daily_local.ps1

# 2. 启动本地轻量化 Web 服务
python -m http.server 8080 --directory docs
```

打开浏览器访问 **`http://127.0.0.1:8080/index.html`** 即可浏览完整看板 🎉。

---

## 🧬 Windows 自动化计划任务挂载

无需每天手动打开终端，一键注册 Windows 任务计划程序：

```powershell
Register-ScheduledTask -TaskName "StockDashboard-DailyUpdate" `
  -Action (New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File D:\股票分析项目\Rainbow_FinGPTv2\tools\daily_local.ps1" -WorkingDirectory "D:\股票分析项目\Rainbow_FinGPTv2") `
  -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 18:00) `
  -User $env:USERNAME -Force
```

---

## 📄 开源许可与免责声明

- **开源协议**：本项目基于 [MIT License](LICENSE) 开源。
- **免责声明**：*本项目产出的所有评分、量化信号与模拟盘持仓均仅供学术研究、量化模型探索与技术交流使用，不构成任何实质性投资建议。市场有风险，投资需谨慎。*
