# 快速上手: Fama-MacBeth 多因子引擎（Phase 1）

**Feature**: 003-fama-macbeth-engine | **Date**: 2026-08-15

## 前置依赖（R1）

```powershell
.venv\Scripts\pip install statsmodels   # 自动安装 scipy、patsy
```

同步更新 requirements.txt（实施任务 T 之一）。

## 1. 准备因子数据（用户提供 CSV）

把 CSMAR/RESSET 导出的 CSV 按 contracts/factors-csv.md 整理（date,MKT,SMB,HML,MOM[,rf]），放入任意路径，如：

```
docs/data/factors/carhart4_20260814.csv
```

## 2. 导入因子库并质检

```powershell
.venv\Scripts\python -m src.analysis.factor_db import --csv docs\data\factors\carhart4_20260814.csv
```

输出：入库统计（行数/区间/缺口率）与数据质量报告（docs/data/factors/quality_report.json）。

## 3. 运行排行榜（含 Alpha 门控）

```powershell
.venv\Scripts\python -m src.build_ranking
```

流水线在机会分之后自动执行两阶段回归与门控，输出：

- ranking.json / {code}.json：新增 alpha_gate 字段组（见 contracts/alpha-gate-output.md）
- 报告：每标的 alpha/p/IR/betas/VIF 与拒绝原因

## 4. 独立运行回归（调试用）

```powershell
.venv\Scripts\python -m src.analysis.fama_macbeth --code 600519
```

## 5. 测试与门禁

```powershell
.venv\Scripts\python -m pytest tests\test_fama_macbeth.py tests\test_fama_macbeth_integration.py -q
tools\run_quality.ps1 begin-unit   # 按 AGENTS.md 工作流
```

## 常见失败排查

| 现象 | 原因与处理 |
|---|---|
| 导入报"缺失列" | CSV 表头与契约不符，按 contracts/factors-csv.md 重排 |
| 回归输出 null | 数据不足最小窗口（默认 1 年）；新股正常现象 |
| 全池 reject | 正常统计现象；激进组合按原机会分回退并告警（spec 假设） |
| 因子与 K 线对不齐 | 查看质量报告中的剔除日期清单，交集策略已记录 |