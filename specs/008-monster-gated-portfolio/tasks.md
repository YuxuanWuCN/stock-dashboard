# 任务清单: 008-monster-gated-portfolio

## 阶段 1: 核心算法与风控管线标准化
- [x] T001 [P] [US1] 强化 `src/analysis/bet_type_classifier.py` 妖股指数 (monster_score) 与特征导出
- [x] T002 [P] [US1] 在 `src/build_ranking.py` 中将 bet_type 注入到排行榜全局数据合同
- [x] T003 [US2] 建立大盘市场温度与仓位联动的 60 天 walk-forward 回测引擎 (`backtest_60d_v4_temp_gated.py`)
- [x] T004 [US2] 在 `tools/paper_portfolio.py` 注入严谨资产结算模型与温度仓位联动数据

## 阶段 2: 前端呈现与交互整合
- [x] T005 [P] [US1] 在 `docs/index.html` 新增【🔥 妖股鉴定器】导航与页面板块
- [x] T006 [P] [US3] 在 `docs/assets/app.js` 中实现妖股雷达 Top 榜、单股性质诊断与筛选渲染
- [x] T007 [US3] 优化模拟盘净值曲线 (`docs/test_paper.html` & `docs/portfolio.html`) 展示 60 天回测与等权基准对比

## 阶段 3: 代码与目录规范整理 (Clean-up)
- [x] T008 [P] 清理根目录无用的中间诊断脚本 (`_check_market_env.py`, `_diag.py`, `_small_test.py` 等)
- [x] T009 [P] 规范回测与风控工具位置并建立版本归档
- [x] T010 运行代码质量门禁并推送到 GitHub Pages 远程仓库
