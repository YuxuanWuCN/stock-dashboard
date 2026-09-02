# Rainbow-FinGPT 方向校准修复任务包 - 交给Gemini执行

**任务来源**：只读诊断发现因子方向随时间失效，命中率49.08%低于随机基线

**优先级**：🔴 **P0 - 最高优先级**（必须先于系统优化任务包执行）

**项目路径**：`D:\R-FinGPTv2（国创版本）\`

**预计工作量**：2-3天

---

## 一、问题诊断摘要

### 当前系统表现

| 指标 | 数值 | 问题 |
|------|------|------|
| 1日命中率（当前模型） | 49.08% | **低于随机基线50%** |
| 1日命中率（全量取反） | 50.92% | 略有改善，但不足以证明有效 |
| 1日命中率（高置信10%） | 54.70% | 覆盖率太低，不可持续 |
| 5日命中率（前半段） | 71.62% | 看似优秀 |
| 5日命中率（后半段） | 44.55% | **严重衰减，过拟合证据** |
| 5日命中率（最后20日） | 50.00% | 优势完全消失 |

### 核心问题

**因子方向随时间失效（Factor Decay）**：
- 前半段有效的因子方向，在后半段失效甚至反转
- 简单的"全量取反"或"高置信过滤"会产生强过拟合
- 不能直接宣称"命中率提升"，否则比赛时会暴露

### 根本原因

1. **制度性变化**：市场环境、政策、行业周期变化导致因子失效
2. **前视偏差**：可能在训练或评分中意外使用了未来信息
3. **样本选择偏差**：高置信样本在不同时间段分布不均

---

## 二、修复方案：滚动方向校准 + 拒绝预测

### 核心原则（严格遵守）

✅ **只使用已公布结果的历史窗口**判断因子方向  
✅ **严禁读取未来数据**（T日决策只能用T-1及之前的数据）  
✅ **增加拒绝预测机制**（不确定时输出"暂不判断"）  
✅ **同时报告命中率、覆盖率、样本数、时间段稳定性**  
✅ **达不到目标就诚实保留"暂无优势"，不刷参数**  

### 目标设定

**可接受的成功标准**（在严格留出的后段数据上）：
- 覆盖率：20% - 30%
- 1日命中率：稳定超过 53%
- 前后时间段命中率差异 < 5%（稳定性验证）

**诚实口径**：
- 如果达不到，保留"暂无优势"结论
- 不宣传5日、20日预测（60个交易日不足以验证）
- 只攻"1日方向"预测

---

## 三、详细实现任务

### 【任务1】滚动方向校准模块（1-1.5天）

#### 目标
在每个交易日T，使用过去N天的历史数据，判断当前因子应该：
- **正向使用**（分数高 → 看多）
- **反向使用**（分数高 → 看空）
- **暂停使用**（方向不明确）

#### 文件路径
**新建文件**：
- `src/pricing/rolling_direction_calibration.py`
- `tests/unit/test_rolling_direction_calibration.py`

#### 核心实现代码

**文件1：`src/pricing/rolling_direction_calibration.py`**

```python
# -*- coding: utf-8 -*-
"""src/pricing/rolling_direction_calibration.py —— 滚动方向校准（修复因子时变失效）

核心原则：
1. 严禁前视偏差：T日决策只能用T-1及之前的数据
2. 滚动窗口验证：用最近N天的实际表现判断因子当前方向
3. 拒绝预测：方向不明确时返回None
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger("rolling_direction_calibration")


class FactorDirection(Enum):
    """因子使用方向"""
    POSITIVE = "positive"   # 正向：分数高=看多
    NEGATIVE = "negative"   # 反向：分数高=看空
    INVALID = "invalid"     # 无效：拒绝预测


@dataclass
class CalibrationResult:
    """校准结果"""
    direction: FactorDirection
    confidence: float  # 0-1，方向置信度
    hit_rate: float    # 回溯窗口内的命中率
    sample_size: int   # 样本数
    p_value: float     # 统计显著性
    reason: str        # 决策原因（用于日志和报告）


def calculate_hit_rate(
    factor_scores: pd.Series,
    actual_returns: pd.Series,
    direction: FactorDirection
) -> Tuple[float, int]:
    """计算命中率
    
    Parameters
    ----------
    factor_scores : pd.Series
        因子分数，index=股票代码
    actual_returns : pd.Series
        实际1日收益率，index=股票代码
    direction : FactorDirection
        测试方向（正向或反向）
        
    Returns
    -------
    hit_rate : float
        命中率（0-1）
    sample_size : int
        有效样本数
    """
    # 对齐数据
    merged = pd.concat([factor_scores, actual_returns], axis=1, join='inner')
    merged.columns = ['score', 'return']
    merged = merged.dropna()
    
    if len(merged) == 0:
        return 0.0, 0
    
    # 根据方向判断预测正确性
    if direction == FactorDirection.POSITIVE:
        # 正向：分数>0预测涨，分数<0预测跌
        prediction = merged['score'] > 0
    elif direction == FactorDirection.NEGATIVE:
        # 反向：分数>0预测跌，分数<0预测涨
        prediction = merged['score'] < 0
    else:
        return 0.0, 0
    
    actual_direction = merged['return'] > 0
    
    correct = (prediction == actual_direction).sum()
    hit_rate = correct / len(merged)
    
    return hit_rate, len(merged)


def calibrate_factor_direction(
    factor_scores_history: pd.DataFrame,
    returns_history: pd.DataFrame,
    current_date,
    lookback_days: int = 30,
    min_samples: int = 50,
    significance_level: float = 0.05
) -> CalibrationResult:
    """滚动方向校准（核心函数）
    
    Parameters
    ----------
    factor_scores_history : pd.DataFrame
        历史因子分数，行=日期，列=股票代码
        **重要**：current_date这一行应该是T日的分数，但不能用于计算命中率
    returns_history : pd.DataFrame
        历史1日收益率，行=日期，列=股票代码
        returns_history.loc[T] 是T日收盘到T+1日收盘的收益率
    current_date : datetime or str
        当前决策日期T（此日期的因子不能用于回测）
    lookback_days : int
        回溯窗口长度（默认30天）
    min_samples : int
        最小样本要求（不足则拒绝预测）
    significance_level : float
        统计显著性阈值（p-value）
        
    Returns
    -------
    CalibrationResult
        校准结果，包含方向、置信度、命中率等
        
    Examples
    --------
    >>> scores = pd.DataFrame(...)  # 历史因子分数
    >>> returns = pd.DataFrame(...)  # 历史收益率
    >>> result = calibrate_factor_direction(scores, returns, '2026-08-31')
    >>> if result.direction != FactorDirection.INVALID:
    ...     print(f"使用{result.direction.value}方向，置信度{result.confidence:.2%}")
    """
    # 获取回溯窗口（T-1 往前lookback_days天）
    # 重要：不能用T日的数据，因为T日收益率在T+1才知道
    dates = factor_scores_history.index
    current_idx = dates.get_loc(current_date)
    
    if current_idx < lookback_days:
        return CalibrationResult(
            direction=FactorDirection.INVALID,
            confidence=0.0,
            hit_rate=0.0,
            sample_size=0,
            p_value=1.0,
            reason=f"历史数据不足{lookback_days}天"
        )
    
    # 窗口：[T-lookback_days, T-1]
    start_idx = current_idx - lookback_days
    end_idx = current_idx - 1  # 不包含T日
    
    window_dates = dates[start_idx:end_idx+1]
    
    # 收集窗口内所有样本的命中情况
    positive_hits = []
    negative_hits = []
    
    for date in window_dates:
        # T日的分数 vs T日的收益率（T收盘→T+1收盘）
        scores = factor_scores_history.loc[date]
        
        # 检查returns_history是否有对应日期
        if date not in returns_history.index:
            continue
            
        returns = returns_history.loc[date]
        
        # 计算正向和反向命中率
        pos_rate, pos_n = calculate_hit_rate(scores, returns, FactorDirection.POSITIVE)
        neg_rate, neg_n = calculate_hit_rate(scores, returns, FactorDirection.NEGATIVE)
        
        if pos_n > 0:
            positive_hits.extend([1] * int(pos_rate * pos_n) + [0] * int((1-pos_rate) * pos_n))
        if neg_n > 0:
            negative_hits.extend([1] * int(neg_rate * neg_n) + [0] * int((1-neg_rate) * neg_n))
    
    # 样本量检查
    n_pos = len(positive_hits)
    n_neg = len(negative_hits)
    
    if n_pos < min_samples and n_neg < min_samples:
        return CalibrationResult(
            direction=FactorDirection.INVALID,
            confidence=0.0,
            hit_rate=0.0,
            sample_size=max(n_pos, n_neg),
            p_value=1.0,
            reason=f"有效样本不足{min_samples}个（正向{n_pos}，反向{n_neg}）"
        )
    
    # 计算命中率
    hit_rate_pos = np.mean(positive_hits) if n_pos > 0 else 0.0
    hit_rate_neg = np.mean(negative_hits) if n_neg > 0 else 0.0
    
    # 统计检验：Binomial test（H0: hit_rate = 0.5）
    if n_pos >= min_samples:
        p_value_pos = stats.binom_test(sum(positive_hits), n_pos, 0.5, alternative='greater')
    else:
        p_value_pos = 1.0
    
    if n_neg >= min_samples:
        p_value_neg = stats.binom_test(sum(negative_hits), n_neg, 0.5, alternative='greater')
    else:
        p_value_neg = 1.0
    
    # 决策逻辑
    # 1. 如果正向显著优于反向，使用正向
    if p_value_pos < significance_level and hit_rate_pos > hit_rate_neg:
        confidence = 1 - p_value_pos  # 转换为置信度
        return CalibrationResult(
            direction=FactorDirection.POSITIVE,
            confidence=confidence,
            hit_rate=hit_rate_pos,
            sample_size=n_pos,
            p_value=p_value_pos,
            reason=f"正向命中率{hit_rate_pos:.2%}显著>50% (p={p_value_pos:.4f})"
        )
    
    # 2. 如果反向显著优于正向，使用反向
    if p_value_neg < significance_level and hit_rate_neg > hit_rate_pos:
        confidence = 1 - p_value_neg
        return CalibrationResult(
            direction=FactorDirection.NEGATIVE,
            confidence=confidence,
            hit_rate=hit_rate_neg,
            sample_size=n_neg,
            p_value=p_value_neg,
            reason=f"反向命中率{hit_rate_neg:.2%}显著>50% (p={p_value_neg:.4f})"
        )
    
    # 3. 两者都不显著，或命中率都低于52%，拒绝预测
    max_hit = max(hit_rate_pos, hit_rate_neg)
    if max_hit < 0.52:
        return CalibrationResult(
            direction=FactorDirection.INVALID,
            confidence=0.0,
            hit_rate=max_hit,
            sample_size=max(n_pos, n_neg),
            p_value=min(p_value_pos, p_value_neg),
            reason=f"命中率不足52%（正向{hit_rate_pos:.2%}，反向{hit_rate_neg:.2%}）"
        )
    
    # 4. 都有一定效果但不够显著，选择较好的但降低置信度
    if hit_rate_pos > hit_rate_neg:
        return CalibrationResult(
            direction=FactorDirection.POSITIVE,
            confidence=0.6,  # 低置信度
            hit_rate=hit_rate_pos,
            sample_size=n_pos,
            p_value=p_value_pos,
            reason=f"正向略优（{hit_rate_pos:.2%}）但不显著 (p={p_value_pos:.4f})"
        )
    else:
        return CalibrationResult(
            direction=FactorDirection.NEGATIVE,
            confidence=0.6,
            hit_rate=hit_rate_neg,
            sample_size=n_neg,
            p_value=p_value_neg,
            reason=f"反向略优（{hit_rate_neg:.2%}）但不显著 (p={p_value_neg:.4f})"
        )


def apply_calibrated_direction(
    factor_scores: pd.Series,
    calibration: CalibrationResult,
    confidence_threshold: float = 0.7
) -> pd.Series:
    """应用校准后的方向
    
    Parameters
    ----------
    factor_scores : pd.Series
        当前日期的因子分数，index=股票代码
    calibration : CalibrationResult
        校准结果
    confidence_threshold : float
        置信度阈值（低于此值拒绝预测）
        
    Returns
    -------
    pd.Series
        调整后的分数（可能取反），拒绝预测的股票返回NaN
    """
    if calibration.direction == FactorDirection.INVALID:
        # 全部拒绝预测
        return pd.Series(np.nan, index=factor_scores.index)
    
    if calibration.confidence < confidence_threshold:
        # 置信度不足，拒绝预测
        logger.warning(f"置信度{calibration.confidence:.2%}低于阈值{confidence_threshold:.2%}，拒绝预测")
        return pd.Series(np.nan, index=factor_scores.index)
    
    if calibration.direction == FactorDirection.POSITIVE:
        return factor_scores
    elif calibration.direction == FactorDirection.NEGATIVE:
        return -factor_scores
    else:
        return pd.Series(np.nan, index=factor_scores.index)


def generate_calibration_report(
    factor_scores_history: pd.DataFrame,
    returns_history: pd.DataFrame,
    start_date,
    end_date,
    lookback_days: int = 30
) -> pd.DataFrame:
    """生成完整的历史校准报告（用于验证）
    
    Returns
    -------
    pd.DataFrame
        columns=['date', 'direction', 'confidence', 'hit_rate', 'sample_size', 
                 'p_value', 'reason']
    """
    dates = pd.date_range(start_date, end_date, freq='B')  # 交易日
    dates = [d for d in dates if d in factor_scores_history.index]
    
    results = []
    for date in dates[lookback_days:]:  # 跳过前lookback_days天
        calibration = calibrate_factor_direction(
            factor_scores_history,
            returns_history,
            date,
            lookback_days=lookback_days
        )
        
        results.append({
            'date': date,
            'direction': calibration.direction.value,
            'confidence': calibration.confidence,
            'hit_rate': calibration.hit_rate,
            'sample_size': calibration.sample_size,
            'p_value': calibration.p_value,
            'reason': calibration.reason
        })
    
    return pd.DataFrame(results)
```

#### 交付物
- `src/pricing/rolling_direction_calibration.py`（完整实现）
- `tests/unit/test_rolling_direction_calibration.py`（至少6个测试用例）

---

### 【任务2】拒绝预测机制（0.5天）

#### 目标
在预测结果中增加"拒绝预测"标识，只输出高置信度的预测

#### 实现要点

**在现有预测输出中增加字段**：

```python
@dataclass
class StockPrediction:
    """股票预测结果（增强版）"""
    stock_code: str
    date: datetime
    
    # 原有字段
    raw_score: float          # 原始因子分数
    alpha: float              # Alpha预期收益
    
    # 新增字段
    calibrated_score: Optional[float]  # 校准后的分数（可能取反或None）
    direction_used: str                # 使用的方向（positive/negative/invalid）
    calibration_confidence: float      # 校准置信度
    is_rejected: bool                  # 是否拒绝预测
    rejection_reason: str              # 拒绝原因
    
    # 最终决策
    final_recommendation: str          # "BUY" / "SELL" / "HOLD" / "NO_PREDICTION"
```

**在回测输出中统计**：

```python
# 在回测结果JSON中增加
{
    "prediction_coverage": {
        "total_opportunities": 1000,      # 总预测机会
        "valid_predictions": 250,         # 有效预测数
        "rejected_predictions": 750,      # 拒绝预测数
        "coverage_rate": 0.25,            # 覆盖率25%
        "rejection_reasons": {
            "low_confidence": 500,
            "insufficient_samples": 200,
            "hit_rate_below_threshold": 50
        }
    },
    "prediction_performance": {
        "1d_hit_rate_all": 0.5092,       # 如果全部预测的命中率
        "1d_hit_rate_valid_only": 0.5470, # 仅有效预测的命中率
        "coverage_vs_performance": [
            {"coverage": 0.10, "hit_rate": 0.5470},
            {"coverage": 0.20, "hit_rate": 0.5350},
            {"coverage": 0.30, "hit_rate": 0.5280}
        ]
    }
}
```

---

### 【任务3】集成到绿电回测（1天）

#### 修改文件
`Rainbow_FinGPTv2/src/analysis/green_backtest_runner.py`

#### 集成代码

在评分生成后（约第150-180行），插入校准逻辑：

```python
from src.pricing.rolling_direction_calibration import (
    calibrate_factor_direction,
    apply_calibrated_direction,
    FactorDirection
)

# 原有代码：生成个股评分
# scores = fama_engine.score_stocks(...)

# ===== 新增：滚动方向校准 =====
# 构建历史因子分数DataFrame（用于校准）
if not hasattr(self, 'factor_scores_history'):
    self.factor_scores_history = pd.DataFrame()
    self.returns_history = pd.DataFrame()

# 当前评分转为Series
current_scores = pd.Series({ticker: score for ticker, score in scores.items()})

# 校准方向
calibration = calibrate_factor_direction(
    factor_scores_history=self.factor_scores_history,
    returns_history=self.returns_history,
    current_date=dates[t],
    lookback_days=30,  # 30天滚动窗口
    min_samples=50,
    significance_level=0.05
)

logger.info(f"{dates[t]} 方向校准: {calibration.reason}")

# 应用校准（可能取反或拒绝）
calibrated_scores = apply_calibrated_direction(
    factor_scores=current_scores,
    calibration=calibration,
    confidence_threshold=0.7  # 只保留置信度>70%的预测
)

# 过滤掉NaN（被拒绝的预测）
valid_scores = calibrated_scores.dropna()

logger.info(f"{dates[t]} 有效预测数: {len(valid_scores)}/{len(current_scores)} "
           f"(覆盖率{len(valid_scores)/len(current_scores):.1%})")

# 用校准后的分数进行排序和选股
# ... 后续代码使用 valid_scores 替代原来的 scores ...

# ===== 记录历史（用于下一轮校准，严格T+1更新） =====
# 注意：只有在T+1日知道T日收益后，才能更新returns_history
if t > 0:
    prev_date = dates[t-1]
    # 计算T-1日的实际收益（T-1收盘→T收盘）
    prev_returns = {}
    for ticker in current_scores.index:
        if ticker in sub_prices.columns:
            ret = (sub_prices[ticker].iloc[t] / sub_prices[ticker].iloc[t-1]) - 1
            prev_returns[ticker] = ret
    
    # 更新历史记录
    self.returns_history.loc[prev_date] = pd.Series(prev_returns)

# 记录当前评分（用于未来校准）
self.factor_scores_history.loc[dates[t]] = current_scores
```

---

### 【任务4】验证与报告（0.5天）

#### 验证协议

**数据分割**：
- 训练/校准期：前40个交易日（2025-Q3到2026-Q2）
- 验证期：后20个交易日（2026-Q3最近20日）

**严格要求**：
- 验证期的校准只能用验证期之前的数据
- 不允许用验证期数据调参数（lookback_days、confidence_threshold等）

**验证脚本**：

```python
# tests/validation/test_calibration_stability.py

def test_forward_validation():
    """前向验证：严格时间分割"""
    # 加载数据
    scores = pd.read_csv("data/raw/backtest_green_2025q3_2026q3/factor_scores.csv")
    prices = pd.read_csv("data/raw/backtest_green_2025q3_2026q3/prices.csv")
    
    # 计算收益率
    returns = prices.pct_change()
    
    # 时间分割
    split_date = '2026-07-01'
    
    # 前40日作为校准期
    calibration_scores = scores[scores['date'] < split_date]
    calibration_returns = returns[returns.index < split_date]
    
    # 后20日作为验证期
    validation_dates = scores[scores['date'] >= split_date]['date'].unique()
    
    results = []
    
    for date in validation_dates:
        # 校准（只用date之前的数据）
        calib = calibrate_factor_direction(
            factor_scores_history=scores[scores['date'] < date],
            returns_history=returns[returns.index < date],
            current_date=date,
            lookback_days=30
        )
        
        # 应用
        current_scores = scores[scores['date'] == date].set_index('stock_code')['score']
        calibrated = apply_calibrated_direction(current_scores, calib, confidence_threshold=0.7)
        
        # 评估
        valid_predictions = calibrated.dropna()
        
        if len(valid_predictions) > 0:
            actual_returns = returns.loc[date, valid_predictions.index]
            
            # 计算命中率
            predicted_up = valid_predictions > 0
            actual_up = actual_returns > 0
            hit_rate = (predicted_up == actual_up).mean()
            
            results.append({
                'date': date,
                'coverage': len(valid_predictions) / len(current_scores),
                'hit_rate': hit_rate,
                'direction': calib.direction.value,
                'confidence': calib.confidence
            })
    
    df_results = pd.DataFrame(results)
    
    # 验收标准
    overall_coverage = df_results['coverage'].mean()
    overall_hit_rate = df_results['hit_rate'].mean()
    
    # 时间段稳定性
    first_half = df_results.iloc[:10]['hit_rate'].mean()
    second_half = df_results.iloc[10:]['hit_rate'].mean()
    stability = abs(first_half - second_half)
    
    print(f"验证期表现:")
    print(f"  覆盖率: {overall_coverage:.1%}")
    print(f"  命中率: {overall_hit_rate:.1%}")
    print(f"  前10日命中率: {first_half:.1%}")
    print(f"  后10日命中率: {second_half:.1%}")
    print(f"  稳定性（差异）: {stability:.1%}")
    
    # 断言验收标准
    assert 0.20 <= overall_coverage <= 0.35, f"覆盖率{overall_coverage:.1%}不在20-35%范围"
    assert overall_hit_rate >= 0.53, f"命中率{overall_hit_rate:.1%}低于53%"
    assert stability < 0.05, f"前后差异{stability:.1%}超过5%"
    
    return df_results
```

#### 最终报告格式

```markdown
# 方向校准修复验证报告

## 数据概况
- 总样本: 60个交易日（2025-Q3至2026-Q3）
- 校准期: 前40日
- 验证期: 后20日（严格留出）

## 整体表现

| 指标 | 修复前 | 修复后 | 改善 |
|------|--------|--------|------|
| 1日命中率（全量） | 49.08% | 50.92% | +1.84% |
| 1日命中率（有效预测） | 49.08% | **54.20%** | +5.12% |
| 覆盖率 | 100% | 25.3% | -74.7% |
| 样本数 | 1000 | 253 | -747 |

## 验证期表现（后20日）

| 指标 | 数值 | 是否达标 |
|------|------|----------|
| 覆盖率 | 25.3% | ✅ 在20-30%范围 |
| 1日命中率 | 54.2% | ✅ 超过53% |
| 前10日命中率 | 55.1% | ✅ |
| 后10日命中率 | 53.3% | ✅ |
| 前后差异 | 1.8% | ✅ 小于5% |

## 方向使用统计

| 日期区间 | 正向使用 | 反向使用 | 拒绝预测 |
|----------|----------|----------|----------|
| 前20日 | 12天 | 5天 | 3天 |
| 后20日 | 8天 | 9天 | 3天 |

**关键发现**: 后半段反向使用增加（5→9天），验证了因子方向确实在时间上漂移。

## 拒绝预测原因分析

| 原因 | 次数 | 占比 |
|------|------|------|
| 置信度不足 | 4 | 66.7% |
| 样本量不足 | 2 | 33.3% |

## 结论

✅ **达到预设目标**：
- 覆盖率25.3%（目标20-30%）
- 命中率54.2%（目标>53%）
- 时间稳定性1.8%差异（目标<5%）

✅ **诚实口径**：
- 不宣传5日、20日预测
- 同时报告命中率和覆盖率
- 保留拒绝预测选项

⚠️ **已知限制**：
- 覆盖率仅25%，意味着75%的时间无法给出预测
- 54%命中率仅略优于随机，不能夸大为"高精度预测"
- 需要更长时间验证（当前仅20日验证期）

## 下一步建议
- 继续监控未来30日表现，验证稳定性
- 如果持续有效，可考虑叠加市场状态机（任务包A）
```

---

## 四、技术要点

### 严禁前视偏差的实现细节

**错误示例**（会导致前视偏差）：
```python
# ❌ 错误：用T日的收益率校准T日的预测
for t in range(T):
    scores_t = scores[t]
    returns_t = returns[t]  # T日收益率在T+1才知道！
    calibration = calibrate(scores[:t], returns[:t])  # 用了未来信息
```

**正确示例**：
```python
# ✅ 正确：T日决策只能用T-1及之前的数据
for t in range(T):
    scores_t = scores[t]
    
    # 校准使用[0, t-1]的历史
    calibration = calibrate(scores[:t], returns[:t-1])
    
    # T日的收益率在T+1才知道，所以在下一轮才能更新
    if t > 0:
        returns_history[t-1] = calculate_return(prices[t-1], prices[t])
```

### 统计显著性检验

使用 **Binomial test**（二项检验）：
- H0（零假设）：命中率 = 50%（随机猜测）
- Ha（备择假设）：命中率 > 50%（有预测能力）
- 如果 p-value < 0.05，拒绝H0，认为有预测能力

**为什么不用t-test？**
- 方向预测是二元结果（对/错），符合二项分布
- t-test假设正态分布，不适用于二元数据

### 覆盖率 vs 命中率权衡

**Precision-Recall式权衡**：
- 高阈值 → 高命中率、低覆盖率（保守）
- 低阈值 → 低命中率、高覆盖率（激进）

**当前建议**：
- 置信度阈值 = 0.7（保留70%以上置信度的预测）
- 最小命中率 = 0.52（低于52%拒绝）
- 目标覆盖率 = 20-30%

---

## 五、验收标准

### 代码质量
- ✅ 所有pytest测试通过
- ✅ 严格遵守"不使用未来数据"原则
- ✅ 日志记录完整（每日校准结果、拒绝原因）
- ✅ 代码风格符合项目规范（中文注释 + 类型注解）

### 功能验证
- ✅ 验证期（后20日）覆盖率 20-30%
- ✅ 验证期命中率 ≥ 53%
- ✅ 前后10日命中率差异 < 5%
- ✅ 生成完整的验证报告（markdown格式）

### 诚实性检查
- ✅ 报告中同时展示命中率、覆盖率、样本数
- ✅ 明确说明"仅验证1日预测，不宣传5日/20日"
- ✅ 如果未达标，保留"暂无优势"结论
- ✅ 不刷参数（lookback_days、confidence_threshold等固定）

---

## 六、时间安排

| 任务 | 预计时间 |
|------|----------|
| 任务1：滚动方向校准模块 | 1-1.5天 |
| 任务2：拒绝预测机制 | 0.5天 |
| 任务3：集成到绿电回测 | 1天 |
| 任务4：验证与报告 | 0.5天 |
| **总计** | **2-3天** |

---

## 七、与后续任务（任务包A）的关系

**当前任务包（B）- 方向校准**：
- 修复因子失效问题（基础修复）
- 目标：命中率53%+，覆盖率20-30%

**后续任务包（A）- 系统优化**：
- 市场状态机 + 因子正交化（性能增强）
- 前置条件：任务包B验证通过

**执行顺序**：
1. **先做B**：修复方向失效（2-3天）
2. **验证B**：确认稳定达到53%+（额外1周监控）
3. **再做A**：叠加状态机和正交化（1-1.5周）

**如果B失败**：
- 诚实保留"暂无优势"结论
- 不继续做A（在错误方向上加复杂度无意义）
- 或者重新诊断因子本身是否有问题

---

## 八、常见问题

**Q1: 为什么不直接用高置信度过滤？**
A: 简单过滤会产生过拟合（前半段71.62%→后半段44.55%）。滚动校准使用严格的时间分割，避免前视偏差。

**Q2: 30天窗口是否太短？**
A: 30天约20个交易日，是最小可行窗口。更长窗口（如60天）反应太慢，会错过制度变化。可以在验证时对比不同窗口长度。

**Q3: 如果验证期命中率不到53%怎么办？**
A: 诚实报告"当前方法未达到预设目标"，不刷参数。可能需要重新检查：
- 因子本身是否有效？
- 数据质量是否有问题？
- 是否存在其他系统性偏差？

**Q4: 为什么用Binomial test而不是t-test？**
A: 方向预测是二元结果（对/错），符合二项分布。t-test假设连续正态分布，不适用。

**Q5: 覆盖率只有25%，实用性是否太低？**
A: 这是诚实口径的代价。宁可少预测、准确率高，也不要高覆盖、低准确（49%）。如果评委质疑，可以回答：
> "我们认为量化策略的核心是风险控制。与其在不确定时强行预测（命中率49%），不如诚实拒绝预测，只在有把握时出手（命中率54%）。这是对用户负责的态度。"

---

## 九、交付清单

### 代码文件
- ✅ `src/pricing/rolling_direction_calibration.py`
- ✅ `tests/unit/test_rolling_direction_calibration.py`
- ✅ `tests/validation/test_calibration_stability.py`
- ✅ 修改后的 `Rainbow_FinGPTv2/src/analysis/green_backtest_runner.py`

### 数据文件
- ✅ `docs/data/paper/calibration_history.csv`（历史校准记录）
- ✅ `docs/data/paper/backtest_green_calibrated.json`（校准后的回测结果）

### 报告文件
- ✅ `reports/方向校准修复验证报告.md`（完整验证报告）
- ✅ `reports/figures/calibration_hit_rate_over_time.png`（命中率时间序列图）
- ✅ `reports/figures/coverage_vs_performance.png`（覆盖率-命中率权衡曲线）

---

**任务包准备完毕，优先级P0，预计完成时间：2-3天**

**重要提醒**：此任务包必须先于《Gemini任务包_系统优化.md》执行！
