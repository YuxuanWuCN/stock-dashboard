# 数据模型：策略增强与学术创新

**项目**：Rainbow-FinGPT 提升计划  
**日期**：2026-09-01  
**阶段**：1 - 数据模型设计

---

## 1. 核心实体与关系

### 1.1 因子数据模型

#### OrthogonalFactor（正交化因子）

```python
@dataclass
class OrthogonalFactor:
    """正交化后的纯净因子"""
    stock_code: str              # 股票代码（如 "688525.SH"）
    date: datetime               # 因子日期
    raw_factor_value: float      # 原始语义因子值
    orthogonal_value: float      # 正交化后的特质成分
    carhart_exposure: Dict[str, float]  # 对四因子的暴露 {"MKT": 0.8, "SMB": 0.2, ...}
    significance: float          # t统计量
    is_significant: bool         # 是否显著（|t| > 2）
```

**关系**：
- 一个股票-日期对应一个 OrthogonalFactor
- 与 CarhartFactors（市场四因子）存在依赖关系

#### CarhartFactors（Carhart四因子）

```python
@dataclass
class CarhartFactors:
    """市场层面的四因子时间序列"""
    date: datetime
    MKT: float    # 市场超额收益
    SMB: float    # 规模因子（小盘-大盘）
    HML: float    # 价值因子（高账面市值比-低账面市值比）
    MOM: float    # 动量因子（过去12月收益-最近1月）
```

**数据源**：
- 从现有回测系统的基准构建模块提取
- 存储路径：`data/factors/carhart_4factors.csv`

---

### 1.2 状态机数据模型

#### MarketRegime（市场状态）

```python
from enum import Enum

class RegimeType(Enum):
    BULL = "bull"           # 牛市
    BEAR = "bear"           # 熊市
    SIDEWAYS = "sideways"   # 震荡

@dataclass
class MarketRegime:
    """市场宏观状态识别结果"""
    date: datetime
    regime: RegimeType
    confidence: float       # 状态置信度（0-1）
    indicators: Dict[str, float]  # 判断依据 {"MA20": 3500, "MA60": 3400, "MACD": 50}
    position_coeff: float   # 该状态下的仓位系数（0-1）
```

**状态转换规则**：
```
BULL → SIDEWAYS: MA20 开始回落但未跌破 MA60
SIDEWAYS → BEAR: MA20 跌破 MA60 且 MACD < 0
BEAR → SIDEWAYS: MACD 转正但 MA20 仍低于 MA60
SIDEWAYS → BULL: MA20 重新站上 MA60
```

#### DynamicPosition（动态仓位）

```python
@dataclass
class DynamicPosition:
    """动态仓位计算结果"""
    date: datetime
    stock_code: str
    base_weight: float           # 基础权重（来自 Alpha 排序）
    regime_adjusted: float       # 状态调整后权重
    drawdown_adjusted: float     # 回撤调整后权重
    final_weight: float          # 最终权重
    adjustment_reason: str       # 调整原因（如 "熊市降仓50%"）
```

**计算公式**：
```
final_weight = base_weight × regime_coeff × max(0, 1 - current_dd/max_dd_limit)
```

---

### 1.3 Fama-MacBeth 增强模型

#### AdaptiveWindow（自适应窗口）

```python
@dataclass
class AdaptiveWindow:
    """动态滚动窗口配置"""
    date: datetime
    market_state: RegimeType    # 当前市场状态
    window_length: int          # 选择的窗口长度（126 或 252）
    rationale: str              # 选择理由
```

**规则**：
- `BULL` → 126 日（半年，快速捕捉新 Alpha）
- `BEAR` / `SIDEWAYS` → 252 日（一年，增强稳健性）

#### FamaMacBethResult（回归结果）

```python
@dataclass
class FamaMacBethResult:
    """Fama-MacBeth 两阶段回归输出"""
    stock_code: str
    date: datetime
    window_length: int          # 使用的窗口长度
    
    # 第一阶段：时序回归（每只股票）
    beta_MKT: float
    beta_SMB: float
    beta_HML: float
    beta_MOM: float
    
    # 第二阶段：截面回归（所有股票）
    alpha: float                # 特质收益
    alpha_tstat: float          # t统计量
    alpha_pvalue: float         # p值
    
    # 稳健性检验
    newey_west_se: float        # Newey-West 标准误
    is_significant: bool        # p < 0.05
    information_ratio: float    # IR = alpha / std(alpha)
```

---

### 1.4 因果推断模型

#### CausalRelation（因果关系）

```python
@dataclass
class CausalRelation:
    """Granger 因果检验结果"""
    cause_factor: str           # 原因变量（如 "semantic_score"）
    effect_variable: str        # 结果变量（如 "forward_return_5d"）
    lag: int                    # 滞后阶数
    f_statistic: float          # F统计量
    p_value: float              # p值
    is_causal: bool             # 是否拒绝"无因果"原假设（p < 0.05）
    test_date: datetime         # 检验时间
```

#### CausalGraph（因果图谱）

```python
@dataclass
class CausalNode:
    """因果图节点"""
    node_id: str                # 节点标识（如 "宁德时代_订单增长"）
    node_type: str              # 类型（factor/stock/event）
    value: float                # 当前值

@dataclass
class CausalEdge:
    """因果图边"""
    from_node: str              # 起点
    to_node: str                # 终点
    edge_type: str              # 关系类型（upstream/downstream/causal）
    weight: float               # 因果强度（-1 到 1）
    granger_pvalue: float       # Granger 检验 p 值

@dataclass
class CausalGraph:
    """完整因果图谱"""
    nodes: List[CausalNode]
    edges: List[CausalEdge]
    timestamp: datetime
```

