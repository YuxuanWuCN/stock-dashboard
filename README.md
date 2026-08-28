# 🏆 R-FinGPTv2（中国国际大学生创新大赛 · 国创版本）

本文件夹为 **2026 中国国际大学生创新大赛（达观数据产业命题）** 独立封闭参赛工作空间。

## 📁 目录架构导览

```
D:\R-FinGPTv2（国创版本）\
├── 参赛要求/                                                  # 📑 大赛官方 5 大红头附件规范
│   ├── 附件1：中国国际大学生创新大赛（2026）产业赛道企业命题入选名单.pdf
│   ├── 附件2：校内产业赛道项目遴选系统申报指引.pdf
│   ├── 附件3：（产业赛道-企业命题组）参赛作品申报表.doc
│   ├── 附件4：（产业赛道-成果转化组）参赛作品申报表.doc
│   └── 附件5：中国国际大学生创新大赛（2026）评审规则.pdf
├── 2026中国国际大学生创新大赛_产业命题申报书_Rainbow-FinGPT.md  # 🌟 官方申报书 (对标附件3填报)
├── 达观数据产业命题答卷方案.md                                    # 📘 命题答卷白皮书
├── 16页金牌路演PPT全景设计与逐页演讲文稿.md                        # 🎤 8分钟路演逐字稿与PPT设计
├── 评委答辩专家攻防QA靶向演练手册.md                              # 🛡️ 评委答辩攻防通关必背
├── research-outputs/                                          # 📑 参赛实证成果库
│   └── reports/                                              # 三大出版级核心实证研报 PDF
│       ├── 存储超级周期_物理隔绝真实交易实测研报.pdf           # 1. 存储高弹性科技周期
│       ├── 黄金地缘避险_物理隔绝真实交易实测研报.pdf           # 2. 黄金宏观避险慢牛
│       └── 绿电公用事业_物理隔绝真实交易实测研报.pdf           # 3. 绿电低估值高股息防御
└── Rainbow_FinGPTv2/                                         # ⚡ 核心量化投研智能体系统
    ├── src/                                                  # 四位一体核心源码 (RAG / 定价 / 图谱 / 风控)
    ├── docs/                                                 # Web 交互看板 & 团队协作复现指南
    ├── data/raw/                                             # 物理隔离数据集 (存储/黄金/绿电)
    ├── tools/                                                # 自动化流水线 & PDF生成工具
    └── tests/                                                # 完整 pytest 自动化测试套件
```

## 🚀 常用操作指引

### 1. 启动本地全功能量化看板
```bash
cd Rainbow_FinGPTv2
python -m http.server 8000 --directory docs
```
浏览器访问: `http://127.0.0.1:8000`

### 2. 运行物理隔离样本外回测 (全量测试)
```bash
cd Rainbow_FinGPTv2
python -m pytest tests/test_storage_backtest_runner.py tests/test_gold_backtest_runner.py tests/test_green_backtest_runner.py
```

### 3. 一键生成三大出版级实证 PDF 研报
```bash
cd Rainbow_FinGPTv2
python tools/generate_isolated_storage_dossier_pdf.py
python tools/generate_isolated_gold_dossier_pdf.py
python tools/generate_isolated_green_dossier_pdf.py
```

---

<div align="center">

# 🌈 Rainbow-FinGPT v2.0
### *Next-Gen Autonomous Quantitative Research & AI-Copilot Terminal*

