# tests/test_fama_macbeth.py —— Fama-MacBeth 多因子引擎单元测试（spec-kit 003）
#
# 本文件分两部分：
#   1) 合成数据生成器（T004，基础设施，供全部故事测试复用）
#   2) US1/US2/US4 的单元测试（T005-T007、T012-T014、后续补充）
#
# 原则：全部离线、确定性（固定 seed）、零外部请求、可复现（AGENTS.md）。

import numpy as np
import pandas as pd

FACTOR_COLS = ["MKT", "SMB", "HML", "MOM"]


# ============================================================
# T004: 合成数据生成器（基础）
# ============================================================

def synthetic_factors(n_days=1250, seed=42, start="2021-08-13", include_rf=True):
    """确定性合成 4 因子日频序列。

    规格与 docs/data/factors/fixture_factors.csv 一致（同 seed 同参数应可复现同值）：
    表头 date,MKT,SMB,HML,MOM[,rf]，无缺口。
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n_days)
    rf_daily = (1.025 ** (1 / 252)) - 1.0
    df = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "MKT": rng.normal(0.0002, 0.012, n_days),
        "SMB": rng.normal(0.0001, 0.005, n_days),
        "HML": rng.normal(0.0001, 0.004, n_days),
        "MOM": rng.normal(0.0002, 0.006, n_days),
    })
    if include_rf:
        df["rf"] = rf_daily
    return df


def synthetic_stock_returns(factors, beta=None, alpha_daily=0.0, resid_vol=0.01, seed=7):
    """给定因子序列与 beta 合成个股超额收益：r_t = rf_t + alpha + sum(beta_k * F_kt) + eps_t。

    alpha_daily / resid_vol 用于构造"已知真值"的回归还原测试（US2）。
    """
    if beta is None:
        beta = {"MKT": 1.0, "SMB": 0.3, "HML": 0.2, "MOM": 0.1}
    rng = np.random.default_rng(seed)
    n = len(factors)
    rf = factors["rf"].to_numpy() if "rf" in factors.columns else np.zeros(n)
    systematic = sum(beta[k] * factors[k].to_numpy() for k in FACTOR_COLS)
    eps = rng.normal(0.0, resid_vol, n)
    return rf + alpha_daily + systematic + eps


def synthetic_kline(n_days=1250, seed=11, start="2021-08-13", base_price=10.0,
                    mu=0.0005, sigma=0.02):
    """合成日 K 线 DataFrame，列序与项目约定一致：[date, open, close, low, high, volume]。

    日期序列与 synthetic_factors 同参数时完全一致，便于对齐测试。
    """
    rng = np.random.default_rng(seed)
    n = n_days
    dates = pd.bdate_range(start, periods=n_days)
    rets = rng.normal(mu, sigma, n_days)
    close = base_price * np.cumprod(1 + rets)
    open_ = np.empty(n)
    low = np.empty(n)
    high = np.empty(n)
    volume = np.empty(n)
    open_[0] = base_price
    for i in range(n):
        if i > 0:
            open_[i] = close[i - 1]
        low[i] = min(open_[i], close[i]) * (1 - abs(rng.normal(0, 0.004)))
        high[i] = max(open_[i], close[i]) * (1 + abs(rng.normal(0, 0.004)))
        volume[i] = float(rng.integers(10000, 100000))
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": open_,
        "close": close,
        "low": low,
        "high": high,
        "volume": volume,
    })


def csv_text(df, with_header=True):
    """DataFrame → CSV 文本（供因子 CSV 校验器测试用）。"""
    if with_header:
        return df.to_csv(index=False)
    return df.to_csv(index=False, header=False)


# ============================================================
# US1: 因子数据层单元测试（T005-T007）
# ============================================================

import json
import os
import sqlite3
import sys as _sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_sys.path.insert(0, os.path.join(_REPO, "src"))

from analysis import factor_db  # noqa: E402


# ---------- T005: CSV 契约校验 ----------

def test_validate_factors_csv_ok():
    df = synthetic_factors()
    result, report = factor_db.validate_factors_csv(csv_text(df))
    assert list(result.columns) == ["date", "MKT", "SMB", "HML", "MOM", "rf"]
    assert report["gap_rate"] == 0.0
    assert report["row_count"] == len(df)


def test_validate_missing_column_raises():
    df = synthetic_factors().drop(columns=["MKT"])
    with pytest.raises(ValueError, match="MKT"):
        factor_db.validate_factors_csv(csv_text(df))


def test_validate_duplicate_dates_raise():
    df = synthetic_factors()
    dup = pd.concat([df.iloc[[0]], df], ignore_index=True)
    with pytest.raises(ValueError, match="重复日期|duplicate"):
        factor_db.validate_factors_csv(csv_text(dup))


def test_validate_gap_rate_exceeded_raises():
    df = synthetic_factors()
    n = len(df)
    df.loc[df.index[: int(n * 0.06)], "MOM"] = np.nan  # 6% > 5% 阈值
    with pytest.raises(ValueError, match="缺口|gap"):
        factor_db.validate_factors_csv(csv_text(df))


def test_validate_gap_within_tolerance():
    df = synthetic_factors()
    df.loc[df.index[:10], "MOM"] = np.nan  # 10/1250 = 0.8%
    result, report = factor_db.validate_factors_csv(csv_text(df))
    assert report["gap_rate"] == pytest.approx(10 / len(df))
    assert len(result) == len(df) - 10


def test_validate_disordered_sorts():
    df = synthetic_factors()
    shuffled = df.sample(frac=1.0, random_state=0).reset_index(drop=True)
    result, _ = factor_db.validate_factors_csv(csv_text(shuffled))
    assert result["date"].is_monotonic_increasing


def test_validate_insufficient_range_raises():
    df = synthetic_factors(n_days=100)
    with pytest.raises(ValueError, match="不足|MIN_OBS|250"):
        factor_db.validate_factors_csv(csv_text(df))


def test_validate_header_case_insensitive():
    df = synthetic_factors()
    txt = csv_text(df)
    txt = txt.replace("MKT", "mkt").replace("SMB", "smb")
    txt = txt.replace("HML", "hml").replace("MOM", "mom")
    result, _ = factor_db.validate_factors_csv(txt)
    assert list(result.columns) == ["date", "MKT", "SMB", "HML", "MOM", "rf"]


def test_validate_rf_optional_fills_default():
    df = synthetic_factors(include_rf=False)
    result, report = factor_db.validate_factors_csv(csv_text(df))
    assert "rf" in result.columns
    assert report["rf_source"] == "default"


# ---------- T006: SQLite 入库与查询 ----------

def test_import_creates_tables_and_rows(tmp_path):
    df = synthetic_factors()
    db = str(tmp_path / "factors.db")
    stats = factor_db.import_to_db(csv_text(df), db_path=db)
    con = sqlite3.connect(db)
    rows = con.execute("SELECT COUNT(*) FROM factors").fetchone()[0]
    dup = con.execute("SELECT COUNT(*) - COUNT(DISTINCT date) FROM factors").fetchone()[0]
    meta = con.execute("SELECT COUNT(*) FROM source_meta").fetchone()[0]
    con.close()
    assert rows == len(df)
    assert dup == 0
    assert meta > 0
    assert stats["row_count"] == len(df)


def test_import_idempotent_upsert(tmp_path):
    df = synthetic_factors()
    db = str(tmp_path / "factors.db")
    factor_db.import_to_db(csv_text(df), db_path=db)
    factor_db.import_to_db(csv_text(df), db_path=db)
    con = sqlite3.connect(db)
    rows = con.execute("SELECT COUNT(*) FROM factors").fetchone()[0]
    con.close()
    assert rows == len(df)


def test_failed_import_leaves_db_unchanged(tmp_path):
    df = synthetic_factors()
    db = str(tmp_path / "factors.db")
    factor_db.import_to_db(csv_text(df), db_path=db)
    bad = csv_text(synthetic_factors()).replace(",MKT,", ",XXT,")
    with pytest.raises(ValueError):
        factor_db.import_to_db(bad, db_path=db)
    con = sqlite3.connect(db)
    rows = con.execute("SELECT COUNT(*) FROM factors").fetchone()[0]
    con.close()
    assert rows == len(df)


def test_query_range(tmp_path):
    df = synthetic_factors()
    db = str(tmp_path / "factors.db")
    factor_db.import_to_db(csv_text(df), db_path=db)
    out = factor_db.query_range(db, "2021-08-13", "2021-08-27")
    assert len(out) == 11  # 2021-08-13(五) ~ 2021-08-27(五) 共 11 个工作日
    assert out["date"].min() == "2021-08-13"
    assert out["date"].max() == "2021-08-27"
    empty = factor_db.query_range(db, "2030-01-01", "2030-01-31")
    assert len(empty) == 0


# ---------- T007: 对齐与质量报告 ----------

def test_align_intersection_and_dropped():
    factors = synthetic_factors()
    kline = synthetic_kline().iloc[10:]
    aligned_f, aligned_k, dropped = factor_db.align_with_kline(factors, kline)
    assert len(aligned_f) == len(aligned_k) == len(factors) - 10
    assert (aligned_f["date"].to_numpy() == aligned_k["date"].to_numpy()).all()
    # K 线被裁掉前 10 天 → 这 10 个日期从因子侧被剔除（交集策略）
    assert len(dropped["dropped_factor_dates"]) == 10
    assert len(dropped["dropped_kline_dates"]) == 0


def test_align_no_value_shift():
    factors = synthetic_factors()
    kline = synthetic_kline()
    aligned_f, aligned_k, _ = factor_db.align_with_kline(factors, kline)
    # 对齐后因子值必须与原始日期对应值一致（无前视/错位）
    assert (aligned_f["MKT"].to_numpy() == factors["MKT"].to_numpy()).all()
    assert (aligned_k["close"].to_numpy() == kline["close"].to_numpy()).all()


def test_quality_report_written(tmp_path):
    report = {
        "generated_at": "2026-08-15T00:00:00",
        "source": "fixture",
        "row_count": 1250,
        "gap_rate": 0.0,
        "alignment": {"dropped_kline_days": 0},
    }
    out = str(tmp_path / "quality_report.json")
    factor_db.write_quality_report(report, path=out)
    with open(out, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["row_count"] == 1250
    assert data["gap_rate"] == 0.0
    assert data["alignment"]["dropped_kline_days"] == 0


# ============================================================
# US4 补充：边界与 CLI 覆盖（T025 覆盖率补齐）
# ============================================================

import io
from pathlib import Path
from unittest import mock

def test_read_csv_supports_path_filelike_and_text(tmp_path):
    df = synthetic_factors()
    p = tmp_path / "f.csv"
    p.write_text(csv_text(df), encoding="utf-8")
    r1, _ = factor_db.validate_factors_csv(str(p))            # 路径分支
    r2, _ = factor_db.validate_factors_csv(io.StringIO(csv_text(df)))  # file-like 分支
    assert len(r1) == len(r2) == len(df)


def test_validate_bad_date_raises():
    df = synthetic_factors()
    df.loc[3, "date"] = "not-a-date"
    with pytest.raises(ValueError, match="无法解析的日期"):
        factor_db.validate_factors_csv(csv_text(df))


def test_validate_rf_nan_fills_default():
    df = synthetic_factors()
    df.loc[df.index[:5], "rf"] = np.nan
    result, report = factor_db.validate_factors_csv(csv_text(df))
    assert report["rf_source"] == "csv_with_default_fill"
    assert result["rf"].isna().sum() == 0


def test_validate_extracts_source_version():
    df = synthetic_factors()
    df["source"] = "CSMAR"
    df["version"] = "20260814"
    _, report = factor_db.validate_factors_csv(csv_text(df))
    assert report["source"] == "CSMAR"
    assert report["version"] == "20260814"


def test_import_rollback_on_write_failure(tmp_path, monkeypatch):
    df = synthetic_factors()
    db = str(tmp_path / "f.db")
    factor_db.import_to_db(csv_text(df), db_path=db)

    class _FakeCon:
        def __init__(self):
            self.rolled_back = False
        def execute(self, sql):
            return None
        def executemany(self, sql, rows):
            raise RuntimeError("disk full")
        def commit(self):
            pass
        def rollback(self):
            self.rolled_back = True
        def close(self):
            pass

    fake = _FakeCon()
    monkeypatch.setattr(factor_db.sqlite3, "connect", lambda path: fake)
    with pytest.raises(RuntimeError, match="disk full"):
        factor_db.import_to_db(csv_text(df), db_path=db)
    assert fake.rolled_back is True
    # 原有库内容未受损
    monkeypatch.undo()
    con = sqlite3.connect(db)
    rows = con.execute("SELECT COUNT(*) FROM factors").fetchone()[0]
    con.close()
    assert rows == len(df)


def test_factor_db_cli_import(monkeypatch, tmp_path, capsys):
    df = synthetic_factors()
    csv_path = tmp_path / "f.csv"
    csv_path.write_text(csv_text(df), encoding="utf-8")
    db = str(tmp_path / "f.db")
    monkeypatch.setattr("sys.argv", ["factor_db", "import", "--csv", str(csv_path), "--db", db])
    assert factor_db.main() == 0
    capsys.readouterr()
    con = sqlite3.connect(db)
    rows = con.execute("SELECT COUNT(*) FROM factors").fetchone()[0]
    con.close()
    assert rows == len(df)


def test_default_db_path_uses_config(monkeypatch):
    monkeypatch.setattr(factor_db, "FACTOR_DB_PATH", "D:/custom/f.db")
    assert factor_db.default_db_path() == Path("D:/custom/f.db")


def test_default_db_path_fallback(monkeypatch):
    monkeypatch.setattr(factor_db, "FACTOR_DB_PATH", None)
    p = factor_db.default_db_path()
    assert str(p).endswith(f"docs{os.sep}data{os.sep}factors{os.sep}factors.db")


def test_regress_length_mismatch_raises():
    f = synthetic_factors()
    r = synthetic_stock_returns(f)
    with pytest.raises(ValueError, match="不一致"):
        fama_macbeth.regress_one(f, r[:-5])


def test_regress_fit_failure_failed_status(monkeypatch):
    """回归拟合抛异常（奇异矩阵等）→ status=failed + 原因（FR-009 不伪造）。"""
    def raiser(*args, **kwargs):
        raise RuntimeError("singular boom")
    monkeypatch.setattr(fama_macbeth.sm, "OLS", raiser)
    f = synthetic_factors()
    r = synthetic_stock_returns(f, seed=7)
    result = fama_macbeth.regress_one(f, r)
    assert result["status"] == "failed"
    assert "singular boom" in result["reason"]


def test_regress_vif_failure_falls_back_none(monkeypatch):
    def raiser(*args, **kwargs):
        raise RuntimeError("vif boom")
    monkeypatch.setattr(
        "statsmodels.stats.outliers_influence.variance_inflation_factor", raiser
    )
    f = synthetic_factors()
    r = synthetic_stock_returns(f, seed=7)
    result = fama_macbeth.regress_one(f, r)
    assert result["status"] == "ok"
    assert all(v is None for v in result["vif"].values())


def test_stage2_skips_none_and_missing_betas():
    factors = synthetic_factors(n_days=300)
    panel_returns = {
        "A": pd.Series([None] * 300),
        "B": pd.Series(np.zeros(300)),
    }
    panel_betas = {"A": dict(DEFAULT_BETA)}  # B 缺 beta → 跳过
    out = fama_macbeth.fama_macbeth_stage2(factors, panel_returns, panel_betas)
    assert out["n_periods"] == 0
    assert out["lambda_mean"]["MKT"] is None
    assert out["lambda_se"]["MKT"] is None
    assert out["intercept_mean"] is None


def test_stage2_too_few_stocks_skips():
    factors = synthetic_factors(n_days=100)
    panel_returns = {}
    panel_betas = {}
    for i in range(10):  # 10 < FM_MIN_CROSS_SECTION 20
        code = f"S{i}"
        panel_returns[code] = pd.Series(np.zeros(100))
        panel_betas[code] = dict(DEFAULT_BETA)
    out = fama_macbeth.fama_macbeth_stage2(factors, panel_returns, panel_betas)
    assert out["n_periods"] == 0


def test_run_all_kline_derived_returns_path():
    factors = synthetic_factors()
    results = fama_macbeth.run_all(factors, {"T000": synthetic_kline()})
    assert results["T000"]["status"] == "ok"
    # pct_change 首行收益为 NaN，regress_one 现会正确丢弃（NaN 防护）
    # 因此有效观测 = 因子行数 - 1
    assert results["T000"]["n_obs"] == len(factors) - 1


def test_run_all_no_overlap_insufficient():
    factors = synthetic_factors()
    kline = synthetic_kline(start="2010-01-01", n_days=500)  # 与因子日期无交集
    results = fama_macbeth.run_all(factors, {"T000": kline})
    assert results["T000"]["status"] == "insufficient_data"
    assert results["T000"]["reason"] == "对齐后无有效收益"


def test_load_kline_json_missing_and_real():
    assert fama_macbeth._load_kline_json("NO_SUCH_CODE") is None
    df = fama_macbeth._load_kline_json("001258")  # 仓库真实缓存
    assert df is not None
    assert list(df.columns) == ["date", "open", "close", "low", "high", "volume"]


def test_fama_macbeth_cli_missing_db(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["fama_macbeth"])
    monkeypatch.setattr(
        fama_macbeth.factor_db, "default_db_path",
        lambda: Path("D:/nonexistent/f.db"),
    )
    assert fama_macbeth.main() == 2
    capsys.readouterr()


def test_fama_macbeth_cli_missing_kline(monkeypatch, tmp_path, capsys):
    from pathlib import Path as _P
    df = synthetic_factors()
    db = str(tmp_path / "f.db")
    factor_db.import_to_db(csv_text(df), db_path=db)
    monkeypatch.setattr(fama_macbeth.factor_db, "default_db_path", lambda: _P(db))
    monkeypatch.setattr("sys.argv", ["fama_macbeth", "--code", "NO_SUCH_CODE"])
    assert fama_macbeth.main() == 2
    capsys.readouterr()


def test_fama_macbeth_cli_success(monkeypatch, tmp_path, capsys):
    from pathlib import Path as _P
    df = synthetic_factors()
    db = str(tmp_path / "f.db")
    factor_db.import_to_db(csv_text(df), db_path=db)
    monkeypatch.setattr(fama_macbeth.factor_db, "default_db_path", lambda: _P(db))
    monkeypatch.setattr("sys.argv", ["fama_macbeth", "--code", "001258"])
    assert fama_macbeth.main() == 0
    out = capsys.readouterr().out
    assert "status" in out


def test_independent_benchmark_manual_ols():
    """独立基准复核（AGENTS.md 第 3 条）：numpy 正规方程手算 OLS 对照模块输出。

    小样本（60 日）上，alpha/betas 点估计必须与独立实现逐位一致，
    IR 必须与手算公式 alpha/sigma(residual) 一致。
    """
    factors = synthetic_factors(n_days=300, seed=7)
    returns = synthetic_stock_returns(factors, alpha_daily=0.003,
                                      resid_vol=0.008, seed=13)
    result = fama_macbeth.regress_one(factors, returns)

    X = np.column_stack(
        [np.ones(300)] + [factors[k].to_numpy() for k in ("MKT", "SMB", "HML", "MOM")]
    )
    y = returns - factors["rf"].to_numpy()
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    resid_sd = float(resid.std(ddof=1))

    assert result["status"] == "ok"
    assert result["alpha"] == pytest.approx(float(coef[0]), abs=1e-9)
    for i, k in enumerate(("MKT", "SMB", "HML", "MOM")):
        assert result["betas"][k] == pytest.approx(float(coef[i + 1]), abs=1e-9)
    assert result["information_ratio"] == pytest.approx(
        float(coef[0]) / resid_sd, abs=1e-9,
    )


# ============================================================
# US2: Fama-MacBeth 两阶段回归单元测试（T012-T014 + 批量入口）
# ============================================================

from analysis import fama_macbeth  # noqa: E402

DEFAULT_BETA = {"MKT": 1.0, "SMB": 0.3, "HML": 0.2, "MOM": 0.1}


# ---------- T012: 已知 Alpha 还原 ----------

def test_regress_restores_injected_alpha():
    factors = synthetic_factors()
    beta = dict(DEFAULT_BETA)
    alpha_daily = 0.005  # 注入 0.5%/日
    resid_vol = 0.01     # IR 设计值 ≈ 0.5
    returns = synthetic_stock_returns(factors, beta=beta, alpha_daily=alpha_daily,
                                      resid_vol=resid_vol, seed=7)
    result = fama_macbeth.regress_one(factors, returns)
    assert result["status"] == "ok"
    assert abs(result["alpha"] - alpha_daily) <= alpha_daily * 0.2  # ±20%
    assert result["alpha_p_value"] < 0.05
    assert result["information_ratio"] >= 0.3
    for key in ("MKT", "SMB", "HML", "MOM"):
        assert abs(result["betas"][key] - beta[key]) <= 0.1


# ---------- T013: 纯因子暴露与数据不足 ----------

def test_regress_pure_factor_exposure_has_no_alpha():
    factors = synthetic_factors()
    returns = synthetic_stock_returns(factors, beta=dict(DEFAULT_BETA),
                                      alpha_daily=0.0, resid_vol=0.01, seed=7)
    result = fama_macbeth.regress_one(factors, returns)
    assert result["status"] == "ok"
    # 双重硬门控下必须不满足"显著且经济"：IR 必然远小于 0.3（alpha≈0）
    assert result["information_ratio"] < 0.3


def test_regress_insufficient_data_returns_null_reason():
    factors = synthetic_factors(n_days=100)
    returns = synthetic_stock_returns(factors, alpha_daily=0.005, seed=7)
    result = fama_macbeth.regress_one(factors, returns)
    assert result["status"] == "insufficient_data"
    assert result["alpha"] is None
    assert result["reason"]


# ---------- T014: 无前视泄漏注入 ----------

def test_regress_no_lookahead_leak():
    factors = synthetic_factors()
    returns = synthetic_stock_returns(factors, alpha_daily=0.005, resid_vol=0.01, seed=7)
    analysis_date = "2026-01-15"
    clean = fama_macbeth.regress_one(factors, returns, analysis_date=analysis_date)

    # 污染未来数据：analysis_date 之后的因子值改成极端值（泄漏会把 beta/alpha 拉偏）
    future_mask = factors["date"].to_numpy() > analysis_date
    contaminated = factors.copy()
    contaminated.loc[future_mask, "MKT"] = 0.5
    contaminated.loc[future_mask, "SMB"] = -0.5
    leaked = fama_macbeth.regress_one(contaminated, returns, analysis_date=analysis_date)

    assert clean["status"] == "ok"
    assert leaked["status"] == "ok"
    assert leaked["alpha"] == clean["alpha"]
    assert leaked["betas"]["MKT"] == clean["betas"]["MKT"]
    assert leaked["window_end"] <= analysis_date


# ---------- T017 批量入口（配合 US3 集成的基础冒烟） ----------

def test_stage2_finite_estimates():
    """阶段二横截面 Fama-MacBeth：25 只合成股票面板 → lambda 均值/SE 有限。"""
    factors = synthetic_factors()
    n_stocks = 25
    panel_returns = {}
    panel_betas = {}
    for i in range(n_stocks):
        beta = {"MKT": 0.8 + 0.05 * (i % 5), "SMB": 0.3, "HML": 0.2, "MOM": 0.1}
        r = synthetic_stock_returns(factors, beta=beta, alpha_daily=0.002,
                                    resid_vol=0.02, seed=100 + i)
        r_excess = r - factors["rf"].to_numpy()
        panel_returns[f"S{i}"] = pd.Series(r_excess)
        panel_betas[f"S{i}"] = beta
    out = fama_macbeth.fama_macbeth_stage2(factors, panel_returns, panel_betas)
    assert out["n_periods"] == len(factors)
    for k in ("MKT", "SMB", "HML", "MOM"):
        assert out["lambda_mean"][k] is not None
        assert np.isfinite(out["lambda_mean"][k])
        assert out["lambda_se"][k] is not None


def test_run_all_synthetic_pool():
    factors = synthetic_factors()
    kline_returns = {}
    klines = {}
    seeds = [11, 21, 31]
    for i, seed in enumerate(seeds):
        code = f"TEST{i}"
        kline = synthetic_kline(seed=seed)
        returns = synthetic_stock_returns(factors, alpha_daily=0.004 + 0.0005 * i,
                                          resid_vol=0.01, seed=seed)
        kline_returns[code] = returns
        klines[code] = kline
    results = fama_macbeth.run_all(factors, klines, kline_returns)
    assert set(results.keys()) == {f"TEST{i}" for i in range(3)}
    for code, res in results.items():
        assert res["status"] in ("ok", "insufficient_data")
        if res["status"] == "ok":
            assert res["information_ratio"] >= 0.3  # 注入 alpha 显著（0.4%/0.45%/0.5%）
