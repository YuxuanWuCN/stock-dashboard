# -*- coding: utf-8 -*-
"""tests/test_p4_real_quant.py —— M4/P4 返工（v2）核心量化内核测试

覆盖目标（AGENTS.md §2/§3：正常、边界、缺失、失败路径 + 独立断言）：

1. 计量工具手算校验：Newey-West 滞后阶数公式、NW HAC t 值、BH-FDR q 值、Bonferroni、
   经验 p 值（含 (count+1)/(n+1) 蒙特卡洛口径）、移动区块 Bootstrap。
2. 前视偏差防护：事件研究的截断不变性（把数据截断到 t 日，t 日及之前的信号必须与全样本一致）。
3. 涨跌停流动性约束：进场日涨停必须被拦截；退出日跌停必须顺延到下一可成交日；
   涨跌停方向重建的正确性（含 ret 缺失时的 price_pos 兜底与不可判情形）。
4. Fama-MacBeth 被解释变量必须是 t+1 可交易收益；涨停剔除口径对定义敏感这一点必须可复现。
5. 三种安慰剂设计（随机日期 / 同日匹配 / 事件级）与逐日配对检验的行为契约。
"""

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.p4_real_data_core import (
    attach_returns,
    benjamini_hochberg_fdr,
    block_bootstrap_ci,
    bonferroni_adjust,
    build_trend_gate_events,
    calc_newey_west_lags,
    calc_peak_to_trough_drawdown,
    classic_iid_t_stat,
    daily_paired_test,
    date_cluster_bootstrap_diff,
    derive_limit_flags,
    empirical_p_value,
    newey_west_t_stat,
    run_date_matched_placebo,
    run_date_placebo,
    run_fama_macbeth,
    run_placebo,
    summarize_events,
)


# ===========================================================================
# 测试夹具
# ===========================================================================
def make_panel(closes, code: str = "000001") -> pd.DataFrame:
    """构造只含事件研究所需列的合成面板（1 支标的，连续交易日）。"""
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    dates = pd.bdate_range("2024-01-02", periods=n).strftime("%Y-%m-%d")
    df = pd.DataFrame({"stock_code": code, "trade_date": dates, "close": closes})
    df["limit_known"] = True
    df["limit_up"] = False
    df["limit_down"] = False
    df["limit_unknown"] = False
    df["suspended"] = False
    return df


def random_walk(n: int, seed: int = 7, start: float = 10.0, vol: float = 0.02) -> np.ndarray:
    rng = np.random.RandomState(seed)
    return start * np.cumprod(1.0 + rng.normal(0.0, vol, size=n))


def make_placebo_events() -> pd.DataFrame:
    """3 个交易日 × 4 只标的；前 2 日各有 1 只触发样本，第 3 日无触发。

    触发样本的值刻意设为 100.0，用于验证「抽样池排除触发样本」——
    只要分布里出现 100 量级的数，就说明抽样池漏进了触发样本。
    池子取值随日期变化（0.01 / 0.02 / 0.03），这样日期级重抽样才有非退化方差。
    """
    rows = []
    days = ["2025-01-02", "2025-01-03", "2025-01-06"]
    for di, d in enumerate(days):
        for i in range(4):
            is_trig = (d != days[2]) and i == 0
            rows.append({
                "trade_date": d,
                "is_downtrend": is_trig,
                "ret_5d_free": 100.0 if is_trig else 0.01 * (di + 1),
                "maxdd_5d_free": -0.01 if is_trig else -0.02,
                "ret_5d": 100.0 if is_trig else 0.01 * (di + 1),
                "maxdd_5d": -0.01 if is_trig else -0.02,
            })
    return pd.DataFrame(rows)


def make_paired_events(date_values: dict) -> pd.DataFrame:
    """按 {日期: (目标组值, 池子值)} 构造逐日配对检验用的长表。"""
    rows = []
    for date, (tval, pval) in date_values.items():
        rows.append({"trade_date": date, "is_downtrend": True, "ret_5d": tval, "ret_5d_free": tval,
                     "maxdd_5d": -0.01, "maxdd_5d_free": -0.01})
        rows.append({"trade_date": date, "is_downtrend": False, "ret_5d": pval, "ret_5d_free": pval,
                     "maxdd_5d": -0.01, "maxdd_5d_free": -0.01})
    return pd.DataFrame(rows)


# ===========================================================================
# 1. 计量工具手算校验
# ===========================================================================
def test_newey_west_lag_formula_hand_checked():
    """q = floor(4 * (T/100)^(2/9))，边界 T=0/1 归一到 1。"""
    assert calc_newey_west_lags(585) == 5     # 4 * 5.85^(2/9) = 5.923 -> 5
    assert calc_newey_west_lags(644) == 6     # 4 * 6.44^(2/9) = 6.051 -> 6
    assert calc_newey_west_lags(557) == 5     # 事件研究日度序列实际使用的期数
    assert calc_newey_west_lags(100) == 4
    assert calc_newey_west_lags(50) == 3      # 4 * 0.5^(2/9) = 3.494 -> 3
    assert calc_newey_west_lags(10) == 2      # 4 * 0.1^(2/9) = 2.398 -> 2
    assert calc_newey_west_lags(1) == 1
    assert calc_newey_west_lags(0) == 1


def test_newey_west_t_stat_matches_hand_computation():
    """series=[1,2,3,4,5], lag=1：gamma0=2.0, gamma1=0.8, w=0.5,
    var_hac=2.0+2*0.5*0.8=2.8, se=sqrt(2.8/5)=0.748331, t=3/0.748331=4.008918。"""
    mean_v, se, t_stat = newey_west_t_stat(np.array([1.0, 2.0, 3.0, 4.0, 5.0]), lags=1)
    assert mean_v == pytest.approx(3.0)
    assert se == pytest.approx(np.sqrt(2.8 / 5.0), rel=1e-12)
    assert t_stat == pytest.approx(3.0 / np.sqrt(0.56), rel=1e-12)
    assert t_stat == pytest.approx(4.0089186, rel=1e-6)


def test_newey_west_equals_iid_when_lags_zero_and_ignores_nan():
    series = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    _, se_hac0, _ = newey_west_t_stat(series, lags=0)
    _, se_iid, _ = classic_iid_t_stat(series)
    # HAC(0) 用 1/T 归一的 gamma0，IID 用 ddof=1，两者仅差 sqrt((T-1)/T)
    assert se_hac0 == pytest.approx(se_iid * np.sqrt(4.0 / 5.0), rel=1e-12)

    mean_nan, _, _ = newey_west_t_stat(np.array([1.0, np.nan, 3.0, np.nan, 5.0]), lags=1)
    assert mean_nan == pytest.approx(3.0)


