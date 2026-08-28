"""用户 PDF 财务周期框架的离线规则测试。"""

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.analysis.fundamental import (
    FundamentalAnalyzer,
    judge_cycle,
    score_asset_quality,
    score_cash_health,
    score_liability_safety,
)


def make_metrics(**overrides):
    """构造评分函数所需的最小财务指标对象。"""
    values = {
        "total_assets_yoy": None,
        "inventory_prepay_ratio": None,
        "receivable_revenue": None,
        "goodwill_equity": None,
        "debt_ratio": None,
        "short_debt_ratio": None,
        "debt_ratio_prev": None,
        "roe": None,
        "netprofit_yoy": None,
        "deduct_ratio": None,
        "gross_margin": None,
        "retained_profit_equity": None,
        "ocf_np_ratio": None,
        "financing_debt": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_cycle_has_expansion_contraction_neutral_and_unknown_states():
    expansion, expansion_return, expansion_days = judge_cycle(
        pd.Series(np.linspace(100, 104, 60))
    )
    contraction, contraction_return, contraction_days = judge_cycle(
        pd.Series(np.linspace(100, 96, 60))
    )
    neutral, neutral_return, neutral_days = judge_cycle(
        pd.Series(np.linspace(100, 101, 60))
    )
    unknown, unknown_return, unknown_days = judge_cycle(pd.Series([100, 101]))

    assert (expansion, expansion_days) == ("expansion", 60)
    assert expansion_return is not None and expansion_return > 3.0
    assert (contraction, contraction_days) == ("contraction", 60)
    assert contraction_return is not None and contraction_return < -3.0
    assert (neutral, neutral_days) == ("neutral", 60)
    assert neutral_return is not None and -3.0 < neutral_return < 3.0
    assert (unknown, unknown_return, unknown_days) == ("unknown", None, 2)


def test_high_inventory_reserve_changes_meaning_with_verified_cycle():
    metrics = make_metrics(inventory_prepay_ratio=0.60)

    expansion = score_asset_quality(metrics, "expansion")
    contraction = score_asset_quality(metrics, "contraction")
    unknown = score_asset_quality(metrics, "unknown")

    assert expansion["score"] > unknown["score"] > contraction["score"]
    assert expansion["reasons"][0]["title"] == "顺周期战略储备"
    assert contraction["reasons"][0]["title"] == "收缩期高周期敞口"
    assert unknown["reasons"][0]["contribution"] == 0.0


def test_worsening_working_capital_and_liquidity_metrics_reduce_scores():
    low_receivable = score_asset_quality(
        make_metrics(receivable_revenue=0.30), "neutral"
    )
    high_receivable = score_asset_quality(
        make_metrics(receivable_revenue=0.60), "neutral"
    )
    low_debt = score_liability_safety(make_metrics(debt_ratio=0.40))
    high_debt = score_liability_safety(make_metrics(debt_ratio=0.70))
    strong_cash = score_cash_health(make_metrics(ocf_np_ratio=1.0))
    weak_cash = score_cash_health(make_metrics(ocf_np_ratio=0.0))

    assert high_receivable["score"] < low_receivable["score"]
    assert high_debt["score"] < low_debt["score"]
    assert weak_cash["score"] < strong_cash["score"]


def test_financial_institutions_do_not_use_inventory_cycle_model():
    analyzer = FundamentalAnalyzer()
    with patch("src.analysis.fundamental.fetch_balance_sheet") as fetch_balance:
        result = analyzer.analyze("600036", "招商银行", category="银行")

    assert result is None
    fetch_balance.assert_not_called()
