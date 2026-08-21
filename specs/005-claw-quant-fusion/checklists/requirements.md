# Requirements Checklist: 005-claw-quant-fusion

> 验证方式：静态审阅 + pytest（tests/test_leading_indicators_real.py、tests/test_scoring_leading.py、tests/test_factor_quality.py、tests/test_thesis.py、tests/test_constraints.py）

| ID | 需求 | 状态 | 证据 |
|----|------|------|------|
| FR-001 | 真实数据抓取 + data_source 字段 | ✅ 通过 | _fetch_akshare_series + fetch_real_leading_signal；test_fetch_real_success_returns_akshare_source |
| FR-002 | 抓取异常隔离降级 | ✅ 通过 | try/except + synthetic_fallback；test_fetch_real_failure_falls_back_to_synthetic、test_fetch_akshare_series_returns_none_without_akshare |
| FR-003 | 合成降级保留为 fallback | ✅ 通过 | generate_synthetic_leading_signal 语义不变 + data_source 标注 |
| FR-004 | compute_composite_score 领先分量 | ✅ 通过 | compute_leading_score + OPPORTUNITY_WEIGHTS.leading_score=0.10；test_composite_leading_affects_rank |
| FR-005 | 缺省/合成降级中性向后兼容 | ✅ 通过 | 中性 50；test_leading_synthetic_fallback_is_neutral、test_composite_backward_compatible_no_leading |
| FR-006 | 因子半衰期/拥挤度入质量报告 | ✅ 通过 | factor_quality.py + factor_db quality 子命令；test_write_factor_quality_report_integration |
| FR-007 | 信念-执行分离 | ✅ 通过 | thesis.py（Thesis/Holdings）；test_price_move_updates_holdings_but_not_thesis |
| FR-008 | 7 类约束引擎 | ✅ 通过 | constraints.py；test_single_position_truncated_to_limit 等 |
| FR-009 | pytest 全覆盖 | ✅ 通过 | 11 个新测试全绿；全量 555 passed |
| FR-010 | 本地抓取入口交付 | ✅ 通过 | tools/fetch_leading_data.py（沙箱降级合成验证 OK） |

## 遗留说明

- akshare 真实接口在沙箱 15s 读超时 → 降级合成；真实数据需用户本地运行 fetch_leading_data.py
- akshare 具体列名/符号以候选列名解析兜底，若本地接口变更按日志降级合成
