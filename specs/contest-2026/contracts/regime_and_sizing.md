# API 契约：市场状态机与动态仓位模块

**模块**：`src/risk/regime_detector.py` + `src/risk/dynamic_sizing.py`  
**版本**：v1.0  
**更新日期**：2026-09-01

---

## 1. 市场状态识别接口

### 1.1 detect_market_regime

**功能**：识别当前市场状态（牛市/熊市/震荡）

**签名**：
```python
from enum import Enum

class RegimeType(Enum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"

def detect_market_regime(
    market_index: pd.Series,
    date: datetime,
    ma_short: int = 20,
    ma_long: int = 60,
    include_macd: bool = True
) -> Tuple[RegimeType, float, Dict[str, float]]:
    """
    基于均线与 MACD 识别市场状态
    
    Parameters
    ----------
    market_index : pd.Series
        市场指数时间序列（如上证指数），index=日期
    date : datetime
        当前日期
    ma_short : int, default 20
        短期均线窗口
    ma_long : int, default 60
        长期均线窗口
    include_macd : bool, default True
        是否使用 MACD 作为辅助判断
    
    Returns
    -------
    regime : RegimeType
        识别的市场状态
    confidence : float
        置信度（0-1），基于信号强度
    indicators : Dict[str, float]
        判断依据 {'MA20': 3500, 'MA60': 3400, 'MACD': 50, 'signal_strength': 0.85}
    
    Examples
    --------
    >>> index = pd.Series([3000, 3100, 3200, ...], index=dates)
    >>> regime, conf, ind = detect_market_regime(index, date='2026-01-15')
    >>> regime
    <RegimeType.BULL: 'bull'>
    >>> conf
    0.85
    """
```

**判断逻辑**：
```python
if MA_short > MA_long:
    if MACD > 0:
        return BULL, confidence=high
    else:
        return SIDEWAYS, confidence=medium  # 均线多头但动量衰竭
elif MA_short < MA_long:
    if MACD < 0:
        return BEAR, confidence=high
    else:
        return SIDEWAYS, confidence=medium  # 均线空头但动量转正
else:
    return SIDEWAYS, confidence=low  # 均线缠绕
```

**置信度计算**：
```python
confidence = min(1.0, abs(MA_short - MA_long) / MA_long * 10 + abs(MACD) / 100)
```

---

### 1.2 get_regime_position_coeff

**功能**：根据市场状态返回仓位系数

**签名**：
```python
def get_regime_position_coeff(
    regime: RegimeType,
    custom_coeffs: Optional[Dict[RegimeType, float]] = None
) -> float:
    """
    获取状态对应的仓位系数
    
    Parameters
    ----------
    regime : RegimeType
        当前市场状态
    custom_coeffs : Dict[RegimeType, float], optional
        自定义系数，默认 {BULL: 1.0, SIDEWAYS: 0.7, BEAR: 0.3}
    
    Returns
    -------
    coeff : float
        仓位系数（0-1）
    
    Examples
    --------
    >>> get_regime_position_coeff(RegimeType.BULL)
    1.0
    >>> get_regime_position_coeff(RegimeType.BEAR)
    0.3
    """
```

**默认系数**：
| 状态 | 系数 | 说明 |
|------|------|------|
| BULL | 1.0 | 满仓 |
| SIDEWAYS | 0.7 | 降低暴露 |
| BEAR | 0.3 | 防御性仓位 |

---

## 2. 动态仓位计算接口

### 2.1 calculate_dynamic_position

**功能**：综合考虑市场状态与回撤，计算最终仓位

**签名**：
```python
def calculate_dynamic_position(
    base_weights: pd.Series,
    regime: RegimeType,
    current_drawdown: float,
    max_drawdown_limit: float = 0.15,
    min_position: float = 0.0
) -> pd.DataFrame:
    """
    动态仓位计算
    
    Parameters
    ----------
    base_weights : pd.Series
        基础权重（来自 Alpha 排序），index=股票代码，values=权重
    regime : RegimeType
        当前市场状态
    current_drawdown : float
        当前回撤（正数，如 0.10 表示 -10%）
    max_drawdown_limit : float, default 0.15
        最大容忍回撤（超过此值触发防御性减仓）
    min_position : float, default 0.0
        最小持仓比例（如 0.05 表示至少保持 5% 仓位）
    
    Returns
    -------
    positions : pd.DataFrame
        仓位明细，columns=['stock_code', 'base_weight', 'regime_adjusted', 
                          'drawdown_adjusted', 'final_weight', 'adjustment_reason']
    
    Examples
    --------
    >>> base = pd.Series({'688525.SH': 0.15, '600989.SH': 0.12, ...})
    >>> pos = calculate_dynamic_position(base, RegimeType.BEAR, current_drawdown=0.08)
    >>> pos['final_weight'].sum()  # 熊市降仓后
    0.30  # 原 1.0 → 0.3
    """
```