**用途**：
- 可视化"语义因子 → 收益"的因果传导路径
- 识别关键节点（高中心性）
- 模拟干预效应（do-calculus）

---

## 2. 数据流与存储

### 2.1 数据管道

```
原始数据
  ↓
[因子正交化模块]
  ↓
OrthogonalFactor (HDF5: data/factors/orthogonal_factors.h5)
  ↓
[Fama-MacBeth 引擎] ← AdaptiveWindow ← MarketRegime
  ↓
FamaMacBethResult (HDF5: data/factors/fm_results.h5)
  ↓
[Alpha 门控] → 筛选显著 Alpha
  ↓
[动态仓位模块] ← MarketRegime
  ↓
DynamicPosition (CSV: data/positions/daily_positions.csv)
  ↓
[回测引擎]
  ↓
BacktestResult (PDF + JSON)
```

### 2.2 存储格式

| 数据类型 | 存储格式 | 路径 | 更新频率 |
|---------|---------|------|---------|
| CarhartFactors | CSV | `data/factors/carhart_4factors.csv` | 每日 |
| OrthogonalFactor | HDF5 | `data/factors/orthogonal_factors.h5` | 每日 |
| MarketRegime | JSON | `data/regime/market_regime.json` | 每日 |
| FamaMacBethResult | HDF5 | `data/factors/fm_results.h5` | 每日 |
| DynamicPosition | CSV | `data/positions/YYYYMMDD_positions.csv` | 每日 |
| CausalGraph | JSON | `data/causal/causal_graph_YYYYMMDD.json` | 每周 |

**HDF5 结构示例**（OrthogonalFactor）：
```
orthogonal_factors.h5
├── /2025-01-02/
│   ├── stock_codes: ["688525.SH", "600989.SH", ...]
│   ├── raw_values: [0.8, 0.5, ...]
│   ├── orthogonal_values: [0.3, -0.1, ...]
│   └── significances: [2.5, 1.2, ...]
├── /2025-01-03/
...
```

---

## 3. 验证规则

### 3.1 数据完整性检查

| 实体 | 检查项 | 规则 |
|------|--------|------|
| OrthogonalFactor | 值范围 | `-5 < orthogonal_value < 5` |
| OrthogonalFactor | 日期连续性 | 交易日无缺失 |
| MarketRegime | 状态合法性 | `regime ∈ {BULL, BEAR, SIDEWAYS}` |
| DynamicPosition | 权重和 | `Σ final_weight ≈ 1.0 (±0.01)` |
| FamaMacBethResult | t统计量一致性 | `|alpha_tstat| > 2 ⇔ alpha_pvalue < 0.05` |

### 3.2 因果检验约束

- Granger 检验最大滞后阶数：`maxlag ≤ 10`（避免自由度耗尽）
- 因果图边数上限：`|edges| ≤ 5 × |nodes|`（稀疏性约束）
- 循环检测：禁止 A→B→C→A 的闭环（DAG 约束）

---

## 4. 状态转换图

### 4.1 市场状态机

```
        ┌─────────────────────────────────────┐
        │                                     │
        ↓                                     │
    ┌──────┐  MA20 > MA60    ┌──────────┐    │
    │ BULL │ ───────────────→ │ SIDEWAYS │    │
    └──────┘                  └──────────┘    │
        ↑                          │          │
        │                          │ MA20 < MA60
        │                          │ MACD < 0
        │                          ↓          │
        │                      ┌──────┐      │
        │  MACD > 0            │ BEAR │      │
        └──────────────────────└──────┘      │
                                   │          │
                                   │          │
                                   └──────────┘
```

### 4.2 Alpha 门控流程

```
原始因子
    ↓
[正交化] → 剥离四因子暴露
    ↓
[Fama-MacBeth] → 计算 alpha, p-value, IR
    ↓
  p < 0.05?  ──No──→ REJECT
    ↓ Yes
  IR ≥ 0.30? ──No──→ REJECT
    ↓ Yes
  ACCEPT → 进入组合
```

---

## 5. 索引策略

为提升查询性能，关键字段建立索引：

| 实体 | 索引字段 | 类型 |
|------|---------|------|
| OrthogonalFactor | (date, stock_code) | 复合主键 |
| FamaMacBethResult | (date, stock_code) | 复合主键 |
| MarketRegime | date | 单列索引 |
| CausalRelation | (cause_factor, effect_variable) | 复合索引 |

**HDF5 分区策略**：
- 按日期分区（每日一个 Group）
- 支持增量追加（无需重写历史数据）

---

## 6. 扩展性考虑

### 6.1 未来可扩展字段

- **OrthogonalFactor**：增加 `pca_component_id`（如果使用 PCA 降维）
- **MarketRegime**：增加 `volatility_regime`（高波/低波分类）
- **CausalGraph**：增加 `intervention_effect`（do-calculus 干预模拟结果）

### 6.2 多板块支持

当前三板块（存储/黄金/绿电）可扩展为通用框架：

```python
@dataclass
class SectorConfig:
    """板块配置"""
    sector_name: str            # 板块名称
    stock_pool: List[str]       # 标的池
    benchmark: str              # 对标基准（如 "芯片ETF"）
    specific_factors: List[str] # 板块特有因子（如黄金："美元指数", "地缘风险"）
```

存储结构：
```
data/
├── factors/
│   ├── storage/orthogonal_factors.h5
│   ├── gold/orthogonal_factors.h5
│   └── green_energy/orthogonal_factors.h5
```
