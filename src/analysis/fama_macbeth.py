# src/analysis/fama_macbeth.py —— Fama-MacBeth 两阶段回归（spec-kit 003 / v3.0 Phase 1 / US2）
#
# 职责（对应 FR-004/005/006/008/009）：
#   1. 阶段一（时间序列，每标的）：OLS + HAC(Newey-West) 稳健标准误
#      (R_it - rf_t) = alpha_i + beta_i1*MKT + beta_i2*SMB + beta_i3*HML + beta_i4*MOM + eps_it
#      输出 alpha、HAC p 值、IR = alpha / sigma(eps)、betas、VIF 诊断
#   2. 阶段二（横截面 FM，信息性）：每日横截面回归 → lambda_t 时间均值/标准误
#   3. 无前视：analysis_date 之后的数据一律截断，绝不进入回归窗口
#   4. 数据不足：有效观测 < MIN_OBS_DAYS → 输出 null + 原因，不伪造
#
# 用法:
#   python -m src.analysis.fama_macbeth --code 600519        # 单标的调试
#   python -m src.analysis.fama_macbeth run-all              # 全池（由 build_ranking 调用 run_all）

import argparse
import json
from pathlib import Path
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd
import statsmodels.api as sm

from .config import HAC_MAXLAGS, MIN_OBS_DAYS as _MIN_OBS
from . import factor_db

FACTOR_COLS = ["MKT", "SMB", "HML", "MOM"]
FM_MIN_CROSS_SECTION = 20  # 阶段二每日横截面最少股票数


def _empty_result(status: str, reason: str, n_obs: int,
                  window_start=None, window_end=None) -> dict:
    return {
        "status": status,
        "reason": reason,
        "alpha": None,
        "alpha_p_value": None,
        "information_ratio": None,
        "betas": None,
        "vif": None,
        "n_obs": n_obs,
        "window_start": window_start,
        "window_end": window_end,
        "converged": False,
    }