def test_benjamini_hochberg_fdr_hand_checked():
    """p=[0.001,0.008,0.039,0.041,0.30], m=5 的 BH q 值可手算：
    raw 0.005/0.020/0.065/0.05125/0.30 -> 步降单调后 0.005/0.02/0.05125/0.05125/0.30。"""
    p = [0.001, 0.008, 0.039, 0.041, 0.30]
    q = benjamini_hochberg_fdr(p)
    assert q[0] == pytest.approx(0.005)
    assert q[1] == pytest.approx(0.02)
    assert q[2] == pytest.approx(0.05125)
    assert q[3] == pytest.approx(0.05125)
    assert q[4] == pytest.approx(0.30)
    assert np.all(q >= np.asarray(p) - 1e-15)
    assert len(benjamini_hochberg_fdr([])) == 0


def test_bonferroni_adjust_hand_checked_and_capped_at_one():
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.30])
    b = bonferroni_adjust(p)
    assert b[0] == pytest.approx(0.005)
    assert b[3] == pytest.approx(0.205)
    assert b[4] == pytest.approx(1.0)          # 0.30*5=1.5 需截断到 1.0
    assert np.all(b <= 1.0)


def test_empirical_p_value_uses_plus_one_monte_carlo_convention():
    """dist=[1..5], 观测 2：<=2 有 2 个、>=2 有 4 个（n=5）
    lower=(2+1)/6=0.5，upper=(4+1)/6=0.8333，two=min(1,2*0.5)=1.0。"""
    dist = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert empirical_p_value(dist, 2.0, "lower") == pytest.approx(3.0 / 6.0)
    assert empirical_p_value(dist, 2.0, "upper") == pytest.approx(5.0 / 6.0)
    assert empirical_p_value(dist, 2.0, "two") == pytest.approx(1.0)

    # 观测高于全部安慰剂：单侧上尾 = 1/(n+1)，双侧 = 2/(n+1)，不再出现「托底后乘 2 失效」
    assert empirical_p_value(dist, 99.0, "lower") == pytest.approx(1.0)
    assert empirical_p_value(dist, 99.0, "upper") == pytest.approx(1.0 / 6.0)
    assert empirical_p_value(dist, 99.0, "two") == pytest.approx(2.0 / 6.0)

    n = 1000
    all_lower = [0.0] * n
    assert empirical_p_value(all_lower, 1.0, "upper") == pytest.approx(1.0 / 1001.0)
    assert empirical_p_value(all_lower, 1.0, "two") == pytest.approx(2.0 / 1001.0)


def test_block_bootstrap_ci_constant_series_and_determinism():
    const = np.full(120, 0.5)
    low, high = block_bootstrap_ci(const, block_len=5, n_boot=50, seed=1)
    assert low == pytest.approx(0.5)
    assert high == pytest.approx(0.5)

    rng = np.random.RandomState(3)
    series = rng.normal(0.0, 1.0, size=200)
    a = block_bootstrap_ci(series, block_len=6, n_boot=100, seed=42)
    b = block_bootstrap_ci(series, block_len=6, n_boot=100, seed=42)
    assert a == b
    assert a[0] < float(np.mean(series)) < a[1]


# ===========================================================================
# 2. 前视偏差防护：截断不变性
# ===========================================================================
def test_event_study_truncation_invariance():
    """把数据截断到第 150 个交易日，截断前共有的全部事件必须逐字段一致。"""
    closes = random_walk(200, seed=11)
    full = build_trend_gate_events(make_panel(closes))
    trunc = build_trend_gate_events(make_panel(closes[:150]))
    assert len(trunc) > 0
    assert len(trunc) < len(full)

    compare_cols = [
        "mom_20d", "is_downtrend", "is_uptrend", "entry_date",
        "entry_tradable", "entry_block_limit_up",
        "ret_5d", "ret_10d", "ret_20d",
        "ret_5d_free", "ret_10d_free", "ret_20d_free",
        "maxdd_5d", "maxdd_20d", "defer_5d", "defer_20d",
    ]
    merged = trunc.merge(full, on="trade_date", suffixes=("_trunc", "_full"))
    assert len(merged) == len(trunc)
    for col in compare_cols:
        left = merged[f"{col}_trunc"].to_numpy()
        right = merged[f"{col}_full"].to_numpy()
        if left.dtype.kind == "f":
            assert np.allclose(left, right, equal_nan=True, rtol=0, atol=0), f"{col} 在截断前后不一致"
        else:
            assert np.array_equal(left, right), f"{col} 在截断前后不一致"


def test_signal_does_not_use_future_prices():
    """人为把 t 日之后的收盘价翻倍，t 日及之前的所有信号必须不变。"""
    closes = random_walk(160, seed=5)
    mutated = closes.copy()
    mutated[100:] *= 2.0
    ev_a = build_trend_gate_events(make_panel(closes))
    ev_b = build_trend_gate_events(make_panel(mutated))
    cutoff = make_panel(closes)["trade_date"].iloc[99]
    a = ev_a[ev_a["trade_date"] <= cutoff]
    b = ev_b[ev_b["trade_date"] <= cutoff]
    assert len(a) > 0
    assert np.array_equal(a["is_downtrend"].to_numpy(), b["is_downtrend"].to_numpy())
    assert np.array_equal(a["mom_20d"].to_numpy(), b["mom_20d"].to_numpy())


# ===========================================================================
# 3. 涨跌停方向重建与流动性约束
# ===========================================================================
def test_derive_limit_flags_direction_and_fallback():
    df = pd.DataFrame({
        "stock_code": ["000001"] * 5,
        "trade_date": ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08"],
        "close": [10.0, 11.0, 9.9, 10.89, 10.5],
        "hit_limit": [1.0, 1.0, 1.0, 1.0, np.nan],
        "ret": [0.10, -0.10, np.nan, np.nan, 0.01],
        "price_pos": [1.0, 0.0, 1.0, 0.5, 0.5],
        "abnormal_trd": [0.0, 0.0, 0.0, 0.0, 0.0],
    })
    out, validation = derive_limit_flags(df)
    assert out["limit_up"].tolist() == [True, False, True, False, False]
    assert out["limit_down"].tolist() == [False, True, False, False, False]
    assert out["limit_unknown"].tolist() == [False, False, False, True, False]
    assert out["limit_known"].tolist() == [True, True, True, True, False]
    assert validation["n_limit_up"] == 2
    assert validation["n_limit_down"] == 1
    assert validation["n_limit_direction_unknown"] == 1


