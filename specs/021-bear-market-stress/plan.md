# 实现计划：熊市回测与压力测试

**分支**：`fix/real-data-rebuild`（实施）/ `specs/021-bear-market-stress` | **日期**：2026-10-14
**规格**：[spec.md](./spec.md)（增补最小化修复规范）与 `工作规划/熊市回测与压力测试方案_交主Agent.md`
**研究**：[research.md](./research.md) | **任务**：[tasks.md](./tasks.md) | **检查清单**：[checklist.md](./checklist.md)

## 概要

在既有 FOF 组合引擎（`src/portfolio/`）与压力测试体系上，完成 T-NALE 与 Risk-Constrained NALE 信号隔离与异质时效逻辑复用修复。由 `scripts/run_bear_market_stress.py` 输出独立修订产物至 `reports/fof_stress_20261014_fixed/`，绝不覆盖旧结果与基准。

## 技术背景

**语言/版本**：Python 3.11+（`.venv`）
**主要依赖项**：pandas、numpy、dataclasses（无新增第三方依赖）
**存储**：本地 JSON K 线（`docs/data/kline/{code}.json`）→ 产物 CSV/MD/JSON
**测试**：pytest（`tests/test_portfolio_stress.py`）
**目标平台**：Windows 本地离线运行
**约束条件**：全量编排 <60s；默认参数 100% 向后兼容；不覆盖旧产物；不人为调参。

## 宪章检查

- 通过：无新增外部网络请求（离线 K 线）；所有新参数默认值不改变既有行为。
- 通过：质量门禁已开启活动单元 `fix_tnale_stress_isolation`。

## 项目结构

### 文档（此功能）

```text
specs/021-bear-market-stress/
├── spec.md              # 最小化规范（5大范围）
├── plan.md              # 本文件
├── tasks.md             # 任务清单
├── checklist.md         # 需求质量检查清单
├── research.md          # Phase 0：数据覆盖 / T-NALE 现状 / 引擎缺口
├── data-model.md        # Phase 1：实体与状态转换
├── quickstart.md        # Phase 1：运行与验证入口
└── contracts/           # Phase 1：函数级契约
    └── stress-contracts.md
```

### 源代码

```text
src/portfolio/
├── stress_scenarios.py   # 新增：窗口识别/冲击矩阵/流动性情景/OFAT 网格
├── backtest.py           # 扩展：STRESS_MODES + t_nale/defensive_only +
│                         #   fill_fraction/delayed_exit_days/frozen_exit_days + _norm_date
├── rebalancer.py         # 扩展：apply_deadband_and_execute(fill_fraction=)
scripts/run_bear_market_stress.py   # 新增：编排 CLI（596 行）
tests/test_portfolio_stress.py      # 新增：33 项单测
reports/fof_stress_20261014/        # 产物目录（随提交固化一次结果）
```

**结构决策**：单项目结构，压力域逻辑独立成 `stress_scenarios.py`（纯函数、无 I/O），编排与 I/O 全部收敛在 scripts 层，引擎只加参数不加新类——与既有 allocator/rebalancer/risk_budget 分层一致。

## 设计要点（Phase 1 结论摘要）

1. **窗口识别与回测解耦**：`identify_bear_windows` 只吐 `BearWindow`（含 pre/post pad、非重叠），回测复用主循环。
2. **冲击只改副本**：`apply_price_shock` 返回新 DataFrame，原数据永不被污染（有不变性测试）。
3. **执行压力三参数各管一段**：`fill_fraction` 在 rebalancer 成交层（未成交保留原仓）；`delayed_exit_days`/`frozen_exit_days` 在引擎主循环风险门层（严重度跳变 trigger 收盘后判定，窗口从 i+1 起算）。
4. **换手上限走现成 `RebalanceConfig.max_single_day_turnover`**，不另造机制。
5. 详细实体见 [data-model.md](./data-model.md)，函数契约见 [contracts/stress-contracts.md](./contracts/stress-contracts.md)。

## 复杂度跟踪

无宪章违规。未引入新抽象层；`LiquidityScenario`/`ShockScenario` 为轻量 dataclass，与既有 `BearWindow` 风格一致。