**计算公式**：
```python
regime_coeff = get_regime_position_coeff(regime)
drawdown_penalty = max(0, 1 - current_drawdown / max_drawdown_limit)

final_weight = base_weight * regime_coeff * drawdown_penalty

# 归一化（使权重和=1或目标仓位）
final_weight = final_weight / final_weight.sum() * target_exposure
```

---

### 2.2 simulate_regime_transitions

**功能**：回测期间的状态转换轨迹模拟

**签名**：
```python
def simulate_regime_transitions(
    market_index: pd.Series,
    start_date: datetime,
    end_date: datetime
) -> pd.DataFrame:
    """
    模拟历史状态转换序列
    
    Returns
    -------
    transitions : pd.DataFrame
        columns=['date', 'regime', 'confidence', 'MA20', 'MA60', 'MACD']
    
    Examples
    --------
    >>> trans = simulate_regime_transitions(index, '2025-01-01', '2026-08-31')
    >>> trans['regime'].value_counts()
    BULL        120
    SIDEWAYS     80
    BEAR         50
    """
```

---

## 3. 数据结构

### 3.1 输入格式

**MarketIndex Series**：
```python
date
2025-01-02    3000.5
2025-01-03    3050.2
...
Name: 上证指数, dtype: float64
```

**BaseWeights Series**：
```python
688525.SH    0.15
600989.SH    0.12
601899.SH    0.10
...
Name: base_weight, dtype: float64
```

### 3.2 输出格式

**DynamicPosition DataFrame**：
```python
   stock_code  base_weight  regime_adjusted  drawdown_adjusted  final_weight adjustment_reason
0  688525.SH         0.15             0.105              0.095         0.095    熊市降仓70% + 回撤惩罚10%
1  600989.SH         0.12             0.084              0.076         0.076    熊市降仓70% + 回撤惩罚10%
...
```

---

## 4. 错误处理

| 异常 | 触发条件 | 处理建议 |
|------|---------|---------|
| `ValueError` | `current_drawdown > 1.0` | 检查回撤计算逻辑 |
| `ValueError` | `base_weights.sum() != 1.0` | 归一化后重试 |
| `InsufficientDataError` | 市场数据 < 60 日 | 无法计算 MA60，使用默认状态 |

---

## 5. 性能指标

| 操作 | 输入规模 | 预期耗时 |
|------|---------|---------|
| `detect_market_regime` | 单日 | < 5ms |
| `calculate_dynamic_position` | 20 只股票 | < 10ms |
| `simulate_regime_transitions` | 300 交易日 | < 100ms |

---

## 6. 测试用例

### 6.1 单元测试

```python
def test_bull_market_detection():
    """测试牛市识别"""
    index = pd.Series([3000, 3100, 3200, 3300], index=pd.date_range('2025-01-01', periods=4))
    # 人工构造 MA20 > MA60
    regime, conf, _ = detect_market_regime(index, date='2025-01-04')
    assert regime == RegimeType.BULL

def test_drawdown_penalty():
    """测试回撤惩罚机制"""
    base = pd.Series({'A': 0.5, 'B': 0.5})
    pos = calculate_dynamic_position(base, RegimeType.BULL, current_drawdown=0.10, max_drawdown_limit=0.15)
    # 回撤 10% / 限制 15% = 66.7% 惩罚
    expected_sum = (1 - 0.10/0.15)
    assert abs(pos['final_weight'].sum() - expected_sum) < 0.01
```

### 6.2 集成测试

```python
def test_regime_switching_backtest():
    """端到端测试：状态切换对回测的影响"""
    # 构造牛转熊场景
    index = create_bull_to_bear_index()
    trans = simulate_regime_transitions(index, ...)
    
    # 验证状态转换
    assert trans.iloc[0]['regime'] == RegimeType.BULL
    assert trans.iloc[-1]['regime'] == RegimeType.BEAR
    
    # 验证仓位随状态降低
    assert trans.iloc[-1]['position_coeff'] == 0.3
```