def regress_one(factors_df: pd.DataFrame, returns: Sequence,
                analysis_date: Optional[str] = None,
                min_obs_days: int = _MIN_OBS,
                hac_maxlags: int = HAC_MAXLAGS) -> dict:
    """阶段一时间序列回归（每标的）。

    factors_df: 含 date,MKT,SMB,HML,MOM,rf 的因子序列（已与收益对齐，行序一致）。
    returns: 与 factors_df 等长的总收益序列。
    analysis_date: 无前视截断点（ISO 字符串，含端点；None = 全窗口）。
    """
    if len(factors_df) != len(returns):
        raise ValueError(
            f"因子行数 {len(factors_df)} 与收益长度 {len(returns)} 不一致"
        )
    f = factors_df.reset_index(drop=True).copy()
    f["_r"] = pd.Series(returns).reset_index(drop=True).to_numpy(dtype=float)

    if analysis_date is not None:
        f = f[f["date"] <= analysis_date].reset_index(drop=True)

    # 丢弃缺失收益/因子/无风险利率的行（如 pct_change 首行 NaN），避免 NaN 污染 OLS
    f = f.dropna(subset=["_r"] + FACTOR_COLS + ["rf"]).reset_index(drop=True)

    n = len(f)
    window_start = str(f["date"].iloc[0]) if n else None
    window_end = str(f["date"].iloc[-1]) if n else None
    if n < min_obs_days:
        return _empty_result(
            "insufficient_data",
            f"有效观测 {n} < {min_obs_days}（最小有效窗口）",
            n, window_start, window_end,
        )

    r_excess = f["_r"].to_numpy(dtype=float) - f["rf"].to_numpy(dtype=float)
    X = sm.add_constant(f[FACTOR_COLS].to_numpy(dtype=float), has_constant="add")

    try:
        maxlags = max(1, min(hac_maxlags, n // 5))
        model = sm.OLS(r_excess, X).fit(
            cov_type="HAC", cov_kwds={"maxlags": maxlags}
        )
    except Exception as exc:  # 奇异矩阵等
        return _empty_result("failed", f"回归失败: {exc}", n, window_start, window_end)

    resid = model.resid
    resid_sd = float(np.std(resid, ddof=1))
    alpha = float(model.params[0])
    information_ratio = alpha / resid_sd if resid_sd > 0 else 0.0

    betas = {k: float(model.params[i + 1]) for i, k in enumerate(FACTOR_COLS)}

    vif: Dict[str, Optional[float]] = {}
    try:
        from statsmodels.stats.outliers_influence import variance_inflation_factor
        for i in range(1, X.shape[1]):
            vif[FACTOR_COLS[i - 1]] = float(variance_inflation_factor(X, i))
    except Exception:
        vif = {k: None for k in FACTOR_COLS}

    return {
        "status": "ok",
        "reason": None,
        "alpha": alpha,
        "alpha_p_value": float(model.pvalues[0]),
        "information_ratio": information_ratio,
        "betas": betas,
        "vif": vif,
        "n_obs": n,
        "window_start": window_start,
        "window_end": window_end,
        "converged": True,
    }


def fama_macbeth_stage2(factors_df: pd.DataFrame,
                        panel_returns: Dict[str, Sequence],
                        panel_betas: Dict[str, Dict[str, float]],
                        min_cross_section: int = FM_MIN_CROSS_SECTION) -> dict:
    """阶段二横截面 Fama-MacBeth（信息性输出，不参与门控）。

    对每个交易日 t，以横截面超额收益对阶段一 beta 回归得到当日因子溢价
    lambda_t；Fama-MacBeth 估计量 = lambda_t 的时间均值，
    标准误 = std(lambda_t)/sqrt(T)。
    """
    dates = factor_db._date_str(factors_df["date"]).to_numpy()
    lambdas = {k: [] for k in FACTOR_COLS}
    intercepts: list = []
    periods = 0

    for t, _ in enumerate(dates):
        y_vals = []
        design = []
        for code in panel_returns:
            r = panel_returns[code]
            val = r.iloc[t] if hasattr(r, "iloc") else r[t]
            if val is None or (isinstance(val, float) and np.isnan(val)):
                continue
            b = panel_betas.get(code)
            if not b or any(b.get(k) is None for k in FACTOR_COLS):
                continue
            y_vals.append(float(val))
            design.append([1.0] + [float(b[k]) for k in FACTOR_COLS])
        if len(y_vals) < min_cross_section:
            continue
        coef, *_ = np.linalg.lstsq(np.asarray(design, dtype=float),
                                   np.asarray(y_vals, dtype=float), rcond=None)
        intercepts.append(float(coef[0]))
        for i, k in enumerate(FACTOR_COLS):
            lambdas[k].append(float(coef[i + 1]))
        periods += 1

    def _mean_se(values):
        if not values:
            return None, None
        arr = np.asarray(values, dtype=float)
        mean = float(np.mean(arr))
        se = float(np.std(arr, ddof=1) / np.sqrt(len(arr))) if len(arr) > 1 else None
        return mean, se

    lambda_mean = {}
    lambda_se = {}
    for k in FACTOR_COLS:
        lambda_mean[k], lambda_se[k] = _mean_se(lambdas[k])
    intercept_mean, intercept_se = _mean_se(intercepts)

    return {
        "n_periods": periods,
        "min_cross_section": min_cross_section,
        "lambda_mean": lambda_mean,
        "lambda_se": lambda_se,
        "intercept_mean": intercept_mean,
        "intercept_se": intercept_se,
    }


def _returns_from_kline(kline: pd.DataFrame) -> pd.Series:
    """K 线 → 日简单收益率，索引为 YYYY-MM-DD 日期字符串。"""
    dates = factor_db._date_str(kline["date"])
    rets = pd.Series(kline["close"].to_numpy(dtype=float)).pct_change(fill_method=None)
    rets.index = dates.to_numpy()
    return rets


def run_all(factors_df: pd.DataFrame,
            klines: Dict[str, pd.DataFrame],
            returns_by_code: Optional[Dict[str, Sequence]] = None,
            analysis_date: Optional[str] = None) -> Dict[str, dict]:
    """全池批量回归入口：对齐 → 回归 → 每标的 result dict。

    returns_by_code: 可选；缺省时由 K 线收盘价计算日收益率（真实流水线路径）。
    """
    results = {}
    for code, kline in klines.items():
        if returns_by_code and code in returns_by_code:
            dates = factor_db._date_str(pd.Series(kline["date"].to_numpy()))
            ret_series = pd.Series(list(returns_by_code[code]), index=dates.to_numpy())
        else:
            ret_series = _returns_from_kline(kline)

        aligned_f, aligned_k, _dropped = factor_db.align_with_kline(factors_df, kline)
        r = ret_series.reindex(aligned_k["date"].to_numpy())
        if len(r.dropna()) == 0:
            results[code] = _empty_result("insufficient_data", "对齐后无有效收益", 0)
            continue
        results[code] = regress_one(aligned_f, r.to_numpy(dtype=float),
                                    analysis_date=analysis_date)
    return results


def _load_kline_json(code: str) -> Optional[pd.DataFrame]:
    """读取项目 K 线缓存（docs/data/kline/{code}.json，格式见 fetch_data.build_kline_json）。"""
    root = Path(__file__).resolve().parent.parent.parent
    path = root / "docs" / "data" / "kline" / f"{code}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    dates = data["dates"]
    rows = data["kline"]  # [open, close, low, high]（ECharts candlestick 顺序）
    volume = data.get("volume", [0] * len(dates))
    df = pd.DataFrame({
        "date": dates,
        "open": [r[0] for r in rows],
        "close": [r[1] for r in rows],
        "low": [r[2] for r in rows],
        "high": [r[3] for r in rows],
        "volume": volume,
    })
    return df


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fama-MacBeth 两阶段回归（spec-kit 003 / Phase 1）"
    )
    parser.add_argument("--code", default=None, help="单标的调试（如 600519）")
    parser.add_argument("--analysis-date", default=None, help="无前视截断点 ISO 日期")
    args = parser.parse_args()

    db = str(factor_db.default_db_path())
    if not Path(db).exists():
        print(f"因子库不存在: {db}，请先运行 factor_db import")
        return 2

    factors = factor_db.query_range(db, "1900-01-01", "2999-12-31")
    if args.code:
        kline = _load_kline_json(args.code)
        if kline is None:
            print(f"K 线缓存不存在: {args.code}")
            return 2
        result = run_all(factors, {args.code: kline},
                         analysis_date=args.analysis_date)[args.code]
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - 仅直接脚本执行路径
    raise SystemExit(main())
