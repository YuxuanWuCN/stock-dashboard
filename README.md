# StockDashboard: An Automated Global Stock Research Platform Powered by FinGPT-Style Pipelines and Large Language Models

**Author:** Wu Yuxuan (吴宇轩)

**Affiliation:** Aberdeen Institute of Data Science and Artificial Intelligence, South China Normal University

**Date:** August 2026

**Repository:** [github.com/YuxuanWuCN/stock-dashboard](https://github.com/YuxuanWuCN/stock-dashboard) · **Live demo:** [yuxuanwucn.github.io/stock-dashboard](https://yuxuanwucn.github.io/stock-dashboard/)

> Chinese project guide (setup / configuration / troubleshooting): [README_CN.md](README_CN.md)

---

## Abstract

This paper presents **StockDashboard**, an end-to-end automated research platform that performs "after-hours homework" for a personal watchlist of **202 global financial instruments** spanning A-share, Hong Kong, US, and Korean equity markets as well as exchange-traded funds. A scheduled local pipeline ingests market data every trading day at 18:00 (CST), computes rule-based technical, risk, and industry scores, generates probabilistic 3-day and 5-day forecasts via K-nearest-neighbor historical similarity matching, and then synthesizes citation-grounded research reports through a **FinGPT-style** large-language-model (LLM) pipeline backed by the DeepSeek API (`deepseek-v4-flash`). A KHunter-merged strategy engine provides trading-signal research, event-driven backtesting, and a market-temperature gauge. To make model outputs accountable rather than anecdotal, the platform runs a daily **paper-trading duel** between a robust and an aggressive portfolio, recording predicted probabilities against realized returns as the foundation of a reinforcement-learning-style calibration (post-training) loop.

The system is deliberately conservative in its claims: forecasts are framed as historical statistics, stale or missing data is explicitly flagged instead of imputed, and no component is connected to any securities account. Preliminary results from the first trading day (single observation) are reported, and the project's scientific contribution lies in its *reproducible data pipeline, honest evaluation protocol, and calibration-first design* rather than in any short-term return.

**Keywords:** Financial Large Language Models; FinGPT; Retrieval-Augmented Generation; DeepSeek; Quantitative Research; Portfolio Calibration

---

## 1. Introduction

Financial markets are information-intensive and time-sensitive. For an individual investor, assembling nightly research across fragmented data sources — mainland China, Hong Kong, the US, Korea, and funds — is both labor-intensive and error-prone. Recent advances in large language models (LLMs) have opened a new path: models such as BloombergGPT and FinGPT demonstrate that domain-adapted LLMs can summarize news, extract sentiment, and generate research narratives at scale [1][2]. However, LLM outputs are prone to hallucination, and market predictions are fundamentally probabilistic. A research platform that simply "asks the model what to buy" is neither scientific nor trustworthy.

StockDashboard addresses this with a **hybrid architecture**: deterministic, reproducible rules compute the numbers, while the LLM explains and synthesizes evidence around them. The contributions of this work are summarized as follows:

1. **Multi-market automated data pipeline.** A direct-connection ingestion layer covers 202 instruments across four markets and funds (A-share 91, Hong Kong 36, US 44, Korea 10, ETFs/funds 21), with per-instrument fallback sources and an explicit *stale-data* flag so that outdated instruments are never silently treated as fresh.
2. **Rule-based scoring plus probabilistic forecasting.** Risk, opportunity, technical, and industry scores are computed from 5-year daily bars, and KNN historical similarity matching produces 3-day and 5-day probability forecasts that are auditable and reproducible.
3. **FinGPT-style LLM research pipeline.** News are analyzed in batched sentiment calls, retrieval-augmented generation (RAG) binds every claim to a dated source, and model identity and fallback behavior are strictly pinned to prevent silent degradation. The project reuses FinGPT's *methodology* (data-centric NLP, RAG, market feedback), not its model weights.
4. **KHunter-merged strategy engine.** Three signal strategies, an event-driven backtest with realistic T+1 costs, a "hunting ground" entry-point module, and a four-factor market-temperature gauge provide structured research signals.
5. **Paper-trading duel for calibration.** Two paper portfolios (robust 80%-position and aggressive fully-invested) are evaluated daily; predicted probabilities and realized returns are persisted to drive a reinforcement-learning-style post-training loop described in the project planning document.

The remainder of this paper is organized as follows. Section 2 reviews related work. Section 3 describes the system design. Section 4 reports experiments and preliminary results. Section 5 discusses limitations, and Section 6 concludes with future work.

## 2. Related Work

**LLMs for finance.** BloombergGPT pioneered domain-specific financial LLMs trained on a large proprietary corpus. FinGPT [1] proposed an open-source, data-centric alternative: a real-time data pipeline, LoRA-based lightweight fine-tuning, and reinforcement learning on stock prices to align sentiment with subsequent market performance. FinRL [4] provides a reinforcement-learning library for automated trading research. This project follows FinGPT's philosophy of *open data pipelines and market feedback*, while performing inference through the DeepSeek API (`deepseek-v4-flash`) rather than training or hosting open weights.

**Retrieval-augmented generation and parameter-efficient tuning.** RAG grounds LLM outputs in external evidence, and LoRA [5] enables cheap domain adaptation. The present system uses RAG for citation binding; LoRA/QLoRA weight adaptation is explicitly out of scope for the current API-based deployment and is planned for a future GPU-backed stage.

**Open-source financial data.** AkShare [6] and similar interfaces expose free market data; their instability motivates the multi-source fallback and stale-detection design adopted here.

**Strategy research (KHunter).** The strategy engine merges capabilities from the open-source KHunter quantitative project, including signal generation, entry-point ("hunting ground") logic, and event-driven backtesting, adapted to a JSON-based, no-trading red-line architecture.

## 3. System Design

### 3.1 Overall Architecture

```
                 Scheduled local task (18:00 CST, Windows Task Scheduler)
                 tools/daily_local.ps1
                 ┌──────────────────────────────────────────────────────────┐
                 │ 1. fetch_data.py      multi-market ingestion + stale check │
                 │ 2. build_ranking.py   scoring + KNN forecast + ranking     │
                 │ 3. run_strategies.py  signals / hunting ground / temp       │
                 │ 4. generate_reports.py  FinGPT-style LLM research pipeline  │
                 │ 5. daily_brief.py    "Tomorrow's Focus" digest              │
                 │ 6. paper_portfolio.py  robust vs aggressive duel + push     │
                 └──────────────────────────────────────────────────────────┘
                                        │  JSON (data contract)
                                        ▼
                 docs/data/  ──►  GitHub Pages (static frontend, no framework)
```

The backend is a local Python pipeline; the frontend is pure static HTML/CSS/JavaScript served by GitHub Pages, so the browser never computes core indicators nor calls the LLM directly. All artifacts are exchanged through a versioned JSON data contract.

### 3.2 Data Acquisition

| Market | Primary source | Fallback |
|---|---|---|
| A-share | Sina daily bars | Eastmoney |
| ETF / funds | Tencent | Eastmoney / fund platform |
| US stocks | Tencent (.OQ/.N suffixes) | — |
| Hong Kong stocks | Tencent (hk prefix) | — |
| Korea stocks | Naver | — |

All connections run in *direct mode* to avoid unstable proxy interference. A watchlist of 202 instruments is maintained in `watchlist.csv`; per-symbol results are stored as JSON. If an instrument's latest bar is older than a configurable threshold (`STALE_DATA_DAYS=10`), it is flagged `stale`, ranked at the bottom, and excluded from recommendations instead of being silently used.

### 3.3 Rule-Based Scoring and Probabilistic Forecasting

For each instrument, the system computes:

- **Risk score (0–100):** 20-day annualized volatility (30%), 60-day maximum drawdown (25%), ATR percentage (20%), volume-price anomalies and liquidity (10%), industry volatility and weakness (15%).
- **Opportunity score:** 35% expected-return percentile + 25% up-sample ratio + 20% technical score + 20% industry score.
- **Risk-adjusted score:** `opportunity × (1 − 0.5 × risk/100)`.

Three ranking views are produced (risk-adjusted, expected return, low-risk). A KNN module matches the current window against historical similar episodes over 5 years of daily bars and outputs probabilistic 3-day and 5-day forecasts (`pred_up3`, `pred_ret3`, `pred_up5`, `pred_ret5`), which are later used to score calibration. The "Tomorrow's Focus" digest (`daily_brief`) distinguishes the analysis day from the recommended next trading day — e.g., Friday's analysis produces Monday's focus — and excludes stale instruments from candidates.

### 3.4 FinGPT-Style LLM Research Pipeline

The LLM layer follows FinGPT's data-centric methodology while keeping determinism in the rule engine:

1. Technical/risk/industry/fundamental scores are computed by rules; the model never modifies these numbers.
2. News are analyzed in **batched sentiment** calls (one API call per batch) to control cost.
3. **RAG** retrieves news and announcements; every claim in a report is bound to a source, date, and quoted snippet.
4. The model is pinned to `deepseek-v4-flash`; environment variables cannot silently switch it.
5. If no key is available, the pipeline safely skips report generation — it never saves template-fabricated "degraded" reports as real ones, and a failed real API call does not interrupt the ranking.
6. Non-sensitive metadata (pipeline/backend/model/mode/fallback reason) is persisted for auditability.

Cost controls include a per-process daily call limit (800) and skip-if-existing logic. The API key lives only in local ignored files (`.env` / `api-key.txt`), is never committed, and is never written into reports or logs.

### 3.5 Strategy Engine (KHunter Merged)

- **Signal strategies:** multi-golden-cross resonance, limit-up pullback ("return horse"), and morning-star patterns, parameterized in `config/strategy_params.json`.
- **Backtest:** event-driven, T+1 settlement, realistic commission/stamp duty/transfer fees, take-profit/stop-loss, trailing stop, and loss cooldown; reports return, drawdown, Sharpe, and win rate.
- **Hunting ground:** support levels (MA20, key closes/opens) and entry-zone judgment (0–3%).
- **Market temperature:** four factors — advance/decline ratio 35%, limit-down 35%, limit-up follow-through 20%, turnover 10% — producing a market state and a position-size reference.

The red line is explicit: **research signals only, no automatic trading, no securities-account connection.**

### 3.6 Paper-Trading Duel and Calibration

Two paper portfolios (initial capital 1,000,000 CNY) run daily:

- **Robust portfolio:** ~80% invested across gold ETF and large-cap defensive names, 20% cash.
- **Aggressive portfolio:** fully invested in 8 instruments selected by a whole-universe aggressive scan (5-day probability, 3-day probability, and 20-day momentum).

Every trading day the system records each holding's *predicted* probabilities versus *realized* returns into performance files, producing the alignment data needed for the calibration loop (thresholds, score weights, prompts, and portfolio construction). According to the project's post-training plan, after 3–5 accumulated trading days the system will generate a calibration report and adjust parameters only if the observed alignment supports it.

## 4. Experiments and Preliminary Results

### 4.1 Coverage and Data Quality

All 202 instruments were fetched and ranked successfully (trade date 2026-08-07, date aligned by mode of per-symbol last-bar dates). One Hong Kong instrument (00011, Hang Seng Bank) was correctly flagged `stale` because third-party sources stop at 2026-01-14; it ranks last and is excluded from recommendations — a deliberate "flag, don't fabricate" behavior.

### 4.2 Market State and Daily Brief

On 2026-08-07 the market temperature was **69.5 (normal)**, implying a position-size reference of ~80%. The daily brief produced a "Monday (2026-08-10) Focus" list from Friday's analysis, with focus names including Mastercard, HSBC Holdings, Ping An, and Minsheng Bank.

### 4.3 Paper-Trading Duel: First Trading Day (n = 1)

| Portfolio | Baseline return (2026-08-07) |
|---|---:|
| Robust (80% position) | −0.29% |
| Aggressive (100% position) | +0.97% |

The aggressive portfolio's best contributor was 立新能源 (up +7.96% on the day), one of the stocks selected by the aggressive scan. **This is a single trading-day observation (n = 1) and must not be interpreted as evidence of predictive skill.** The purpose of the duel is to accumulate enough days to measure *calibration* (predicted probability vs. realized frequency), not to maximize short-term returns.

### 4.4 Toward Calibration

The recorded `pred_up3/pred_ret3/pred_up5/pred_ret5` values versus realized outcomes constitute the calibration dataset. Once 3–5 trading days are available, the platform will report alignment rates for the robust, aggressive, and equal-weight baselines and decide, with evidence, whether parameter adjustments are justified. All changes are version-controlled and revertible.

## 5. Discussion and Limitations

- **Sample size.** All current "results" rest on one trading day; no statistical conclusion can be drawn yet. The project explicitly rejects the goal of a guaranteed daily return as unrealistic and non-scientific.
- **Data-source dependency.** Third-party free interfaces can pause or lag (e.g., Hang Seng Bank), which the stale-flag mechanism mitigates but cannot eliminate.
- **Coverage gaps.** Capital-flow and event data requiring paid sources are not integrated; the watchlist is user-curated, so selection bias is inherent and acknowledged.
- **LLM limits.** DeepSeek API inference is not local fine-tuned FinGPT; hallucinations are mitigated by RAG citation binding but not eliminated.
- **No guarantees.** Historical statistics are not a promise of future performance, and the system never executes trades.

## 6. Conclusion and Future Work

StockDashboard demonstrates a feasible, honest, and reproducible pattern for personal quantitative research: deterministic rules for numbers, LLMs for evidence-bound narrative, and paper trading for calibration. Its first trading-day results are preliminary by design. Future work includes (i) accumulating calibration data and applying the post-training loop, (ii) deploying real FinGPT weights with local GPU serving, (iii) expanding multi-factor and cross-market risk experiments, and (iv) adding English-language coverage and further data-quality telemetry.

## Disclaimer

This project is for **research and education only**. It does not constitute investment advice, does not guarantee returns, does not connect to any securities account, and does not execute trades automatically. All forecasts are historical statistics, not promises of future performance.

## References

1. Yang, H., Liu, X.-Y., and Wang, C. D. (2023). *FinGPT: Open-Source Financial Large Language Models*. arXiv:2306.06031.
2. DeepSeek-AI (2024). *DeepSeek-V3 Technical Report*. arXiv:2412.19437.
3. DeepSeek-AI (2025). *DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning*. arXiv:2501.12948.
4. Liu, X.-Y., Yang, H., Chen, Q., Zhang, R., Yang, L., Xiao, B., and Wang, C. D. (2020). *FinRL: A Deep Reinforcement Learning Library for Automated Stock Trading in Quantitative Finance*. arXiv:2011.09607.
5. Hu, E. J., Shen, Y., Wallis, P., Allen-Zhu, Z., Li, Y., Wang, S., Wang, L., and Chen, W. (2021). *LoRA: Low-Rank Adaptation of Large Language Models*. arXiv:2106.09685.
6. AkShare (2026). *AkShare: An open-source financial data interface*. [https://akshare.akfamily.xyz/](https://akshare.akfamily.xyz/).
7. KHunter. *Open-source quantitative strategy research project* (methodology reference, adapted in this repository).