def test_limit_up_on_entry_day_blocks_event():
    closes = random_walk(120, seed=13)
    panel = make_panel(closes)
    panel.loc[61, "limit_up"] = True          # t=60 的进场日

    events = build_trend_gate_events(panel)
    first = events.iloc[0]
    assert first["trade_date"] == panel["trade_date"].iloc[60]
    assert bool(first["entry_block_limit_up"]) is True
    assert bool(first["entry_tradable"]) is False
    assert np.isnan(first["ret_5d"])
    assert np.isfinite(first["ret_5d_free"])

    summary = summarize_events(events, np.ones(len(events), dtype=bool), mode="constrained")
    assert summary["h5"]["n_valid"] == len(events) - 1
    assert summary["entry_blocked_limit_up_share"] == pytest.approx(1.0 / len(events))


def test_limit_down_on_exit_day_defers_to_next_tradable_day():
    closes = random_walk(120, seed=17)
    panel = make_panel(closes)
    entry_idx = 61
    target_idx = entry_idx + 5
    panel.loc[target_idx, "limit_down"] = True

    first = build_trend_gate_events(panel).iloc[0]
    assert bool(first["exit_blocked_5d"]) is False
    assert int(first["defer_5d"]) == 1
    assert float(first["ret_5d"]) == pytest.approx(closes[target_idx + 1] / closes[entry_idx] - 1.0, rel=1e-12)
    assert float(first["ret_5d_free"]) == pytest.approx(closes[target_idx] / closes[entry_idx] - 1.0, rel=1e-12)

    panel_all = make_panel(closes)
    for k in range(target_idx, target_idx + 6):
        panel_all.loc[k, "limit_down"] = True
    blocked = build_trend_gate_events(panel_all).iloc[0]
    assert bool(blocked["exit_blocked_5d"]) is True
    assert np.isnan(blocked["ret_5d"])


def test_unobserved_limit_state_excluded_from_tradable_sample():
    panel = make_panel(random_walk(120, seed=19))
    panel["limit_known"] = False
    events = build_trend_gate_events(panel)
    assert len(events) > 0
    assert not events["entry_tradable"].any()
    summary = summarize_events(events, np.ones(len(events), dtype=bool), mode="constrained")
    assert summary["h20"]["n_valid"] == 0
    assert summary["entry_limit_unobserved_share"] == pytest.approx(1.0)


# ===========================================================================
# 4. Fama-MacBeth 被解释变量与涨停剔除口径
# ===========================================================================
def make_fm_panel(n_stocks: int = 40, n_dates: int = 80, seed: int = 23) -> pd.DataFrame:
    """构造「因子只预测次日收益」的合成面板：
    ret_next = 0.01*f1 + 噪声(σ=0.0005)；ret 与 f1 无关(σ=0.01)。"""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2024-01-02", periods=n_dates).strftime("%Y-%m-%d")
    rows = []
    for d in dates:
        f1 = rng.normal(0.0, 1.0, size=n_stocks)
        ret = rng.normal(0.0, 0.01, size=n_stocks)
        ret_next = 0.01 * f1 + rng.normal(0.0, 0.0005, size=n_stocks)
        for i in range(n_stocks):
            rows.append({
                "stock_code": f"{i:06d}", "trade_date": d, "f1": float(f1[i]),
                "ret": float(ret[i]), "ret_next": float(ret_next[i]), "limit_up": False,
            })
    return pd.DataFrame(rows)


def test_fama_macbeth_dependent_variable_is_next_day_return():
    panel = make_fm_panel()
    next_day = run_fama_macbeth(panel, factors=["f1"], dependent="ret_next", min_stocks=30, bootstrap_runs=50)
    same_day = run_fama_macbeth(panel, factors=["f1"], dependent="ret", min_stocks=30, bootstrap_runs=50)

    assert next_day["n_periods"] == 80
    assert next_day["hac_lags"] == calc_newey_west_lags(80)
    t_next = next_day["factors_stats"]["f1"]["newey_west_t"]
    t_same = same_day["factors_stats"]["f1"]["newey_west_t"]
    assert abs(t_next) > 50, f"次日收益口径应高度显著，实际 t={t_next}"
    assert abs(t_same) < 5, f"同期收益口径不应显著，实际 t={t_same}"
    assert next_day["factors_stats"]["f1"]["mean_risk_premium_daily"] == pytest.approx(0.01, abs=0.0005)


def test_fama_macbeth_multiple_testing_and_annualization():
    panel = make_fm_panel(n_stocks=40, n_dates=90, seed=29)
    rng = np.random.RandomState(31)
    for extra in ("f2", "f3"):
        panel[extra] = rng.normal(size=len(panel))
    res = run_fama_macbeth(panel, factors=["f1", "f2", "f3"], dependent="ret_next",
                           min_stocks=30, bootstrap_runs=50)

    assert res["n_tests"] == 3
    assert res["annualization_days"] == 244
    assert res["hac_kernel"] == "bartlett"
    for _name, st in res["factors_stats"].items():
        assert st["annualized_premium_244d"] == pytest.approx(st["mean_risk_premium_daily"] * 244.0)
        assert st["fdr_q_value"] >= st["p_value_two_sided"] - 1e-15
        assert st["bonferroni_p_value"] >= st["p_value_two_sided"] - 1e-15
    assert res["factors_stats"]["f1"]["significant_5pct_fdr"] is True
    assert res["factors_stats"]["f2"]["significant_5pct_fdr"] is False


def test_fama_macbeth_limit_up_definitions_are_distinguishable():
    """重建口径与字面口径剔除的行数必须不同，且各自可手算复核。"""
    panel = make_fm_panel(n_stocks=40, n_dates=40, seed=37)
    # 手工制造 6 行「重建口径为涨停但字面口径不成立」的样本：
    # hit_limit=1 但 ret 为空（字面口径要求 ret>0），重建口径仍按 limit_up 剔除。
    panel["hit_limit"] = 0.0
    panel["limit_up"] = False
    idx = panel.index[:6]
    panel.loc[idx, "limit_up"] = True
    panel.loc[idx, "hit_limit"] = 1.0
    panel.loc[idx, "ret"] = np.nan

    reconstructed = run_fama_macbeth(panel, factors=["f1"], dependent="ret_next", min_stocks=30,
                                     bootstrap_runs=20, drop_limit_up_at_t=True,
                                     limit_up_definition="reconstructed")
    literal = run_fama_macbeth(panel, factors=["f1"], dependent="ret_next", min_stocks=30,
                               bootstrap_runs=20, drop_limit_up_at_t=True,
                               limit_up_definition="literal")

    assert reconstructed["limit_up_definition"] == "reconstructed"
    assert literal["limit_up_definition"] == "literal"
    assert reconstructed["n_rows_excluded"] == 6           # 按 limit_up 标志剔除
    assert literal["n_rows_excluded"] == 0                 # ret 为 NaN，字面口径不成立
    with pytest.raises(ValueError):
        run_fama_macbeth(panel, factors=["f1"], dependent="ret_next",
                         drop_limit_up_at_t=True, limit_up_definition="bogus")


