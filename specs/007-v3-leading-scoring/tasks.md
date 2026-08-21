# Tasks: 3.0 前沿信息主导评分引擎与双轨对比

- [X] T001 [P] 编写 `src/analysis/scoring_v3.py`：实现 3.0 机会分（Leading 45% + KNN 30% + Tech 25%）与财报排雷门禁
- [X] T002 [P] 编写 `tests/test_scoring_v3.py` 单元测试（前沿主导打分、排雷门禁拦截、正常通过不加分）
- [X] T003 编写 `tools/compare_v2_v3.py`：生成 3.0 榜单 `ranking_v3.json` 与比对报告 `reports/v2_vs_v3_comparison.md`
- [X] T004 在 `docs/index.html` 与 `docs/assets/app.js` 中实现 2.0 / 3.0 榜单的 CLI 切换胶囊
- [X] T005 运行全量测试与本地浏览器实测验收