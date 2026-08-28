# Implementation Plan: 立新能源教师框架验证 (Teacher Framework Validation)

**Branch**: `001-teacher-framework-validation` | **Date**: 2026-08-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-teacher-framework-validation/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

把经济学老师对立新能源（001258）的口头分析翻译为可验证规则，用历史数据逐条验证，产出面向老师第二次对话的对比报告。

核心验证点：
1. **翻倍事实核验**：连板口径 +112%、滚动低点口径 +100.8%，翻倍成立
2. **三组操作对照**：滚动 60 日低点翻倍触发（唯一触发点 2026-07-24）→ 次日开盘价成交 → 全清仓 / 减至 1/3 / 持有不动 在 5/10/20 日窗口收益与回撤
3. **回调统计**：涨停后 20 日内回调（自高点回落 ≥10%）的发生率、等待天数、幅度分布
4. **四因子风险评分**：规模/资金/行业/情绪 → 每日 0-100 评分曲线 → 检验对 07-28/07-29 连续跌停的预警能力
5. **报告**：验证结论分类表 + ≥2 研究问题 + 对话开场话术，存 reports/

范围：只做研究验证，**不修改 src/strategies/**（澄清 Q1）。

## Technical Context

**Language/Version**: Python 3.x（项目 .venv，pandas 2.3.3）

**Primary Dependencies**: pandas, numpy, json（项目已有依赖，无需新增）

**Storage**: 读取 docs/data/kline/001258.json（K线 [开,收,低,高]）、docs/data/strategy/market_temperature.json（市场温度）；输出 reports/ 下验证报告

**Testing**: pytest（项目已有质量门禁体系，本次为研究脚本，配冒烟断言即可）

**Target Platform**: Windows 本地运行（与项目一致）

**Project Type**: 数据分析/研究脚本（非库、非服务）

**Performance Goals**: 268 根K线，秒级完成，无性能压力

**Constraints**: 不修改 src/strategies/（范围澄清）；不写数据库；研究脚本独立于生产流水线

**Scale/Scope**: 单标的（001258）验证研究，5 个 story

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- 项目 constitution.md 为官方模板占位符（未实质化），无强制约束 → GATE 通过
- 项目红线（README）：研究信号仅供参考，不自动交易，不构成投资建议 → 报告中所有结论以"历史统计"表述

## Project Structure

### Documentation (this feature)

```text
specs/001-teacher-framework-validation/
├── spec.md              # 规格 + 澄清（已定稿）
├── plan.md              # 本文件
├── research.md          # 数据勘察输出
├── tasks.md             # 任务拆解（/speckit-tasks 生成，本 feature 由 plan 直接细化）
└── checklists/
    └── requirements.md  # 规格质量清单（已通过）
```

### Source Code (repository root)

```text
# 单项目结构：研究脚本独立于生产流水线（不修改 src/）
tools/
└── validate_teacher_framework.py   # 本次验证主脚本（幂等、输出报告到 reports/）

reports/
└── teacher_framework_validation.md # 验证报告（面向老师第二次对话）
```

**Structure Decision**: 采用单脚本结构。验证是纯研究任务、只读数据、不改 src/，单文件脚本最符合 KISS；输出为 markdown 报告。脚本放 tools/（与 aggressive_scan.py、calibration.py 等同级，属"工具/研究"性质）。

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

无（无违规）。

## Implementation Phases

### Phase 0 - Research（数据勘察）

- 确认 001258 K线列序 [开,收,低,高]，268 根无异常
- 扫描滚动 60 日低点翻倍触发点（预期唯一：2026-07-24）
- 确认 market_temperature.json 结构与可用字段
- 确认市值数据可得性（预期不可得 → 标注未验证）
- 产出 research.md

### Phase 1 - Design（脚本设计）

- 脚本结构：load 数据 → 核验事实（Story1）→ 触发扫描 + 三组回测（Story2）→ 回调统计（Story3）→ 四因子评分 + 预警检验（Story4）→ 报告生成（Story5）
- 数据契约：统一以 pandas DataFrame（日期升序，列 date/open/close/low/high/volume）为中间格式
- 输出契约：reports/teacher_framework_validation.md

### Phase 2 - Implementation（实现 + 验证）

- 实现 validate_teacher_framework.py（含 5 个 story 的函数）
- 冒烟断言：触发点数量=1、三组收益可复算、回调分布非空、风险评分 0-100 范围
- 运行脚本，检查报告完整

## Success Criteria Mapping

| Spec 成功标准 | 实现验证点 |
|---------------|-----------|
| SC-001 翻倍结论 | Story1 两个口径涨幅输出 |
| SC-002 三组收益全计算 | Story2 触发点扫描 + 三组回测 |
| SC-003 回调统计完整 | Story3 发生率/中位天数/中位幅度 |
| SC-004 四因子评分曲线 | Story4 每日评分 + 行业缺数据标注 |
| SC-005 预警对比数字 | Story4 跌停前5日均分 vs 全样本均分 |
| SC-006 报告完备 | Story5 分类表 + ≥2 研究问题 + 话术 |
| SC-007 无未来数据泄漏 | 截断 2026-08-13 + 缺数据显式标注 |
