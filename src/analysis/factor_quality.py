"""src/analysis/factor_quality.py —— 因子半衰期与拥挤度（005 融合 US3 / SFM 层）

对应师叔 claw-quant 的 SFM（因子流形）层：因子不是越多越好，
要度量"预测力衰减速度（半衰期）"与"市场拥挤度"来防因子动物园。

口径说明（诚实标注）：
- half_life：以因子收益序列的"自相关衰减"作为预测力持续性代理——
  IC_k = corr(F_t, F_{t+k})，半衰期 = |IC_k| 衰减到峰值一半所需天数。
- crowding：多因子收益两两相关的平均绝对值 + 方差集中度（HHI）。
"""

from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


def half_life(ic_series: List[float]) -> Optional[int]:
    """计算 IC 半衰期（天数）。

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
        factors[c] = {
            "half_life_days": hl,
            "note": None if hl is not None else "未衰减到一半/样本不足",
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
            "half_life 以因子收益自相关衰减为预测力持续性代理",
            "crowding 由两两相关均值与方差集中度(HHI)度量",
        ],
    }
