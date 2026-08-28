# 快速上手: LLM 情绪信号度量与数据口径修复（Phase 0）

**Feature**: 004-sentiment-signal-fix | **Date**: 2026-08-15

## 1. 离线诊断（零网络，先看真相）

    .venv\Scripts\python tools\diagnose_sentiment_alignment.py

输出：根因审计（ret 来源代码位置）、alignment_rate 分母构成分解、真实方向统计（Wilson 95% CI vs 50% 基线）、三选一结论。
报告归档：reports/sentiment_signal_diagnosis.md

## 2. 历史样本回填（幂等，可重跑）

    .venv\Scripts\python tools\backfill_market_feedback.py

行为：首次运行先快照（market_feedback.backup_YYYYMMDD.json）→ 用 K 线真实收益重算 realized_ret_3d/5d → 原子写回 → 输出回填前后对比。
重跑结果逐字节一致（幂等）。

## 3. 度量验证

    .venv\Scripts\python -c "from src.market_feedback import MarketFeedbackTracker; import json; t=MarketFeedbackTracker(); print(json.dumps(t.compute_summary(), ensure_ascii=False, indent=2))"

检查新字段：directional_accuracy、decisive_sample_count、no_score_sample_count（旧 alignment_rate 仍在）。

## 4. 测试与门禁

    .venv\Scripts\python -m pytest tests\test_market_feedback_realized.py -q
    tools\run_quality.ps1 begin-unit   # 按 AGENTS.md 工作流

## 常见问题

| 现象 | 原因与处理 |
|---|---|
| 样本 realized_ret 为 null | K 线缺失或窗口不足（event_date 距最新交易日 <5 天），正常标注 |
| 诊断结论"无显著差异" | 样本量不足或信号确实弱；如实入档，留 Phase 2 增强 |
| 回填前后 ret 变化大 | 预期现象：旧值来自 KNN 预测，新值来自真实收益 |