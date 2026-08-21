"""tests/test_thesis.py —— 信念-执行分离（005 融合 US4）单元测试。"""

from src.analysis.thesis import Holdings, Thesis


def test_price_move_updates_holdings_but_not_thesis():
    """价格下跌只更新盯市，信念内容与状态不变。"""
    thesis = Thesis(
        code="600519", name="贵州茅台",
        core_logic="批价企稳 + 渠道库存去化",
        expectation_gap="市场担心需求，实际动销超预期",
        invalidation_conditions=["批价跌破 2000", "渠道库存超 3 个月"],
    )
    holdings = Holdings(code="600519", quantity=100, avg_cost=1500.0, last_price=1600.0)

    before = thesis.to_dict()
    result = holdings.mark_to_market(price=1400.0)

    assert holdings.market_value == 100 * 1400.0
    assert holdings.unrealized_pnl_pct is not None
    # 信念未被价格波动改写
    assert thesis.to_dict()["core_logic"] == before["core_logic"]
    assert thesis.to_dict()["status"] == "valid"
    assert result["market_value"] == 140000.0


def test_invalidation_condition_triggers_review():
    """失效条件被触发 → thesis 转 invalid（信念再验证）。"""
    thesis = Thesis(
        code="002415", core_logic="订单饱满",
        invalidation_conditions=["大客户砍单"],
    )
    res = thesis.revalidate(triggered_conditions=["大客户砍单"])
    assert res["status"] == "invalid"
    assert res["thesis_unchanged"] is False
    assert thesis.status == "invalid"
    assert len(thesis.history) == 1


def test_price_move_alone_never_invalidates_thesis():
    """仅价格波动（无失效条件）不触发信念改写。"""
    thesis = Thesis(code="NVDA", core_logic="AI 算力需求", invalidation_conditions=["需求证伪"])
    res = thesis.revalidate(triggered_conditions=[])
    assert res["status"] == "valid"
    assert res["thesis_unchanged"] is True


def test_thesis_and_holdings_are_independent_entities():
    """新建标的可只有信念没有持仓，互不报错。"""
    thesis = Thesis(code="300750", name="宁德时代", core_logic="储能放量")
    assert thesis.to_dict()["status"] == "valid"
    # 无 holdings 时 thesis 独立存在
    assert thesis.to_dict()["code"] == "300750"
