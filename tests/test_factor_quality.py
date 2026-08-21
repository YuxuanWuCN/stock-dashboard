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
    assert "crowding" in report
