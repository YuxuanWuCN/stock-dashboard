# 快速入门：Rainbow-FinGPT 策略增强与学术创新

**项目**：Rainbow-FinGPT 提升计划  
**目标读者**：开发者、研究人员  
**预计时间**：30 分钟

---

## 1. 环境准备

### 1.1 依赖安装

```bash
# 基础依赖（已有）
pip install pandas numpy statsmodels scikit-learn matplotlib

# 新增依赖（策略增强）
pip install scipy

# 新增依赖（因果推断，可选）
pip install dowhy networkx
```

### 1.2 数据准备

确保以下数据文件存在：

```
data/
├── factors/
│   └── carhart_4factors.csv          # Carhart 四因子（必需）
├── processed/
│   ├── storage_prices.csv            # 存储板块行情
│   ├── gold_prices.csv               # 黄金板块行情
│   └── green_energy_prices.csv       # 绿电板块行情
└── market/
    └── sse_index.csv                 # 上证指数（用于状态识别）
```

**快速生成四因子数据**（如果没有）：
```python
from src.utils.benchmark import build_carhart_factors

carhart = build_carhart_factors(
    start_date='2025-01-01',
    end_date='2026-08-31'
)
carhart.to_csv('data/factors/carhart_4factors.csv')
```

---

## 2. 策略增强快速验证

### 2.1 因子正交化（5 分钟）

**场景**：验证立新能源案例 - 高涨幅但 Alpha 不显著

```python
from src.pricing.factor_orthogonalization import orthogonalize_factor
import pandas as pd

# 1. 加载数据
立新能源_returns = pd.read_csv('data/processed/立新能源_returns.csv', index_col='date', parse_dates=True)
carhart = pd.read_csv('data/factors/carhart_4factors.csv', index_col='date', parse_dates=True)

# 2. 正交化
residual, exposures = orthogonalize_factor(
    candidate_factor=立新能源_returns['return'],
    carhart_factors=carhart,
    return_exposure=True
)

# 3. 查看结果
print(f"原始收益: {立新能源_returns['return'].mean():.4f}")
print(f"特质成分: {residual.mean():.4f}")
print(f"市场暴露: {exposures['MKT']:.2f}")
print(f"R²: {exposures['R2']:.2f}")  # 如果 R²=0.65，说明 65% 收益来自风格暴露

# 预期输出：
# 原始收益: 0.0032
# 特质成分: 0.0008  # 大幅降低
# 市场暴露: 0.83     # 高度相关
# R²: 0.65
```

**解读**：如果 R² 很高（>0.6），说明该股收益主要来自风格因子，而非特质 Alpha。

---

### 2.2 市场状态识别（5 分钟）

**场景**：识别 2026 年 A 股牛熊转换点

```python
from src.risk.regime_detector import detect_market_regime, simulate_regime_transitions
import pandas as pd

# 1. 加载上证指数
sse_index = pd.read_csv('data/market/sse_index.csv', index_col='date', parse_dates=True)['close']

# 2. 识别当前状态
regime, confidence, indicators = detect_market_regime(
    market_index=sse_index,
    date='2026-08-31'
)

print(f"当前状态: {regime.value}")
print(f"置信度: {confidence:.2f}")
print(f"MA20: {indicators['MA20']:.2f}, MA60: {indicators['MA60']:.2f}")
print(f"MACD: {indicators['MACD']:.2f}")

# 3. 模拟历史状态转换
transitions = simulate_regime_transitions(
    market_index=sse_index,
    start_date='2025-01-01',
    end_date='2026-08-31'
)

# 4. 可视化
import matplotlib.pyplot as plt
plt.figure(figsize=(12, 6))
plt.plot(sse_index.index, sse_index.values, label='上证指数', alpha=0.5)
colors = {'bull': 'green', 'sideways': 'yellow', 'bear': 'red'}
for _, row in transitions.iterrows():
    plt.axvspan(row['date'], row['date'] + pd.Timedelta(days=1), 
                color=colors[row['regime']], alpha=0.3)
plt.legend()
plt.savefig('regime_transitions.png')
```

---

### 2.3 动态仓位计算（5 分钟）

**场景**：熊市自动降仓

