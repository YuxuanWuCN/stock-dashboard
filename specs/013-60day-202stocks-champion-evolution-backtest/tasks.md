# Task Breakdown: 60日202支股票全池物理隔离量化回测与每周冠军演化

- [x] **Task 1: 构建 202 支股票 60 交易日物理隔离原始数据集**
  - 在 `data/raw/backtest_paper_60d_202stocks/` 组装包含 202 支股票/ETF 的真实日 K、多因子特征与大盘温度时序。
  - 严格保持只读。
- [x] **Task 2: 研发拟真交易人与每周冠军演化回测执行器**
  - 构建 `src/pipeline/paper_60d_evolution_runner.py`。
  - 实现六大主力组合日频择票换仓、-8% 强制止损、Trend Gate 过滤与大盘温度门控。
  - 实现每周五复盘周冠军评选算法（Weekly Sharpe / Calmar）与参数派生变体生成。
- [x] **Task 3: 执行回测并计算四维量化正确率与预测命中率矩阵**
  - 统计方向预测命中率（对比 70% 基线）、交易胜率、盈亏比与 Brier 校准度。
  - 生成 `reports/tables/backtest_paper_60d_202stocks/accuracy_and_performance_report.md`。
- [x] **Task 4: 渲染出版级高清走势图与策略演化树图**
  - 生成 `reports/figures/backtest_paper_60d_202stocks/` 下的 3 张高清图表（六大组合净值图、水下回撤图、策略演化派生树）。
- [x] **Task 5: 全量同步更新前端 HTML 看板与模拟盘数据包**
  - 全量更新 `docs/data/paper/`、`docs/data/quantitative/` 与 `docs/portfolio.html`、`docs/index.html`。
- [x] **Task 6: 单元测试与端到端 Smoke Test 验证**
  - 编写 `tests/test_paper_60d_evolution.py` 确保 100% 测试通过。
