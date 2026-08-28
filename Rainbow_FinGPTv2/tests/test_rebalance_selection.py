# tests/test_rebalance_selection.py —— 稳健组合选股字段修复回归测试（spec-kit 004b）
#
# 守护修复：嵌套字段 risk.score / total_score 的正确读取，
# 防止再次误读不存在的顶层 risk_score / score。

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO / "tools"))

import rebalance_all_portfolios as rab


def _item(code, risk_score, up3, total_score, name="X"):
    """构造排行榜条目：嵌套 risk.score + 顶层 total_score（与 ranking.json 一致）。"""
    return {
        "code": code,
        "name": name,
        "risk": {"score": risk_score, "level": "low", "label": "低风险"},
        "forecast": {"up_probability_3d_pct": up3},
        "total_score": total_score,
    }


def test_robust_candidates_filters_and_sorts():
    ranking = [
        _item("A", risk_score=20, up3=70, total_score=80),
        _item("B", risk_score=25, up3=63, total_score=90),
        _item("C", risk_score=45, up3=70, total_score=99),  # 风险过高 → 排除
        _item("D", risk_score=15, up3=50, total_score=88),  # 概率过低 → 排除
        _item("E", risk_score=30, up3=65, total_score=70),
    ]
    candidates = rab.robust_candidates(ranking)
    assert [c["code"] for c in candidates] == ["B", "A", "E"]  # 按综合分降序
    assert candidates[0]["score"] == 90
    assert candidates[0]["risk"] == 25


def test_robust_candidates_reads_nested_risk_score():
    """核心回归：条目没有顶层 risk_score，只有嵌套 risk.score，必须能正确过滤。"""
    ranking = [
        _item("GOOD", risk_score=30, up3=80, total_score=75),
        _item("BAD", risk_score=55, up3=80, total_score=95),  # 风险 55 应被排除
    ]
    candidates = rab.robust_candidates(ranking)
    assert [c["code"] for c in candidates] == ["GOOD"]


def test_robust_candidates_empty_when_nothing_passes():
    ranking = [_item("X", risk_score=60, up3=90, total_score=50)]
    assert rab.robust_candidates(ranking) == []


def test_robust_candidates_missing_risk_block_defaults_high():
    """缺少 risk 块 → 默认风险 100 → 被排除（不误选）。"""
    item = {"code": "N", "name": "n", "forecast": {"up_probability_3d_pct": 90}, "total_score": 80}
    assert rab.robust_candidates([item]) == []
