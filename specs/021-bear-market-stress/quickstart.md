# Quickstart —— 熊市回测与压力测试

工作目录：仓库根（`Rainbow_FinGPTv2/`），Python 用 `.\.venv\Scripts\python.exe`。
PowerShell 会话先设环境（避免门禁 TEMP 冲突、GBK 乱码）：

```powershell
$env:TEMP="C:\Users\45607\AppData\Local\Temp\qgate_tmp"; $env:TMPDIR=$env:TEMP; $env:PYTHONIOENCODING="utf-8"
```

## 1. 跑全量压力测试（离线，约 18s）

```powershell
.\.venv\Scripts\python.exe scripts\run_bear_market_stress.py --out reports/fof_stress_20261014
```

产物：`historical_results.csv`、`synthetic_shock_results.csv`（153 行）、
`liquidity_results.csv`（9 情景）、`parameter_sensitivity.csv`（24 OFAT 变体）、
`state_transition_logs.csv`、`independent_recheck.json`、`bear_stress_report.md`。

## 2. 单元测试（33 项）

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_stress.py -q
```

关注四组关键锁：
- `TestRebalancerFillFraction` —— 半成交手算（0.45/0.55、换手 0.15）与向后兼容；
- `TestEngineLiquidityStress` —— 引擎级接线真实生效（默认值不变行为 / half_fill 降换手 / frozen 拦减仓 / delayed 生效）；
- `TestBearWindowDetection` / `TestShockMatrix` —— 窗口识别与冲击边界手算；
- `TestIndependentRecheck` —— 最大回撤独立复算。

## 3. 回归面

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -k "portfolio or fof or rebalancer or allocator or risk_budget"   # 105 项
.\.venv\Scripts\python.exe -m pytest tests -q --co                                                                 # 全量收集无 import 冲突
```

## 4. 质量门禁与提交（Rainbow_bug_finding 流程）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/run_quality.ps1 small
powershell -NoProfile -ExecutionPolicy Bypass -File tools/run_quality.ps1 medium --feature "portfolio_bear_stress"
git add -A; git commit -m "feat(portfolio): ..."   # feat: 提交必须先过 medium 凭证
```

## 5. 结果判读须知

- 历史窗口返回 0 个是**当前数据的真实结论**（仅 13 个月覆盖），不要调低 `dd_threshold` 掩饰。
- 报告中历史（§2）、合成（§3）、执行压力（§4）三类结论必须分开引用；合成冲击数字不得写成"历史实证"。
- 若流动性 9 情景出现除成本维度外完全相同的结果，说明接线失效，优先查 `run_backtest` 参数透传与 `_norm_date`。
