# Implementation Plan: LLM 情绪信号度量与数据口径修复（Phase 0）

**Branch**: 004-sentiment-signal-fix | **Date**: 2026-08-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from specs/004-sentiment-signal-fix/spec.md

## Summary

修复市场反馈数据管线与度量口径：① 离线诊断报告（确认 ret 来源是 KNN 预测值、alignment_rate 分母污染）；② record_event 改为记录真实已实现收益（K 线收盘价计算），历史 144 样本幂等回填（快照+对比）；③ compute_summary 新增 directional_accuracy（决定性样本口径）并保留旧字段；④ Wilson 置信区间与 50% 基线对比的验证报告；质量门禁全绿。详见 research.md。

## Technical Context

**Language/Version**: Python（项目 venv 3.12；numpy/pandas/statsmodels 已就绪）

**Primary Dependencies**: 无新增依赖（Wilson 区间手写；K 线读 JSON；诊断/回填脚本用 pandas）

**Storage**: docs/data/kline/*.json（只读）、docs/data/llm/market_feedback.json（派生数据，回填式更新 + 快照）

**Testing**: pytest + 项目质量门禁（small/medium/heavy）；合成夹具 + 真实数据子集；泄漏注入

**Target Platform**: Windows 本地 + 每日流水线（record_event 契约修复后自然生效）

**Project Type**: 数据管线修复 + 审计工具

**Performance Goals**: 诊断/回填对 144 样本 < 1 分钟（K 线 JSON 读取为主）

**Constraints**: 无前视（收益只用 event_date 之后交易日）；不伪造（None+标注）；原始 K 线只读；离线可复现

**Scale/Scope**: 144 条历史样本 + 每日新增样本

## Constitution Check

> .specify/memory/constitution.md 仍为未填充模板；以 AGENTS.md 为等效依据。

| 章程/规则项 | 本计划合规性 | 依据 |
|---|---|---|
| 数据诚实（AGENTS.md 2） | 通过 | 真实收益 None 不伪造；诊断结论三选一 + 置信区间，不夸大 |
| 不覆盖原始数据（AGENTS.md 2） | 通过 | K 线只读；market_feedback 为派生数据，回填前快照 |
| 可复现（AGENTS.md 1） | 通过 | 诊断/回填零网络；幂等；夹具测试 |
| 质量工作流（AGENTS.md 1） | 通过 | begin-unit → small → medium → heavy；100% 覆盖 |
| 独立复核（AGENTS.md 3） | 通过 | realized_return 手算对照；构造样本手算 directional_accuracy |

*门禁结论：无违规。*

## Project Structure

### Documentation (this feature)

    specs/004-sentiment-signal-fix/
    ├── plan.md / research.md / quickstart.md / data-model.md
    ├── checklists/requirements.md   # 14/14 通过
    └── tasks.md                     # speckit-tasks 输出

### Source Code (repository root)

    src/market_feedback.py          # 修改：realized_return 函数 + record_event 契约 + compute_summary 新字段
    src/llm/generate_reports.py     # 修改：_record_market_feedback 改为从 K 线计算真实收益（预测值独立保存）
    tools/diagnose_sentiment_alignment.py   # 新增：离线诊断报告（根因审计 + 真实方向统计 + Wilson CI）
    tools/backfill_market_feedback.py       # 新增：历史样本真实收益回填（快照 + 幂等 + 对比）
    tests/test_market_feedback_realized.py  # 新增：契约/口径/回填/泄漏/诊断的单元与集成测试
    docs/data/llm/market_feedback.json      # 派生数据（回填更新 + 快照）
    reports/sentiment_signal_diagnosis.md   # 诊断报告（覆盖式归档）

**Structure Decision**: 核心修复在既有模块（market_feedback.py 是领域归属），审计类一次性脚本放 tools/，与项目惯例一致。

## Complexity Tracking

> 无违规，本表不适用。