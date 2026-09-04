"""tests/test_factor_quality.py —— 因子半衰期/拥挤度（005 融合 US3）单元测试。"""

import json

import numpy as np
import pandas as pd

from src.analysis.factor_db import import_to_db, write_factor_quality_report
from src.analysis.factor_quality import (
    compute_factor_quality_report,
    crowding,
    half_life,
)


def test_half_life_known_decay():
    """已知衰减序列：峰值 0.2，一半 0.1 出现在第 2 个位置 → 半衰期 2 天。"""
    ic = [0.2, 0.15, 0.1, 0.05, 0.01]
    assert half_life(ic) == 2


def test_half_life_no_decay_returns_none():
    ic = [0.2, 0.19, 0.18, 0.17, 0.16]
    assert half_life(ic) is None


def test_half_life_short_series_returns_none():
    assert half_life([0.1, 0.2]) is None


def test_crowding_high_correlation_is_crowded():
    base = np.arange(1.0, 60.0)
    rng = np.random.default_rng(1)
    returns = {
        "A": (base + rng.standard_normal(59) * 0.01).tolist(),
        "B": (base * 1.1 + rng.standard_normal(59) * 0.01).tolist(),
    }
    r = crowding(returns)
    assert r["level"] == "crowded"
    assert r["avg_corr"] > 0.9


def test_crowding_low_correlation_is_uncrowded():
    n = 59
    a = np.arange(1.0, 1.0 + n)
    b = np.array([(i % 2) * 10.0 + (i % 3) for i in range(n)], dtype=float)
    r = crowding({"A": a.tolist(), "B": b.tolist()})
    assert r["level"] == "uncrowded"
    assert r["avg_corr"] < 0.5


def test_crowding_insufficient_factors_unknown():
    r = crowding({"A": [1.0, 2.0, 3.0]})
    assert r["level"] == "unknown"


def test_compute_report_contains_new_fields():
    n = 200
    rng = np.random.default_rng(42)
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="B"),
        "MKT": rng.standard_normal(n),
        "SMB": rng.standard_normal(n),
        "HML": rng.standard_normal(n),
        "MOM": rng.standard_normal(n),
    })
    report = compute_factor_quality_report(df)
    assert "half_life_days" in report["factors"]["MKT"]
    assert "crowding" in report
    assert report["crowding"]["level"] in (
        "crowded", "moderately_crowded", "uncrowded", "unknown",
    )


def test_write_factor_quality_report_integration(tmp_path):
    """因子库 → 质量报告全链路：JSON 含 half_life/crowding 字段。"""
    n = 260
    rng = np.random.default_rng(7)
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    csv_text = "date,MKT,SMB,HML,MOM\n" + "\n".join(
        f"{d.strftime('%Y-%m-%d')},{rng.standard_normal():.6f},"
        f"{rng.standard_normal():.6f},{rng.standard_normal():.6f},{rng.standard_normal():.6f}"
        for d in dates
    )
    db = str(tmp_path / "factors.db")
    import_to_db(csv_text, db_path=db)

    out = str(tmp_path / "quality_report.json")
    written = write_factor_quality_report(db_path=db, out_path=out)
    with open(written, encoding="utf-8") as f:
        report = json.load(f)
    assert "half_life_days" in report["factors"]["MKT"]
    assert "half_life_continuous_days" in report["factors"]["MKT"]
    assert "decay_fit_valid" in report["factors"]["MKT"]
    assert "crowding" in report


def test_fit_exponential_decay_known_half_life():
    """已知指数衰减序列：半衰期精确设定为 4.0 天。"""
    from src.analysis.factor_quality import fit_exponential_decay
    # t_1/2 = 4.0 -> lambda = ln(2)/4 = 0.173286795
    decay_lambda = float(np.log(2.0) / 4.0)
    lags = np.arange(1, 15)
    ic_values = (0.35 * np.exp(-decay_lambda * lags)).tolist()

    res = fit_exponential_decay(ic_values)
    assert res.is_valid is True
    assert res.half_life_days is not None
    assert abs(res.half_life_days - 4.0) < 0.15
    assert res.r_squared is not None and res.r_squared > 0.99
    assert res.decay_rate_lambda is not None
    assert abs(res.decay_rate_lambda - decay_lambda) < 0.01


def test_fit_exponential_decay_non_decaying_and_zeros():
    """测试不衰减或全零序列的健壮性。"""
    from src.analysis.factor_quality import fit_exponential_decay
    # 增长序列（反向不衰减）
    growing_ic = [0.05, 0.10, 0.15, 0.20, 0.25]
    res_grow = fit_exponential_decay(growing_ic)
    assert res_grow.is_valid is False
    assert res_grow.half_life_days is None

    # 全零序列
    res_zero = fit_exponential_decay([0.0, 0.0, 0.0, 0.0])
    assert res_zero.is_valid is False
    assert res_zero.half_life_days is None

    # 样本不足
    res_short = fit_exponential_decay([0.2, 0.1])
    assert res_short.is_valid is False


def test_compute_forward_rank_ic():
    """测试前向 Rank IC 均值序列计算。"""
    from src.analysis.factor_quality import compute_forward_rank_ic
    dates = pd.date_range("2026-01-01", periods=30, freq="B")
    tickers = ["S1", "S2", "S3", "S4", "S5"]
    rng = np.random.default_rng(42)

    # 构造因子与未来收益正相关的模拟数据
    factor_df = pd.DataFrame(rng.standard_normal((30, 5)), index=dates, columns=tickers)
    # 未来 1 日收益部分来源于当日因子
    returns_df = pd.DataFrame(
        factor_df.shift(1).to_numpy() * 0.02 + rng.standard_normal((30, 5)) * 0.01,
        index=dates,
        columns=tickers,
    )

    rank_ic = compute_forward_rank_ic(factor_df, returns_df, max_lag=5)
    assert len(rank_ic) > 0
    assert 1 in rank_ic
    assert -1.0 <= rank_ic[1] <= 1.0


def test_decay_weighted_smoothing_causality():
    """测试指数记忆平滑的因果性：修改未来数据绝不影响历史值。"""
    from src.analysis.factor_quality import decay_weighted_smoothing
    s1 = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], name="test")
    s2 = pd.Series([1.0, 2.0, 3.0, 999.0, 999.0, 999.0], name="test")

    smoothed1 = decay_weighted_smoothing(s1, half_life_days=3.0, max_lags=4)
    smoothed2 = decay_weighted_smoothing(s2, half_life_days=3.0, max_lags=4)

    # t=0, 1, 2 时刻由于历史完全一致，平滑结果必须严格完全相等（无前视泄漏）
    assert np.allclose(smoothed1.iloc[:3], smoothed2.iloc[:3])
    # t=3 之后因为输入不同而分化
    assert not np.isclose(smoothed1.iloc[3], smoothed2.iloc[3])
