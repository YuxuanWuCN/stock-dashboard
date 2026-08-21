# Implementation Plan: 师叔 claw-quant 核心融合进 2.0版 判断主流程

**Branch**: `005-claw-quant-fusion` | **Date**: 2026-08-17 | **Spec**: [spec.md](./spec.md)

**Input**: /specs/005-claw-quant-fusion/spec.md

## Summary

按 claw-quant 的 Fisher→SFM→Graham→Markowitz+Damodaran 架构，把四块核心融合进 2.0版：① P1 领先指标引擎接真实 akshare 数据源（海关/现货/原厂代理），合成降级为 fallback；② P1 领先信号进 `compute_composite_score`（新增 leading 分量，让浏览器排名可见变化）；③ P2 因子半衰期/拥挤度（SFM 层）；④ P2 信念-执行分离（thesis/holdings）；⑤ P3 Damodaran 7 类约束监管。真实抓取在沙箱外由用户本地执行，代码用 mock/夹具验证。

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: pandas/numpy（已有）；akshare（真实抓取，仅用户本地环境，沙箱内 mock）

**Storage**: 文件系统 JSON（docs/data/leading_signals/、docs/data/factors/quality_report.json、组合/thesis JSON）

**Testing**: pytest（mock akshare、合成因子序列、约束引擎手算）

**Target Platform**: Windows 本地 + GitHub Pages 静态前端

**Project Type**: 单体 Python 分析系统 + 静态前端

**Performance Goals**: 领先指标抓取单标的 < 2s（本地）；评分新增分量 O(1) 追加

**Constraints**: 不推翻既有技术/行业分（只新增领先分量，小权重引入）；信息单向流动（下游不改上游）；外部请求可 mock 复现

**Scale/Scope**: 202 只标的；4 类领先映射；因子库现有因子集；7 类组合约束

## Constitution Check

*GATE: 依据 2.0版/AGENTS.md（项目事实章程）*

1. **质量工作流**：涉及 scoring.py/leading_indicators.py/factor_db.py 等源码改动 → begin-unit 起步，small→medium→heavy 收尾。
2. **数据与测试**：外部 akshare 请求必须可 mock/夹具复现（沙箱无网）；时间序列不 shuffle；领先信号缺省保持中性向后兼容。
3. **独立复核**：领先信号"换位"结论必须用独立断言（构造 A/B 标的 positive vs negative）复核，不依赖"git push 成功"或测试数量作正确性证明。

## Project Structure

### Documentation (this feature)

```text
specs/005-claw-quant-fusion/
├── plan.md              # 本文件
├── spec.md              # 功能规范
├── research.md          # Phase 0 侦察（claw-quant 架构映射）
├── data-model.md        # Phase 1 数据模型
├── quickstart.md        # 本地真实抓取入门
├── tasks.md             # 任务列表
├── contracts/           # 评分/因子质量/约束 输出契约
└── checklists/
    └── requirements.md
```

### Source Code（改动/新增）

```text
src/analysis/
├── leading_indicators.py   # 改：新增真实抓取 fetch_real_leading_signal + 降级
├── scoring.py              # 改：compute_composite_score 新增 leading 分量
├── factor_db.py            # 改：新增半衰期/拥挤度
├── factor_quality.py       # 新：半衰期/拥挤度计算
├── constraints.py          # 新：Damodaran 7 类约束
└── thesis.py               # 新：信念-执行分离（thesis/holdings）
tools/
└── fetch_leading_data.py   # 新：本地真实抓取入口
docs/data/leading_signals/  # 新：真实/合成领先信号落盘
```

**Structure Decision**: 单项目；新增模块放在 src/analysis/ 与既有评分/因子同层，避免过度分层（遵循项目现有平铺约定）。

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| 新增 3 个 src 模块（factor_quality/constraints/thesis） | 对应 claw-quant SFM/Graham/Damodaran 三层，职责各异 | 合并进 scoring.py 会使 17k 行文件更臃肿且职责混淆，违背单一职责 |
