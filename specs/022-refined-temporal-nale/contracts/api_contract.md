# API 与模块契约规范：NALE 时效动态原型 (contracts/api_contract.md)

**功能**：`022-refined-temporal-nale`  

---

## 1. Python 内部核心类契约

### 1.1 `EventAgeTracker`
负责按交易日顺序跟踪个股催化事件与时效年龄：

```python
class EventAgeTracker:
    def __init__(self, volume_surge_multiplier: float = 2.0, min_return_pct: float = 4.0):
        ...
        
    def step(
        self,
        date_str: str,
        df_daily: pd.DataFrame,
    ) -> Dict[str, NodeEventState]:
        """推进单日截面。
        
        参数:
            date_str: 当前交易日 YYYY-MM-DD
            df_daily: 包含 ['code', 'close', 'ret', 'volume', 'hit_limit'] 的当日截面
            
        返回:
            各标的最新的 NodeEventState 映射字典
        """
        ...
```

---

### 1.2 `TemporalKernelOptimizer`
负责在 Walk-Forward 窗口内自适应学习最优高斯时滞核与双波峰参数：

```python
class TemporalKernelOptimizer:
    def __init__(
        self,
        tau_bounds: Tuple[float, float] = (6.0, 25.0),
        sigma_bounds: Tuple[float, float] = (2.0, 8.0),
        regularization: float = 0.01,
    ):
        ...
        
    def fit(
        self,
        s0_history: List[np.ndarray],
        adjacency_history: List[np.ndarray],
        ages_history: List[np.ndarray],
        realized_returns_history: List[np.ndarray],
        horizon_days: float = 5.0,
    ) -> LearnedTemporalParameters:
        """基于 L-BFGS-B 算法在训练集上平滑优化时空高斯核参数。"""
        ...
```

---

### 1.3 `LearnedTemporalNALE`
负责应用拟合参数进行无前视因果时空图卷积：

```python
class LearnedTemporalNALE:
    def __init__(self, params: LearnedTemporalParameters):
        ...
        
    def compute_cross_section(
        self,
        s0: np.ndarray,
        adj: np.ndarray,
        node_ages: np.ndarray,
        horizon_days: float = 5.0,
    ) -> np.ndarray:
        """输出向前推演 horizon_days 天的最终综合得分。"""
        ...
```

---

## 2. CLI 运行契约

```bash
# 在 scratch 隔离区一键运行端到端原型评测
python scratch/refined_temporal_nale/run_prototype.py \
  --data-path data/task_split/csmar_master/csmar_factor_panel_master.parquet \
  --universe-path data/task_split/universe_300_assigned.csv \
  --horizons 5,10 \
  --plot-figures
```

**控制台输出约定 (JSON + Markdown Summary)**：
- 打印 4 个版本的 OOS Rank IC 均值、ICIR、Newey-West $t$ 统计量及相对提升幅度；
- 生成图表保存至 `reports/figures/refined_temporal_nale/impulse_response_curve.png`。
