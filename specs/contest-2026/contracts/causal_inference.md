# API 契约：因果推断框架

**模块**：`src/research/causal/`  
**版本**：v1.0  
**更新日期**：2026-09-01

---

## 1. Granger 因果检验接口

### 1.1 granger_causality_test

**功能**：检验因子是否 Granger-cause 未来收益

**签名**：
```python
def granger_causality_test(
    cause_series: pd.Series,
    effect_series: pd.Series,
    maxlag: int = 5,
    alpha: float = 0.05
) -> Dict[str, Any]:
    """
    Granger 因果检验
    
    Parameters
    ----------
    cause_series : pd.Series
        原因变量（如语义因子得分）
    effect_series : pd.Series
        结果变量（如未来5日收益）
    maxlag : int, default 5
        最大滞后阶数
    alpha : float, default 0.05
        显著性水平
    
    Returns
    -------
    result : Dict[str, Any]
        {
            'is_causal': bool,              # 是否拒绝零假设（因子确实 cause 收益）
            'best_lag': int,                # 最优滞后阶数
            'f_statistic': float,           # F统计量
            'p_value': float,               # p值
            'test_summary': str             # 文字总结
        }
    
    Examples
    --------
    >>> factor = pd.Series([0.5, 0.7, 0.6, ...], index=dates)
    >>> returns = pd.Series([0.02, 0.03, -0.01, ...], index=dates)
    >>> result = granger_causality_test(factor, returns, maxlag=5)
    >>> result['is_causal']
    True
    >>> result['p_value']
    0.012  # < 0.05，显著
    """
```

**前置条件**：
- 两个序列长度相同且日期对齐
- 长度 ≥ `maxlag * 10`（保证自由度）
- 数据平稳性（建议先做 ADF 检验）

**后置条件**：
- p < 0.05 → 拒绝"无因果"假设 → `is_causal = True`

---

### 1.2 batch_granger_test

**功能**：批量测试多个因子对收益的因果关系

**签名**：
```python
def batch_granger_test(
    factors_df: pd.DataFrame,
    returns_series: pd.Series,
    maxlag: int = 5,
    n_jobs: int = -1
) -> pd.DataFrame:
    """
    批量 Granger 检验
    
    Parameters
    ----------
    factors_df : pd.DataFrame
        多个因子，columns = ['订单增长', '产能扩张', ...]
    returns_series : pd.Series
        目标收益序列
    n_jobs : int, default -1
        并行作业数（-1 表示使用所有 CPU）
    
    Returns
    -------
    results : pd.DataFrame
        columns=['factor_name', 'is_causal', 'best_lag', 'f_stat', 'p_value']
        按 p_value 升序排列
    
    Examples
    --------
    >>> factors = pd.DataFrame({'订单增长': [...], '产能扩张': [...]})
    >>> returns = pd.Series([...])
    >>> res = batch_granger_test(factors, returns)
    >>> res.query('is_causal == True')  # 筛选显著因子
       factor_name  is_causal  best_lag  f_stat  p_value
    0      订单增长       True         3   8.52    0.003
    """
```

---

## 2. 因果图谱构建接口

### 2.1 build_causal_graph

**功能**：构建"因子→收益"的因果有向无环图（DAG）

