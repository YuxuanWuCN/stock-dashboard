# Rainbow-FinGPT 系统优化任务包 - 交给Gemini执行

**任务来源**：用户需求 - 提升系统策略表现和学术创新性，为省赛做准备

**项目路径**：`D:\R-FinGPTv2（国创版本）\`

**预计工作量**：1-1.5周

---

## 一、项目背景

### 当前系统状态

**Rainbow-FinGPT** 是基于解耦三引擎架构的量化投研系统：
- **Layer 1**：SCNU-RAG 定性知识引擎（语义因子提取）
- **Layer 2**：Fama-MacBeth 资产定价引擎（Alpha计算）
- **Layer 3**：Trend Gate 风控引擎（趋势过滤 + C浪清仓）

**已完成校赛材料**：
- 商业计划书、申报表、网评PPT、3份实测研报
- 三板块回测：存储（Sharpe 4.63）、黄金（Sharpe 2.87）、绿电（Sharpe 1.19）

### 优化需求

**时间约束**：省赛2-3个月内，不急着交成果

**优化方向**：
1. **策略增强**（优先）：因子正交化 + 动态窗口 + 市场状态机
2. **学术创新**（看时间）：因果推断框架

**验证板块**：绿电板块（Sharpe 1.19 → 1.31+，MaxDD 24.9% → 19.9-）

---

## 二、详细任务清单

### 【优先级P0】任务1：下载CSMAR因子数据（1小时）

#### 背景
- 用户在学校，可访问CSMAR数据库
- Python SDK已安装：`from csmarapi.CsmarService import CsmarService`
- 需要下载高质量Carhart四因子替代当前Akshare数据

#### 操作步骤

**Step 1：连接CSMAR**
```python
from csmarapi.CsmarService import CsmarService
import pandas as pd

# 初始化服务
csmar = CsmarService()

# 用户需要先在CSMAR网站查询表名和字段名
# 常见表名：STK_MKT_Thrfac（三因子/四因子表）
```

**Step 2：查询并下载数据**
```python
# 下载Carhart四因子（2020-2026，日度）
# 注意：字段名可能需要根据CSMAR实际表结构调整

data = csmar.query(
    table_name="STK_MKT_Thrfac",  # 需确认实际表名
    start_date="2020-01-01",
    end_date="2026-09-01",
    fields=["TradingDate", "RiskPremium1", "SMB1", "HML1", "UMD1", "RiskFreeRate"]
)

# 字段映射（根据项目既有映射表）
data_clean = data.rename(columns={
    "TradingDate": "date",
    "RiskPremium1": "MKT",    # 市场超额收益
    "SMB1": "SMB",            # 规模因子
    "HML1": "HML",            # 价值因子
    "UMD1": "MOM",            # 动量因子
    "RiskFreeRate": "rf"      # 无风险利率
})

# 保存到项目热插拔目录
data_clean.to_csv("data/school_factors/csmar_carhart_4factors.csv", index=False)
```

**Step 3：数据质量检查**
```python
# 验证数据
df = pd.read_csv("data/school_factors/csmar_carhart_4factors.csv")

print(f"数据行数: {len(df)}")
print(f"时间跨度: {df['date'].min()} 至 {df['date'].max()}")
print(f"缺失值: {df.isnull().sum().sum()}")
print(f"列名: {df.columns.tolist()}")

# 断言检查
assert len(df) > 1000, "数据量太少，至少需要4年数据"
assert df.isnull().sum().sum() == 0, "存在缺失值"
assert set(df.columns) >= {'date', 'MKT', 'SMB', 'HML', 'MOM', 'rf'}, "列名不完整"
```

**可选：下载宏观情绪因子**
```python
# 用于增强状态机（可选）
# - 市场换手率
# - 融资融券余额
# - 新增开户数（如果CSMAR有）

