"""tests/test_constraints.py —— 组合约束监管（005 融合 US5）单元测试。"""

from src.analysis.constraints import apply_constraints


def test_single_position_truncated_to_limit():
    """单标的 60% 权重被截断到 20% 上限并记录理由。"""
    cands = [
        {"code": "A", "weight": 0.60},
        {"code": "B", "weight": 0.10},
        {"code": "C", "weight": 0.10},
    ]
    r = apply_constraints(cands)
    by_code = {i["code"]: i for i in r["adjusted"]}
    assert by_code["A"]["weight"] == 0.20
    assert by_code["A"].get("_truncated") is True
    assert any(v["type"] == "single_position" and v["code"] == "A" for v in r["violations"])


def test_industry_concentration_flagged():
    """行业集中度超限 → 该行业标的被标记。"""
    cands = [
        {"code": "A", "weight": 0.15},
        {"code": "B", "weight": 0.15},
        {"code": "C", "weight": 0.15},
        {"code": "D", "weight": 0.10},
    ]
    ind = {"A": "半导体", "B": "半导体", "C": "半导体", "D": "白酒"}
    r = apply_constraints(cands, industry_of=ind)
    flagged = [i["code"] for i in r["adjusted"] if i.get("_flagged")]
    assert "A" in flagged and "B" in flagged and "C" in flagged
    assert "D" not in flagged
    assert any(v["type"] == "industry_concentration" for v in r["violations"])


def test_all_pass_no_side_effects():
    """全部约束通过时无违规、无标记。"""
    cands = [
        {"code": "A", "weight": 0.10},
        {"code": "B", "weight": 0.10},
        {"code": "C", "weight": 0.10},
        {"code": "D", "weight": 0.10},
    ]
    ind = {"A": "白酒", "B": "银行", "C": "科技", "D": "医药"}
    r = apply_constraints(cands, industry_of=ind)
    assert r["violations"] == []
    for i in r["adjusted"]:
        assert "_flagged" not in i
        assert "_truncated" not in i


def test_valuation_and_liquidity_flagged():
    """估值分位/流动性超限被标记。"""
    cands = [{"code": "X", "weight": 0.10}, {"code": "Y", "weight": 0.10}]
    r = apply_constraints(
        cands,
        constraints={"max_valuation_percentile": 0.90, "min_daily_liquidity": 1e8},
        valuation_pct_of={"X": 0.99, "Y": 0.50},
        liquidity_of={"X": 5e7, "Y": 2e8},
    )
    by_code = {i["code"]: i for i in r["adjusted"]}
    assert by_code["X"].get("_flagged") is True
    assert any(v["type"] == "valuation" for v in r["violations"])
    assert any(v["type"] == "liquidity" for v in r["violations"])
