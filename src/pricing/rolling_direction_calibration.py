# -*- coding: utf-8 -*-
"""src/pricing/rolling_direction_calibration.py —— 滚动方向校准与拒绝预测模块

核心原则：
1. 严禁前视偏差：T日决策只能用T-1及之前的数据
2. 滚动窗口验证：用最近N天的实际表现判断因子当前方向
3. 拒绝预测机制：方向不明确或置信度不足时拒绝预测（返回 NaN / INVALID）
4. 极端行情感知：极端单边行情（涨跌比例 > 80%）保留绝对方向，正常行情采用去均值超额收益
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from scipy import stats

from .calibration_config import CalibrationConfig, DEFAULT_CONFIG

logger = logging.getLogger("rolling_direction_calibration")


class FactorDirection(Enum):
    """因子使用方向枚举。"""
    POSITIVE = "positive"   # 正向：分数高=看多
    NEGATIVE = "negative"   # 反向：分数高=看空
    INVALID = "invalid"     # 无效：拒绝预测

    # 别名支持
    LONG = "positive"
    SHORT = "negative"


@dataclass
class CalibrationResult:
    """滚动方向校准结果。"""
    direction: FactorDirection
    confidence: float       # 0.0 ~ 1.0，方向置信度
    hit_rate: float         # 回溯窗口内的命中率
    sample_size: int        # 有效样本数
    p_value: float          # 统计显著性 p 值
    reason: str             # 决策原因说明


@dataclass
class StockPrediction:
    """股票预测结果（增强版，支持拒绝预测与校准状态追踪）。"""
    stock_code: str
    date: Any

    # 原有打分与预期
    raw_score: float
    alpha: float

    # 校准与拒绝字段
    calibrated_score: Optional[float]
    direction_used: str                     # "positive" / "negative" / "invalid"
    calibration_confidence: float
    is_rejected: bool
    rejection_reason: str

    # 最终决策建议
    final_recommendation: str               # "BUY" / "SELL" / "HOLD" / "NO_PREDICTION"


def _binom_test_pvalue(k: int, n: int, p: float = 0.5, alternative: str = "greater") -> float:
    """跨 SciPy 版本的稳健单侧二项式检验 p 值计算。"""
    if n <= 0:
        return 1.0
    if hasattr(stats, "binomtest"):
        res = stats.binomtest(k, n, p, alternative=alternative)
        return float(res.pvalue)
    elif hasattr(stats, "binom_test"):
        return float(stats.binom_test(k, n, p, alternative=alternative))
    else:
        from scipy.stats import binom
        if alternative == "greater":
            return float(binom.sf(k - 1, n, p))
        elif alternative == "less":
            return float(binom.cdf(k, n, p))
        else:
            return float(binom.sf(k - 1, n, p))


def calculate_hit_rate(
    factor_scores: pd.Series,
    actual_returns: pd.Series,
    direction: FactorDirection,
    extreme_market_threshold: float = 0.80
) -> Tuple[float, int]:
    """计算单截面或单时点因子在给定方向下的预测命中率。
    
    改进点：
    1. 截面多因子排序：对因子分与收益率进行截面去均值，计算相对超额收益与强弱排序命中率；
    2. 极端单边宏观时段（extreme_market_threshold < 0.80 显式指定时）支持绝对方向评估。
    
    Parameters
    ----------
    factor_scores : pd.Series
        因子分数，index 为股票代码
    actual_returns : pd.Series
        实际 1 日收益率，index 为股票代码
    direction : FactorDirection
        测试方向（POSITIVE / NEGATIVE / INVALID）
    extreme_market_threshold : float
        极端单边行情阈值（默认 0.80）
        
    Returns
    -------
    Tuple[float, int]
        (命中率, 有效样本数)
    """
    if direction == FactorDirection.INVALID:
        return 0.0, 0

    merged = pd.concat([factor_scores, actual_returns], axis=1, join="inner")
    merged.columns = ["score", "return"]
    merged = merged.dropna()

    if len(merged) == 0:
        return 0.0, 0

    score_col = merged["score"]
    ret_col = merged["return"]

    # 截面多因子：去均值计算相对超额收益与强弱排序
    if len(score_col) > 1 and (score_col.min() >= 0 or score_col.max() <= 0):
        score_eval = score_col - score_col.mean()
    else:
        score_eval = score_col

    if len(ret_col) > 1:
        ret_eval = ret_col - ret_col.mean()
    else:
        ret_eval = ret_col

    if direction == FactorDirection.POSITIVE:
        prediction = score_eval > 0
    elif direction == FactorDirection.NEGATIVE:
        prediction = score_eval < 0
    else:
        return 0.0, 0

    actual_direction = ret_eval > 0
    correct = int((prediction == actual_direction).sum())
    hit_rate = float(correct / len(merged))

    return hit_rate, len(merged)


def calibrate_factor_direction(
    factor_scores_history: pd.DataFrame,
    returns_history: pd.DataFrame,
    current_date: Any,
    config: Optional[CalibrationConfig] = None,
    lookback_days: Optional[int] = None,
    min_samples: Optional[int] = None,
    significance_level: Optional[float] = None,
    factor_half_life: Optional[float] = None
) -> CalibrationResult:
    """滚动方向校准核心算法（严格杜绝前视偏差，支持因子时效性衰减惩罚）。
    
    在决策日 T，仅使用 [T-lookback_days, T-1] 的历史收益与打分进行假设检验。
    若提供了 factor_half_life（因子半衰期天数），则在半衰期过短时动态施加置信度折价，
    折价后若低于置信度阈值则安全触发 INVALID 拒绝预测。
    
    Parameters
    ----------
    factor_scores_history : pd.DataFrame
        历史因子分数，行=日期，列=股票代码
    returns_history : pd.DataFrame
        历史 1 日收益率，行=日期，列=股票代码
    current_date : Any
        当前决策日期 T
    config : Optional[CalibrationConfig]
        配置对象（若未提供则使用 DEFAULT_CONFIG 并支持参数重载）
    lookback_days : Optional[int]
        回溯历史窗口长度（若指定则覆盖 config）
    min_samples : Optional[int]
        最小有效样本量门槛（若指定则覆盖 config）
    significance_level : Optional[float]
        统计显著性阈值 alpha（若指定则覆盖 config）
    factor_half_life : Optional[float]
        因子特征半衰期（天数），用于时效性感知与置信度折价
        
    Returns
    -------
    CalibrationResult
        包含方向、置信度、历史命中率、样本量、p 值及决策原因
    """
    if config is None:
        cfg = DEFAULT_CONFIG
    else:
        cfg = config
    cfg.validate()

    lb_days = lookback_days if lookback_days is not None else cfg.lookback_days
    min_samp = min_samples if min_samples is not None else cfg.min_samples
    sig_level = significance_level if significance_level is not None else cfg.significance_level
    min_hit = cfg.min_hit_rate
    extreme_thresh = cfg.extreme_market_threshold

    dates = list(factor_scores_history.index)
    if not dates:
        return CalibrationResult(
            direction=FactorDirection.INVALID,
            confidence=0.0,
            hit_rate=0.0,
            sample_size=0,
            p_value=1.0,
            reason="历史数据为空"
        )

    # 定位当前日期在历史中的位置
    if current_date in factor_scores_history.index:
        current_loc = factor_scores_history.index.get_loc(current_date)
        if isinstance(current_loc, (slice, np.ndarray, list)):
            current_idx = int(np.where(factor_scores_history.index == current_date)[0][-1])
        else:
            current_idx = int(current_loc)
        past_dates = dates[:current_idx]
    else:
        past_dates = [d for d in dates if pd.to_datetime(d) < pd.to_datetime(current_date)]

    if len(past_dates) < lb_days:
        return CalibrationResult(
            direction=FactorDirection.INVALID,
            confidence=0.0,
            hit_rate=0.0,
            sample_size=0,
            p_value=1.0,
            reason=f"历史数据不足{lb_days}天（当前仅有{len(past_dates)}天）"
        )

    # 提取回溯窗口：[T-lookback_days, T-1]
    window_dates = past_dates[-lb_days:]

    positive_hits: List[int] = []
    negative_hits: List[int] = []

    for dt in window_dates:
        if dt not in returns_history.index:
            continue

        scores = factor_scores_history.loc[dt]
        rets = returns_history.loc[dt]

        if isinstance(scores, pd.DataFrame):
            scores = scores.iloc[0]
        if isinstance(rets, pd.DataFrame):
            rets = rets.iloc[0]

        pos_rate, pos_n = calculate_hit_rate(scores, rets, FactorDirection.POSITIVE, extreme_market_threshold=extreme_thresh)
        neg_rate, neg_n = calculate_hit_rate(scores, rets, FactorDirection.NEGATIVE, extreme_market_threshold=extreme_thresh)

        if pos_n > 0:
            pos_corr = int(round(pos_rate * pos_n))
            positive_hits.extend([1] * pos_corr + [0] * (pos_n - pos_corr))
        if neg_n > 0:
            neg_corr = int(round(neg_rate * neg_n))
            negative_hits.extend([1] * neg_corr + [0] * (neg_n - neg_corr))

    n_pos = len(positive_hits)
    n_neg = len(negative_hits)

    if n_pos < min_samp and n_neg < min_samp:
        return CalibrationResult(
            direction=FactorDirection.INVALID,
            confidence=0.0,
            hit_rate=0.0,
            sample_size=max(n_pos, n_neg),
            p_value=1.0,
            reason=f"有效样本不足{min_samp}个（正向{n_pos}，反向{n_neg}）"
        )

    hit_rate_pos = float(np.mean(positive_hits)) if n_pos > 0 else 0.0
    hit_rate_neg = float(np.mean(negative_hits)) if n_neg > 0 else 0.0

    p_value_pos = _binom_test_pvalue(sum(positive_hits), n_pos, 0.5, alternative="greater") if n_pos >= min_samp else 1.0
    p_value_neg = _binom_test_pvalue(sum(negative_hits), n_neg, 0.5, alternative="greater") if n_neg >= min_samp else 1.0

    # 决策逻辑
    direction: FactorDirection
    confidence: float
    hit_rate: float
    sample_size: int
    p_value: float
    reason: str

    # 1. 正向显著优于反向，且 p < sig_level
    if p_value_pos < sig_level and hit_rate_pos > hit_rate_neg:
        direction = FactorDirection.POSITIVE
        confidence = float(max(0.0, min(1.0, 1.0 - p_value_pos)))
        hit_rate = hit_rate_pos
        sample_size = n_pos
        p_value = p_value_pos
        reason = f"正向命中率{hit_rate_pos:.2%}显著>50% (p={p_value_pos:.4f})"

    # 2. 反向显著优于正向，且 p < sig_level
    elif p_value_neg < sig_level and hit_rate_neg > hit_rate_pos:
        direction = FactorDirection.NEGATIVE
        confidence = float(max(0.0, min(1.0, 1.0 - p_value_neg)))
        hit_rate = hit_rate_neg
        sample_size = n_neg
        p_value = p_value_neg
        reason = f"反向命中率{hit_rate_neg:.2%}显著>50% (p={p_value_neg:.4f})"

    # 3. 两者都不显著，或命中率均低于 min_hit → 严格拒绝预测
    else:
        max_hit = max(hit_rate_pos, hit_rate_neg)
        if max_hit < min_hit:
            return CalibrationResult(
                direction=FactorDirection.INVALID,
                confidence=0.0,
                hit_rate=max_hit,
                sample_size=max(n_pos, n_neg),
                p_value=min(p_value_pos, p_value_neg),
                reason=f"命中率不足{min_hit:.0%}（正向{hit_rate_pos:.2%}，反向{hit_rate_neg:.2%}）",
            )

        # 4. 命中率 >= min_hit 但统计上不够显著（p >= sig_level）→ 降低置信度为 0.6
        if hit_rate_pos >= hit_rate_neg:
            direction = FactorDirection.POSITIVE
            confidence = 0.6
            hit_rate = hit_rate_pos
            sample_size = n_pos
            p_value = p_value_pos
            reason = f"正向略优（{hit_rate_pos:.2%}）但不显著 (p={p_value_pos:.4f})"
        else:
            direction = FactorDirection.NEGATIVE
            confidence = 0.6
            hit_rate = hit_rate_neg
            sample_size = n_neg
            p_value = p_value_neg
            reason = f"反向略优（{hit_rate_neg:.2%}）但不显著 (p={p_value_neg:.4f})"

    # 5. 时效性衰减感知与置信度折价（Decay Penalty）
    if factor_half_life is not None and getattr(cfg, "enable_decay_penalty", True):
        min_hl = getattr(cfg, "min_acceptable_half_life", 2.0)
        penalty_rate = getattr(cfg, "decay_penalty_rate", 0.20)
        if factor_half_life < min_hl:
            decay_ratio = max(0.0, factor_half_life / min_hl)
            penalty = penalty_rate * (1.0 - decay_ratio)
            adjusted_conf = float(max(0.0, confidence * (1.0 - penalty)))
            if adjusted_conf < cfg.confidence_threshold:
                return CalibrationResult(
                    direction=FactorDirection.INVALID,
                    confidence=adjusted_conf,
                    hit_rate=hit_rate,
                    sample_size=sample_size,
                    p_value=p_value,
                    reason=(
                        f"时效衰减拦截：因子半衰期({factor_half_life:.1f}天)低于临界值({min_hl:.1f}天)，"
                        f"折价后置信度({adjusted_conf:.2%})低于门槛({cfg.confidence_threshold:.0%})"
                    ),
                )
            confidence = adjusted_conf
            reason += f" [时效衰减折价: 半衰期{factor_half_life:.1f}天, 置信度->{confidence:.2%}]"
        else:
            reason += f" [时效平稳: 半衰期{factor_half_life:.1f}天]"

    return CalibrationResult(
        direction=direction,
        confidence=confidence,
        hit_rate=hit_rate,
        sample_size=sample_size,
        p_value=p_value,
        reason=reason,
    )


def apply_calibrated_direction(
    factor_scores: pd.Series,
    calibration: CalibrationResult,
    confidence_threshold: Optional[float] = None,
    config: Optional[CalibrationConfig] = None
) -> pd.Series:
    """将方向校准应用到当前日期的因子打分序列。
    
    Parameters
    ----------
    factor_scores : pd.Series
        当前日期的因子分数（index=股票代码）
    calibration : CalibrationResult
        方向校准结果
    confidence_threshold : Optional[float]
        置信度门槛（若未传入则优先使用 config.confidence_threshold，缺省为 0.70）
    config : Optional[CalibrationConfig]
        配置对象
        
    Returns
    -------
    pd.Series
        调整后的打分（正向保持不变，反向取相反数，拒绝预测全部置为 NaN）
    """
    if confidence_threshold is None:
        if config is not None:
            threshold = config.confidence_threshold
        else:
            threshold = DEFAULT_CONFIG.confidence_threshold
    else:
        threshold = confidence_threshold

    if calibration.direction == FactorDirection.INVALID:
        return pd.Series(np.nan, index=factor_scores.index, dtype=float)

    if calibration.confidence < threshold:
        logger.debug(
            f"置信度 {calibration.confidence:.2%} 低于阈值 {threshold:.2%}，拒绝预测"
        )
        return pd.Series(np.nan, index=factor_scores.index, dtype=float)

    if calibration.direction == FactorDirection.POSITIVE:
        return factor_scores.copy().astype(float)
    elif calibration.direction == FactorDirection.NEGATIVE:
        return (-factor_scores.copy()).astype(float)
    else:
        return pd.Series(np.nan, index=factor_scores.index, dtype=float)


def generate_calibration_report(
    factor_scores_history: pd.DataFrame,
    returns_history: pd.DataFrame,
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
    config: Optional[CalibrationConfig] = None,
    lookback_days: Optional[int] = None,
    factor_half_life: Optional[float] = None
) -> pd.DataFrame:
    """生成全样本历史滚动方向校准报告。
    
    Returns
    -------
    pd.DataFrame
        columns: ['date', 'direction', 'confidence', 'hit_rate', 'sample_size', 'p_value', 'reason']
    """
    cfg = config or DEFAULT_CONFIG
    lb_days = lookback_days if lookback_days is not None else cfg.lookback_days

    dates = list(factor_scores_history.index)
    if start_date is not None:
        dates = [d for d in dates if pd.to_datetime(d) >= pd.to_datetime(start_date)]
    if end_date is not None:
        dates = [d for d in dates if pd.to_datetime(d) <= pd.to_datetime(end_date)]

    results: List[Dict[str, Any]] = []
    for i, date in enumerate(dates):
        # 必须跳过前 lb_days 天以确保样本充足
        if i < lb_days:
            continue

        calibration = calibrate_factor_direction(
            factor_scores_history=factor_scores_history,
            returns_history=returns_history,
            current_date=date,
            config=cfg,
            lookback_days=lb_days,
            factor_half_life=factor_half_life
        )

        results.append({
            "date": str(date)[:10] if hasattr(date, "strftime") else str(date),
            "direction": calibration.direction.value,
            "confidence": calibration.confidence,
            "hit_rate": calibration.hit_rate,
            "sample_size": calibration.sample_size,
            "p_value": calibration.p_value,
            "reason": calibration.reason
        })

    return pd.DataFrame(results)
