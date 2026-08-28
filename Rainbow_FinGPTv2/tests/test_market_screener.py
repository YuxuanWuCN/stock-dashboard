# -*- coding: utf-8 -*-
"""tests/test_market_screener.py —— 全市场轻量级两级初筛模块单元测试"""

from pathlib import Path
import pandas as pd
import pytest

from src.analysis.market_screener import (
    fetch_market_snapshot,
    screen_active_stocks,
    merge_with_core_watchlist,
)


@pytest.fixture
def sample_snapshot_df() -> pd.DataFrame:
    return pd.DataFrame({
        "代码": ["688525", "300750", "000001", "600519", "002594", "600999", "000002"],
        "名称": ["佰维存储", "宁德时代", "*ST平银", "贵州茅台", "比亚迪", "ST华安", "万科A"],
        "成交额": [8.5e8, 35e8, 5.0e8, 45e8, 22e8, 4.0e8, 1.2e8],
        "涨跌幅": [5.2, 3.1, -5.0, 1.2, 2.8, 1.0, -4.5],
        "换手率": [6.5, 2.8, 4.0, 0.4, 2.1, 3.5, 0.8],
        "总市值": [3e10, 8e11, 2e11, 2e12, 7e11, 1e10, 9e10],
    })


def test_screen_active_stocks_filters_st_and_low_liquidity(sample_snapshot_df):
    """测试过滤 ST 股票、低流动性以及暴跌破位标的。"""
    active = screen_active_stocks(
        df_snapshot=sample_snapshot_df,
        min_amount=3e8,
        min_turnover=2.0,
        min_market_cap=5e9,
        filter_st=True,
        max_candidates=10,
    )

    codes = active["code"].tolist()
    names = active["name"].tolist()

    # 1. 验证 ST 股票被彻底剔除
    assert "*ST平银" not in names
    assert "ST华安" not in names

    # 2. 验证低流动性/低换手标的被剔除 (茅台换手 0.4% < 2.0%, 万科成交 1.2亿 < 3亿)
    assert "贵州茅台" not in names
    assert "万科A" not in names

    # 3. 验证高流动性优质标的入选
    assert "688525" in codes
    assert "300750" in codes
    assert "002594" in codes


def test_screen_active_stocks_empty_snapshot():
    """测试空快照输入时的防御健壮性。"""
    empty_df = pd.DataFrame()
    res = screen_active_stocks(empty_df)
    assert isinstance(res, pd.DataFrame)
    assert res.empty
    assert "code" in res.columns


def test_screen_active_stocks_ranking_order(sample_snapshot_df):
    """测试按成交额与动量综合打分排序。"""
    active = screen_active_stocks(
        df_snapshot=sample_snapshot_df,
        min_amount=1e8,
        min_turnover=1.0,
        min_market_cap=1e9,
        max_candidates=3,
    )
    assert len(active) <= 3
    # 榜首应该具有极高综合动量与成交额
    assert active.iloc[0]["code"] in ["688525", "300750", "002594"]


def test_merge_with_core_watchlist(tmp_path, sample_snapshot_df):
    """测试核心自选池与全市场动态筛选池的无缝合并与去重。"""
    core_csv = tmp_path / "core_watchlist.csv"
    core_csv.write_text("code,name,type,category\n300750,宁德时代,stock,新能源\n688525,佰维存储,stock,科技\n", encoding="utf-8")

    active = screen_active_stocks(sample_snapshot_df, min_amount=1e8, min_turnover=1.0)
    out_csv = tmp_path / "dynamic_watchlist.csv"

    merged = merge_with_core_watchlist(core_csv, active, output_path=out_csv)

    # 验证去重：宁德时代和佰维存储在两者都存在，但只保留一条，且优先保留核心自选分类
    assert len(merged[merged["code"] == "300750"]) == 1
    assert merged[merged["code"] == "300750"]["category"].values[0] == "新能源"

    # 验证新标的成功加入
    assert "002594" in merged["code"].values
    assert out_csv.exists()
