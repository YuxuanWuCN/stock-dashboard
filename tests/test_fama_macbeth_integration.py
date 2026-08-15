# tests/test_fama_macbeth_integration.py —— Alpha 门控接入集成测试（spec-kit 003 / US3）
#
# 覆盖（对应 spec US3 / FR-006/007/011）：
#   - 门控判定：True Alpha（p<0.05 且 IR>=0.3）才 pass，拒绝原因枚举正确
#   - 候选选择：候选 = 原候选 ∩ pass 集合；不足 min_size 回退 + fallback 标记
#   - 汇总：passed_count / aggressive_candidates / 阈值透传
#   - 因子库不可用 → 诚实降级为 data_unavailable，不伪造 pass

import os
import sys
from pathlib import Path

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "src"))
sys.path.insert(0, _REPO)

from tests.test_fama_macbeth import (  # noqa: E402
    DEFAULT_BETA,
    synthetic_factors,
    synthetic_kline,
    synthetic_stock_returns,
)
from analysis import alpha_gate, factor_db, fama_macbeth  # noqa: E402


def _build_pool(n_stocks=8, alpha_stocks=3, seed_base=51):
    """构造合成股票池：前 alpha_stocks 只有真实 alpha（0.5%/日），其余纯因子暴露。"""
    factors = synthetic_factors()
    klines = {}
    returns = {}
    for i in range(n_stocks):
        code = f"T{i:03d}"
        klines[code] = synthetic_kline(seed=11 + i)
        returns[code] = synthetic_stock_returns(
            factors,
            beta=dict(DEFAULT_BETA),
            alpha_daily=0.005 if i < alpha_stocks else 0.0,
            resid_vol=0.01,
            seed=seed_base + i,
        )
    return factors, klines, returns


def _ranked_items(n_stocks=8):
    return [{"code": f"T{i:03d}", "rank": i + 1, "name": f"测试{i}"} for i in range(n_stocks)]


def _gates(factors, klines, returns):
    results = fama_macbeth.run_all(factors, klines, returns_by_code=returns)
    return {code: alpha_gate.evaluate_gate(res) for code, res in results.items()}


# ---------- T018: 门控流水线集成 ----------

def test_gate_pipeline_pass_and_reject():
    factors, klines, returns = _build_pool(alpha_stocks=3)
    gates = _gates(factors, klines, returns)
    passed = [c for c, g in gates.items() if g["verdict"] == "pass"]
    assert len(passed) == 3
    for c in passed:
        assert gates[c]["reject_reason"] is None
        assert gates[c]["alpha_p_value"] < 0.05
        assert gates[c]["information_ratio"] >= 0.3
        assert gates[c]["alpha"] is not None
    for c, g in gates.items():
        if g["verdict"] == "reject":
            assert g["reject_reason"] in (
                "statistical", "economical", "insufficient_data", "data_unavailable",
            )
            if g["reject_reason"] == "insufficient_data":
                assert g["alpha"] is None and g["information_ratio"] is None


def test_select_gated_candidates_intersection():
    """候选 = 原候选 ∩ 通过门控集合（US3 验收 1）；通过数足够时无回退。"""
    factors, klines, returns = _build_pool(alpha_stocks=6)  # 6 >= min_size 5
    gates = _gates(factors, klines, returns)
    items = _ranked_items()
    selected, fallback = alpha_gate.select_gated_candidates(items, gates, top_n=8, min_size=5)
    assert not fallback
    assert len(selected) == 6
    assert all(gates[it["code"]]["verdict"] == "pass" for it in selected)
    expected = [it for it in items if gates[it["code"]]["verdict"] == "pass"]
    assert [it["code"] for it in selected] == [it["code"] for it in expected]


# ---------- T019: 降级策略 ----------

def test_select_gated_candidates_fallback_when_none_pass():
    """全池 reject → 按原机会分回退补齐 + fallback 标记，不产生空组合（US3 验收 2 / FR-011）。"""
    factors, klines, returns = _build_pool(alpha_stocks=0)
    gates = _gates(factors, klines, returns)
    assert all(g["verdict"] == "reject" for g in gates.values())
    items = _ranked_items()
    selected, fallback = alpha_gate.select_gated_candidates(items, gates, top_n=8, min_size=5)
    assert fallback is True
    assert len(selected) == 8
    assert [it["code"] for it in selected] == [it["code"] for it in items]


def test_gate_summary_fields():
    """通过数足够（6 >= min_size 5）→ 无回退，候选为全部通过者。"""
    factors, klines, returns = _build_pool(alpha_stocks=6)
    gates = _gates(factors, klines, returns)
    items = [dict(it, alpha_gate=gates[it["code"]]) for it in _ranked_items()]
    summary = alpha_gate.gate_summary(items, min_size=5, top_n=8)
    assert summary["passed_count"] == 6
    assert summary["fallback_applied"] is False
    assert set(summary["aggressive_candidates"]) == {
        "T000", "T001", "T002", "T003", "T004", "T005",
    }
    assert summary["thresholds"]["alpha_p_threshold"] == 0.05
    assert summary["thresholds"]["ir_threshold"] == 0.3