def test_fama_macbeth_rejects_insufficient_cross_section():
    res = run_fama_macbeth(make_fm_panel(n_stocks=10, n_dates=20), factors=["f1"],
                           dependent="ret_next", min_stocks=30)
    assert res["n_periods"] == 0
    assert res["n_dates_skipped_insufficient_cross_section"] == 20


def test_fama_macbeth_raises_on_missing_factor_columns():
    with pytest.raises(ValueError):
        run_fama_macbeth(make_fm_panel(n_stocks=40, n_dates=10), factors=["not_a_factor"],
                         dependent="ret_next")


# ===========================================================================
# 5. 三种安慰剂设计与逐日配对检验
# ===========================================================================
def test_event_level_placebo_excludes_triggers_and_matches_size_per_horizon():
    """事件级抽样：抽样池排除触发样本；每个 horizon 的抽样量分别等于目标组该 horizon 的有效数。"""
    events = make_placebo_events()
    events["ret_10d_free"] = events["ret_5d_free"]
    events["maxdd_10d_free"] = events["maxdd_5d_free"]
    pool = (~events["is_downtrend"]).to_numpy()
    target = events["is_downtrend"].to_numpy()

    dist = run_placebo(events, pool, target, horizons=(5, 10), n_runs=200, seed=7, mode="free")
    assert dist["design"] == "event_level"
    assert dist["h5"]["pool_size"] == 10        # 12 行中 2 行触发被排除
    assert dist["h5"]["target_size"] == 2
    assert dist["h5"]["draw_per_run"] == 2
    assert dist["h10"]["draw_per_run"] == 2
    assert max(dist["h5"]["dist_ret_means"]) < 1.0     # 分布里绝不能出现触发样本的 100.0


def test_date_level_placebo_resamples_dates_with_replacement():
    """随机日期安慰剂：按目标组占用的交易日数有放回抽日期，分布必须非退化。"""
    events = make_placebo_events()
    pool = (~events["is_downtrend"]).to_numpy()
    target = events["is_downtrend"].to_numpy()

    dist = run_date_placebo(events, pool, target, horizons=(5,), n_runs=300, seed=11, mode="free")
    block = dist["h5"]
    assert dist["design"] == "date_level"
    assert block["target_dates"] == 2          # 触发事件分布在 2 个交易日
    assert block["dates_per_run"] == 2
    assert block["pool_dates"] == 3
    assert block["resample_with_replacement"] is True
    assert block["std"] > 0                    # 有放回抽样不得退化为一个点
    assert max(block["dist_ret_means"]) < 1.0


def test_date_matched_placebo_preserves_per_date_counts():
    """同日匹配安慰剂：每次抽样的事件数必须等于目标组样本数（日期分布被固定）。"""
    events = make_placebo_events()
    pool = (~events["is_downtrend"]).to_numpy()
    target = events["is_downtrend"].to_numpy()

    dist = run_date_matched_placebo(events, pool, target, horizons=(5,), n_runs=200, seed=13, mode="free")
    block = dist["h5"]
    assert dist["design"] == "date_matched"
    assert block["target_size"] == 2
    assert block["dates_matched"] == 2
    assert block["events_per_run_mean"] == pytest.approx(2.0)
    assert block["dates_capped_or_missing"] == 0
    assert max(block["dist_ret_means"]) < 1.0


def test_placebo_is_deterministic_under_fixed_seed():
    events = make_placebo_events()
    pool = (~events["is_downtrend"]).to_numpy()
    target = events["is_downtrend"].to_numpy()
    for fn, label in ((run_placebo, "event_level"), (run_date_placebo, "date_level"),
                      (run_date_matched_placebo, "date_matched")):
        a = fn(events, pool, target, horizons=(5,), n_runs=100, seed=99, mode="free")
        b = fn(events, pool, target, horizons=(5,), n_runs=100, seed=99, mode="free")
        assert a["h5"]["dist_ret_means"] == b["h5"]["dist_ret_means"], label
        assert a["h5"]["dist_maxdd_means"] == b["h5"]["dist_maxdd_means"], label


def test_placebo_reports_error_on_empty_pool_instead_of_fabricating():
    events = make_placebo_events()
    empty = np.zeros(len(events), dtype=bool)
    target = events["is_downtrend"].to_numpy()
    for fn in (run_placebo, run_date_placebo, run_date_matched_placebo):
        dist = fn(events, empty, target, horizons=(5,), n_runs=10, seed=1, mode="free")
        assert dist["h5"]["error"] == "empty_pool"
        if fn is run_date_matched_placebo:
            assert dist["h5"]["status"] == "invalid_insufficient_control"
            assert dist["h5"]["is_valid_inference"] is False


def test_placebo_rejects_unknown_mode():
    events = make_placebo_events()
    pool = (~events["is_downtrend"]).to_numpy()
    target = events["is_downtrend"].to_numpy()
    for fn in (run_placebo, run_date_placebo, run_date_matched_placebo):
        with pytest.raises(ValueError):
            fn(events, pool, target, horizons=(5,), n_runs=5, mode="bogus")


def test_daily_paired_test_zero_difference_and_direction():
    """同一天目标组与池子完全一致时差值必须为 0；目标组系统性偏低时 t 必须为负。"""
    flat = make_paired_events({
        "2025-01-02": (0.010, 0.010),
        "2025-01-03": (0.020, 0.020),
        "2025-01-06": (0.030, 0.030),
    })
    res = daily_paired_test(flat, flat["is_downtrend"].to_numpy(),
                            (~flat["is_downtrend"]).to_numpy(), horizons=(5,), mode="free")
    assert res["design"] == "daily_paired"
    assert res["h5"]["n_days"] == 3
    assert res["h5"]["mean_diff"] == pytest.approx(0.0, abs=1e-15)

    lower = make_paired_events({
        "2025-01-02": (0.000, 0.010),
        "2025-01-03": (0.000, 0.030),
        "2025-01-06": (0.000, 0.020),
    })
    res_low = daily_paired_test(lower, lower["is_downtrend"].to_numpy(),
                                (~lower["is_downtrend"]).to_numpy(), horizons=(5,), mode="free")
    assert res_low["h5"]["mean_diff"] == pytest.approx(-0.02)
    assert res_low["h5"]["nw_t"] < 0
    assert res_low["h5"]["share_days_target_lower"] == pytest.approx(1.0)


