# 任务清单 010：可插拔因子定价引擎与贝叶斯闭环校准系统 (Tasks-Kit 010)

## 任务执行进度

- [x] **T-001**: 实现 `src/analysis/factor_providers.py` 可插拔因子适配器（Akshare, Kenneth French, Wind/CSMAR 迁移桩）。
- [x] **T-002**: 完善 `src/analysis/fama_macbeth.py` 中的 `FamaMacBethEngine` 与 Newey-West HAC 滞后计算公式 $q = \lfloor 4(T/100)^{2/9} \rfloor$。
- [x] **T-003**: 更新 `src/build_ranking.py`，将多因子定价、$\beta$ 载荷与特质 $\alpha$ 输出注入每日排行榜 JSON 数据中。
- [x] **T-004**: 在 `src/analysis/similarity.py` 中增加 `process_node` 工艺节点空间过滤接口与开关配置。
- [x] **T-005**: 实现 `src/analysis/calibrate_weights.py`，完成基于模拟盘交叉熵与 Brier Score 的贝叶斯/优化调优算法。
- [x] **T-006**: 创建 `.github/workflows/calibrate.yml` 每周日定时校准流水线。
- [x] **T-007**: 编写单元测试 `tests/test_factor_providers.py` 与 `tests/test_calibration_loop.py`。
- [x] **T-008**: 运行全量测试套件，确保 100% 通过（92/92 测试通过）。
