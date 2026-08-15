# 规范质量检查清单: LLM 情绪信号度量与数据口径修复（Phase 0）

**Purpose**: 验证 spec.md 是否满足 speckit 规范质量标准
**Created**: 2026-08-15
**Feature**: [specs/004-sentiment-signal-fix/spec.md](../../004-sentiment-signal-fix/spec.md)

## 完整性

- [x] CHK001 必填部分齐全：User Scenarios & Testing、Requirements、Success Criteria、Assumptions 全部存在且非占位符
- [x] CHK002 背景含可复现依据：34.7% 数据出处（校准报告文件）、侦察结论与证据位置（_record_market_feedback 代码位置、样本统计）均已写入
- [x] CHK003 范围界定明确：做（诊断/数据修复/度量修复）与不做（词典/阈值/提示词增强留 Phase 2）边界清晰

## 可测试性

- [x] CHK004 每个 FR 可测试：FR-001~FR-011 均有明确可验证行为（MUST + 具体口径）
- [x] CHK005 用户故事独立可测：US1 诊断（零网络）、US2 数据修复（合成夹具手算对照）、US3 度量修复（构造样本手算）、US4 验证门禁，各含 Independent Test
- [x] CHK006 边界条件覆盖：K 线缺失/窗口不足/幂等/除零/停牌/样本量小/无前视
- [x] CHK007 澄清标记数量：0 个（全部有合理默认值，无需澄清）

## 一致性

- [x] CHK008 FR 与 US 对齐：FR-001/002→US1，FR-003/004/005/007/008/011→US2，FR-006→US3，FR-009/010→US4
- [x] CHK009 SC 与 FR 对齐：SC-001↔FR-001/002，SC-002/005↔FR-005，SC-003↔FR-010，SC-004↔FR-009，SC-006↔FR-010
- [x] CHK010 与差距分析/README 一致：诊断先行、真实收益口径、与抛硬币对比、不预设结论
- [x] CHK011 与项目约定一致：不伪造（None+标注）、不覆盖原始 K 线（AGENTS.md）、离线可复现

## 可衡量性与范围控制

- [x] CHK012 成功标准全部可衡量：置信区间、100% 覆盖、幂等逐字节一致、三选一对比结论
- [x] CHK013 假设记录合理默认：收益口径公式、中性阈值 0.1、回填时机、信号增强留 Phase 2
- [x] CHK014 无实现细节泄漏到成功标准：SC 均以可验证结果表述

## 结论

- 验证迭代 1：**14/14 全部通过**
- 状态：规范就绪，可进入下一阶段（speckit-plan）