def test_gate_summary_fallback_flag_when_insufficient_pass():
    factors, klines, returns = _build_pool(alpha_stocks=1)
    gates = _gates(factors, klines, returns)
    items = [dict(it, alpha_gate=gates[it["code"]]) for it in _ranked_items()]
    summary = alpha_gate.gate_summary(items, min_size=5, top_n=8)
    assert summary["passed_count"] == 1
    assert summary["fallback_applied"] is True


# ---------- 边界：数据不可用 ----------

def test_evaluate_gate_insufficient_and_unavailable():
    insuff = {"status": "insufficient_data", "reason": "有效观测不足", "window_end": "2026-01-01"}
    g = alpha_gate.evaluate_gate(insuff)
    assert g["verdict"] == "reject"
    assert g["reject_reason"] == "insufficient_data"
    assert g["alpha"] is None and g["information_ratio"] is None

    failed = {"status": "failed"}
    g2 = alpha_gate.evaluate_gate(failed)
    assert g2["verdict"] == "reject"
    assert g2["reject_reason"] == "data_unavailable"


def test_run_alpha_gate_without_factor_db(monkeypatch):
    """因子库不可用 → 全部 data_unavailable，诚实降级而非伪造 pass。"""
    monkeypatch.setattr(alpha_gate, "_load_factors", lambda: None)
    klines = {f"T{i:03d}": synthetic_kline(seed=11 + i) for i in range(3)}
    gates = alpha_gate.run_alpha_gate(klines)
    assert len(gates) == 3
    assert all(g["verdict"] == "reject" and g["reject_reason"] == "data_unavailable"
               for g in gates.values())


def test_schema_validate_alpha_gate_contract():
    """alpha_gate 字段组 schema 校验（pass/reject 契约规则）。"""
    from analysis.schema import _validate_alpha_gate

    good = {
        "verdict": "pass", "reject_reason": None, "alpha": 0.005,
        "alpha_p_value": 0.01, "information_ratio": 0.5,
        "betas": {"MKT": 1.0, "SMB": 0.3, "HML": 0.2, "MOM": 0.1},
        "window_end": "2026-05-28",
    }
    assert _validate_alpha_gate(good, "g") == []

    bad_reason = dict(good, verdict="reject", reject_reason="weird")
    assert any("reject_reason" in e for e in _validate_alpha_gate(bad_reason, "g"))

    insuff_bad = dict(good, verdict="reject", reject_reason="insufficient_data")
    assert any("应为 null" in e for e in _validate_alpha_gate(insuff_bad, "g"))

    p_out_of_range = dict(good, alpha_p_value=1.5)
    assert any("越界" in e for e in _validate_alpha_gate(p_out_of_range, "g"))

    pass_with_reason = dict(good, reject_reason="statistical")
    assert any("pass 时应为 null" in e for e in _validate_alpha_gate(pass_with_reason, "g"))


def test_load_factors_real_db(tmp_path, monkeypatch):
    """_load_factors 真实路径：库存在 → 返回全量因子序列。"""
    from tests.test_fama_macbeth import csv_text, synthetic_factors

    df = synthetic_factors()
    db = str(tmp_path / "f.db")
    factor_db.import_to_db(csv_text(df), db_path=db)
    monkeypatch.setattr(alpha_gate.factor_db, "default_db_path", lambda: Path(db))
    loaded = alpha_gate._load_factors()
    assert loaded is not None
    assert len(loaded) == len(df)


def test_load_factors_missing_db_returns_none(tmp_path, monkeypatch):
    """_load_factors 库不存在 → None（诚实降级分支）。"""
    monkeypatch.setattr(
        alpha_gate.factor_db, "default_db_path",
        lambda: Path(str(tmp_path / "nope.db")),
    )
    assert alpha_gate._load_factors() is None


def test_run_alpha_gate_loads_from_db(tmp_path, monkeypatch):
    """run_alpha_gate 缺省加载因子库路径。"""
    from tests.test_fama_macbeth import csv_text, synthetic_factors

    df = synthetic_factors()
    db = str(tmp_path / "f.db")
    factor_db.import_to_db(csv_text(df), db_path=db)
    monkeypatch.setattr(alpha_gate.factor_db, "default_db_path", lambda: Path(db))
    klines = {"T000": synthetic_kline()}
    gates = alpha_gate.run_alpha_gate(klines)
    assert "T000" in gates
    assert gates["T000"]["verdict"] in ("pass", "reject")


def test_run_alpha_gate_with_factors():
    factors, klines, returns = _build_pool(alpha_stocks=2)
    gates = alpha_gate.run_alpha_gate(klines, factors_df=factors, returns_by_code=returns)
    assert len(gates) == 8
    assert sum(1 for g in gates.values() if g["verdict"] == "pass") == 2