**签名**：
```python
from typing import List, Tuple

@dataclass
class CausalNode:
    node_id: str
    node_type: str  # 'factor' | 'stock' | 'event'
    value: float

@dataclass
class CausalEdge:
    from_node: str
    to_node: str
    edge_type: str      # 'causal' | 'upstream' | 'downstream'
    weight: float       # 因果强度（-1 到 1）
    p_value: float

@dataclass
class CausalGraph:
    nodes: List[CausalNode]
    edges: List[CausalEdge]
    timestamp: datetime

def build_causal_graph(
    granger_results: pd.DataFrame,
    supply_chain_edges: Optional[List[Tuple[str, str]]] = None,
    significance_threshold: float = 0.05
) -> CausalGraph:
    """
    构建因果图谱
    
    Parameters
    ----------
    granger_results : pd.DataFrame
        来自 batch_granger_test 的输出
    supply_chain_edges : List[Tuple[str, str]], optional
        供应链关系 [('宁德时代', '比亚迪'), ...]
    significance_threshold : float, default 0.05
        仅保留 p < threshold 的边
    
    Returns
    -------
    graph : CausalGraph
        因果图对象
    
    Examples
    --------
    >>> granger_res = batch_granger_test(...)
    >>> supply_chain = [('宁德时代', '赣锋锂业'), ('赣锋锂业', '天齐锂业')]
    >>> graph = build_causal_graph(granger_res, supply_chain)
    >>> len(graph.edges)
    15  # 显著的因果边数量
    """
```

**图约束**：
- 必须为 DAG（无环）：使用拓扑排序验证
- 稀疏性：`|edges| ≤ 5 × |nodes|`
- 所有边的 p_value < threshold

---

### 2.2 visualize_causal_graph

**功能**：可视化因果图谱

**签名**：
```python
def visualize_causal_graph(
    graph: CausalGraph,
    output_path: str,
    layout: str = 'hierarchical',
    highlight_nodes: Optional[List[str]] = None
) -> None:
    """
    绘制因果图谱
    
    Parameters
    ----------
    graph : CausalGraph
        因果图对象
    output_path : str
        输出图片路径（PNG/SVG）
    layout : str, default 'hierarchical'
        布局算法 ('hierarchical' | 'spring' | 'circular')
    highlight_nodes : List[str], optional
        高亮节点（如核心龙头股）
    
    Examples
    --------
    >>> graph = build_causal_graph(...)
    >>> visualize_causal_graph(graph, 'causal_graph.png', highlight_nodes=['宁德时代'])
    """
```

**输出示例**：
```
[订单增长] --0.85--> [宁德时代收益]
     ↓ 0.62
[产能扩张] --0.73--> [比亚迪收益]
     ↓ 0.54
[上游供应链]
```

---

## 3. 干预效应模拟接口（do-calculus）

### 3.3 estimate_intervention_effect

**功能**：模拟"如果强制某因子=X，收益会如何变化"

**签名**：
```python
def estimate_intervention_effect(
    graph: CausalGraph,
    intervention: Dict[str, float],
    target_node: str,
    method: str = 'backdoor'
) -> Dict[str, float]:
    """
    估计干预效应
    
    Parameters
    ----------
    graph : CausalGraph
        因果图
    intervention : Dict[str, float]
        干预变量 {'订单增长': 0.9}（强制设为 0.9）
    target_node : str
        目标变量（如 '宁德时代_forward_return_5d'）
    method : str, default 'backdoor'
        识别策略 ('backdoor' | 'frontdoor' | 'iv')
    
    Returns
    -------
    effect : Dict[str, float]
        {
            'ate': 0.025,           # 平均处理效应（Average Treatment Effect）
            'ci_lower': 0.018,      # 95% 置信下界
            'ci_upper': 0.032,      # 95% 置信上界
            'method': 'backdoor'
        }
    
    Examples
    --------
    >>> graph = build_causal_graph(...)
    >>> effect = estimate_intervention_effect(
    ...     graph, 
    ...     intervention={'订单增长': 1.0}, 
    ...     target_node='宁德时代_5d_return'
    ... )
    >>> effect['ate']
    0.025  # 强制"订单增长"=1.0 → 未来5日平均收益 +2.5%
    """
```

**实现框架**（基于 DoWhy）：
```python
import dowhy

# 步骤1：建模
model = dowhy.CausalModel(
    data=df,
    treatment='订单增长',
    outcome='forward_return_5d',
    common_causes=['market_beta', 'size'],
    graph=gml_string
)

# 步骤2：识别
identified_estimand = model.identify_effect(proceed_when_unidentifiable=True)

# 步骤3：估计
estimate = model.estimate_effect(identified_estimand, method_name="backdoor.linear_regression")

return {'ate': estimate.value, ...}
```

