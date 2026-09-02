# 实现计划：半导体存储 + 黄金避险跨周期双资产杠铃融合回测引擎

> **分支**：`017-storage-gold-joint-barbell` | **日期**：2026-09-03 | **规格**：`specs/017-storage-gold-joint-barbell/spec.md`  
> **输入**：存储与黄金两大独立实测数据集、市场状态机、动态调仓引擎  

---

## 概要
在物理时间隔离与无前视偏差约束下，融合半导体存储（进攻型成长）与黄金避险（防御型对冲）两大资产池（共 14 支股票）。接入市场三状态机（BULL / BEAR / SIDEWAYS），构建动态杠铃自适应资产配置模型（Regime-Switched Barbell Strategy），计算多资产分散化收益、Sharpe 提升与 Harvey Alpha $t$-stat。

---

## 技术背景

- **语言/版本**：Python 3.11+ / 3.13
- **主要依赖**：pandas, numpy, scipy, statsmodels, matplotlib
- **存储**：CSV (行情与因子) / JSON (指标与净值序列) / Markdown (学术报告)
- **测试**：pytest 自动化单元测试
- **性能目标**：250+ 交易日 × 14 支股票全量回测执行耗时 $< 2.0\text{ s}$
- **约束条件**：买入 0.125%，卖出 0.175%，闲置现金年化 1.5%

---

## 项目结构与文档

```text
specs/017-storage-gold-joint-barbell/
├── spec.md              # 功能需求规格
├── plan.md              # 实施架构与计划（本文件）
├── research.md          # 理论研究与资产配置文献
├── data-model.md        # 实体与数据契约
├── quickstart.md        # 运行与验证指引
└── tasks.md             # 任务开发清单

src/
└── analysis/
    └── storage_gold_joint_runner.py  # 存储+黄金联合杠铃回测核心引擎

scripts/
└── run_storage_gold_joint_backtest.py # CLI 执行脚本
```

---

## 实施阶段

- **阶段 0（研究）**：分析存储与黄金收益率低相关性与杠铃配置数学前沿；
- **阶段 1（设计与契约）**：构建 14 支标的数据模型与调仓状态机规则；
- **阶段 2（编码与回测）**：编写 `storage_gold_joint_runner.py`，执行逐步推进因果回测；
- **阶段 3（验证与报告）**：输出 JSON 数据工件、Markdown 报告并生成 300 DPI 净值对比图。