# 保存到：data/school_factors/csmar_macro_sentiment.csv
```

#### 交付物
- `data/school_factors/csmar_carhart_4factors.csv`（必需）
- `data/school_factors/csmar_macro_sentiment.csv`（可选）

#### 验收标准
- 数据时间跨度 2020-2026（至少1500行）
- 无缺失值
- 列名符合项目规范

---

### 【优先级P0】任务2：实现市场状态机模块（3-4天）

#### 目标
识别大盘牛市/熊市/震荡三状态，输出动态仓位系数

#### 文件路径
**新建文件**：
- `src/risk/regime_detector.py`（市场状态识别）
- `src/risk/dynamic_sizing.py`（动态仓位计算）
- `tests/unit/test_regime_detector.py`（单元测试）

**修改文件**：
- `Rainbow_FinGPTv2/src/analysis/green_backtest_runner.py`（集成状态机）

#### 核心实现代码

**文件1：`src/risk/regime_detector.py`**

```python
# -*- coding: utf-8 -*-
"""src/risk/regime_detector.py —— 市场状态机（牛市/熊市/震荡三状态识别）

依据规范：
1. 基于均线多空排列（MA20 vs MA60）
2. 结合MACD动量确认
3. 输出状态类型 + 置信度 + 仓位系数
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Dict, Tuple

import pandas as pd

logger = logging.getLogger("regime_detector")


class RegimeType(Enum):
    """市场状态枚举"""
    BULL = "bull"           # 牛市
    BEAR = "bear"           # 熊市
    SIDEWAYS = "sideways"   # 震荡


def calculate_macd(close_series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> float:
    """计算MACD柱状图（Histogram）
    
    Returns
    -------
    float : 最新的MACD柱状图值
    """
    ema_fast = close_series.ewm(span=fast, adjust=False).mean()
    ema_slow = close_series.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2.0
    return float(hist.iloc[-1])


def detect_market_regime(
    market_index: pd.Series,
    date,
    ma_short: int = 20,
    ma_long: int = 60,
    include_macd: bool = True
) -> Tuple[RegimeType, float, Dict[str, float]]:
    """识别市场状态
    
    Parameters
    ----------
    market_index : pd.Series
        市场指数时间序列（如上证指数），index=日期
    date : datetime or str
        当前日期
    ma_short : int
        短期均线窗口（默认20）
    ma_long : int
        长期均线窗口（默认60）
    include_macd : bool
        是否使用MACD作为辅助判断
        
    Returns
    -------
    regime : RegimeType
        识别的市场状态
    confidence : float
        置信度（0-1）
    indicators : Dict[str, float]
        判断依据指标
        
    Examples
    --------
    >>> index = pd.Series([3000, 3100, 3200, ...], index=dates)
    >>> regime, conf, ind = detect_market_regime(index, '2026-08-31')
    >>> regime
    <RegimeType.BULL: 'bull'>
    """
    # 计算均线
    ma20 = market_index.rolling(ma_short).mean().loc[date]
    ma60 = market_index.rolling(ma_long).mean().loc[date]
    
    # 计算MACD
    macd = calculate_macd(market_index.loc[:date]) if include_macd else 0.0
    
    # 状态判断逻辑
    if ma20 > ma60:
        if include_macd and macd > 0:
            regime = RegimeType.BULL
            confidence = 0.9  # 高置信度
        else:
            regime = RegimeType.SIDEWAYS
            confidence = 0.6  # 均线多头但动量衰竭
    elif ma20 < ma60:
        if include_macd and macd < 0:
            regime = RegimeType.BEAR
            confidence = 0.9  # 高置信度
        else:
            regime = RegimeType.SIDEWAYS
            confidence = 0.6  # 均线空头但动量转正
    else:
        regime = RegimeType.SIDEWAYS
        confidence = 0.4  # 均线缠绕
    
    indicators = {
        "MA20": float(ma20),
        "MA60": float(ma60),
        "MACD": macd,
        "signal_strength": confidence
    }
    
    logger.info(f"{date} 市场状态: {regime.value}, 置信度: {confidence:.2f}")
    
    return regime, confidence, indicators


def get_regime_position_coeff(
    regime: RegimeType,
    custom_coeffs: Dict[RegimeType, float] = None
) -> float:
    """获取状态对应的仓位系数
    
    Parameters
    ----------
    regime : RegimeType
        当前市场状态
    custom_coeffs : Dict[RegimeType, float], optional
        自定义系数，默认 {BULL: 1.0, SIDEWAYS: 0.7, BEAR: 0.3}
        
    Returns
    -------
    float : 仓位系数（0-1）
    """
    default_coeffs = {
        RegimeType.BULL: 1.0,      # 满仓
        RegimeType.SIDEWAYS: 0.7,  # 降低暴露
        RegimeType.BEAR: 0.3       # 防御性仓位
    }
    
    coeffs = custom_coeffs if custom_coeffs else default_coeffs
    return coeffs[regime]


def simulate_regime_transitions(
    market_index: pd.Series,
    start_date,
    end_date
) -> pd.DataFrame:
    """模拟历史状态转换序列
    
    Returns
    -------
    pd.DataFrame : columns=['date', 'regime', 'confidence', 'MA20', 'MA60', 'MACD']
    """
    dates = market_index.loc[start_date:end_date].index
    
    results = []
    for date in dates[60:]:  # 跳过前60天（需要MA60）
        regime, conf, ind = detect_market_regime(market_index, date)
        results.append({
            'date': date,
            'regime': regime.value,
            'confidence': conf,
            'MA20': ind['MA20'],
            'MA60': ind['MA60'],
            'MACD': ind['MACD']
        })
    
    return pd.DataFrame(results)
```

**文件2：`src/risk/dynamic_sizing.py`**

```python
# -*- coding: utf-8 -*-
"""src/risk/dynamic_sizing.py —— 动态仓位管理（状态依赖 + 回撤惩罚）"""

from __future__ import annotations

import logging
from typing import Dict

import pandas as pd

from src.risk.regime_detector import RegimeType, get_regime_position_coeff

logger = logging.getLogger("dynamic_sizing")


def calculate_dynamic_position(
    base_weights: pd.Series,
    regime: RegimeType,
    current_drawdown: float,
    max_drawdown_limit: float = 0.15,
    min_position: float = 0.0
) -> pd.DataFrame:
    """动态仓位计算（综合状态与回撤）
    
    Parameters
    ----------
    base_weights : pd.Series
        基础权重（来自Alpha排序），index=股票代码，values=权重
    regime : RegimeType
        当前市场状态
    current_drawdown : float
        当前回撤（正数，如0.10表示-10%）
    max_drawdown_limit : float
        最大容忍回撤（超过触发防御性减仓）
    min_position : float
        最小持仓比例
        
    Returns
    -------
    pd.DataFrame : columns=['stock_code', 'base_weight', 'regime_adjusted', 
                           'drawdown_adjusted', 'final_weight', 'adjustment_reason']
    
    Examples
    --------
    >>> base = pd.Series({'688525.SH': 0.15, '600989.SH': 0.12})
    >>> pos = calculate_dynamic_position(base, RegimeType.BEAR, current_drawdown=0.08)
    >>> pos['final_weight'].sum()  # 熊市降仓后
    0.30
    """
    # 状态系数
    regime_coeff = get_regime_position_coeff(regime)
    
    # 回撤惩罚
    drawdown_penalty = max(0, 1 - current_drawdown / max_drawdown_limit)
    
    # 计算调整后权重
    regime_adjusted = base_weights * regime_coeff
    drawdown_adjusted = regime_adjusted * drawdown_penalty
    final_weight = drawdown_adjusted.clip(lower=min_position)
    
    # 归一化（使权重和=1或目标仓位）
    total = final_weight.sum()
    if total > 0:
        final_weight = final_weight / total * (regime_coeff * drawdown_penalty)
    
    # 构建结果DataFrame
    results = []
    for stock_code in base_weights.index:
        adjustment_reason = []
        if regime != RegimeType.BULL:
            adjustment_reason.append(f"{regime.value}降仓{int((1-regime_coeff)*100)}%")
        if current_drawdown > 0.05:
            adjustment_reason.append(f"回撤惩罚{int((1-drawdown_penalty)*100)}%")
        
        results.append({
            'stock_code': stock_code,
            'base_weight': base_weights[stock_code],
            'regime_adjusted': regime_adjusted[stock_code],
            'drawdown_adjusted': drawdown_adjusted[stock_code],
            'final_weight': final_weight[stock_code],
            'adjustment_reason': ' + '.join(adjustment_reason) if adjustment_reason else '无调整'
        })
    
    df = pd.DataFrame(results)
    
    logger.info(f"动态仓位调整: {regime.value}, 总仓位={df['final_weight'].sum():.2%}")
    
    return df
```

**文件3：`tests/unit/test_regime_detector.py`**

```python
# -*- coding: utf-8 -*-
"""tests/unit/test_regime_detector.py —— 市场状态机单元测试"""

import pytest
import pandas as pd
import numpy as np

from src.risk.regime_detector import (
    RegimeType,
    detect_market_regime,
    get_regime_position_coeff,
    simulate_regime_transitions
)
from src.risk.dynamic_sizing import calculate_dynamic_position


def test_bull_market_detection():
    """测试牛市识别：价格上升，MA20>MA60"""
    dates = pd.date_range('2025-01-01', periods=100)
    prices = pd.Series(np.linspace(3000, 3500, 100), index=dates)
    
    regime, conf, ind = detect_market_regime(prices, dates[-1])
    
    assert regime == RegimeType.BULL
    assert conf > 0.7
    assert ind['MA20'] > ind['MA60']


def test_bear_market_detection():
    """测试熊市识别：价格下跌，MA20<MA60"""
    dates = pd.date_range('2025-01-01', periods=100)
    prices = pd.Series(np.linspace(3500, 3000, 100), index=dates)
    
    regime, conf, ind = detect_market_regime(prices, dates[-1])
    
    assert regime == RegimeType.BEAR
    assert conf > 0.7
    assert ind['MA20'] < ind['MA60']


def test_sideways_market_detection():
    """测试震荡市识别：价格横盘，均线缠绕"""
    dates = pd.date_range('2025-01-01', periods=100)
    prices = pd.Series(3300 + np.random.randn(100) * 50, index=dates)
    
    regime, conf, ind = detect_market_regime(prices, dates[-1])
    
    # 震荡市置信度应较低
    assert conf < 0.8


def test_position_coeff():
    """测试仓位系数"""
    assert get_regime_position_coeff(RegimeType.BULL) == 1.0
    assert get_regime_position_coeff(RegimeType.SIDEWAYS) == 0.7
    assert get_regime_position_coeff(RegimeType.BEAR) == 0.3


def test_dynamic_position_bear_market():
    """测试熊市动态仓位：应降至30%左右"""
    base = pd.Series({'A': 0.5, 'B': 0.5})
    adjusted = calculate_dynamic_position(
        base,
        RegimeType.BEAR,
        current_drawdown=0.05,
        max_drawdown_limit=0.15
    )
    
    # 熊市系数0.3，回撤惩罚 1-0.05/0.15=0.67
    # 总仓位应约 0.3 * 0.67 = 0.20
    assert 0.15 < adjusted['final_weight'].sum() < 0.25


def test_dynamic_position_bull_market():
    """测试牛市动态仓位：应接近100%"""
    base = pd.Series({'A': 0.5, 'B': 0.5})
    adjusted = calculate_dynamic_position(
        base,
        RegimeType.BULL,
        current_drawdown=0.02,
        max_drawdown_limit=0.15
    )
    
    # 牛市系数1.0，小回撤，应接近满仓
    assert adjusted['final_weight'].sum() > 0.85


def test_simulate_transitions():
    """测试状态转换序列生成"""
    dates = pd.date_range('2025-01-01', periods=200)
    prices = pd.Series(np.linspace(3000, 3500, 200), index=dates)
    
    trans = simulate_regime_transitions(prices, '2025-01-01', '2025-07-19')
    
    assert len(trans) > 0
    assert set(trans.columns) >= {'date', 'regime', 'confidence', 'MA20', 'MA60', 'MACD'}
    assert trans['regime'].isin(['bull', 'bear', 'sideways']).all()
```

#### 集成到绿电回测

**修改文件**：`Rainbow_FinGPTv2/src/analysis/green_backtest_runner.py`

在 `run_walk_forward_backtest` 方法中（约第122行），插入以下代码：

```python
# 在原有的宏观门控代码之前插入

from src.risk.regime_detector import detect_market_regime, get_regime_position_coeff
from src.risk.dynamic_sizing import calculate_dynamic_position

# 逐步推进仿真
for t in range(20, T):
    dt_str = str(dates[t].date())
    sub_prices = prices_df.iloc[:t]
    sub_nowcast = nowcast_df.iloc[:t]
    
    # ===== 新增：市场状态识别 =====
    sse_index = sub_prices["000300.SH"]  # 或单独加载上证指数
    regime, confidence, regime_indicators = detect_market_regime(sse_index, dates[t])
    regime_coeff = get_regime_position_coeff(regime)
    
    # 原有的宏观门控代码（保留）
    curr_absorb = float(sub_nowcast["grid_absorption_rate"].iloc[-1])
    curr_spot = float(sub_nowcast["green_power_market_price"].iloc[-1])
    macro_regime = (curr_absorb >= 90.0) and (curr_spot >= 0.35)
    
    # ... 原有的个股评分代码（保留）...
    
    # 在权重分配阶段（约第180行）插入动态仓位调整
    # 原代码：
    # current_weights = {ticker: weight for ticker, weight in ...}
    
    # 新代码：
    base_weights = pd.Series({ticker: weight for ticker, weight in ...})
    
    # 计算当前回撤
    if len(strat_nav) > 1:
        peak = max(strat_nav)
        current_dd = (peak - strat_nav[-1]) / peak
    else:
        current_dd = 0.0
    
    # 动态仓位调整
    adjusted_positions = calculate_dynamic_position(
        base_weights=base_weights,
        regime=regime,
        current_drawdown=current_dd,
        max_drawdown_limit=0.15
    )
    
    # 应用调整后的权重
    current_weights = adjusted_positions.set_index('stock_code')['final_weight'].to_dict()
    
    # ... 后续代码保持不变 ...
```

#### 运行与验证

```bash
# 1. 运行单元测试
pytest tests/unit/test_regime_detector.py -v

# 2. 运行完整回测
python Rainbow_FinGPTv2/src/analysis/green_backtest_runner.py

# 3. 对比指标
# Baseline: Sharpe 1.19, MaxDD 24.9%
# Target: Sharpe 1.31+, MaxDD 19.9-
```

#### 交付物
- 实现文件：`src/risk/regime_detector.py`, `src/risk/dynamic_sizing.py`
- 测试文件：`tests/unit/test_regime_detector.py`（至少6个测试用例）
- 更新后的回测脚本：`Rainbow_FinGPTv2/src/analysis/green_backtest_runner.py`

#### 验收标准
- ✅ 所有pytest测试通过
- ✅ 回测成功运行，生成结果JSON
- ✅ Sharpe Ratio 提升 ≥10%（1.19 → 1.31+）
- ✅ MaxDD 降低 ≥5%（24.9% → 19.9-）

---

### 【优先级P1】任务3：实现因子正交化模块（3天，依赖任务1）

#### 目标
剥离传统因子暴露，提取特质Alpha

#### 文件路径
**新建文件**：
- `src/pricing/factor_orthogonalization.py`
- `tests/unit/test_factor_orthogonalization.py`

#### 核心实现代码

**文件1：`src/pricing/factor_orthogonalization.py`**

```python
# -*- coding: utf-8 -*-
"""src/pricing/factor_orthogonalization.py —— 因子正交化（剥离风格暴露）"""

from __future__ import annotations

import logging
from typing import Dict, Tuple, Union

import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.decomposition import PCA

logger = logging.getLogger("factor_orthogonalization")


def orthogonalize_factor(
    candidate_factor: pd.Series,
    carhart_factors: pd.DataFrame,
    return_exposure: bool = False
) -> Union[pd.Series, Tuple[pd.Series, Dict[str, float]]]:
    """对Carhart四因子正交化，提取特质成分
    
    Parameters
    ----------
    candidate_factor : pd.Series
        原始因子值，index为日期
    carhart_factors : pd.DataFrame
        Carhart四因子时间序列，columns=['MKT','SMB','HML','MOM']
    return_exposure : bool
        是否返回对四因子的暴露系数
        
    Returns
    -------
    residual : pd.Series
        正交化后的特质成分（残差）
    exposures : Dict[str, float], optional
        对四因子的回归系数 {'MKT': 0.8, 'SMB': 0.2, 'R2': 0.65, ...}
        
    Raises
    ------
    ValueError
        如果日期不对齐或存在缺失值
        
    Examples
    --------
    >>> factor = pd.Series([0.5, 0.8, 0.3], index=dates)
    >>> carhart = pd.DataFrame({'MKT': [0.01, 0.02, -0.01], ...})
    >>> residual = orthogonalize_factor(factor, carhart)
    >>> residual.mean()  # 应接近0
    0.001
    """
    # 对齐日期
    merged = pd.concat([candidate_factor, carhart_factors], axis=1, join='inner')
    
    if len(merged) < 30:
        raise ValueError(f"对齐后数据点不足30个（实际{len(merged)}），无法进行回归")
    
    if merged.isnull().any().any():
        raise ValueError("存在缺失值或无穷值，请先清洗数据")
    
    y = merged.iloc[:, 0].values
    X = merged.iloc[:, 1:].values
    
    # OLS回归
    model = LinearRegression()
    model.fit(X, y)
    
    # 残差即为正交化后的特质成分
    residual = y - model.predict(X)
    residual_series = pd.Series(residual, index=merged.index, name='orthogonal_factor')
    
    logger.info(f"因子正交化完成: R²={model.score(X, y):.3f}, 残差均值={residual.mean():.6f}")
    
    if return_exposure:
        exposures = {
            name: coef 
            for name, coef in zip(carhart_factors.columns, model.coef_)
        }
        exposures['R2'] = model.score(X, y)
        exposures['intercept'] = model.intercept_
        
        # 计算t统计量
        n, p = X.shape
        residual_std = np.sqrt(np.sum(residual**2) / (n - p - 1))
        X_with_intercept = np.column_stack([np.ones(n), X])
        se = residual_std * np.sqrt(np.diag(np.linalg.inv(X_with_intercept.T @ X_with_intercept)))
        
        for i, name in enumerate(carhart_factors.columns):
            exposures[f't_{name}'] = model.coef_[i] / se[i+1]
        
        return residual_series, exposures
    
    return residual_series


def pca_factor_reduction(
    semantic_factors: pd.DataFrame,
    n_components: Union[int, float] = 0.8,
    return_loadings: bool = False
) -> Union[pd.DataFrame, Tuple[pd.DataFrame, pd.DataFrame]]:
    """对语义因子矩阵进行PCA降维，避免多重共线性
    
    Parameters
    ----------
    semantic_factors : pd.DataFrame
        语义因子矩阵，行=日期，列=因子名称
    n_components : int or float
        保留的主成分数量（int）或解释方差比例（float, 0-1）
    return_loadings : bool
        是否返回主成分载荷矩阵
        
    Returns
    -------
    principal_components : pd.DataFrame
        主成分矩阵，columns=['PC1', 'PC2', ...]
    loadings : pd.DataFrame, optional
        载荷矩阵，行=原始因子，列=主成分
        
    Examples
    --------
    >>> factors = pd.DataFrame({'订单增长': [...], '产能扩张': [...]})
    >>> pcs = pca_factor_reduction(factors, n_components=0.8)
    >>> pcs.shape[1]  # 保留80%方差所需的主成分数
    3
    """
    if semantic_factors.shape[1] < 2:
        raise ValueError("至少需要2个因子才能进行PCA")
    
    pca = PCA(n_components=n_components)
    principal_components = pca.fit_transform(semantic_factors)
    
    pc_df = pd.DataFrame(
        principal_components,
        index=semantic_factors.index,
        columns=[f'PC{i+1}' for i in range(principal_components.shape[1])]
    )
    
    logger.info(f"PCA降维: {semantic_factors.shape[1]}维 → {pc_df.shape[1]}维, "
                f"累计解释方差={pca.explained_variance_ratio_.sum():.2%}")
    
    if return_loadings:
        loadings = pd.DataFrame(
            pca.components_.T,
            index=semantic_factors.columns,
            columns=pc_df.columns
        )
        return pc_df, loadings
    
    return pc_df
```

**文件2：`tests/unit/test_factor_orthogonalization.py`**

```python
# -*- coding: utf-8 -*-
"""tests/unit/test_factor_orthogonalization.py"""

import pytest
import pandas as pd
import numpy as np

from src.pricing.factor_orthogonalization import orthogonalize_factor, pca_factor_reduction


def test_orthogonalize_removes_market_exposure():
    """验证正交化后与市场因子不相关"""
    # 构造与MKT高度相关的人工因子
    carhart = pd.DataFrame({
        'MKT': np.random.randn(100),
        'SMB': np.random.randn(100),
        'HML': np.random.randn(100),
        'MOM': np.random.randn(100)
    })
    factor = 0.8 * carhart['MKT'] + np.random.randn(100) * 0.2
    
    residual = orthogonalize_factor(pd.Series(factor), carhart)
    
    # 残差与MKT相关系数应接近0
    assert abs(residual.corr(carhart['MKT'])) < 0.1


def test_orthogonalize_with_exposure():
    """测试返回暴露系数"""
    carhart = pd.DataFrame({
        'MKT': np.random.randn(100),
        'SMB': np.random.randn(100),
        'HML': np.random.randn(100),
        'MOM': np.random.randn(100)
    })
    factor = 0.8 * carhart['MKT'] + 0.2 * carhart['SMB'] + np.random.randn(100) * 0.1
    
    residual, exposures = orthogonalize_factor(pd.Series(factor), carhart, return_exposure=True)
    
    # MKT暴露应接近0.8
    assert 0.7 < exposures['MKT'] < 0.9
    # R2应较高
    assert exposures['R2'] > 0.6


def test_orthogonalize_residual_mean_near_zero():
    """验证残差均值接近0"""
    carhart = pd.DataFrame({
        'MKT': np.random.randn(100),
        'SMB': np.random.randn(100),
        'HML': np.random.randn(100),
        'MOM': np.random.randn(100)
    })
    factor = pd.Series(np.random.randn(100))
    
    residual = orthogonalize_factor(factor, carhart)
    
    assert abs(residual.mean()) < 0.1


def test_pca_orthogonality():
    """验证主成分两两正交"""
    factors = pd.DataFrame({
        f'factor_{i}': np.random.randn(100) for i in range(5)
    })
    
    pcs = pca_factor_reduction(factors, n_components=3)
    
    corr_matrix = pcs.corr()
    off_diagonal = corr_matrix.values[np.triu_indices_from(corr_matrix.values, k=1)]
    
    # 主成分相关系数应接近0
    assert np.all(np.abs(off_diagonal) < 0.01)


def test_pca_variance_explained():
    """验证方差解释比例"""
    factors = pd.DataFrame({
        f'factor_{i}': np.random.randn(100) for i in range(10)
    })
    
    pcs = pca_factor_reduction(factors, n_components=0.8)
    
    # 应保留足够的主成分以达到80%方差
    assert pcs.shape[1] >= 2
```

#### 使用示例（如果有语义因子）

```python
# 在 FamaMacBethV3Engine 之前预处理
from src.pricing.factor_orthogonalization import orthogonalize_factor

# 加载CSMAR四因子
carhart = pd.read_csv("data/school_factors/csmar_carhart_4factors.csv", 
                      index_col='date', parse_dates=True)

# 对语义因子正交化（如果有）
semantic_score = ...  # 从SCNU-RAG或其他来源获取
orthogonal_alpha = orthogonalize_factor(semantic_score, carhart)

# 或者用资金流向因子演示（当前绿电板块有）
large_order = factors_df['LARGE_ORDER_INFLOW']
orthogonal_order = orthogonalize_factor(large_order, carhart)
```

#### 交付物
- 实现文件：`src/pricing/factor_orthogonalization.py`
- 测试文件：`tests/unit/test_factor_orthogonalization.py`（至少5个测试用例）

#### 验收标准
- ✅ 所有pytest测试通过
- ✅ 正交化后因子与Carhart四因子相关系数 < 0.05
- ✅ 代码风格符合项目规范（中文注释 + 类型注解）

---

### 【优先级P2】任务4：因果推断框架原型（可选，7-10天）

**说明**：此任务为学术创新加分项，时间不够可跳过。

详细设计参考：`specs/contest-2026/contracts/causal_inference.md`

核心功能：
- Granger 因果检验（验证"因子 → 收益"因果链）
- 因果图谱构建（可视化传导路径）
- do-calculus 干预模拟（"如果X=1.0，收益变化多少"）

**交付物**：
- `src/research/causal/granger_test.py`
- `src/research/causal/causal_graph.py`
- 简短实验报告（3-5页PDF）

---

## 三、项目技术参考

### 代码风格要求（必须遵守）
1. **中文注释**：所有docstring和注释用中文
2. **类型注解**：使用 `from __future__ import annotations` + 完整类型注解
3. **dataclass**：用 `@dataclass` 定义数据结构
4. **日志记录**：`logger = logging.getLogger("module_name")`
5. **测试覆盖率**：核心逻辑 >90%，边界情况 >80%

### 现有代码参考
**核心引擎**：
- `Rainbow_FinGPTv2/src/execution/trend_gate.py` - 趋势门控实现
- `Rainbow_FinGPTv2/src/analysis/famamacbethv3.py` - Fama-MacBeth回归
- `Rainbow_FinGPTv2/src/analysis/green_backtest_runner.py` - 回测主程序

**数据目录**：
- `data/raw/backtest_green_2025q3_2026q3/` - 绿电原始数据
- `data/school_factors/` - CSMAR因子存放目录（热插拔）

### 设计文档（已生成）
所有文档位于 `specs/contest-2026/`：
1. `spec.md` - 功能规格
2. `research.md` - 技术选型（15 KB，详细评估了4个学术方向）
3. `data-model.md` - 数据结构设计
4. `contracts/` - API契约（正交化/状态机/因果推断）
5. `quickstart.md` - 30分钟快速入门

---

## 四、验收标准

### 代码质量
- ✅ 所有pytest测试通过（`pytest tests/unit/ -v`）
- ✅ 代码风格符合项目规范
- ✅ 无硬编码路径，使用相对路径或配置
- ✅ 日志记录完整

### 功能验证
- ✅ 绿电回测成功运行，生成结果JSON
- ✅ Sharpe Ratio 提升 ≥10%（1.19 → 1.31+）
- ✅ MaxDD 降低 ≥5%（24.9% → 19.9-）

### 文档交付
- ✅ CSMAR数据文件：`data/school_factors/csmar_carhart_4factors.csv`
- ✅ 实现文件：`src/risk/regime_detector.py`, `src/risk/dynamic_sizing.py`, `src/pricing/factor_orthogonalization.py`（可选）
- ✅ 测试文件：对应的 `tests/unit/test_*.py`
- ✅ 回测输出：`docs/data/paper/backtest_green_enhanced.json`

---

## 五、时间安排

| 任务 | 预计时间 | 优先级 |
|------|---------|--------|
| 任务1：下载CSMAR数据 | 1小时 | P0 |
| 任务2：市场状态机 | 3-4天 | P0 |
| 任务3：因子正交化 | 3天 | P1 |
| 任务4：因果推断 | 7-10天 | P2（可跳过）|

**总计**：
- 最小交付（任务1+2）：4天
- 完整交付（任务1+2+3）：1-1.5周
- 学术创新（全部）：3-4周

---

## 六、常见问题

**Q1：CSMAR API调用失败怎么办？**
A：检查网络（需校内IP或VPN），确认表名和字段名（在CSMAR网站查询文档）

**Q2：回测指标没有提升反而下降？**
A：检查状态机参数（MA20/MA60是否合理）、动态仓位系数（是否过于保守）

**Q3：pytest测试失败？**
A：检查依赖库版本（pandas, numpy, sklearn），确认测试数据构造是否合理

**Q4：时间不够怎么办？**
A：优先完成任务1+2（市场状态机），这是最核心的改进，任务3（正交化）可暂缓

---

## 七、技术支持

如遇到问题，参考以下资源：
1. **设计文档**：`specs/contest-2026/` 下的所有文件
2. **现有代码**：`Rainbow_FinGPTv2/src/` 下的参考实现
3. **测试用例**：`tests/unit/` 下的既有测试

---

**任务包准备完毕，预计完成时间：1-1.5周（最小交付4天）**