```python
from src.risk.dynamic_sizing import calculate_dynamic_position
from src.risk.regime_detector import RegimeType

# 1. 假设 Alpha 排序得到基础权重
base_weights = pd.Series({
    '688525.SH': 0.20,  # 佰维存储
    '600989.SH': 0.15,  # 赤峰黄金
    '300750.SZ': 0.15,  # 宁德时代
    '601899.SH': 0.12,  # 紫金矿业
    # ... 其他标的
})

# 2. 模拟熊市场景
positions = calculate_dynamic_position(
    base_weights=base_weights,
    regime=RegimeType.BEAR,
    current_drawdown=0.08,  # 当前回撤 8%
    max_drawdown_limit=0.15
)

print(positions[['stock_code', 'base_weight', 'final_weight', 'adjustment_reason']])

# 预期输出：
#    stock_code  base_weight  final_weight              adjustment_reason
# 0  688525.SH         0.20         0.048  熊市降仓70% + 回撤惩罚47%
### 2.4 滚动方向校准与拒绝预测机制（5 分钟）

**场景**：解决时变因子漂移与制度失效，低置信度时主动持币防御

```python
from src.pricing.calibration_config import DEFAULT_CONFIG, HIGH_CONFIDENCE_CONFIG
from src.pricing.rolling_direction_calibration import (
    calibrate_factor_direction,
    apply_calibrated_direction,
    FactorDirection
)
import pandas as pd

# 1. 加载因子打分历史与收益率历史
scores_df = pd.read_csv('docs/data/factors/green_scores_history.csv', index_col=0, parse_dates=True)
returns_df = pd.read_csv('docs/data/factors/green_returns_history.csv', index_col=0, parse_dates=True)

# 2. 决策日 T 滚动校准（严格仅使用 T-1 及历史数据，零前视偏差）
today = scores_df.index[-1]
calibration = calibrate_factor_direction(
    factor_scores_history=scores_df,
    returns_history=returns_df,
    current_date=today,
    config=DEFAULT_CONFIG
)

print(f"校准方向: {calibration.direction.value}")
print(f"置信度: {calibration.confidence:.2%}")
print(f"回溯 30 日命中率: {calibration.hit_rate:.2%}")
print(f"决策依据: {calibration.reason}")

# 3. 应用校准到当前打分（置信度不足 70% 或无效时输出 NaN 拒绝盲猜）
calibrated_scores = apply_calibrated_direction(
    factor_scores=scores_df.loc[today],
    calibration=calibration,
    config=DEFAULT_CONFIG
)
valid_predictions = calibrated_scores.dropna()
print(f"有效预测标的数: {len(valid_predictions)} / {len(scores_df.columns)}")
```

---



## 3. 学术创新快速原型

### 3.1 Granger 因果检验（10 分钟）

**场景**：验证"订单增长"因子是否 cause 未来收益

```python
from src.research.causal.granger_test import granger_causality_test, batch_granger_test
import pandas as pd

# 1. 单因子检验
订单增长 = pd.read_csv('data/factors/semantic_factors.csv', index_col='date')['订单增长']
forward_returns = pd.read_csv('data/processed/宁德时代_returns.csv', index_col='date')['forward_5d']

result = granger_causality_test(
    cause_series=订单增长,
    effect_series=forward_returns,
    maxlag=5
)

print(result['test_summary'])
# 输出：因子"订单增长"在滞后3期显著 Granger-cause 收益（F=8.52, p=0.003）

# 2. 批量检验（多个因子）
all_factors = pd.read_csv('data/factors/semantic_factors.csv', index_col='date')
batch_results = batch_granger_test(
    factors_df=all_factors,
    returns_series=forward_returns,
    maxlag=5
)

# 筛选显著因子
significant_factors = batch_results.query('is_causal == True').sort_values('p_value')
print(significant_factors)
```

---

### 3.2 因果图谱构建（10 分钟）

**场景**：可视化"因子→收益"传导路径

```python
from src.research.causal.causal_graph import build_causal_graph, visualize_causal_graph

# 1. 基于 Granger 结果构建图谱
supply_chain_edges = [
    ('宁德时代', '赣锋锂业'),  # 宁德是赣锋的下游
    ('赣锋锂业', '天齐锂业'),  # 竞争关系
]

graph = build_causal_graph(
    granger_results=batch_results,
    supply_chain_edges=supply_chain_edges,
    significance_threshold=0.05
)

print(f"节点数: {len(graph.nodes)}, 边数: {len(graph.edges)}")

# 2. 可视化
visualize_causal_graph(
    graph=graph,
    output_path='causal_graph.png',
    layout='hierarchical',
    highlight_nodes=['宁德时代']  # 高亮龙头股
)

# 3. 识别关键节点（中心性分析）
import networkx as nx
G = nx.DiGraph()
for edge in graph.edges:
    G.add_edge(edge.from_node, edge.to_node, weight=abs(edge.weight))

centrality = nx.betweenness_centrality(G)
print("中心性排名（关键传导节点）:")
for node, score in sorted(centrality.items(), key=lambda x: x[1], reverse=True)[:5]:
    print(f"  {node}: {score:.3f}")
```

---

### 3.3 干预效应模拟（可选，5 分钟）

**场景**：如果强制"订单增长"=1.0，收益会如何？

```python
from src.research.causal.intervention import estimate_intervention_effect