def test_daily_paired_test_weighting_diagnostics():
    """等权日与事件加权口径必须给出不同结果，并定位到「高触发日」。

    构造：第 1 日 10 个目标事件（值 +0.05，池子 +0.01，差 +0.04）；
    第 2~4 日各 1 个目标事件（值与池子相同，差 0）。
    等权日差 = 0.04/4 = 0.01；按触发数加权 = 10*0.04/13 = 0.030769。
    """
    rows = []
    for _ in range(10):
        rows.append({"trade_date": "2025-01-02", "is_downtrend": True, "ret_5d": 0.05,
                     "ret_5d_free": 0.05, "maxdd_5d": -0.01, "maxdd_5d_free": -0.01})
    for _ in range(10):
        rows.append({"trade_date": "2025-01-02", "is_downtrend": False, "ret_5d": 0.01,
                     "ret_5d_free": 0.01, "maxdd_5d": -0.01, "maxdd_5d_free": -0.01})
    for d in ("2025-01-03", "2025-01-06", "2025-01-07"):
        rows.append({"trade_date": d, "is_downtrend": True, "ret_5d": 0.01,
                     "ret_5d_free": 0.01, "maxdd_5d": -0.01, "maxdd_5d_free": -0.01})
        rows.append({"trade_date": d, "is_downtrend": False, "ret_5d": 0.01,
                     "ret_5d_free": 0.01, "maxdd_5d": -0.01, "maxdd_5d_free": -0.01})
    events = pd.DataFrame(rows)

    res = daily_paired_test(events, events["is_downtrend"].to_numpy(),
                            (~events["is_downtrend"]).to_numpy(), horizons=(5,), mode="free")
    b = res["h5"]
    assert b["n_days"] == 4
    assert b["mean_diff"] == pytest.approx(0.01)
    assert b["weighted_mean_diff"] == pytest.approx(10 * 0.04 / 13)
    assert b["weighted_mean_diff"] > b["mean_diff"]
    assert b["diff_on_heavy_trigger_days"] == pytest.approx(0.04)
    assert b["diff_on_light_trigger_days"] == pytest.approx(0.0)
    assert b["heavy_trigger_day_share_of_events"] == pytest.approx(10.0 / 13.0)


