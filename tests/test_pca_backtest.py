# -*- coding: utf-8 -*-
"""tests/test_pca_backtest.py —— A 股 PCA 复合因子多空投资组合回测测试套件

遵循 AGENTS.md 质量门禁体系与 BUG-0021 强断言规范（严禁裸 assertTrue / assertIsNotNone 等弱断言）。
覆盖以下核心契约：
1. 因子打分覆盖度 (>=290 标的) 与正态标准化分布 (mean ≈ 0, std ≈ 1，容差 10%);
2. 4 大宇宙周度多空回测执行、多空腿选股规模 (>=10 股/腿)、有限非 NaN 夏普比率及换手率合法区间 [0, 10];
3. 历年市场基准回归分解覆盖 2024、2025、2026 全部三个日历年且统计量有限有效;
4. 回测流水线产物（5 个 CSV 报表与 5 张出版级 PNG 图表）完整存在且文件大小合规。
"""

from __future__ import annotations

import math
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.pricing.pca_backtest import (
    BacktestResult,
    compute_alpha_composite_nale,
    compute_performance_metrics,
    decompose_annual_alpha_beta,
    load_and_align_datasets,
    run_pipeline,
    run_weekly_long_short_backtest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def loaded_data():
    """加载真实基准数据夹具。"""
    factors_df, csmar_panel, latest_mv = load_and_align_datasets()
    return factors_df, csmar_panel, latest_mv


@pytest.fixture(scope="module")
def factor_and_returns(loaded_data):
    """计算因子与日收益率矩阵夹具。"""
    factors_df, csmar_panel, _ = loaded_data
    alpha_series, returns_matrix = compute_alpha_composite_nale(
        factors_df=factors_df,
        csmar_panel=csmar_panel,
    )
    return alpha_series, returns_matrix


def test_factor_signal_coverage_and_distribution(factor_and_returns):
    """测试综合因子覆盖度 (>= 290 标的) 与截面均值/方差标准化属性。"""
    alpha_series, _ = factor_and_returns

    # 1. 标的覆盖度断言
    valid_count = int(alpha_series.notna().sum())
    assert valid_count >= 290
    assert valid_count <= 300
    assert len(alpha_series) == 299

    # 2. 均值归零断言 (容差 10%)
    mean_val = float(alpha_series.mean())
    assert abs(mean_val) < 0.10
    assert math.isfinite(mean_val)

    # 3. 标准差归一断言 (容差 10%)
    std_val = float(alpha_series.std(ddof=1))
    assert abs(std_val - 1.0) < 0.10
    assert math.isfinite(std_val)

    # 4. 无 Inf 与 NaN 残留断言
    assert int(np.isinf(alpha_series.values).sum()) == 0
    assert int(np.isnan(alpha_series.values).sum()) == 0


def test_full_universe_backtest_leg_sizes_and_returns(loaded_data, factor_and_returns):
    """测试全池回测持仓规模 (>= 10 股/腿)、收益率连续性与非 NaN 夏普比率。"""
    factors_df, csmar_panel, _ = loaded_data
    alpha_series, returns_matrix = factor_and_returns

    volume_matrix = csmar_panel.pivot(
        index="trade_date", columns="stock_code", values="volume"
    ).fillna(0.0)

    result = run_weekly_long_short_backtest(
        alpha_series=alpha_series,
        returns_df=returns_matrix,
        stock_metadata=factors_df,
        cohort="full",
        rebalance_freq=5,
        top_pct=0.2,
        bot_pct=0.2,
        volume_df=volume_matrix,
        transaction_cost=0.0,
    )

    # 1. 结果类型与宇宙标识
    assert result.universe == "full"
    assert len(result.daily_returns) == 644
    assert len(result.rebalance_dates) == 129

    # 2. 持仓股票数量断言 (全池每腿 >= 10 股)
    for reb_date in result.rebalance_dates:
        long_leg = result.long_holdings[reb_date]
        short_leg = result.short_holdings[reb_date]
        assert len(long_leg) >= 10
        assert len(short_leg) >= 10
        assert len(long_leg) <= 60
        assert len(short_leg) <= 60

    # 3. 绩效指标强断言
    metrics = compute_performance_metrics(result)
    assert metrics["universe"] == "full"
    assert math.isfinite(metrics["annualized_return"])
    assert metrics["annualized_volatility"] > 0.01
    assert metrics["annualized_volatility"] < 0.30
    assert math.isfinite(metrics["sharpe_ratio"])
    assert metrics["sharpe_ratio"] > -2.0
    assert metrics["sharpe_ratio"] < 2.0
    assert metrics["max_drawdown"] >= 0.0
    assert metrics["max_drawdown"] <= 1.0

    # 4. 年化换手率在合法区间 [0, 10]
    ann_to = metrics["annualized_turnover"]
    assert math.isfinite(ann_to)
    assert ann_to >= 0.0
    assert ann_to <= 10.0


def test_cohort_backtests_execution_and_metrics(loaded_data, factor_and_returns):
    """测试 A/B/C 三大子板块回测均成功执行且换手率与夏普比率合规。"""
    factors_df, csmar_panel, _ = loaded_data
    alpha_series, returns_matrix = factor_and_returns

    volume_matrix = csmar_panel.pivot(
        index="trade_date", columns="stock_code", values="volume"
    ).fillna(0.0)

    for cohort in ["student_A", "student_B", "student_C"]:
        res = run_weekly_long_short_backtest(
            alpha_series=alpha_series,
            returns_df=returns_matrix,
            stock_metadata=factors_df,
            cohort=cohort,
            rebalance_freq=5,
            top_pct=0.2,
            bot_pct=0.2,
            volume_df=volume_matrix,
            transaction_cost=0.0,
        )

        assert res.universe == cohort
        assert len(res.daily_returns) == 644

        # 检查每腿持仓数 (每组 100 股或 99 股的 20% 约为 20 股，均严格 >= 10)
        for reb_date in res.rebalance_dates:
            assert len(res.long_holdings[reb_date]) >= 10
            assert len(res.short_holdings[reb_date]) >= 10

        metrics = compute_performance_metrics(res)
        assert metrics["universe"] == cohort
        assert math.isfinite(metrics["annualized_return"])
        assert math.isfinite(metrics["sharpe_ratio"])
        assert metrics["annualized_volatility"] > 0.02
        assert metrics["annualized_volatility"] < 0.35
        assert metrics["max_drawdown"] > 0.0
        assert metrics["max_drawdown"] < 0.50
        assert metrics["annualized_turnover"] >= 0.0
        assert metrics["annualized_turnover"] <= 10.0


def test_annual_alpha_decomposition_covers_three_years(loaded_data, factor_and_returns):
    """测试分年度 Alpha/Beta 分解完整覆盖 2024、2025、2026 三年。"""
    factors_df, csmar_panel, _ = loaded_data
    alpha_series, returns_matrix = factor_and_returns

    res = run_weekly_long_short_backtest(
        alpha_series=alpha_series,
        returns_df=returns_matrix,
        stock_metadata=factors_df,
        cohort="full",
    )

    bench_series = returns_matrix[list(alpha_series.index)].mean(axis=1)
    decomp_df = decompose_annual_alpha_beta(
        portfolio_returns=res.daily_returns,
        benchmark_returns=bench_series,
    )

    # 1. 行数与年份覆盖断言
    assert len(decomp_df) == 3
    years_present = sorted(decomp_df["year"].astype(int).tolist())
    assert years_present == [2024, 2025, 2026]

    # 2. 回归字段完整性断言
    required_cols = ["year", "annual_alpha", "beta", "r_squared", "t_stat"]
    for col in required_cols:
        assert col in decomp_df.columns
        vals = decomp_df[col].tolist()
        assert len(vals) == 3
        for v in vals:
            assert math.isfinite(float(v))

    # 3. R² 在 [0, 1] 区间
    for r2 in decomp_df["r_squared"]:
        assert float(r2) >= 0.0
        assert float(r2) <= 1.0


def test_pipeline_output_artifacts_exist_and_valid():
    """测试流水线端到端生成的所有 5 个 CSV 报表与 5 张 PNG 图表物理存在且非空。"""
    # 确保流水线生成
    tables_dir = PROJECT_ROOT / "reports" / "tables" / "ashare_pca_backtest"
    figures_dir = PROJECT_ROOT / "reports" / "figures" / "ashare_pca_backtest"

    summary_file = tables_dir / "backtest_summary.csv"
    if not summary_file.exists():
        run_pipeline()

    # 1. 验证汇总表
    assert summary_file.exists()
    assert summary_file.stat().st_size > 100
    df_sum = pd.read_csv(summary_file)
    assert len(df_sum) == 4
    assert set(df_sum["universe"].tolist()) == {
        "full",
        "student_A",
        "student_B",
        "student_C",
    }
    for col in [
        "annualized_return",
        "annualized_volatility",
        "sharpe_ratio",
        "max_drawdown",
        "annualized_turnover",
        "calmar_ratio",
    ]:
        assert col in df_sum.columns
        for val in df_sum[col]:
            assert math.isfinite(float(val))

    # 2. 验证 4 个年度分解表
    for cohort in ["full", "student_a", "student_b", "student_c"]:
        csv_path = tables_dir / f"annual_alpha_{cohort}.csv"
        assert csv_path.exists()
        assert csv_path.stat().st_size > 80
        df_a = pd.read_csv(csv_path)
        assert len(df_a) == 3
        assert df_a["year"].tolist() == [2024, 2025, 2026]

    # 3. 验证 5 张 PNG 图表
    expected_figures = [
        "full_pnl.png",
        "student_a_pnl.png",
        "student_b_pnl.png",
        "student_c_pnl.png",
        "combined_pnl.png",
    ]
    for fig_name in expected_figures:
        fig_path = figures_dir / fig_name
        assert fig_path.exists()
        assert fig_path.stat().st_size > 50000  # 高清图表文件大小均大于 50KB
