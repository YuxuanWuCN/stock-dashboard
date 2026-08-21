# GitHub Issue 草稿（英文版，直接粘贴）

# Observed inconsistencies between ADRs and v2.1 README/SKILL.md + backtest evidence for two architecture improvements

**Repository**: serenity-chokepoint-investing-enhanced
**Author**: Yuxuan Wu (u11yw25@abdn.ac.uk, South China Normal University Aberdeen Institute, Information Management, Year 2)

Hi! My teacher asked me to study this framework carefully, and I spent two days reading all 6 ADRs, the README and SKILL.md line by line. I also ran two "sealed-box" backtests (Lixin New Energy 001258 and Micron MU) using the four-factor Fama-MacBeth + IR gating idea. I'd like to share what I found, hoping it helps.

---

## Part A — Documentation inconsistencies (probably v2.0 → v2.1 leftovers)

### A1. IR rejection threshold: 0.5 vs 0.3

- `docs/adr/0001-two-stage-multiplicative-model.md` (Hard Constraints table, and "IR < 0.5" in the Layer-2 section) says: **IR < 0.5 → Reject**
- `README.md` and `SKILL.md` (v2.1) say: **IR < 0.3 → Reject**, with 0.3–0.5 classified as "weak alpha, small position only"

**Suggestion**: Add a "v2.1 update" note in ADR-0001 pointing to the current 0.3 threshold, so future readers don't get conflicting signals.

### A2. Position-sizing adjustment: multiplicative vs additive

- `docs/adr/0006-catalyst-driven-position-sizing.md` uses a **multiplicative** formula: `Final = Base × (1+adj₁) × (1+adj₂) × ...`
- `README.md` / `SKILL.md` (v2.1) use **additive percentage-point** adjustments with a hard floor `max(Base×25%, 0.5%)`

**Suggestion**: Same — add a v2.1 note in ADR-0006 documenting the additive scheme and the hard floor.

---

## Part B — Two architecture improvements supported by backtest evidence

### B1. Bet-type classification should be data-driven, not LLM-guessed

ADR-0006 asks the agent to classify Super Beta / Catalyst Alpha / Event-Driven, but the criteria are qualitative (LLM judgment). I ran the same rule-based signal ensemble on two stocks:

| Stock | Character | Buy & Hold | Signal strategy (daily timing) |
|---|---|---|---|
| 立新能源 001258 | high-volatility "monster" stock | +85.3% | **+163.0%** (timing wins) |
| Micron MU | strong-trend winner | **+423.3%** | +161.0% (timing loses badly) |

The *same* strategy is inverted between the two. This is quantitative evidence that the optimal holding period/position logic depends on the stock's statistical character (volatility, momentum half-life, autocorrelation). **Suggestion**: add a lightweight statistical classifier (e.g. 20d volatility + momentum half-life + ATR) that maps the stock to a bet type, instead of relying on LLM judgment alone.

### B2. Missing trend-environment filter (worst blind spot)

On Micron MU, the ensemble's 1-day direction accuracy by regime:

| Regime (20d trend) | Accuracy |
|---|---|
| Up | 53.7% |
| **Down** | **45.2%** (below random!) |
| Flat | 56.8% |

The system systematically predicts "up" during downtrends. **Suggestion**: add a trend gate — when the stock's 20/60d trend is negative, suppress or downweight long signals. This is the single highest-impact fix I measured.

---

All backtest artifacts (reports + JSON + scripts) are available on request. Happy to turn any of these into a PR — especially the A1/A2 doc fixes, which are trivial and safe.

Thanks for reading!


---

# GitHub Issue 草稿（中文版，供你理解内容）

# 【Issue】ADR 与 v2.1 正文不一致 + 两个基于回测证据的架构改进建议

**仓库**: serenity-chokepoint-investing-enhanced
**作者**: 吴宇轩（华南师范大学阿伯丁学院 信管专业 二年级；u11yw25@abdn.ac.uk）

师叔您好！老师让我认真研读这个框架，我花了两天逐字读完了全部 6 篇 ADR、README 和 SKILL.md，并用"封箱回测"跑了两只标的（立新能源 001258、美光科技 MU），有一些发现想分享给您。

## A 部分 —— 文档不一致（疑似 v2.0→v2.1 迭代遗留）

**A1. IR 淘汰阈值 0.5 vs 0.3**
- `ADR-0001` 硬约束表写 IR<0.5 拒绝；`README/SKILL.md`（v2.1）已改为 IR<0.3 拒绝（0.3~0.5 为弱 alpha 仅小仓位）
- 建议：在 ADR-0001 加"v2.1 更新说明"，指向现行 0.3 阈值

**A2. 仓位调整：乘法 vs 加权**
- `ADR-0006` 用乘法公式；v2.1 正文已改为绝对百分点加减 + 硬地板 max(Base×25%, 0.5%)
- 建议：在 ADR-0006 补 v2.1 说明

## B 部分 —— 两个有回测证据的架构改进

**B1. 赌注类型应数据化分类**：同一套信号，立新能源上择时翻倍（+163% vs 持有 +85%），美光上择时跑输（+161% vs 持有 +423%）——说明持仓周期/仓位逻辑取决于标的的统计特征（波动率、动量半衰期）。建议加一个轻量统计分类器。

**B2. 缺趋势环境过滤**：美光回测中，下跌段集成预测命中率仅 45.2%（低于随机），系统在下跌中系统性看多。建议加"趋势门"：20/60 日趋势向下时抑制看多信号。这是我实测影响最大的一个改进点。

所有回测产物（报告/JSON/脚本）可提供。如果方便，我可以把 A1/A2 的文档修复直接做成 PR。

