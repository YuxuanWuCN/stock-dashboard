# 数据模型与契约：存储 + 黄金双板块杠铃回测

> **功能分支**：`017-storage-gold-joint-barbell`  
> **文档类型**：数据结构与交互契约  

---

## 1. 实体定义

### 1.1 `BarbellStockConfig`
```python
@dataclass
class BarbellStockConfig:
    code: str
    name: str
    sector: str         # "storage" | "gold"
    base_alpha: float
    beta: float
    role: str           # "growth_spear" | "safe_shield"
```

### 1.2 `JointBacktestResult`
```python
@dataclass
class JointBacktestResult:
    period: str
    sample_days: int
    storage_stocks: List[str]
    gold_stocks: List[str]
    strategies: Dict[str, StrategyStats]  # "pure_storage", "pure_gold", "static_barbell_50_50", "dynamic_regime_barbell"
    correlation_storage_gold: float
    diversification_ratio: float
    harvey_alpha_t_stat: float
    nav_series: Dict[str, List[float]]
```

---

## 2. 状态映射契约
| 状态机输出 | 存储板块总权重 ($W_{\text{storage}}$) | 黄金板块总权重 ($W_{\text{gold}}$) | 目标定位 |
| :--- | :---: | :---: | :--- |
| **BULL** | $80\%$ | $20\%$ | 顺势进攻，最大化半导体 Beta 与 Alpha 爆发力 |
| **SIDEWAYS** | $50\%$ | $50\%$ | 杠铃中性对冲，降低组合波动与回撤 |
| **BEAR** | $15\%$ | $85\%$ | 全面避险，借助黄金避险属性保全本金 |
