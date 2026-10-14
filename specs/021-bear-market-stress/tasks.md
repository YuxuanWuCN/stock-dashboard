# 任务分解：熊市压力测试 T-NALE 与 Risk-Constrained NALE 隔离与时效复用修复

**规范**：[spec.md](./spec.md)  
**当前状态**：已完成 (Completed)  

---

## 任务列表

### Phase 1: 逻辑抽引与接口规范 (Setup & Logic Modularization)
- [x] **Task 1.1**：在 `src/portfolio/stress_scenarios.py` 或 `src/portfolio/signal_adapter.py` 中抽取可复用的点时异质 T-NALE 信号生成函数与行业异质半衰期先验（`SECTOR_HALF_LIVES`），严格复用 `tools/run_fof_pipeline.py` 的信息年龄追踪机制。
- [x] **Task 1.2**：检查并增强 `src/portfolio/backtest.py` 的 `_apply_t_nale_decay` 与 `run_backtest`，使其支持按标的传入异质半衰期字典（`Dict[str, float]`）及逐日动态信息年龄，避免因标量常量乘除在截面归一化中约去。

### Phase 2: 压力测试脚本接线与目录隔离 (Stress Script Fixes & Directory Protection)
- [x] **Task 2.1**：修改 `scripts/run_bear_market_stress.py` 中的 `generate_signals` 与 `run_all_modes`，为 `t_nale` 生成带有异质半衰期与动态年龄分化的点时有效信号，与 `risk_constrained_nale`（静态无时效衰减）彻底解耦隔离。
- [x] **Task 2.2**：修复 `scripts/run_bear_market_stress.py` 中 `run_param_sensitivity` 的模式调用错误：半衰期敏感性测试必须传入 `mode="t_nale"` 而非 `"risk_constrained_nale"`。
- [x] **Task 2.3**：更新默认输出路径为 `reports/fof_stress_20261014_fixed`，严禁写入或覆盖 `reports/fof_stress_20261014/` 和 `reports/fof_rebuild_20261013/`。

### Phase 3: 自动化测试套件构建 (Verification & Invariance Tests)
- [x] **Task 3.1**：在 `tests/test_portfolio_stress.py` 中增加用例：
  1. 静态 NALE 与 T-NALE 产生截面差异有效信号与目标配置权重（`test_static_vs_t_nale_signal_differentiation`）；
  2. 模式调用验证：T-NALE 模式不会被映射成 risk_constrained_nale（`test_mode_isolation_no_aliasing`）；
  3. 点时性与未来数据截断不变性测试（`test_t_nale_point_in_time_truncation_invariance`）；
  4. 输出目录隔离测试：运行脚本不会覆盖 `reports/fof_stress_20261014/` 与 `reports/fof_rebuild_20261013/`（`test_output_dir_isolation`）。
- [x] **Task 3.2**：运行质量门禁测试（small -> medium），确保测试全部通过且断言强度严格。

### Phase 4: 执行与独立复核报告 (Execution, Metric Comparison & Final Report)
- [x] **Task 4.1**：运行 `scripts/run_bear_market_stress.py` 生成新产物至 `reports/fof_stress_20261014_fixed/`。
- [x] **Task 4.2**：对比修复前后的新旧结果，进行独立基准复核与统计检验，如实报告全部指标变化与客观局限性（不调参、不隐藏劣化指标）。
