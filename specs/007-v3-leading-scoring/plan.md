# Implementation Plan: 3.0 前沿信息主导评分引擎与双轨对比

**Branch**: `007-v3-leading-scoring` | **Date**: 2026-08-18 | **Spec**: [spec.md](./spec.md)

## Technical Context

- **Language/Version**: Python 3.12, Vanilla JS (ES6)
- **Architecture**: 双轨并存（2.0 保持现有逻辑不改动，3.0 作为新一代前沿主导引擎）
- **Storage**: `docs/data/analysis/ranking.json` (2.0) & `docs/data/analysis/ranking_v3.json` (3.0)
- **Testing**: pytest (tests/test_scoring_v3.py)

## Project Structure

```text
src/analysis/
├── scoring.py          # 2.0 评分引擎（保持稳定不变）
└── scoring_v3.py       # 3.0 前沿主导评分引擎（新增）

tools/
└── compare_v2_v3.py    # 2.0 vs 3.0 榜单生成与比对分析器

reports/
└── v2_vs_v3_comparison.md  # 详细比对报告

docs/
├── index.html          # 增加 2.0 / 3.0 切换器
├── assets/app.js       # 增加 ranking_v3 数据加载与视图切换
└── data/analysis/
    ├── ranking.json    # 2.0 榜单
    └── ranking_v3.json # 3.0 榜单
```