# ===========================================================================
# 7. 日期级 cluster bootstrap 与报告产物一致性
# ===========================================================================
def test_date_cluster_bootstrap_diff_matches_hand_computation():
    """两天的组间差都是 +0.01，故事件加权与等权日的观测差都应为 +0.01，
    且 bootstrap 分布恒定 → SE 为 0。"""
    rows = []
    for _ in range(2):
        rows.append({"trade_date": "2025-01-02", "is_downtrend": True, "is_target": True,
                     "ret_5d": 0.02, "ret_5d_free": 0.02, "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
    for _ in range(3):
        rows.append({"trade_date": "2025-01-02", "is_downtrend": False, "is_target": False,
                     "ret_5d": 0.01, "ret_5d_free": 0.01, "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
    for _ in range(2):
        rows.append({"trade_date": "2025-01-03", "is_downtrend": True, "is_target": True,
                     "ret_5d": 0.04, "ret_5d_free": 0.04, "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
    for _ in range(3):
        rows.append({"trade_date": "2025-01-03", "is_downtrend": False, "is_target": False,
                     "ret_5d": 0.03, "ret_5d_free": 0.03, "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
    events = pd.DataFrame(rows)

    res = date_cluster_bootstrap_diff(events, events["is_target"].to_numpy(),
                                      (~events["is_target"]).to_numpy(),
                                      horizons=(5,), n_runs=50, seed=3, mode="free")
    b = res["h5"]
    assert res["design"] == "date_cluster_bootstrap_diff"
    assert b["n_days_joined"] == 2
    assert b["events_target"] == 4
    assert b["events_pool"] == 6
    # 事件加权：(0.02*2+0.04*2)/4 − (0.01*3+0.03*3)/6 = 0.03 − 0.02
    assert b["event_weighted"]["observed_diff"] == pytest.approx(0.01)
    assert b["date_equal"]["observed_diff"] == pytest.approx(0.01)
    assert b["event_weighted"]["boot_iid_se"] == pytest.approx(0.0, abs=1e-15)
    assert b["event_weighted"]["hac_se"] == pytest.approx(0.0, abs=1e-8)


def test_date_cluster_bootstrap_difference_cancels_common_day_shock():
    """日期级配对差必须抵消同日共同冲击：全样本存在巨大的日度共同波动时，
    若两组当日成分相同，差的 bootstrap SE 应塌到 0，而把事件当独立样本的 SE 仍很大。

    这正是「配对」相对「两组均值各自抽样」的核心价值，也是日期级设计的依据。
    """
    rng = np.random.RandomState(5)
    rows = []
    for d in range(30):
        date = f"2025-02-{d + 1:02d}"
        day_shock = rng.normal(0.0, 0.05)
        for i in range(20):
            is_t = i < 10
            # 同一天内不含个体噪声：两组共享完全相同的日度冲击，仅目标组多 +0.002
            value = day_shock + (0.002 if is_t else 0.0)
            rows.append({"trade_date": date, "is_target": is_t, "ret_5d": value, "ret_5d_free": value,
                         "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
    events = pd.DataFrame(rows)
    tgt = events["is_target"].to_numpy()

    res = date_cluster_bootstrap_diff(events, tgt, ~tgt, horizons=(5,), n_runs=100, seed=7, mode="free")
    b = res["h5"]["event_weighted"]
    assert b["observed_diff"] == pytest.approx(0.002, abs=1e-12)
    assert b["boot_iid_se"] == pytest.approx(0.0, abs=1e-12)
    assert b["hac_se"] == pytest.approx(0.0, abs=1e-8)

    vals = events["ret_5d_free"].to_numpy()
    naive_se = float(np.sqrt(vals[tgt].var(ddof=1) / tgt.sum() + vals[~tgt].var(ddof=1) / (~tgt).sum()))
    assert naive_se > 0.003, f"未配对的 iid SE 应很大，实际 {naive_se}"
    assert b["hac_se"] < naive_se / 10


def test_date_cluster_bootstrap_diff_reports_correlation_and_both_weightings():
    """必须同时给出事件加权与等权日两种口径，以及日度均值的相关系数。"""
    rows = []
    for d, (tv, pv) in enumerate(((0.02, 0.01), (0.04, 0.03), (0.06, 0.05))):
        date = f"2025-03-{d + 2:02d}"
        for _ in range(2):
            rows.append({"trade_date": date, "is_target": True, "ret_5d": tv,
                         "ret_5d_free": tv, "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
        for _ in range(3):
            rows.append({"trade_date": date, "is_target": False, "ret_5d": pv,
                         "ret_5d_free": pv, "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
    events = pd.DataFrame(rows)
    tgt = events["is_target"].to_numpy()
    b = date_cluster_bootstrap_diff(events, tgt, ~tgt, horizons=(5,), n_runs=50, seed=2, mode="free")["h5"]
    assert b["n_days_joined"] == 3
    assert b["event_weighted"]["observed_diff"] == pytest.approx(0.01)
    assert b["date_equal"]["observed_diff"] == pytest.approx(0.01)
    assert b["corr_of_date_means"] == pytest.approx(1.0)
    for field in ("boot_iid_se", "hac_se", "block5_se", "boot_iid_p_two_sided", "hac_p_two_sided", "block5_p_two_sided"):
        assert field in b["event_weighted"]
    for field in ("hac_se", "hac_p_two_sided", "block5_p_two_sided"):
        assert field in b["date_equal"]


def test_date_matched_placebo_reports_same_weight_target_mean():
    """同日匹配被截断时，必须给出与基线同权重的目标组均值。"""
    rows = []
    for _ in range(3):                                # 第 1 日：目标 3 个（值 0.05），池子只有 1 个
        rows.append({"trade_date": "2025-01-02", "is_target": True,
                     "ret_5d": 0.05, "ret_5d_free": 0.05, "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
    rows.append({"trade_date": "2025-01-02", "is_target": False,
                 "ret_5d": 0.01, "ret_5d_free": 0.01, "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
    rows.append({"trade_date": "2025-01-03", "is_target": True,
                 "ret_5d": 0.01, "ret_5d_free": 0.01, "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
    for _ in range(3):
        rows.append({"trade_date": "2025-01-03", "is_target": False,
                     "ret_5d": 0.01, "ret_5d_free": 0.01, "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
    events = pd.DataFrame(rows)
    tgt = events["is_target"].to_numpy()

    res = run_date_matched_placebo(events, ~tgt, tgt, horizons=(5,), n_runs=20, seed=11, mode="free")
    b = res["h5"]
    assert b["dates_capped_or_missing"] == 1                      # 第 1 日池子不足
    assert b["control_insufficient"] is True
    assert b["sample_equality_claimed"] is False
    assert b["status"] == "invalid_insufficient_control"
    assert b["match_status"] == "invalid_insufficient_control"
    assert b["is_valid_inference"] is False
    assert b["events_per_run_mean"] == pytest.approx(2.0)         # k=1 + k=1
    assert b["target_mean_full_sample"] == pytest.approx((3 * 0.05 + 0.01) / 4)
    # 同权重：第 1 日权重 1（被截断）而非 3
    assert b["target_mean_under_matched_weights"] == pytest.approx((0.05 + 0.01) / 2)


def test_date_matched_placebo_invalid_insufficient_control_flag():
    """验证当任一目标交易日缺乏充足对照事件时，同日匹配显式标记为 invalid_insufficient_control，
    下游 _placebo_p_values 亦显式继承该失效状态，杜绝被误标为有效匹配推断。"""
    from scripts.run_p4_trend_gate_study import _placebo_p_values
    rows = []
    # 目标组需要 3 个事件，但池子只有 1 个事件 -> 严重对照不足
    rows.append({"trade_date": "2024-01-02", "is_target": True, "ret_5d": 0.05, "ret_5d_free": 0.05, "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
    rows.append({"trade_date": "2024-01-02", "is_target": True, "ret_5d": 0.05, "ret_5d_free": 0.05, "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
    rows.append({"trade_date": "2024-01-02", "is_target": True, "ret_5d": 0.05, "ret_5d_free": 0.05, "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
    rows.append({"trade_date": "2024-01-02", "is_target": False, "ret_5d": 0.02, "ret_5d_free": 0.02, "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
    df = pd.DataFrame(rows)
    tgt = df["is_target"].to_numpy()
    dist = run_date_matched_placebo(df, ~tgt, tgt, horizons=(5,), n_runs=10, seed=42, mode="free")
    b = dist["h5"]
    assert b["control_insufficient"] is True
    assert b["sample_equality_claimed"] is False
    assert b["status"] == "invalid_insufficient_control"
    assert b["match_status"] == "invalid_insufficient_control"
    assert b["is_valid_inference"] is False
    assert b["dates_capped_or_missing"] == 1

    # 检验下游 _placebo_p_values 转换结果
    pv = _placebo_p_values(dist, {"h5": 0.05}, (5,))
    assert pv["h5"]["p_value_status"] == "invalid_insufficient_control"
    assert pv["h5"]["match_status"] == "invalid_insufficient_control"
    assert pv["h5"]["status"] == "invalid_insufficient_control"
    assert pv["h5"]["is_valid_inference"] is False


def test_placebo_p_values_use_per_horizon_observed_mean():
    """回归测试：h5/h10 的 p 值必须用它们各自的观测均值，而不是复用 h20 的。

    早期版本把同一个（h20）观测值传给所有 horizon，导致 h5/h10 的 p 值字段全错。
    """
    from scripts.run_p4_trend_gate_study import _placebo_p_values

    dist = {
        h: {"dist_ret_means": [0.0] * 100, "mean": 0.0, "std": 0.0, "ci_95": [0.0, 0.0]}
        for h in ("h5", "h10", "h20")
    }
    observed = {"h5": 0.05, "h10": 0.0, "h20": -0.05}
    out = _placebo_p_values(dist, observed, (5, 10, 20))
    assert out["h5"]["observed_mean_ret"] == pytest.approx(0.05)
    assert out["h10"]["observed_mean_ret"] == pytest.approx(0.0)
    assert out["h20"]["observed_mean_ret"] == pytest.approx(-0.05)
    # 观测高于全部安慰剂 → 单侧上尾为 1/101；低于全部 → 单侧下尾为 1/101
    assert out["h5"]["p_one_sided_upper"] == pytest.approx(1.0 / 101.0)
    assert out["h20"]["p_one_sided_lower"] == pytest.approx(1.0 / 101.0)
    # 观测落在分布正中 → 双侧 p 必为 1；若误用 h20 的观测值，h10 会得到 0.0198
    assert out["h10"]["p_two_sided"] == pytest.approx(1.0)
    assert out["h5"]["p_two_sided"] == pytest.approx(2.0 / 101.0)


def test_generated_reports_match_artifacts():
    """交付的 markdown 必须与当前 JSON + 当前生成器完全一致。

    这条测试专门防止「报告与产物脱节」——第一轮返工时正是因为缺少它，
    才让一句取值失败的结论（渲染成 0 / nan）随产物出厂。
    """
    out_dir = Path(__file__).resolve().parents[1] / "reports" / "real_rebuild_20261010"
    if not (out_dir / "results.json").exists():
        pytest.skip("尚未生成 P4 产物")
    trend = json.loads((out_dir / "trend_gate_event_study.json").read_text(encoding="utf-8"))
    fm = json.loads((out_dir / "fama_macbeth_hac_results.json").read_text(encoding="utf-8"))
    from scripts.run_real_m4_rebuild import build_paper_checklist_md, build_report_md, build_vs_old_md

    assert (out_dir / "report.md").read_text(encoding="utf-8") == build_report_md(trend, fm)
    assert (out_dir / "vs_old.md").read_text(encoding="utf-8") == build_vs_old_md(trend, fm)
    assert (out_dir / "paper_correction_checklist.md").read_text(encoding="utf-8") == build_paper_checklist_md(trend, fm)


def test_generated_report_has_no_unrendered_placeholders():
    """报告中不得残留未渲染的 f-string 占位符或 NaN/None。

    注意：`{0,1}` 这类字面文本是合法的，因此只匹配 `{` 后紧跟字母/下划线的形式。
    """
    out_dir = Path(__file__).resolve().parents[1] / "reports" / "real_rebuild_20261010"
    report = (out_dir / "report.md").read_text(encoding="utf-8")
    for pattern in (r"\bnan\b", r"\bNone\b", r"\bn/?a\b", r"\{[A-Za-z_]"):
        assert not re.search(pattern, report, flags=re.IGNORECASE), f"报告出现未渲染占位符: {pattern}"


def test_paper_draft_generated_matches_artifact_and_has_no_placeholders():
    """验证生成的学术论文初稿 (paper_draft_zh.md) 与构建器脚本生成的文本逐字节一致，
    且无任何未渲染的异常空值或 Python 格式占位符。"""
    out_dir = Path(__file__).resolve().parents[1] / "reports" / "real_rebuild_20261010"
    paper_path = out_dir / "paper_draft_zh.md"
    if not paper_path.exists():
        pytest.skip("paper_draft_zh.md 尚未生成")

    trend = json.loads((out_dir / "trend_gate_event_study.json").read_text(encoding="utf-8"))
    fm = json.loads((out_dir / "fama_macbeth_hac_results.json").read_text(encoding="utf-8"))
    results = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))

    from scripts.p4_paper_builder import build_paper_draft_zh, validate_no_unrendered_placeholders
    generated = build_paper_draft_zh(trend, fm, results)
    on_disk = paper_path.read_text(encoding="utf-8")

    assert generated == on_disk, "磁盘上的 paper_draft_zh.md 与 build_paper_draft_zh() 存在差异"
    validate_no_unrendered_placeholders(generated)


# ===========================================================================
# 6. 收益构造
# ===========================================================================
def test_attach_returns_next_day_and_fallback():
    df = pd.DataFrame({
        "stock_code": ["000001"] * 4,
        "trade_date": ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"],
        "close": [10.0, 11.0, 12.1, 13.31],
        "ret": [0.10, np.nan, 0.10, 0.10],
    })
    out = attach_returns(df)
    assert out["close_ret"].iloc[1] == pytest.approx(0.10)
    assert out["ret_used"].iloc[1] == pytest.approx(0.10)      # ret 缺失时回落到 close 口径
    assert out["ret_used"].iloc[0] == pytest.approx(0.10)
    assert out["ret_next"].iloc[0] == pytest.approx(out["ret_used"].iloc[1])
    assert out["ret_next"].iloc[1] == pytest.approx(out["ret_used"].iloc[2])
    assert np.isnan(out["ret_next"].iloc[3])
    # 官方口径次日收益在 ret 缺失处保持缺失，不做回落
    assert np.isnan(out["ret_next_official"].iloc[0])
    assert out["ret_next_official"].iloc[1] == pytest.approx(0.10)


# ===========================================================================
# 7. 阶段二 Acceptance 严格数学与计量断言测试
# ===========================================================================
def test_drawdown_peak_to_trough_vs_adverse_excursion():
    """Acceptance 1: 真实峰谷最大回撤必须为 min(p/cummax(p)-1)，非 min(p)/entry-1。
    手算小样本 [100, 120, 110] 峰谷回撤必须为 -1/12，而入场最大不利偏移 (MAE) 为 0。
    """
    prices = [100.0, 120.0, 110.0]
    maxdd, mae = calc_peak_to_trough_drawdown(prices)
    # cummax 为 [100, 120, 120]，p/cummax - 1 为 [0, 0, -10/120] = [0, 0, -1/12]
    assert maxdd == pytest.approx(-1.0 / 12.0, abs=1e-12)
    assert mae == pytest.approx(0.0, abs=1e-12)

    # 复杂样本：[100, 150, 120, 130, 90]
    # cummax: [100, 150, 150, 150, 150]
    # drawdowns: [0, 0, -30/150=-0.2, -20/150=-0.1333, -60/150=-0.4] -> min = -0.4
    # MAE from entry: min(p)/100 - 1 = 90/100 - 1 = -0.10
    maxdd2, mae2 = calc_peak_to_trough_drawdown([100.0, 150.0, 120.0, 130.0, 90.0])
    assert maxdd2 == pytest.approx(-0.40, abs=1e-12)
    assert mae2 == pytest.approx(-0.10, abs=1e-12)

    # 边界情况：单价格或非正价格
    assert calc_peak_to_trough_drawdown([100.0]) == (pytest.approx(0.0), pytest.approx(0.0))
    nan_dd, nan_mae = calc_peak_to_trough_drawdown([])
    assert np.isnan(nan_dd) and np.isnan(nan_mae)


def test_fama_macbeth_rf_subtraction_shifts_intercept_only():
    """Acceptance 2: OLS 截面回归含截距时，被解释变量减去日度固定 Rf，
    仅平移截距项 alpha_t -> alpha_t - Rf，z-score 因子斜率 lambda_{f,t} 严格保持不变。
    因此不得从每个因子斜率中扣除 Rf。
    """
    rng = np.random.RandomState(42)
    dates = [f"2025-01-{d:02d}" for d in range(2, 12)]  # 10 个交易日
    rows = []
    rf_daily = 0.015 / 244.0  # 年化 1.5%

    for d in dates:
        for i in range(40):  # 40 只股票
            f1_val = rng.normal(0.0, 1.0)
            f2_val = rng.normal(0.0, 1.0)
            # 真实生成收益：y = alpha_true + 0.03 * f1 - 0.02 * f2 + noise
            ret_val = 0.005 + 0.03 * f1_val - 0.02 * f2_val + rng.normal(0.0, 0.01)
            rows.append({
                "stock_code": f"{i:06d}",
                "trade_date": d,
                "f1": f1_val,
                "f2": f2_val,
                "ret_raw": ret_val,
                "ret_excess": ret_val - rf_daily,
                "limit_up": False,
            })
    df = pd.DataFrame(rows)

    res_raw = run_fama_macbeth(df, factors=["f1", "f2"], dependent="ret_raw", min_stocks=30, bootstrap_runs=50)
    res_excess = run_fama_macbeth(df, factors=["f1", "f2"], dependent="ret_excess", min_stocks=30, bootstrap_runs=50)

    # 1. 逐期因子斜率 lambda 严格相同（浮点精度 1e-12）
    for f in ["f1", "f2"]:
        l_raw = np.array(res_raw["per_period_lambdas"][f])
        l_excess = np.array(res_excess["per_period_lambdas"][f])
        np.testing.assert_allclose(l_raw, l_excess, atol=1e-12)
        # 因子统计量完全一致
        assert res_raw["factors_stats"][f]["mean_risk_premium_daily"] == pytest.approx(
            res_excess["factors_stats"][f]["mean_risk_premium_daily"], abs=1e-12
        )
        assert res_raw["factors_stats"][f]["newey_west_t"] == pytest.approx(
            res_excess["factors_stats"][f]["newey_west_t"], abs=1e-12
        )
        # 因子年化溢价 excess 字段不得机械扣除 rf
        assert res_raw["factors_stats"][f]["annualized_premium_excess_244d"] == pytest.approx(
            res_raw["factors_stats"][f]["annualized_premium_244d"], abs=1e-12
        )

    # 2. 截距项逐期严格平移 -rf_daily
    a_raw = np.array(res_raw["per_period_alpha"])
    a_excess = np.array(res_excess["per_period_alpha"])
    np.testing.assert_allclose(a_raw - rf_daily, a_excess, atol=1e-12)
    assert res_raw["mean_alpha_daily"] - rf_daily == pytest.approx(res_excess["mean_alpha_daily"], abs=1e-12)


def test_paired_ratio_influence_varying_counts_cancels_when_means_constant():
    """Acceptance 3: 比率估计量的中心化影响函数在各日样本量变化但日均值差恒定时方差为零。
    若采用未中心化的 S_t/N - R_t/M，会因各日样本量 N_t, M_t 的波动引入虚假方差。
    """
    # 5 个交易日，各日样本量剧烈变化，但各日组内均值完全恒定：目标恒为 0.05，池恒为 0.02
    target_counts = [100, 2, 50, 10, 20]
    pool_counts = [10, 80, 20, 5, 40]
    dates = [f"2025-01-{d:02d}" for d in range(2, 7)]

    rows = []
    for d, nt, np_cnt in zip(dates, target_counts, pool_counts):
        for _ in range(nt):
            rows.append({"trade_date": d, "is_target": True, "ret_5d": 0.05, "ret_5d_free": 0.05,
                         "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
        for _ in range(np_cnt):
            rows.append({"trade_date": d, "is_target": False, "ret_5d": 0.02, "ret_5d_free": 0.02,
                         "maxdd_5d": 0.0, "maxdd_5d_free": 0.0})
    events = pd.DataFrame(rows)
    tgt = events["is_target"].to_numpy()

    res = date_cluster_bootstrap_diff(events, tgt, ~tgt, horizons=(5,), n_runs=100, seed=1, mode="free")
    ew = res["h5"]["event_weighted"]

    # 观测均值差严格为 0.05 - 0.02 = 0.03
    assert ew["observed_diff"] == pytest.approx(0.03, abs=1e-12)
    # 中心化影响函数的 HAC SE 和 iid SE 均严格为 0
    assert ew["hac_se"] == pytest.approx(0.0, abs=1e-8)
    assert ew["boot_iid_se"] == pytest.approx(0.0, abs=1e-8)

    # 验证未中心化的 naive 贡献序列在各日样本量波动下有很大方差（证明为何必须中心化）
    ts = np.array([0.05 * c for c in target_counts])
    tn = np.array(target_counts, dtype=float)
    ps = np.array([0.02 * c for c in pool_counts])
    pn = np.array(pool_counts, dtype=float)
    m = len(dates)
    naive_z = (ts / tn.sum() - ps / pn.sum()) * m
    assert np.std(naive_z) > 0.05, "未中心化分数因日样本量波动引入了虚假方差"


def test_serial_correlated_ar1_understates_iid_se():
    """Acceptance 6: 正序列相关下（类似 20 日重叠持有期），经典 IID 标准误严重低估，
    导致 IID t 值被虚假放大；Newey-West HAC 标准误正确放大以校正自相关。
    """
    rng = np.random.RandomState(123)
    T = 300
    rho = 0.8
    # 模拟 AR(1) 过程: x_t = rho * x_{t-1} + e_t + 0.02 (带漂移)
    innovations = rng.normal(0.0, 0.05, size=T)
    x = np.empty(T, dtype=float)
    x[0] = innovations[0] + 0.02
    for t in range(1, T):
        x[t] = rho * x[t - 1] + innovations[t] + 0.02 * (1.0 - rho)

    _, se_iid, t_iid = classic_iid_t_stat(x)
    _, se_hac, t_hac = newey_west_t_stat(x, lags=15)

    # 理论上 AR(1) 在 rho=0.8 时方差膨胀系数约为 (1+rho)/(1-rho) = 9，SE 膨胀约 3 倍
    assert se_iid < se_hac * 0.55, f"IID SE ({se_iid:.6f}) 未显著低于 HAC SE ({se_hac:.6f})"
    assert abs(t_iid) > abs(t_hac) * 1.5, f"IID t ({t_iid:.2f}) 未显著虚高过 HAC t ({t_hac:.2f})"
