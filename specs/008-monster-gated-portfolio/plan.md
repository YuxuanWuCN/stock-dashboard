# 实现计划: 008-monster-gated-portfolio

## 技术栈与设计
- **后端算法**: Python 3.12, `bet_type_classifier.py`, `market_temperature.py`
- **回测与风控**: 严谨账户资产模型 (Cash + MV), 单股-8%止损, 移动止盈, 波动率倒数配仓
- **数据管线**: 60天历史日线无前视 walk-forward 选股与再平衡
- **前端展示**: 原生 HTML5/CSS3/ES6, ECharts 5.5.1, 响应式卡片与图表

## 架构演进
1. `src/analysis/bet_type_classifier.py` -> 导出 monster_score & 属性画像
2. `src/strategies/market_temperature.py` -> 导出宏观温度并注入组合引擎
3. `tools/paper_portfolio.py` & `tools/rebalance_all_portfolios.py` -> 统一风控与温度联动
4. `docs/index.html` & `docs/assets/app.js` -> 完整集成妖股雷达、单股性质卡片与模拟盘曲线
