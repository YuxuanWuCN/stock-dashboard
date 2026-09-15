# -*- coding: utf-8 -*-
"""tests/test_grs_and_high_dim_report.py

针对 768 维高维资产定价回归引擎与学术报告的专项测试套件：
1. Gibbons-Ross-Shanken (GRS 1989) 联合截距 F 检验数学性质与边界条件
2. 动态显著性评估契约（拒绝假性显著性声明，严格保持统计一致性）
3. 全量 768 维截面 Ridge 顶层因子重要度排序与稳健收敛
4. 回归流水线 5 大核心产物完整性与报告零矛盾一致性检验
"""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]

from scripts.run_768d_high_dimensional_regression import (
    compute_grs_test,
    get_dynamic_sig_label,
    run_ridge_high_dim_cross_sectional,
    generate_academic_markdown_report,
)


class TestGRSJointFTest:
    """Gibbons-Ross-Shanken (GRS 1989) 联合截距 F 检验测试。"""

    def test_grs_zero_alpha_produces_zero_statistic(self):
        """验证当所有资产真实定价误差 alpha 全为 0 时，GRS 统计量精确为 0，p 值为 1.0。"""
        rng = np.random.default_rng(42)
        T, N, K = 200, 20, 3
        df_returns = pd.DataFrame(rng.normal(0, 0.02, (T, N)), columns=[f"S{i}" for i in range(N)])
        factors_mat = rng.normal(0, 0.01, (T, K))
        alphas = np.zeros(N)

        res = compute_grs_test(df_returns, factors_mat, alphas)
        assert res["grs_stat"] == pytest.approx(0.0, abs=1e-12)
        assert res["p_value"] == pytest.approx(1.0, abs=1e-6)
        assert res["df1"] == N
        assert res["df2"] == T - N - K

    def test_grs_nonzero_alpha_produces_positive_statistic(self):
        """验证存在非零定价误差时，GRS 统计量为正，且显著拒绝原假设。"""
        rng = np.random.default_rng(42)
        T, N, K = 300, 15, 2
        df_returns = pd.DataFrame(rng.normal(0.05, 0.02, (T, N)), columns=[f"S{i}" for i in range(N)])
        factors_mat = rng.normal(0.01, 0.01, (T, K))
        alphas = np.full(N, 0.05)

        res = compute_grs_test(df_returns, factors_mat, alphas)
        assert res["grs_stat"] > 0.0
        assert res["p_value"] < 0.01
        assert res["alpha_quad"] > 0.0
        assert res["factor_quad"] >= 0.0

    def test_grs_insufficient_degrees_of_freedom_graceful_handling(self):
        """验证当样本期数 T <= N + K 时，GRS 检验优雅返回 NaN 而非崩溃。"""
        rng = np.random.default_rng(42)
        T, N, K = 25, 20, 10  # T < N + K (25 < 30)
        df_returns = pd.DataFrame(rng.normal(0, 0.02, (T, N)), columns=[f"S{i}" for i in range(N)])
        factors_mat = rng.normal(0, 0.01, (T, K))
        alphas = rng.normal(0, 0.01, N)

        res = compute_grs_test(df_returns, factors_mat, alphas)
        assert np.isnan(res["grs_stat"])
        assert np.isnan(res["p_value"])
        assert res["df2"] < 0

    def test_grs_monotonicity_with_alpha_scale(self):
        """验证随着 Alpha 定价误差尺度放大，GRS 统计量单调放大。"""
        rng = np.random.default_rng(123)
        T, N, K = 200, 10, 2
        df_returns = pd.DataFrame(rng.normal(0, 0.02, (T, N)), columns=[f"S{i}" for i in range(N)])
        factors_mat = rng.normal(0.005, 0.01, (T, K))

        alphas_small = np.full(N, 0.001)
        alphas_large = np.full(N, 0.01)

        res_small = compute_grs_test(df_returns, factors_mat, alphas_small)
        res_large = compute_grs_test(df_returns, factors_mat, alphas_large)

        assert res_large["grs_stat"] > res_small["grs_stat"]


class TestDynamicSignificance:
    """动态显著性评估契约测试。"""

    def test_dynamic_sig_label_threshold(self):
        """验证 |t| > 1.96 判为显著，|t| <= 1.96 判为未达显著水平。"""
        assert "显著" in get_dynamic_sig_label(2.05)
        assert "显著" in get_dynamic_sig_label(-2.05)
        assert "未达" in get_dynamic_sig_label(0.52)
        assert "未达" in get_dynamic_sig_label(-0.52)
        assert "未达" in get_dynamic_sig_label(1.95)
        assert "未达" in get_dynamic_sig_label(-1.96)
        assert get_dynamic_sig_label(np.nan) == "N/A"


class TestDeliverablesAndConsistency:
    """回归流水线产物与报告一致性校验。"""

    def test_all_five_deliverables_exist(self):
        """验证 M2 所要求的 5 项产物及辅助表全量就绪。"""
        dir_path = ROOT_DIR / "reports/tables/regression_768d"
        assert (dir_path / "pca_768d_explained_variance.csv").exists()
        assert (dir_path / "stage1_time_series_regression_summary.csv").exists()
        assert (dir_path / "stage1_stock_betas_768d.csv").exists()
        assert (dir_path / "stage2_factor_premia_768d.csv").exists()
        assert (dir_path / "ridge_cross_sectional_top_factors.csv").exists()
        assert (dir_path / "model_comparison_baseline_vs_768d.csv").exists()
        assert (dir_path / "high_dim_regression_report.md").exists()

    def test_ridge_top_factors_csv_schema_and_ordering(self):
        """验证 ridge_cross_sectional_top_factors.csv 包含 768 个维度且按绝对值降序排列。"""
        csv_path = ROOT_DIR / "reports/tables/regression_768d/ridge_cross_sectional_top_factors.csv"
        df = pd.read_csv(csv_path)
        assert len(df) == 768
        assert "feature" in df.columns
        assert "rank" in df.columns
        assert "abs_mean_coefficient" in df.columns
        assert (df["abs_mean_coefficient"].diff().dropna() <= 1e-10).all()

    def test_report_and_csv_zero_contradiction(self):
        """严格核验学术报告与底层 CSV 结果零矛盾。"""
        dir_path = ROOT_DIR / "reports/tables/regression_768d"
        df_premia = pd.read_csv(dir_path / "stage2_factor_premia_768d.csv")
        report_text = (dir_path / "high_dim_regression_report.md").read_text(encoding="utf-8")

        pc5_row = df_premia[df_premia["Factor"] == "PC5"].iloc[0]
        pc5_t = pc5_row["t_statistic"]
        pc5_sig = pc5_row["Significant_5pct"]

        # 1. 报告必须包含准确的 t 统计量
        assert f"{pc5_t:.2f}" in report_text

        # 2. 当 |t| <= 1.96 时，报告绝对不得宣称"高度显著"
        if abs(pc5_t) <= 1.96:
            assert pc5_sig == "NO"
            assert "高度显著 ($|t| > 1.96$)" not in report_text
            assert "未达 5% 显著水平" in report_text

        # 3. 报告必须包含 GRS 检验章节
        assert "Gibbons-Ross-Shanken (GRS 1989)" in report_text