---

## 4. 数据结构

### 4.1 Granger 检验输出

```python
{
    'is_causal': True,
    'best_lag': 3,
    'f_statistic': 8.52,
    'p_value': 0.0032,
    'test_summary': '因子"订单增长"在滞后3期显著 Granger-cause 收益（F=8.52, p=0.003）'
}
```

### 4.2 因果图 JSON 格式

```json
{
    "nodes": [
        {"node_id": "订单增长", "node_type": "factor", "value": 0.85},
        {"node_id": "宁德时代_5d_return", "node_type": "stock", "value": 0.025}
    ],
    "edges": [
        {
            "from_node": "订单增长",
            "to_node": "宁德时代_5d_return",
            "edge_type": "causal",
            "weight": 0.85,
            "p_value": 0.003
        }
    ],
    "timestamp": "2026-09-01T12:00:00"
}
```

---

## 5. 错误处理

| 异常 | 触发条件 | 处理建议 |
|------|---------|---------|
| `InsufficientDataError` | 样本数 < maxlag × 10 | 扩展时间窗口或降低 maxlag |
| `NonStationaryError` | ADF 检验 p > 0.05（非平稳） | 差分或去趋势 |
| `CyclicGraphError` | 检测到环路 | 移除冲突边 |
| `UnidentifiableError` | do-calculus 无法识别 | 尝试其他识别策略或增加工具变量 |

---

## 6. 性能指标

| 操作 | 输入规模 | 预期耗时 |
|------|---------|---------|
| `granger_causality_test` | 250 天 × 1 因子 | < 100ms |
| `batch_granger_test` | 250 天 × 20 因子 | < 5s（并行） |
| `build_causal_graph` | 20 节点 × 50 边 | < 200ms |
| `estimate_intervention_effect` | 单次干预 | < 500ms |

---

## 7. 测试用例

### 7.1 单元测试

```python
def test_granger_with_known_causal():
    """测试已知因果关系（构造数据）"""
    # X(t) → Y(t+1)：Y = 0.5*X(t-1) + noise
    X = np.random.randn(200)
    Y = np.concatenate([[0], 0.5 * X[:-1]]) + np.random.randn(200) * 0.1
    
    result = granger_causality_test(pd.Series(X), pd.Series(Y), maxlag=3)
    assert result['is_causal'] == True
    assert result['p_value'] < 0.05

def test_dag_constraint():
    """测试 DAG 约束（不允许环路）"""
    edges = [
        CausalEdge('A', 'B', 'causal', 0.8, 0.01),
        CausalEdge('B', 'C', 'causal', 0.7, 0.02),
        CausalEdge('C', 'A', 'causal', 0.6, 0.03)  # 形成环 A→B→C→A
    ]
    with pytest.raises(CyclicGraphError):
        build_causal_graph_from_edges(edges)
```

### 7.2 集成测试

```python
def test_end_to_end_causal_workflow():
    """端到端：因子检验 → 图谱构建 → 干预模拟"""
    # 1. Granger 检验
    granger_res = batch_granger_test(factors_df, returns)
    
    # 2. 构建图谱
    graph = build_causal_graph(granger_res)
    assert len(graph.edges) > 0
    
    # 3. 干预模拟
    effect = estimate_intervention_effect(
        graph, 
        intervention={'订单增长': 1.0}, 
        target_node='stock_return'
    )
    assert 'ate' in effect
```

---

## 8. 参考文献实现

| 功能 | 对应文献 | 实现库 |
|------|---------|--------|
| Granger 检验 | Granger (1969) | `statsmodels.tsa.stattools.grangercausalitytests` |
| 因果图构建 | Pearl (2009) | 自实现（基于 networkx） |
| do-calculus | Pearl (2009) | `dowhy.CausalModel` |
| 反事实推断 | Pearl (2009) | `dowhy.causal_refuters` |
