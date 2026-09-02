# 任务清单：存储 + 黄金双板块杠铃融合回测

> **功能分支**：`017-storage-gold-joint-barbell`  

- [x] **Task 1: 核心引擎实现** (`src/analysis/storage_gold_joint_runner.py`)
  - [x] 1.1 资产池与价格/因子时间序列对齐加载
  - [x] 1.2 市场状态机驱动的动态杠铃资产配置模型实现
  - [x] 1.3 4 大策略并行逐步推进仿真与净值结算
  - [x] 1.4 相关系数、分散化比率、Sharpe、MaxDD、Harvey t-stat 计算
- [x] **Task 2: CLI 运行脚本与图表绘制** (`scripts/run_storage_gold_joint_backtest.py`)
  - [x] 2.1 运行回测并落盘 JSON 数据工件 (`docs/data/paper/backtest_storage_gold_joint.json`)
  - [x] 2.2 自动生成 300 DPI 净值对比与水下回撤高清图 (`reports/figures/backtest_storage_gold_joint/fig1_nav_and_drawdown.png`)
  - [x] 2.3 生成 Markdown 学术评估报告 (`reports/tables/backtest_storage_gold_joint_report.md`)
- [x] **Task 3: 单元测试套件** (`tests/test_storage_gold_joint_runner.py`)
  - [x] 3.1 覆盖数据对齐、状态机权重分配、无前视因果性与指标计算 (3 项单元测试 100% PASS)