effect = estimate_intervention_effect(
    graph=graph,
    intervention={'订单增长': 1.0},
    target_node='宁德时代_forward_5d',
    method='backdoor'
)

print(f"平均处理效应: {effect['ate']:.4f}")
print(f"95% 置信区间: [{effect['ci_lower']:.4f}, {effect['ci_upper']:.4f}]")

# 输出：
# 平均处理效应: 0.0253
# 95% 置信区间: [0.0182, 0.0324]
# 解读：强制"订单增长"=1.0 → 未来5日平均多涨 2.53%
```

---

## 4. 端到端回测验证

### 4.1 增强策略回测（完整流程）

```python
from src.pricing.fama_macbeth_v2 import FamaMacBethV2
from src.risk.regime_detector import detect_market_regime
from src.risk.dynamic_sizing import calculate_dynamic_position
from src.utils.backtest_engine import run_backtest

# 1. 初始化增强引擎
fm_engine = FamaMacBethV2(
    adaptive_window=True,  # 启用动态窗口
    orthogonalize=True      # 启用因子正交化
)

# 2. 回测循环（简化伪代码）
for date in trading_dates:
    # Step 1: 识别市场状态
    regime, _, _ = detect_market_regime(market_index, date)
    
    # Step 2: 因子正交化 + Fama-MacBeth
    alpha_scores = fm_engine.compute_alpha(
        date=date,
        factors=semantic_factors.loc[date],
        regime=regime  # 根据状态选择窗口
    )
    
    # Step 3: Alpha 门控
    significant_alphas = alpha_scores.query('p_value < 0.05 and IR >= 0.30')
    
    # Step 4: 动态仓位
    positions = calculate_dynamic_position(
        base_weights=significant_alphas['weight'],
        regime=regime,
        current_drawdown=portfolio.get_drawdown()
    )
    
    # Step 5: 执行调仓
    portfolio.rebalance(positions)

# 3. 输出结果
metrics = portfolio.get_metrics()
print(f"Sharpe Ratio: {metrics['sharpe']:.2f}")
print(f"Max Drawdown: {metrics['max_dd']:.2%}")
print(f"IR: {metrics['ir']:.2f}")
```

---

## 5. 常见问题排查

### 5.1 因子正交化后全部不显著

**症状**：所有因子 p-value > 0.05

**原因**：
- 原始因子本身就是风格因子（如市值加权的行业指数）
- 数据时间窗口太短（< 126 天）

**解决**：
- 检查因子来源：应为公司特质信息（订单、产能），而非行业宽基
- 扩展时间窗口至 252 天

---

### 5.2 Granger 检验全部不显著

**症状**：batch_granger_test 全部返回 `is_causal=False`

**原因**：
- 收益序列非平稳（含趋势/季节性）
- 因子与收益时间错位（对齐问题）

**解决**：
```python
from statsmodels.tsa.stattools import adfuller

# 检查平稳性
adf_result = adfuller(forward_returns)
if adf_result[1] > 0.05:
    # 非平稳，差分
    forward_returns_diff = forward_returns.diff().dropna()
```

---

### 5.3 状态识别频繁震荡

**症状**：regime 每天都在 BULL/SIDEWAYS/BEAR 之间跳变

**原因**：
- MA 周期太短（如 MA5/MA10）
- 市场本身就在震荡（正常）

**解决**：
- 使用更长周期（MA20/MA60）
- 增加状态切换惯性（连续3天满足条件才切换）

---

## 6. 下一步

- **阅读详细文档**：
  - `specs/contest-2026/data-model.md` - 数据结构设计
  - `specs/contest-2026/contracts/` - API 契约
  - `specs/contest-2026/research.md` - 技术选型理由

- **运行完整测试**：
  ```bash
  pytest tests/unit/test_factor_ortho.py -v
  pytest tests/integration/test_enhanced_strategy.py -v
  ```

- **查看实验报告**：
  - `research-outputs/reports/策略增强实验报告.pdf`（阶段 2 生成）
  - `research-outputs/reports/因果推断白皮书.pdf`（阶段 2 生成）

---

## 7. 性能基准

在标准配置（Intel i7, 16GB RAM）下的预期耗时：

| 任务 | 数据规模 | 耗时 |
|------|---------|------|
| 因子正交化（单股） | 252 天 | < 10ms |
| 状态识别（全历史） | 300 天 | < 100ms |
| Granger 批量检验 | 20 因子 × 250 天 | < 5s |
| 完整回测（单板块） | 15 股 × 300 天 | < 5 分钟 |

如果耗时显著超出预期，检查：
- 数据是否有大量缺失值（触发额外的插补计算）
- 是否未启用并行（`n_jobs=-1`）
- 磁盘 I/O 是否成为瓶颈（使用 SSD）
