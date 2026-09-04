"""src/analysis/factor_quality.py —— 因子半衰期与拥挤度（005 融合 US3 / SFM 层）

对应师叔 claw-quant 的 SFM（因子流形）层：因子不是越多越好，
要度量"预测力衰减速度（半衰期）"与"市场拥挤度"来防因子动物园。

口径说明（诚实标注）：
- half_life：以因子收益序列的"自相关衰减"作为预测力持续性代理——
  IC_k = corr(F_t, F_{t+k})，半衰期 = |IC_k| 衰减到峰值一半所需天数。
- crowding：多因子收益两两相关的平均绝对值 + 方差集中度（HHI）。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class DecayFitResult:
    """因子时效性指数衰减拟合结果。

    连续模型：|IC(tau)| = IC_0 * exp(-lambda * tau)
    等价对数回归：ln |IC(tau)| = ln IC_0 - lambda * tau
    连续半衰期：t_{1/2} = ln(2) / lambda
    """
    half_life_days: Optional[float]
    decay_rate_lambda: Optional[float]
    initial_ic: Optional[float]
    r_squared: Optional[float]
    is_valid: bool
    reason: str


def half_life(ic_series: List[float]) -> Optional[int]:
    """计算 IC 离散半衰期（天数）。

    峰值后第一个 |IC| <= 峰值一半的位置与峰值的距离；
    样本不足（<5）或未在窗口内衰减到一半 → None。
    """
    ic = np.asarray(ic_series, dtype=float)
    ic = ic[~np.isnan(ic)]
    if len(ic) < 5:
        return None
    peak_idx = int(np.argmax(np.abs(ic)))
    peak = float(abs(ic[peak_idx]))
    if peak <= 0:
        return None
    for j in range(peak_idx + 1, len(ic)):
        if abs(ic[j]) <= peak / 2.0:
            return j - peak_idx
    return None


def fit_exponential_decay(
    ic_series: List[float],
    dt: float = 1.0,
    min_lags: int = 3
) -> DecayFitResult:
    """对 IC(tau) 序列拟合连续指数衰减模型。

    根据 Grinold & Kahn (1999) 信息衰减模型：
    |IC(tau)| = IC_0 * exp(-lambda * tau)
    连续半衰期 t_{1/2} = ln(2) / lambda。

    参数
    ----
    ic_series : List[float]
        按滞后阶数 tau = 1, 2, ... 排列的 IC 序列
    dt : float
        滞后阶数之间的时间步长（天数），默认 1.0
    min_lags : int
        有效滞后期最小数量，默认 3

    返回
    ----
    DecayFitResult
        拟合半衰期、衰减率 lambda、初值 IC_0、R^2 与决策依据
    """
    arr = np.asarray(ic_series, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < min_lags:
        return DecayFitResult(
            half_life_days=None,
            decay_rate_lambda=None,
            initial_ic=None,
            r_squared=None,
            is_valid=False,
            reason=f"有效滞后阶数不足（{len(arr)} < {min_lags}）",
        )

    abs_ic = np.abs(arr)
    peak_idx = int(np.argmax(abs_ic))
    peak_val = float(abs_ic[peak_idx])

    if peak_val <= 1e-6:
        return DecayFitResult(
            half_life_days=None,
            decay_rate_lambda=None,
            initial_ic=0.0,
            r_squared=None,
            is_valid=False,
            reason="IC序列接近全零，无有效预测力",
        )

    # 优先取峰值及之后的衰减段
    post_peak = abs_ic[peak_idx:]
    if len(post_peak) < min_lags:
        post_peak = abs_ic

    x = np.arange(len(post_peak), dtype=float) * dt
    y = np.log(np.maximum(post_peak, 1e-6))

    if np.all(y == y[0]):
        return DecayFitResult(
            half_life_days=None,
            decay_rate_lambda=0.0,
            initial_ic=float(np.exp(y[0])),
            r_squared=0.0,
            is_valid=False,
            reason="IC序列平坦无衰减",
        )

    # 线性回归：y = a + b * x，其中 b = -lambda, a = ln(IC_0)
    poly = np.polyfit(x, y, 1)
    slope, intercept = float(poly[0]), float(poly[1])
    decay_lambda = -slope

    # 计算判定系数 R^2
    y_pred = slope * x + intercept
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    ss_res = float(np.sum((y - y_pred) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-9 else 0.0

    if decay_lambda <= 1e-5:
        return DecayFitResult(
            half_life_days=None,
            decay_rate_lambda=round(decay_lambda, 5),
            initial_ic=round(float(np.exp(intercept)), 4),
            r_squared=round(max(0.0, min(1.0, r2)), 4),
            is_valid=False,
            reason=f"信号未呈现正向衰减(lambda={decay_lambda:.5f} <= 0)",
        )

    hl_days = float(np.log(2.0) / decay_lambda)
    return DecayFitResult(
        half_life_days=round(hl_days, 2),
        decay_rate_lambda=round(decay_lambda, 5),
        initial_ic=round(float(np.exp(intercept)), 4),
        r_squared=round(max(0.0, min(1.0, r2)), 4),
        is_valid=True,
        reason=f"指数衰减拟合成功(半衰期={hl_days:.2f}天, R2={r2:.2%})",
    )


def compute_forward_rank_ic(
    factor_scores: pd.DataFrame,
    returns: pd.DataFrame,
    max_lag: int = 20
) -> Dict[int, float]:
    """计算多期前向收益率的截面 Spearman Rank IC 均值。

    参数
    ----
    factor_scores : pd.DataFrame
        行=日期，列=股票代码的因子打分
    returns : pd.DataFrame
        行=日期，列=股票代码的 1 日收益率
    max_lag : int
        最大前向步长，默认 20

    返回
    ----
    Dict[int, float]
        {lag_k: mean_rank_ic}
    """
    common_dates = factor_scores.index.intersection(returns.index)
    if len(common_dates) < 5:
        return {}

    fs = factor_scores.loc[common_dates]
    rets = returns.loc[common_dates]
    common_cols = fs.columns.intersection(rets.columns)
    if len(common_cols) < 2:
        return {}

    fs = fs[common_cols]
    rets = rets[common_cols]

    rank_ic_by_lag: Dict[int, List[float]] = {k: [] for k in range(1, max_lag + 1)}
    n_dates = len(common_dates)

    for k in range(1, max_lag + 1):
        for t in range(n_dates - k):
            f_row = fs.iloc[t]
            r_row = rets.iloc[t + k]
            valid = (~f_row.isna()) & (~r_row.isna())
            if valid.sum() >= 3:
                f_rank = f_row[valid].rank()
                r_rank = r_row[valid].rank()
                corr = f_rank.corr(r_rank)
                if not pd.isna(corr):
                    rank_ic_by_lag[k].append(float(corr))

    return {
        k: float(np.mean(vals))
        for k, vals in rank_ic_by_lag.items()
        if len(vals) > 0
    }


def decay_weighted_smoothing(
    factor_series: pd.Series,
    half_life_days: float,
    max_lags: int = 10
) -> pd.Series:
    """基于因子特征半衰期的因果指数记忆平滑（杜绝前视偏差）。

    依据 Grinold & Kahn (1999) 信号衰减模型：
    w_k = exp(-lambda * k)，其中 lambda = ln(2) / half_life_days。
    S_t = sum_{k=0}^K w_k * F_{t-k} / sum_{k=0}^K w_k

    参数
    ----
    factor_series : pd.Series
        时序因子序列
    half_life_days : float
        特征半衰期（天数）
    max_lags : int
        最大回溯历史滞后数，默认 10

    返回
    ----
    pd.Series
        平滑后的时序因子（索引与原序列一致）
    """
    s = factor_series.copy()
    if len(s) == 0 or half_life_days <= 0:
        return s

    decay_lambda = float(np.log(2.0) / half_life_days)
    lags = min(max_lags, len(s))
    weights = np.exp(-decay_lambda * np.arange(lags))
    weights /= weights.sum()

    vals = s.to_numpy(dtype=float)
    smoothed = np.full_like(vals, np.nan)

    for i in range(len(vals)):
        available_lags = min(i + 1, lags)
        w = weights[:available_lags]
        w = w / w.sum()
        window_vals = vals[i - available_lags + 1 : i + 1][::-1]
        valid_mask = ~np.isnan(window_vals)
        if valid_mask.any():
            valid_w = w[valid_mask]
            smoothed[i] = float(np.sum(valid_w * window_vals[valid_mask]) / np.sum(valid_w))
        else:
            smoothed[i] = np.nan

    return pd.Series(smoothed, index=s.index, name=s.name)


def _ic_series_from_returns(factor_returns: pd.Series, max_lag: int = 60) -> Optional[List[float]]:
    """把因子收益序列转成逐期自相关 IC 序列（信号持续性代理）。

    IC_k = corr(F_t, F_{t+k})，k = 1..max_lag。
    """
    s = pd.to_numeric(factor_returns, errors="coerce").dropna().reset_index(drop=True)
    if len(s) < 2 * max_lag:
        return None
    ic_list = []
    for k in range(1, max_lag + 1):
        r = s.iloc[:-k].reset_index(drop=True).corr(s.iloc[k:].reset_index(drop=True))
        if pd.isna(r):
            continue
        ic_list.append(float(r))
    return ic_list or None


def crowding(factor_returns: Dict[str, List[float]]) -> dict:
    """计算因子拥挤度。

    输入：{因子名: 收益序列}。输出：
    {"level": "crowded"|"moderately_crowded"|"uncrowded"|"unknown",
     "avg_corr": 平均两两相关绝对值, "hhi": 方差集中度}
    因子数 < 2 或有效期数 < 20 → level="unknown"。
    """
    names = list(factor_returns)
    if len(names) < 2:
        return {"level": "unknown", "avg_corr": None, "hhi": None, "detail": "因子数不足"}

    arr = np.array(
        [pd.to_numeric(pd.Series(v), errors="coerce").to_numpy() for v in factor_returns.values()],
        dtype=float,
    )
    valid = ~np.isnan(arr).any(axis=0)
    if valid.sum() < 20:
        return {"level": "unknown", "avg_corr": None, "hhi": None, "detail": "有效期数不足"}

    a = arr[:, valid]
    corr = np.corrcoef(a)
    n = corr.shape[0]
    tri = [abs(corr[i, j]) for i in range(n) for j in range(i + 1, n)]
    avg_corr = float(np.mean(tri)) if tri else None

    var = np.var(a, axis=1)
    var_sum = float(var.sum())
    hhi = None
    if var_sum > 0:
        share = var / var_sum
        hhi = float(share @ share)

    if avg_corr is None:
        level = "unknown"
    elif avg_corr > 0.7:
        level = "crowded"
    elif avg_corr > 0.5:
        level = "moderately_crowded"
    else:
        level = "uncrowded"

    return {
        "level": level,
        "avg_corr": round(avg_corr, 3) if avg_corr is not None else None,
        "hhi": round(hhi, 3) if hhi is not None else None,
    }


def compute_factor_quality_report(factors_df: pd.DataFrame) -> dict:
    """从因子 DataFrame（date,MKT,SMB,HML,MOM）计算因子质量报告。

    输出含每因子的 half_life_days 与整体 crowding 字段（写入
    docs/data/factors/quality_report.json）。
    """
    factor_cols = ["MKT", "SMB", "HML", "MOM"]
    factors: Dict[str, dict] = {}
    rets: Dict[str, List[float]] = {}
    for c in factor_cols:
        if c not in factors_df.columns:
            continue
        s = pd.to_numeric(factors_df[c], errors="coerce").dropna()
        if len(s) < 40:
            factors[c] = {"half_life_days": None, "note": "样本不足"}
            continue
        ic_series = _ic_series_from_returns(s)
        hl = half_life(ic_series) if ic_series else None
        decay_fit = fit_exponential_decay(ic_series) if ic_series else None
        factors[c] = {
            "half_life_days": hl,
            "half_life_continuous_days": decay_fit.half_life_days if decay_fit and decay_fit.is_valid else None,
            "decay_rate_lambda": decay_fit.decay_rate_lambda if decay_fit else None,
            "decay_r_squared": decay_fit.r_squared if decay_fit else None,
            "decay_fit_valid": decay_fit.is_valid if decay_fit else False,
            "note": None if (hl is not None or (decay_fit and decay_fit.is_valid)) else "未衰减到一半/样本不足",
        }
        rets[c] = s.tolist()

    crowd = (
        crowding(rets)
        if len(rets) >= 2
        else {"level": "unknown", "avg_corr": None, "hhi": None, "detail": "因子数不足"}
    )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "factors": factors,
        "crowding": crowd,
        "notes": [
            "half_life 以因子收益自相关衰减为预测力持续性代理（离散天数）",
            "half_life_continuous_days 由指数衰减模型 fit_exponential_decay 拟合导出",
            "crowding 由两两相关均值与方差集中度(HHI)度量",
        ],
    }