[![Python 3.12](https://img.shields.io/badge/Python-3.12%2B-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![LLM Backend](https://img.shields.io/badge/LLM-DeepSeek--V4--Flash-6366f1.svg?style=for-the-badge&logo=openai&logoColor=white)](https://deepseek.com/)
[![Framework](https://img.shields.io/badge/Pipeline-FinGPT--RAG-8b5cf6.svg?style=for-the-badge)](https://github.com/AI4Finance-Foundation/FinGPT)
[![Live Demo](https://img.shields.io/badge/Live_Terminal-Online-10b981.svg?style=for-the-badge&logo=vercel&logoColor=white)](https://yuxuanwucn.github.io/stock-dashboard/)
[![License](https://img.shields.io/badge/License-MIT-amber.svg?style=for-the-badge)](LICENSE)

**An end-to-end automated quantitative trading-day research platform.**  
Integrating **Fama-MacBeth 4-Factor Alpha Screening**, **Multi-Factor Trend Gate (Wave C Exclusion)**, **Deterministic KNN Similarity Forecasting**, and **Citation-Grounded DeepSeek Financial LLM Pipelines**.

[🚀 Live Web Demo](https://yuxuanwucn.github.io/stock-dashboard/) · [📖 中文说明文档 (README_CN)](README_CN.md) · [📄 Academic Paper](本人研究成果/Rainbow_FinGPT_v2_Paper.docx) · [⚡ Quick Start](#-quick-start)

---

<img src="本人研究成果/figures/arch_framework.png" alt="Rainbow-FinGPT Architecture Framework" width="90%">

</div>

---

## 🌟 Key Highlights

- 🤖 **FinGPT-Style RAG Agent**: Automatically digests financial news, announcements, and macro data daily at 18:00 CST. Synthesizes structured investment briefs with **verifiable citation audits**.
- 🛡️ **Mathematical Trend Gate™**: Multi-layered defense incorporating **MA20 alignment, MACD momentum divergence, and Elliott Wave Phase C exclusion** to mathematically filter out catastrophic drawdowns.
- 📐 **Rigorous Asset Pricing Engine**: Implements the **Fama-MacBeth Two-Stage Cross-Sectional Regression** with Newey-West HAC covariance estimators. Separates true idiosyncratic $\alpha$ from systematic factor risk premiums ($MKT, SMB, HML, MOM$).
- 📈 **Standardized KNN Pattern Forecasting**: Matches real-time technical volume-price matrices against a 5-year rolling history (1200+ daily bars) to derive empirical 3-day and 5-day conditional upward probabilities.
- 💼 **Multi-Strategy Paper Duel**: Tracks 6 diversified live simulated portfolios (*Aggressive Momentum, Volatility Hunter, Macro Defensive, Tech Growth, Bluechip Value, Global Multi-Asset*) with automated post-close rebalancing.
- 🎨 **Modern FinTech Glassmorphism UI**: High-refresh-rate interactive web terminal built with responsive glassmorphism, ECharts visual engine, and full mobile adaptation.

---

## 📊 Empirical Performance & Backtesting

### 🔬 Sealed-Box Regression: Realized Anti-Drawdown Proof

Below is the verified out-of-sample backtest comparison across extreme market downturns. The **Trend Gate** successfully shielded the portfolio by cutting maximum drawdowns from **-46.3% down to -16.9%** while preserving upward alpha momentum:

<div align="center">
  <img src="本人研究成果/figures/001258_sealed_box.png" alt="Trend Gate Backtest 001258" width="48%">
  <img src="本人研究成果/figures/MU_sealed_box.png" alt="Trend Gate Backtest MU" width="48%">
  <p><em>Figure: Realized drawdown suppression and alpha preservation verified under strict T+1 sealed-box testing.</em></p>
</div>

---

## 🏛️ System Architecture

Rainbow-FinGPT operates on a strict **three-tier decoupled pipeline**:

```
 ┌────────────────────────────────────────────────────────────────────────┐
 │ 1. Data Ingestion & Fallback Engine (Every Trading Day 18:00 CST)     │
 │    - Multi-source fallback: Sina Finance -> Eastmoney -> Tencent Cloud │
 │    - Auto-detects & flags stale/halted quotes (Stale Data Isolation)   │
 └────────────────────────────────────┬───────────────────────────────────┘
                                      ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │ 2. Quantitative & AI Reasoning Core                                   │
 │    - Fama-MacBeth 2-Stage Regression & Alpha Gate Filtering            │
 │    - 4-Dimensional Balance Sheet Quality Scoring (Asset/Debt/ROE/OCF)  │
 │    - DeepSeek-V4-Flash RAG Report Synthesizer & Citation Auditor       │
 │    - Multi-Portfolio Clearing & Auto-Rebalancing Engine                │
 └────────────────────────────────────┬───────────────────────────────────┘
                                      ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │ 3. Contract-Driven Static UI Layer (GitHub Pages / Local Host)         │
 │    - Zero-backend server overhead (Static JSON Schema 2.0 Contract)    │
 │    - ECharts 5.5 High-Precision Interactive Canvas                     │
 └────────────────────────────────────────────────────────────────────────┘
```

---

## ⚡ Quick Start

### 1. Clone & Environment Setup

```bash
# Clone the repository
git clone https://github.com/YuxuanWuCN/stock-dashboard.git
cd stock-dashboard/Rainbow_FinGPTv2

# Create virtual environment (Python 3.12+ recommended)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\Activate.ps1

# Install core dependencies
pip install -r requirements.txt
```

### 2. Configure API Keys

Create a `.env` file in the project root:

```env
DEEPSEEK_API_KEY="your-deepseek-api-key-here"
STOCK_PROXY="direct"
LLM_DAILY_CALL_LIMIT="800"
```

### 3. Run Pipeline & Launch Local Terminal

```powershell
# 1. Execute full daily pipeline (Data fetch -> Scoring -> AI Reports -> Rebalance)
powershell -ExecutionPolicy Bypass -File tools\daily_local.ps1

# 2. Launch local FinTech Web GUI
python -m http.server 8080 --directory docs
```

Open your browser and navigate to **`http://127.0.0.1:8080/index.html`** 🎉.

---

## 🧬 Automated Daily Task Scheduler

To enable fully autonomous "after-hours homework" without touching the terminal, register the background scheduler:

```powershell
# Auto-runs at 18:00 every trading day
Register-ScheduledTask -TaskName "StockDashboard-DailyUpdate" `
  -Action (New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File D:\股票分析项目\Rainbow_FinGPTv2\tools\daily_local.ps1" -WorkingDirectory "D:\股票分析项目\Rainbow_FinGPTv2") `
  -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 18:00) `
  -User $env:USERNAME -Force
```

---

## 📑 Quantitative Formulation & Methodology

<details>
<summary><b>📐 Click to expand Mathematical Formulations</b></summary>

### 1. Fama-MacBeth 4-Factor Model
In Stage 1, time-series regressions estimate factor loadings for each asset $i$:
$$R_{i,t} - R_{f,t} = \alpha_i + \beta_{i,MKT} MKT_t + \beta_{i,SMB} SMB_t + \beta_{i,HML} HML_t + \beta_{i,MOM} MOM_t + \epsilon_{i,t}$$

In Stage 2, cross-sectional regressions at each $t$ estimate risk premia $\gamma$:
$$R_{i,t} - R_{f,t} = \gamma_{0,t} + \gamma_{MKT,t}\hat{\beta}_{i,MKT} + \gamma_{SMB,t}\hat{\beta}_{i,SMB} + \gamma_{HML,t}\hat{\beta}_{i,HML} + \gamma_{MOM,t}\hat{\beta}_{i,MOM} + \eta_{i,t}$$

### 2. Multi-Factor Trend Gate™ Boolean Logic
A candidate asset passes the execution gate iff:
$$\text{GatePass}_i = \mathbb{I}(P_t > \text{MA20}_t) \times \mathbb{I}(\text{MACD\_DIF}_t > \text{MACD\_DEA}_t) \times (1 - \mathbb{I}(\text{WavePhase}_t = \text{Phase C}))$$

</details>

---

## 🤝 Citation & Research

If you use this repository or its methodology in your quantitative research or academic projects, please cite:

```bibtex
@software{RainbowFinGPT2026,
  author = {Wu, Yuxuan},
  title = {Rainbow-FinGPT: An Automated Quantitative Research Platform Powered by Multi-Factor Trend Gate and Financial LLMs},
  year = {2026},
  publisher = {GitHub},
  url = {https://github.com/YuxuanWuCN/stock-dashboard}
}
```

---

## 📄 License & Disclaimer

- **License**: Released under the [MIT License](LICENSE).
- **Disclaimer**: *All contents, signals, and simulated portfolio allocations produced by this project are strictly for academic research and educational purposes. Nothing herein constitutes financial or investment advice.*
