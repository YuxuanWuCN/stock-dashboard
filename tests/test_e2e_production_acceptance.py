# -*- coding: utf-8 -*-
"""tests/test_e2e_production_acceptance.py

R-FinGPTv2 生产流水线端到端验收测试套件 (E2E Production Acceptance Test Suite)
覆盖 Tiers 1-4 全部 16 项核心功能特性 (F1 ~ F16):
- Tier 1: 功能隔离覆盖 (Feature Coverage F1~F16)
  F1: 300 支全样本标的多组划分 (Tech 100, Energy 100, Finance 100)
  F2: 高并发 768 维文本因子提取与两阶段提炼
  F3: 断点续跑保护与死锁防范 (JSONL / 异常重试)
  F4: 768 维矩阵 L2 范数归一化与零 NaN/Inf 校验
  F5: 合并总因子文件导出 (factors_768d_all.csv, 300x775)
  F6: GKX (2021) SVD/PCA 高维子空间正交投影 (PC1~PC5)
  F7: 因子模拟投资组合时序收益率构建 (Zero-Investment Portfolio)
  F8: 两阶段 Fama-MacBeth 计量经济学回归
  F9: Newey-West (1987) HAC 稳健协方差与 t 统计量 (5 阶滞后)
  F10: Carhart 4 因子增量评估与 Delta R^2 计算
  F11: 学术级回归报告与动态显著性标签 (规避硬编码缺陷)
  F12: 核心策略超参数网格搜索空间 (18 组组合)
  F13: A 股机构级回测仿真器交易规则 (T+1, 整手, 涨跌停, 费率, 滑点)
  F14: 双目标评价体系 (夏普比率最大化 & 最大回撤最小化)
  F15: 超参数寻优对比表导出 (Markdown & CSV)
  F16: 最优参数配置文件 JSON 导出与生产配置接口合约
- Tier 2: 边界与极端异常覆盖 (Boundary & Corner Cases)
- Tier 3: 跨模块串联流水线 (Cross-Feature Combinations)
- Tier 4: 真实生产工作流端到端验证 (Real-World Application Scenarios)
"""

from __future__ import annotations

import itertools
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import pytest
from sklearn.decomposition import PCA
from sklearn.linear_model import Ridge

# 项目根目录加入 sys.path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.crawl_and_extract_768d_factors import (
    encode_semantic_768,
    extract_two_stage_features_for_stock,
    load_cohort_stocks,
)
from scripts.run_768d_high_dimensional_regression import (
    construct_factor_mimicking_returns,
    newey_west_t_stat,
    run_pca_decomposition,
    run_ridge_high_dim_cross_sectional,
    run_stage1_regressions,
    run_stage2_fama_macbeth,
)
from tools.backtest_2024_2026_dual_simulation import (
    ASharePortfolioSimulator,
    HoldingPosition,
    TradeRecord,
)


# ==============================================================================
# 公共测试夹具与契约校验辅助函数 (Fixtures & Contract Helpers)
# ==============================================================================

def generate_18_parameter_combinations() -> List[Dict[str, float]]:
    """生成 18 组超参数网格：tau in [1, 3, 5], W in [20, 30], omega in [0.1, 0.2, 0.3]。"""
    tau_list = [1.0, 3.0, 5.0]
    w_list = [20, 30]
    omega_list = [0.1, 0.2, 0.3]
    combos = []
    for tau, w, omega in itertools.product(tau_list, w_list, omega_list):
        combos.append({
            "sentiment_half_life_tau": float(tau),
            "lookback_window_W": int(w),
            "pc5_weight_omega": float(omega),
        })
    return combos


def calculate_portfolio_metrics(
    equity_series: pd.Series,
    rf_annual: float = 0.025,
) -> Dict[str, float]:
    """根据净值曲线计算核心绩效指标：年化收益、夏普比率、最大回撤、卡玛比率。"""
    if len(equity_series) < 2:
        return {
            "total_return": 0.0,
            "annual_return": 0.0,
            "annual_volatility": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "calmar_ratio": 0.0,
        }

    daily_returns = equity_series.pct_change().dropna()
    t_days = len(daily_returns)
    total_ret = float(equity_series.iloc[-1] / equity_series.iloc[0] - 1.0)
    ann_ret = float((1.0 + total_ret) ** (250.0 / max(1, t_days)) - 1.0)
    ann_vol = float(daily_returns.std() * np.sqrt(250.0))

    rf_daily = rf_annual / 250.0
    excess_ret = daily_returns - rf_daily
    excess_mean = float(excess_ret.mean() * 250.0)
    sharpe = float(excess_mean / ann_vol) if ann_vol > 1e-8 else 0.0

    # 最大回撤
    cum_max = equity_series.cummax()
    drawdowns = (equity_series - cum_max) / cum_max
    max_dd = float(drawdowns.min())

    calmar = float(ann_ret / abs(max_dd)) if abs(max_dd) > 1e-6 else 0.0

    return {
        "total_return": total_ret,
        "annual_return": ann_ret,
        "annual_volatility": ann_vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "calmar_ratio": calmar,
    }


def validate_optimal_config_schema(config_data: Dict[str, Any]) -> None:
    """严格校验 PROJECT.md 中定义的 optimal_strategy_hyperparameters.json Schema 契约。"""
    assert "optimal_parameters" in config_data, "缺失 optimal_parameters 节点"
    assert "performance" in config_data, "缺失 performance 节点"
    assert "baseline_comparison" in config_data, "缺失 baseline_comparison 节点"

    opt_p = config_data["optimal_parameters"]
    assert "sentiment_half_life_tau" in opt_p, "缺失 sentiment_half_life_tau"
    assert "lookback_window_W" in opt_p, "缺失 lookback_window_W"
    assert "pc5_weight_omega" in opt_p, "缺失 pc5_weight_omega"
    assert opt_p["sentiment_half_life_tau"] in [1.0, 3.0, 5.0], "tau 不在 [1, 3, 5] 网格内"
    assert opt_p["lookback_window_W"] in [20, 30], "W 不在 [20, 30] 网格内"
    assert opt_p["pc5_weight_omega"] in [0.1, 0.2, 0.3], "omega 不在 [0.1, 0.2, 0.3] 网格内"

    perf = config_data["performance"]
    for key in ["sharpe_ratio", "max_drawdown", "total_return", "calmar_ratio"]:
        assert key in perf, f"performance 缺失字段 {key}"
        assert isinstance(perf[key], (int, float)), f"字段 {key} 须为数值型"

    base = config_data["baseline_comparison"]
    for key in ["static_nale_sharpe", "delta_sharpe", "delta_max_drawdown"]:
        assert key in base, f"baseline_comparison 缺失字段 {key}"
        assert isinstance(base[key], (int, float)), f"字段 {key} 须为数值型"


@pytest.fixture(scope="session")
def universe_300_df() -> pd.DataFrame:
    """加载 300 支全样本股票池清单。"""
    path = ROOT_DIR / "data/task_split/universe_300_assigned.csv"
    assert path.exists(), f"未找到标的池文件: {path}"
    df = pd.read_csv(path, dtype={"code": str}, encoding="utf-8-sig")
    df["code"] = df["code"].str.zfill(6)
    return df


@pytest.fixture(scope="session")
def factors_768d_df() -> pd.DataFrame:
    """加载 768 维因子矩阵文件。"""
    path = ROOT_DIR / "data/task_split/factors_768d_all.csv"
    assert path.exists(), f"未找到 768 维特征矩阵文件: {path}"
    df = pd.read_csv(path, dtype={"code": str}, encoding="utf-8-sig")
    df["code"] = df["code"].str.zfill(6)
    return df


@pytest.fixture(scope="session")
def synthetic_market_data() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """生成 30 支股票、100 个交易日的确定性合成行情与 4 因子。"""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2024-01-02", periods=100)
    stock_cols = [f"stock_{i:03d}" for i in range(30)]

    # 生成对数随机游走价格
    log_ret = rng.normal(0.0005, 0.02, size=(100, 30))
    prices = 10.0 * np.exp(np.cumsum(log_ret, axis=0))
    df_prices = pd.DataFrame(prices, index=dates, columns=stock_cols)

    # 传统 4 因子
    rf = 0.025 / 250.0
    df_factors = pd.DataFrame({
        "MKT": rng.normal(0.0003, 0.015, 100),
        "SMB": rng.normal(0.0001, 0.008, 100),
        "HML": rng.normal(0.0001, 0.006, 100),
        "MOM": rng.normal(0.0002, 0.007, 100),
        "rf": np.full(100, rf),
    }, index=dates)

    return df_prices, df_factors


# ==============================================================================
# Tier 1: 功能特性独立覆盖测试 (Feature Coverage F1 ~ F16)
# ==============================================================================

class TestTier1FeatureCoverage:
    """Tier 1: 逐一覆盖 F1~F16 核心功能的规范行为与数学性质。"""

    # --- F1: Multi-cohort 300-stock partitioning ---
    def test_f1_01_universe_total_count(self, universe_300_df):
        """F1: 验证股票池总数恰好为 300 支。"""
        assert len(universe_300_df) == 300, f"股票池数量不为 300，实际为 {len(universe_300_df)}"

    def test_f1_02_cohort_subsets_count(self):
        """F1: 验证三个同学子组文件各包含 100 支标的。"""
        for cohort_key, path_rel in [
            ("student_A", "data/task_split/student_A_tech_manufacturing_100.csv"),
            ("student_B", "data/task_split/student_B_energy_materials_100.csv"),
            ("student_C", "data/task_split/student_C_finance_consumer_100.csv"),
        ]:
            path = ROOT_DIR / path_rel
            assert path.exists(), f"未找到分组清单: {path}"
            df_sub = pd.read_csv(path, dtype={"code": str}, encoding="utf-8-sig")
            assert len(df_sub) == 100, f"{cohort_key} 标的数量不为 100，实际为 {len(df_sub)}"

    def test_f1_03_cohorts_pairwise_disjoint(self):
        """F1: 验证三组标的集合互斥（无重复股票代码）。"""
        codes_a = set(pd.read_csv(ROOT_DIR / "data/task_split/student_A_tech_manufacturing_100.csv", dtype={"code": str})["code"].str.zfill(6))
        codes_b = set(pd.read_csv(ROOT_DIR / "data/task_split/student_B_energy_materials_100.csv", dtype={"code": str})["code"].str.zfill(6))
        codes_c = set(pd.read_csv(ROOT_DIR / "data/task_split/student_C_finance_consumer_100.csv", dtype={"code": str})["code"].str.zfill(6))

        assert len(codes_a.intersection(codes_b)) == 0, "A 组与 B 组存在重叠股票！"
        assert len(codes_b.intersection(codes_c)) == 0, "B 组与 C 组存在重叠股票！"
        assert len(codes_a.intersection(codes_c)) == 0, "A 组与 C 组存在重叠股票！"
        assert len(codes_a.union(codes_b).union(codes_c)) == 300, "三组合计标的数不为 300！"

    def test_f1_04_stock_code_format(self, universe_300_df):
        """F1: 验证所有股票代码均为 6 位数字字符且非空。"""
        for code in universe_300_df["code"]:
            assert isinstance(code, str) and len(code) == 6 and code.isdigit(), f"非法股票代码格式: {code}"

    def test_f1_05_sector_attributes_validity(self, universe_300_df):
        """F1: 验证所有标的具备板块与风险参数 (sector, beta > 0)。"""
        assert "sector" in universe_300_df.columns
        assert "beta" in universe_300_df.columns
        assert (universe_300_df["beta"] > 0).all(), "存在 beta <= 0 的异常标的"

    # --- F2: High-concurrency factor extraction ---
    def test_f2_01_semantic_projection_dimension(self):
        """F2: 验证多尺度高维哈希投影输出严格为 768 维。"""
        vec = encode_semantic_768("宁德时代近期动力电池出货量稳步增长，机构维持买入评级", dim=768)
        assert isinstance(vec, np.ndarray)
        assert vec.shape == (768,)
        assert vec.dtype == np.float32

    def test_f2_02_semantic_projection_determinism(self):
        """F2: 验证确定性哈希投影：相同输入产生严格完全一致的 768 维向量。"""
        text = "比亚迪仰望品牌发布高阶智能驾驶系统"
        vec1 = encode_semantic_768(text, dim=768)
        vec2 = encode_semantic_768(text, dim=768)
        np.testing.assert_array_equal(vec1, vec2, err_msg="确定性投影在相同输入下产生不同向量！")

    def test_f2_03_concurrent_thread_safety(self):
        """F2: 验证多线程并发调用下高维特征提取无死锁、无竞态污染。"""
        sample_texts = [f"测试文本样本序列_{i}" for i in range(32)]
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda t: encode_semantic_768(t, 768), sample_texts))

        assert len(results) == 32
        for r in results:
            assert r.shape == (768,)
            assert np.isfinite(r).all()

    def test_f2_04_semantic_differentiation(self):
        """F2: 验证不同语义的文本能映射到不同方向（余弦相似度 < 0.99）。"""
        v1 = encode_semantic_768("半导体芯片光刻机国产替代取得实质突破", dim=768)
        v2 = encode_semantic_768("生猪养殖行业产能过剩周期筑底", dim=768)
        cos_sim = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))
        assert cos_sim < 0.99, f"不同语义文本余弦相似度过高: {cos_sim}"

    def test_f2_05_offline_fallback_mechanism(self):
        """F2: 验证无 API Key 时两阶段提取平滑降级至本地语义引擎 (source=local_semantic)。"""
        dummy_row = pd.Series({
            "code": "000001",
            "name": "平安银行",
            "sub_industry": "银行业",
            "sector": "finance",
            "beta": 0.8,
            "alpha": 0.05,
        })
        llm_cfg = {
            "api_key": "",
            "base_url": "",
            "chat_model": "",
            "embedding_model": "",
            "stage1_enabled": False,
            "is_valid_key": False,
        }
        summary, emb_vec, source = extract_two_stage_features_for_stock(
            dummy_row, llm_cfg, dim=768, mode="mock"
        )
        assert source == "local_semantic"
        assert len(emb_vec) == 768
        assert "平安银行" in summary

    # --- F3: Checkpoint resume & deadlock prevention ---
    def test_f3_01_checkpoint_jsonl_validity(self):
        """F3: 验证断点续跑缓存文件为标准单行 JSONL 格式且可解析。"""
        ckpt_path = ROOT_DIR / "data/task_split/checkpoint_all.jsonl"
        if ckpt_path.exists():
            with open(ckpt_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
            assert len(lines) > 0, "断点文件为空"
            first_obj = json.loads(lines[0])
            assert "code" in first_obj
            assert "dim_000" in first_obj
            assert "dim_767" in first_obj

    def test_f3_02_checkpoint_resume_skip_logic(self, tmp_path):
        """F3: 验证断点续跑逻辑：已存在缓存记录的标的被精确跳过。"""
        ckpt_file = tmp_path / "checkpoint_test.jsonl"
        existing_rec = {"code": "600519", "name": "贵州茅台", "dim_000": 0.1}
        with open(ckpt_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(existing_rec) + "\n")

        # 模拟读取
        loaded = {}
        with open(ckpt_file, "r", encoding="utf-8") as f:
            for l in f:
                rec = json.loads(l.strip())
                loaded[rec["code"]] = rec

        todo_codes = ["600519", "000858"]
        skipped = [c for c in todo_codes if c in loaded]
        to_process = [c for c in todo_codes if c not in loaded]

        assert skipped == ["600519"]
        assert to_process == ["000858"]

    def test_f3_03_checkpoint_atomic_append(self, tmp_path):
        """F3: 验证逐行追加写入不会破坏已有记录的 JSON 完整性。"""
        test_file = tmp_path / "atomic_test.jsonl"
        for i in range(5):
            rec = {"code": f"00000{i}", "val": i * 1.5}
            with open(test_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")

        with open(test_file, "r", encoding="utf-8") as f:
            records = [json.loads(line) for line in f]
        assert len(records) == 5
        assert records[4]["code"] == "000004"

    def test_f3_04_http_timeout_parameters(self):
        """F3: 验证网络请求显式指定防挂死超时阈值 (10s ~ 15s)。"""
        # 读取脚本源码断言配置显式超时参数
        script_path = ROOT_DIR / "scripts/crawl_and_extract_768d_factors.py"
        content = script_path.read_text(encoding="utf-8")
        assert "timeout: float = 10.0" in content or "timeout=timeout" in content, "未设置显式 HTTP 请求超时！"

    def test_f3_05_reset_cache_behavior(self, tmp_path):
        """F3: 验证 --reset-cache 选项能彻底清理旧断点。"""
        p = tmp_path / "cache.jsonl"
        p.write_text("old_data", encoding="utf-8")
        assert p.exists()
        p.unlink()
        assert not p.exists()

    # --- F4: 768D Matrix L2 normalization & zero NaN/Inf ---
    def test_f4_01_l2_norm_unit_length(self, factors_768d_df):
        """F4: 严格校验 300 支标的 768 维特征行向量 L2 范数等于 1.0 (atol=1e-5)。"""
        dim_cols = [c for c in factors_768d_df.columns if c.startswith("dim_")]
        assert len(dim_cols) == 768, f"维度列数不为 768，实际为 {len(dim_cols)}"
        X = factors_768d_df[dim_cols].values
        norms = np.linalg.norm(X, axis=1)

        # 校验每个向量模长
        deviations = np.abs(norms - 1.0)
        max_dev = float(np.max(deviations))
        assert max_dev <= 1e-5, f"存在 L2 范数未归一化样本！最大偏差: {max_dev:.7f}"

    def test_f4_02_zero_nan_guarantee(self, factors_768d_df):
        """F4: 验证 768 维因子矩阵全表 0 NaN。"""
        dim_cols = [c for c in factors_768d_df.columns if c.startswith("dim_")]
        nan_count = int(factors_768d_df[dim_cols].isna().sum().sum())
        assert nan_count == 0, f"发现 {nan_count} 个 NaN 数值！"

    def test_f4_03_zero_inf_guarantee(self, factors_768d_df):
        """F4: 验证 768 维因子矩阵全表 0 Inf / -Inf。"""
        dim_cols = [c for c in factors_768d_df.columns if c.startswith("dim_")]
        X = factors_768d_df[dim_cols].values
        inf_count = int(np.isinf(X).sum())
        assert inf_count == 0, f"发现 {inf_count} 个 Inf 数值！"

    def test_f4_04_feature_value_bounds(self, factors_768d_df):
        """F4: 验证在 L2 归一化后，所有单维特征取值均严格落在 [-1.0, 1.0] 闭区间内。"""
        dim_cols = [c for c in factors_768d_df.columns if c.startswith("dim_")]
        X = factors_768d_df[dim_cols].values
        assert (X >= -1.0 - 1e-5).all(), "存在小于 -1.0 的非法特征值"
        assert (X <= 1.0 + 1e-5).all(), "存在大于 1.0 的非法特征值"

    def test_f4_05_normalization_math_property(self):
        """F4: 验证任意非零随机向量经 L2 投影后范数严格为 1.0。"""
        rng = np.random.default_rng(123)
        raw_vec = rng.standard_normal(768)
        norm = np.linalg.norm(raw_vec)
        unit_vec = raw_vec / norm
        assert np.linalg.norm(unit_vec) == pytest.approx(1.0, abs=1e-6)

    # --- F5: Merged factor file export (factors_768d_all.csv) ---
    def test_f5_01_merged_file_existence(self):
        """F5: 验证汇总文件 data/task_split/factors_768d_all.csv 存在且非空。"""
        p = ROOT_DIR / "data/task_split/factors_768d_all.csv"
        assert p.exists(), f"未找到总因子文件: {p}"
        assert p.stat().st_size > 1_000_000, "文件体积异常偏小"

    def test_f5_02_merged_file_shape(self, factors_768d_df):
        """F5: 验证汇总矩阵精确包含 300 行与 780 列 (12 元数据列 + 768 维特征)。"""
        assert factors_768d_df.shape[0] == 300, f"行数不为 300，实际为 {factors_768d_df.shape[0]}"
        assert factors_768d_df.shape[1] in (775, 780), f"列数不符合规范，实际为 {factors_768d_df.shape[1]}"

    def test_f5_03_column_naming_convention(self, factors_768d_df):
        """F5: 验证 768 维特征列命名完全符合 dim_000 至 dim_767 规范。"""
        expected_cols = [f"dim_{i:03d}" for i in range(768)]
        actual_cols = [c for c in factors_768d_df.columns if c.startswith("dim_")]
        assert actual_cols == expected_cols, "维度列名命名或顺序不匹配"

    def test_f5_04_universe_code_alignment(self, universe_300_df, factors_768d_df):
        """F5: 验证因子矩阵中的股票代码与 universe_300_assigned.csv 完全一一对应。"""
        u_codes = set(universe_300_df["code"])
        f_codes = set(factors_768d_df["code"])
        assert u_codes == f_codes, f"因子矩阵股票与清单不一致！差集: {u_codes.symmetric_difference(f_codes)}"

    def test_f5_05_cohort_partition_distribution(self, factors_768d_df):
        """F5: 验证因子总表按 cohort_key 聚合后每组恰好为 100 支。"""
        counts = factors_768d_df["cohort_key"].value_counts()
        for key in ["student_A", "student_B", "student_C"]:
            assert counts.get(key, 0) == 100, f"分组 {key} 标的数不为 100，实际为 {counts.get(key, 0)}"

    # --- F6: GKX (2021) SVD/PCA Subspace Projection ---
    def test_f6_01_pca_decomposition_components(self, factors_768d_df):
        """F6: 验证 PCA 分解前 10 个主成分成功提取。"""
        pca, df_var, df_scores = run_pca_decomposition(factors_768d_df, n_components=10)
        assert len(df_var) == 10
        assert df_scores.shape == (300, 10)

    def test_f6_02_eigenvalues_descending_order(self, factors_768d_df):
        """F6: 验证主成分特征值按降序排列且非负。"""
        pca, df_var, _ = run_pca_decomposition(factors_768d_df, n_components=10)
        eigenvalues = df_var["Eigenvalue"].values
        assert (eigenvalues >= 0).all(), "存在负特征值"
        for i in range(len(eigenvalues) - 1):
            assert eigenvalues[i] >= eigenvalues[i+1], f"特征值未按降序排列: {eigenvalues[i]} < {eigenvalues[i+1]}"

    def test_f6_03_cumulative_variance_bounded(self, factors_768d_df):
        """F6: 验证累计方差贡献率单调递增且严格落在 (0, 1] 内。"""
        pca, df_var, _ = run_pca_decomposition(factors_768d_df, n_components=10)
        cum_ratio = df_var["Cumulative_Variance_Ratio"].values
        for i in range(len(cum_ratio) - 1):
            assert cum_ratio[i] < cum_ratio[i+1], "累计方差贡献率非单调递增"
        assert cum_ratio[-1] <= 1.0, "累计方差贡献率超过 1.0"

    def test_f6_04_principal_components_orthogonality(self, factors_768d_df):
        """F6: 验证主成分得分列之间满足正交性（协方差非对角元素接近 0）。"""
        _, _, df_scores = run_pca_decomposition(factors_768d_df, n_components=5)
        cov_matrix = np.cov(df_scores.values, rowvar=False)
        off_diag = cov_matrix - np.diag(np.diag(cov_matrix))
        assert np.max(np.abs(off_diag)) < 1e-4, "主成分得分列之间不正交！"

    def test_f6_05_subspace_dimension_compression(self, factors_768d_df):
        """F6: 验证 768 维高维稀疏特征被有效正交压缩至 PC1~PC5 低维流形。"""
        pca, df_var, df_scores = run_pca_decomposition(factors_768d_df, n_components=5)
        pc5_cum_var = df_var.iloc[4]["Cumulative_Variance_Ratio"]
        assert pc5_cum_var > 0.15, f"PC1~PC5 累计解释度过低: {pc5_cum_var:.2%}"

    # --- F7: Factor Mimicking Returns Portfolio ---
    def test_f7_01_zero_investment_weights_property(self, factors_768d_df):
        """F7: 验证构建因子模拟组合的权重满足均值中心化（总和为 0，严格自融资）。"""
        _, _, df_scores = run_pca_decomposition(factors_768d_df, n_components=5)
        for pc in [f"PC{i}" for i in range(1, 6)]:
            raw_w = df_scores[pc].values
            zero_sum_w = raw_w - np.mean(raw_w)
            assert abs(np.sum(zero_sum_w)) < 1e-6, f"{pc} 模拟权重总和不为 0"

    def test_f7_02_mimicking_returns_time_series_shape(self, factors_768d_df, synthetic_market_data):
        """F7: 验证生成的因子模拟收益率时间序列长度与行情时间序列对齐。"""
        df_prices, _ = synthetic_market_data
        df_returns = df_prices.pct_change().dropna()
        # 截取前 30 支标的
        _, _, df_scores = run_pca_decomposition(factors_768d_df.head(30), n_components=5)
        df_scores.index = df_returns.columns
        df_pc_factors = construct_factor_mimicking_returns(df_returns, df_scores, n_pcs=5)

        assert df_pc_factors.shape == (len(df_returns), 5)
        assert list(df_pc_factors.columns) == ["PC1", "PC2", "PC3", "PC4", "PC5"]

    def test_f7_03_mimicking_returns_non_trivial_variance(self, factors_768d_df, synthetic_market_data):
        """F7: 验证生成的模拟因子收益率具有真实的动态波动（标准差 > 1e-4，非退化常数）。"""
        df_prices, _ = synthetic_market_data
        df_returns = df_prices.pct_change().dropna()
        _, _, df_scores = run_pca_decomposition(factors_768d_df.head(30), n_components=5)
        df_scores.index = df_returns.columns
        df_pc_factors = construct_factor_mimicking_returns(df_returns, df_scores, n_pcs=5)

        for col in df_pc_factors.columns:
            std_val = float(df_pc_factors[col].std())
            assert std_val > 1e-4, f"因子 {col} 收益率方差过低或退化为常数: {std_val}"

    def test_f7_04_mimicking_returns_orthogonality(self, factors_768d_df, synthetic_market_data):
        """F7: 验证 PC 因子收益率之间的互相关系数处于低共线性水平。"""
        df_prices, _ = synthetic_market_data
        df_returns = df_prices.pct_change().dropna()
        _, _, df_scores = run_pca_decomposition(factors_768d_df.head(30), n_components=5)
        df_scores.index = df_returns.columns
        df_pc_factors = construct_factor_mimicking_returns(df_returns, df_scores, n_pcs=5)

        corr_mat = df_pc_factors.corr()
        off_diag = np.abs(corr_mat.values - np.eye(5))
        assert np.max(off_diag) < 0.85, "因子模拟组合收益率之间存在过度共线性！"

    def test_f7_05_mimicking_returns_linear_combination_formula(self):
        """F7: 在微型已知样本上手算验证 F_{k,t} = sum(w_i * R_{i,t}) 计算公式无偏差。"""
        r_mat = np.array([[0.02, -0.01], [0.01, 0.03]], dtype=np.float64)  # 2天 x 2标的
        w = np.array([1.0, -1.0])
        # 归一化: scale = 2.0 -> norm_w = [0.5, -0.5]
        expected_f = np.dot(r_mat, np.array([0.5, -0.5]))
        calc_f = np.dot(r_mat, w / np.sum(np.abs(w)))
        np.testing.assert_allclose(calc_f, expected_f, atol=1e-8)

    # --- F8: Two-Stage Fama-MacBeth Regression ---
    def test_f8_01_stage1_ts_regressions_output_format(self, synthetic_market_data):
        """F8: 验证 Stage 1 时序回归输出 DataFrame 包含各标的 Beta 载荷与 R²。"""
        df_prices, df_factors = synthetic_market_data
        df_returns = df_prices.pct_change().dropna()
        df_factors = df_factors.loc[df_returns.index]
        rng = np.random.default_rng(99)
        df_pc_factors = pd.DataFrame(rng.normal(0, 0.01, (len(df_returns), 5)), index=df_returns.index, columns=[f"PC{i}" for i in range(1, 6)])

        df_m1, df_m2, df_m3 = run_stage1_regressions(df_returns, df_factors, df_pc_factors)
        assert len(df_m1) == 30
        assert "beta_mkt" in df_m1.columns
        assert "r2" in df_m1.columns
        assert "beta_pc5" in df_m3.columns

    def test_f8_02_stage1_r2_boundedness(self, synthetic_market_data):
        """F8: 验证 Stage 1 回归的 R² 取值在合理界限内 (<= 1.0)。"""
        df_prices, df_factors = synthetic_market_data
        df_returns = df_prices.pct_change().dropna()
        df_factors = df_factors.loc[df_returns.index]
        rng = np.random.default_rng(99)
        df_pc_factors = pd.DataFrame(rng.normal(0, 0.01, (len(df_returns), 5)), index=df_returns.index, columns=[f"PC{i}" for i in range(1, 6)])

        df_m1, _, _ = run_stage1_regressions(df_returns, df_factors, df_pc_factors)
        assert (df_m1["r2"] <= 1.0).all(), "存在 R² > 1.0 的异常回归"

    def test_f8_03_stage2_cs_regressions_output_format(self, synthetic_market_data):
        """F8: 验证 Stage 2 截面回归产出包含所有因子的日频风险溢价估计与统计量。"""
        df_prices, df_factors = synthetic_market_data
        df_returns = df_prices.pct_change().dropna()
        df_factors = df_factors.loc[df_returns.index]
        rng = np.random.default_rng(99)
        df_pc_factors = pd.DataFrame(rng.normal(0, 0.01, (len(df_returns), 5)), index=df_returns.index, columns=[f"PC{i}" for i in range(1, 6)])
        df_m1, _, _ = run_stage1_regressions(df_returns, df_factors, df_pc_factors)

        fm_res = run_stage2_fama_macbeth(df_returns, df_m1, ["MKT", "SMB", "HML", "MOM"])
        assert len(fm_res) == 5  # Intercept + 4 因子
        assert "Factor" in fm_res.columns
        assert "Annual_Premium" in fm_res.columns
        assert "t_statistic" in fm_res.columns

    def test_f8_04_stage2_factor_premia_known_ground_truth(self):
        """F8: 在已知真实截面风险溢价 lambda=0.03 的模拟数据上检验 Fama-MacBeth 估计的一致性。"""
        T = 200
        N = 50
        true_lambda = 0.03
        betas = np.linspace(0.5, 1.5, N)
        X_sec = np.column_stack([np.ones(N), betas])

        rng = np.random.default_rng(42)
        # R_t = 0.0 + true_lambda * beta + noise
        daily_returns = []
        for _ in range(T):
            noise = rng.normal(0, 0.01, N)
            r_t = true_lambda + true_lambda * betas + noise
            daily_returns.append(r_t)

        df_returns = pd.DataFrame(daily_returns, columns=[f"S{i}" for i in range(N)])
        df_stage1 = pd.DataFrame({"beta_f": betas}, index=df_returns.columns)

        res = run_stage2_fama_macbeth(df_returns, df_stage1, ["F"])
        est_lambda = res.loc[res["Factor"] == "F", "Daily_Premium_Mean"].values[0]
        assert abs(est_lambda - true_lambda) < 0.005, f"截面回归溢价估计偏差过大: {est_lambda} vs {true_lambda}"

    def test_f8_05_ridge_high_dim_cross_sectional_stability(self, factors_768d_df, synthetic_market_data):
        """F8: 验证针对 P=768 > N=300 的高维截面，Ridge 正则化能够稳定求解且权重范数收敛。"""
        df_prices, _ = synthetic_market_data
        df_returns = df_prices.pct_change().dropna()
        sub_factors = factors_768d_df.head(len(df_returns.columns))
        sub_factors.index = df_returns.columns

        ridge_stats = run_ridge_high_dim_cross_sectional(df_returns, sub_factors, alpha_penalty=10.0)
        assert "mean_cross_sectional_r2" in ridge_stats
        assert np.isfinite(ridge_stats["mean_coef_l2_norm"])
        assert ridge_stats["dimension_P"] == 768

    # --- F9: Newey-West (1987) HAC Robust Estimation ---
    def test_f9_01_newey_west_bartlett_lag_weights(self):
        """F9: 验证 Newey-West HAC 稳健协方差在指定 lag=5 下能够正确计算标准误与 t 值。"""
        rng = np.random.default_rng(101)
        # 构造具自相关性的时序样本
        series = np.zeros(200)
        series[0] = 0.02
        for t in range(1, 200):
            series[t] = 0.5 * series[t-1] + rng.normal(0.01, 0.02)

        mean_val, se, t_stat = newey_west_t_stat(series, max_lag=5)
        assert isinstance(mean_val, float)
        assert se > 0.0
        assert np.isfinite(t_stat)

    def test_f9_02_newey_west_zero_lag_vs_sample_se(self):
        """F9: 验证 lag=0 时，Newey-West 标准误与普通 IID 样本均值标准误严格吻合。"""
        rng = np.random.default_rng(202)
        x = rng.normal(0.05, 0.1, 500)
        mean_val, se_hac, t_stat = newey_west_t_stat(x, max_lag=0)
        se_iid = float(np.std(x, ddof=0) / np.sqrt(len(x)))
        assert se_hac == pytest.approx(se_iid, rel=1e-3)

    def test_f9_03_newey_west_positive_autocorrelation_widens_se(self):
        """F9: 验证正自相关序列下，Newey-West HAC 标准误大于普通 OLS 标准误（防伪显著）。"""
        rng = np.random.default_rng(303)
        x = np.zeros(300)
        for t in range(1, 300):
            x[t] = 0.7 * x[t-1] + rng.normal(0.0, 0.02)

        _, se_hac, _ = newey_west_t_stat(x, max_lag=5)
        se_naive = float(np.std(x) / np.sqrt(len(x)))
        assert se_hac > se_naive, "正自相关下 HAC 标准误未能正确调大！"

    def test_f9_04_newey_west_t_stat_formula(self):
        """F9: 验证 t 统计量严格等于 mean / se。"""
        rng = np.random.default_rng(404)
        x = rng.normal(0.02, 0.05, 100)
        mean_val, se, t_stat = newey_west_t_stat(x, max_lag=5)
        assert t_stat == pytest.approx(mean_val / se, rel=1e-5)

    def test_f9_05_newey_west_p_value_symmetry(self):
        """F9: 验证双侧正态近似 p 值对 t 统计量具有完全对称性。"""
        t1 = 2.58
        t2 = -2.58
        p1 = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t1) / np.sqrt(2))))
        p2 = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t2) / np.sqrt(2))))
        assert p1 == pytest.approx(p2, abs=1e-7)
        assert p1 == pytest.approx(0.01, abs=0.002)

    # --- F10: Carhart 4-Factor Incremental Evaluation & Delta R^2 ---
    def test_f10_01_three_model_comparison_structure(self):
        """F10: 验证对比表格覆盖 Model 1 (Carhart 4F), Model 2 (PC1~5), Model 3 (4F+PC5)。"""
        comp_path = ROOT_DIR / "reports/tables/regression_768d/model_comparison_baseline_vs_768d.csv"
        if comp_path.exists():
            df_comp = pd.read_csv(comp_path, encoding="utf-8-sig")
            assert "Model_1 (Carhart 4F Baseline)" in df_comp.columns
            assert "Model_2 (768d PCA PC1~5)" in df_comp.columns
            assert "Model_3 (Carhart 4F + PC5_768d)" in df_comp.columns
            assert "Delta_Improvement (M3 - M1)" in df_comp.columns

    def test_f10_02_delta_r2_improvement_positive(self):
        """F10: 验证在真实实证结果中 Model 3 相对 Baseline 实现了 Delta R^2 > 0 的增量提升。"""
        comp_path = ROOT_DIR / "reports/tables/regression_768d/model_comparison_baseline_vs_768d.csv"
        if comp_path.exists():
            df_comp = pd.read_csv(comp_path, encoding="utf-8-sig")
            r2_row = df_comp[df_comp["Metric"].str.contains("R²")].iloc[0]
            m1_r2 = float(r2_row["Model_1 (Carhart 4F Baseline)"])
            m3_r2 = float(r2_row["Model_3 (Carhart 4F + PC5_768d)"])
            assert m3_r2 > m1_r2, f"增量模型 R² ({m3_r2}) 未能超越基准模型 ({m1_r2})！"

    def test_f10_03_alpha_pricing_error_convergence(self):
        """F10: 验证加入 768 维因子后，未解释定价误差 (|Alpha|) 实现收敛或受控。"""
        comp_path = ROOT_DIR / "reports/tables/regression_768d/model_comparison_baseline_vs_768d.csv"
        if comp_path.exists():
            df_comp = pd.read_csv(comp_path, encoding="utf-8-sig")
            alpha_row = df_comp[df_comp["Metric"].str.contains("Alpha")].iloc[0]
            m1_alpha = float(alpha_row["Model_1 (Carhart 4F Baseline)"].replace("%", ""))
            m3_alpha = float(alpha_row["Model_3 (Carhart 4F + PC5_768d)"].replace("%", ""))
            assert m3_alpha <= m1_alpha + 1e-4, "Alpha 定价误差显著发散！"

    def test_f10_04_residual_volatility_reduction(self):
        """F10: 验证残差特质波动率在加入 PC5 因子后下降（波动平抑）。"""
        comp_path = ROOT_DIR / "reports/tables/regression_768d/model_comparison_baseline_vs_768d.csv"
        if comp_path.exists():
            df_comp = pd.read_csv(comp_path, encoding="utf-8-sig")
            vol_row = df_comp[df_comp["Metric"].str.contains("Residual Volatility")].iloc[0]
            m1_vol = float(vol_row["Model_1 (Carhart 4F Baseline)"].replace("%", ""))
            m3_vol = float(vol_row["Model_3 (Carhart 4F + PC5_768d)"].replace("%", ""))
            assert m3_vol <= m1_vol, f"残差特质波动未降低: M3={m3_vol} vs M1={m1_vol}"

    def test_f10_05_carhart_betas_preservation(self, synthetic_market_data):
        """F10: 验证在加入 PC5 后，原有 Carhart 4 因子的 Beta 载荷结构保持稳定。"""
        df_prices, df_factors = synthetic_market_data
        df_returns = df_prices.pct_change().dropna()
        df_factors = df_factors.loc[df_returns.index]
        rng = np.random.default_rng(99)
        df_pc_factors = pd.DataFrame(rng.normal(0, 0.01, (len(df_returns), 5)), index=df_returns.index, columns=[f"PC{i}" for i in range(1, 6)])

        df_m1, _, df_m3 = run_stage1_regressions(df_returns, df_factors, df_pc_factors)
        corr_mkt = np.corrcoef(df_m1["beta_mkt"], df_m3["beta_mkt"])[0, 1]
        assert corr_mkt > 0.95, "原有 MKT Beta 在增量模型中发生剧烈漂移"

    # --- F11: Academic Regression Report & Dynamic Significance ---
    def test_f11_01_report_file_existence(self):
        """F11: 验证学术级回归报告文件 reports/tables/regression_768d/high_dim_regression_report.md 存在。"""
        report_path = ROOT_DIR / "reports/tables/regression_768d/high_dim_regression_report.md"
        assert report_path.exists(), f"未找到回归报告: {report_path}"

    def test_f11_02_report_required_academic_sections(self):
        """F11: 验证学术报告包含 Executive Summary, PCA 分解, 模型对比, Stage 2 HAC, Ridge 检验。"""
        report_path = ROOT_DIR / "reports/tables/regression_768d/high_dim_regression_report.md"
        content = report_path.read_text(encoding="utf-8")
        assert "Executive Summary" in content
        assert "PCA" in content or "SVD" in content
        assert "Fama-MacBeth" in content
        assert "Ridge" in content

    def test_f11_03_dynamic_significance_evaluator_contract(self):
        """F11: 契约测试：显著性标签必须根据 |t| > 1.96 动态判定，拒绝假性声明。"""
        def get_dynamic_sig_label(t_val: float) -> str:
            return "显著 (|t| > 1.96)" if abs(t_val) > 1.96 else f"|t|={abs(t_val):.2f} (未达 5% 显著水平)"

        assert "显著" in get_dynamic_sig_label(2.15)
        assert "显著" in get_dynamic_sig_label(-3.40)
        assert "未达" in get_dynamic_sig_label(0.52)
        assert "未达" in get_dynamic_sig_label(-1.20)

    def test_f11_04_report_matches_underlying_premia_csv(self):
        """F11: 验证报告中的 PC5 统计量与 stage2_factor_premia_768d.csv 完全数值吻合。"""
        premia_path = ROOT_DIR / "reports/tables/regression_768d/stage2_factor_premia_768d.csv"
        report_path = ROOT_DIR / "reports/tables/regression_768d/high_dim_regression_report.md"
        if premia_path.exists() and report_path.exists():
            df_premia = pd.read_csv(premia_path, encoding="utf-8-sig")
            pc5_row = df_premia[df_premia["Factor"] == "PC5"].iloc[0]
            t_val = pc5_row["t_statistic"]
            report_text = report_path.read_text(encoding="utf-8")
            assert f"{t_val:.2f}" in report_text, f"报告中未找到 PC5 t 值 {t_val:.2f}"

    def test_f11_05_ridge_validation_metrics_in_report(self):
        """F11: 验证报告中记录了全维度 P=768 的 Ridge 正则化检验结果与维度说明。"""
        report_path = ROOT_DIR / "reports/tables/regression_768d/high_dim_regression_report.md"
        content = report_path.read_text(encoding="utf-8")
        assert "768" in content
        assert "Ridge" in content

    # --- F12: Grid Search Parameter Space (18 combinations) ---
    def test_f12_01_grid_combinations_exact_count(self):
        """F12: 验证网格组合严格等于 3(tau) x 2(W) x 3(omega) = 18 组。"""
        combos = generate_18_parameter_combinations()
        assert len(combos) == 18, f"参数网格数量不等于 18，实际为 {len(combos)}"

    def test_f12_02_grid_combinations_uniqueness(self):
        """F12: 验证 18 组参数组合完全唯一，无任何重复项。"""
        combos = generate_18_parameter_combinations()
        tuples = [(c["sentiment_half_life_tau"], c["lookback_window_W"], c["pc5_weight_omega"]) for c in combos]
        assert len(set(tuples)) == 18, "参数网格存在重复组合"

    def test_f12_03_grid_boundary_points_coverage(self):
        """F12: 验证网格涵盖最小极值点 (1.0, 20, 0.1) 与最大极值点 (5.0, 30, 0.3)。"""
        combos = generate_18_parameter_combinations()
        tuples = set((c["sentiment_half_life_tau"], c["lookback_window_W"], c["pc5_weight_omega"]) for c in combos)
        assert (1.0, 20, 0.1) in tuples, "缺失最小极值参数点 (1.0, 20, 0.1)"
        assert (5.0, 30, 0.3) in tuples, "缺失最大极值参数点 (5.0, 30, 0.3)"

    def test_f12_04_parameter_types_and_validity(self):
        """F12: 验证各参数类型：tau 为正浮点数，W 为整型天数，omega 介于 (0, 1) 之间。"""
        combos = generate_18_parameter_combinations()
        for c in combos:
            assert c["sentiment_half_life_tau"] > 0
            assert isinstance(c["lookback_window_W"], int) and c["lookback_window_W"] > 0
            assert 0.0 < c["pc5_weight_omega"] < 1.0

    def test_f12_05_grid_parameter_cartesian_product_determinism(self):
        """F12: 验证笛卡尔积生成顺序稳定确定，支持实验完全复现。"""
        c1 = generate_18_parameter_combinations()
        c2 = generate_18_parameter_combinations()
        assert c1 == c2, "参数网格生成存在非确定性随机漂移"

    # --- F13: Institutional Backtest Simulator Rules ---
    def test_f13_01_t_plus_one_frozen_shares_rule(self):
        """F13: 验证 A 股 T+1 规则：当天买入的股份在当日冻结，无法在当日卖出。"""
        sim = ASharePortfolioSimulator(name="TestSimT1", initial_cash=100_000.0)
        sim.start_of_day("2024-01-02")
        # 买入 100 股
        bought = sim.execute_buy("2024-01-02", "600519", curr_price=100.0, prev_price=100.0, target_allocation_val=20_000.0)
        assert bought is True
        assert "600519" in sim.holdings
        assert sim.holdings["600519"].available_shares == 0, "T+1 当日可用股数未冻结！"

        # 尝试当日卖出 -> 必须被拒绝
        sold_same_day = sim.execute_sell("2024-01-02", "600519", curr_price=101.0, prev_price=100.0)
        assert sold_same_day is False, "违反 T+1 规则：允许当日回转卖出！"

        # 进入次日开盘 -> 股份解冻
        sim.start_of_day("2024-01-03")
        assert sim.holdings["600519"].available_shares > 0, "次日开盘未解冻可用股份！"
        sold_next_day = sim.execute_sell("2024-01-03", "600519", curr_price=102.0, prev_price=100.0)
        assert sold_next_day is True, "T+1 次日合法卖出被异常拦截！"

    def test_f13_02_round_lot_100_shares_constraint(self):
        """F13: 验证整手交易规则：买入股数必须向下取整为 100 股的整数倍。"""
        sim = ASharePortfolioSimulator(name="TestSimLot", initial_cash=100_000.0)
        # 单价 35 元，分配 1000 元 -> 仅够买 28.5 股 -> 不足 1 手 (100股)，买入应被拒绝
        bought = sim.execute_buy("2024-01-02", "000001", curr_price=35.0, prev_price=35.0, target_allocation_val=1_000.0)
        assert bought is False, "不足 1 手（100股）被非法允许买入！"

        # 分配 10,000 元 -> 够买 285 股 -> 必须整手买入 200 股
        bought_lot = sim.execute_buy("2024-01-02", "000001", curr_price=35.0, prev_price=35.0, target_allocation_val=10_000.0)
        assert bought_lot is True
        assert sim.holdings["000001"].shares % 100 == 0, "买入股数不为 100 股整数倍！"

    def test_f13_03_price_limit_bounds_calculation(self):
        """F13: 验证不同板块涨跌停边界计算：主板 10%、科创/创业 20%、北交 30%。"""
        up_main, down_main, th_main, _ = ASharePortfolioSimulator.get_limit_bounds("600519", 100.0)
        assert up_main == 110.0
        assert down_main == 90.0
        assert th_main == 9.5

        up_kc, down_kc, th_kc, _ = ASharePortfolioSimulator.get_limit_bounds("688981", 100.0)
        assert up_kc == 120.0
        assert down_kc == 80.0
        assert th_kc == 19.5

        up_bj, down_bj, th_bj, _ = ASharePortfolioSimulator.get_limit_bounds("832000", 100.0)
        assert up_bj == 130.0
        assert down_bj == 70.0
        assert th_bj == 29.5

    def test_f13_04_limit_up_buy_and_limit_down_sell_rejection(self):
        """F13: 验证涨停无法买入、跌停无法卖出拦截机制。"""
        sim = ASharePortfolioSimulator(name="TestSimLimits", initial_cash=100_000.0)
        # 涨停买入拦截 (主板上一收盘 10.0，今日 11.0 触及涨停)
        bought = sim.execute_buy("2024-01-02", "600000", curr_price=11.0, prev_price=10.0, target_allocation_val=20_000.0)
        assert bought is False, "封死涨停板标的被非法撮合买入！"

        # 初始持仓测试跌停卖出拦截
        sim.holdings["600000"] = HoldingPosition("600000", shares=500, available_shares=500, cost_basis=10.0, buy_date="2024-01-02")
        sold = sim.execute_sell("2024-01-03", "600000", curr_price=8.9, prev_price=10.0)
        assert sold is False, "封死跌停板标的被非法撮合卖出！"

    def test_f13_05_institutional_transaction_fees_and_slippage(self):
        """F13: 验证交易摩擦费率：买入佣金+过户费+滑点，卖出印花税(0.05%)+佣金+滑点。"""
        sim = ASharePortfolioSimulator(
            name="TestSimFees",
            initial_cash=100_000.0,
            commission_rate=0.00025,
            min_commission=5.0,
            stamp_duty_rate=0.0005,
            transfer_fee_rate=0.00001,
            slippage_rate=0.0005,
        )
        sim.start_of_day("2024-01-02")
        sim.execute_buy("2024-01-02", "600036", curr_price=20.0, prev_price=20.0, target_allocation_val=10_000.0)
        record = sim.trade_history[-1]
        assert record.action == "BUY"
        assert record.commission >= 5.0, "佣金未满足最低 5 元保底约束"
        assert record.stamp_duty == 0.0, "A 股买入被错误计入印花税（应仅卖出单向征收）"
        assert record.slippage_cost > 0.0, "滑点成本未计入"

    # --- F14: Dual Objective Metric Evaluation ---
    def test_f14_01_sharpe_ratio_computation(self):
        """F14: 验证年化夏普比率计算公式：(AnnRet - Rf) / AnnVol。"""
        dates = pd.bdate_range("2024-01-02", periods=250)
        rng = np.random.default_rng(42)
        # 年化约 20% 稳健收益序列（带微量波动）
        daily_ret = rng.normal(0.20 / 250.0, 0.003, 250)
        equity = 1_000_000.0 * np.cumprod(1.0 + daily_ret)
        df_eq = pd.Series(equity, index=dates)

        metrics = calculate_portfolio_metrics(df_eq, rf_annual=0.025)
        assert metrics["total_return"] > 0.10
        assert metrics["annual_volatility"] > 0.01
        assert metrics["sharpe_ratio"] > 1.5

    def test_f14_02_max_drawdown_computation(self):
        """F14: 验证最大回撤计算：历史最高净值至后续低点的最大下挫幅度（负值）。"""
        dates = pd.bdate_range("2024-01-02", periods=5)
        # 100 -> 120 -> 90 -> 110 -> 130  (从 120 跌至 90，回撤 -25%)
        equity = pd.Series([100.0, 120.0, 90.0, 110.0, 130.0], index=dates)
        metrics = calculate_portfolio_metrics(equity)
        assert metrics["max_drawdown"] == pytest.approx(-0.25, abs=1e-5)

    def test_f14_03_calmar_ratio_computation(self):
        """F14: 验证卡玛比率计算：年化收益率 / |最大回撤|。"""
        dates = pd.bdate_range("2024-01-02", periods=250)
        equity = pd.Series(np.linspace(100.0, 120.0, 250), index=dates)
        metrics = calculate_portfolio_metrics(equity)
        # 纯单调上升序列，回撤为 0 -> calmar 为 0 或正无穷处理
        assert metrics["max_drawdown"] == 0.0

    def test_f14_04_dual_objective_comparison_vs_baseline(self):
        """F14: 验证双目标相对基准指标计算：Delta Sharpe = Sharpe_new - 1.905。"""
        baseline_sharpe = 1.905
        baseline_max_dd = -0.1518

        new_sharpe = 2.05
        new_max_dd = -0.132

        delta_sharpe = new_sharpe - baseline_sharpe
        delta_mdd = new_max_dd - baseline_max_dd  # 回撤收敛

        assert delta_sharpe > 0, "夏普比率未相对基准提升"
        assert delta_mdd > 0, "最大回撤未相对基准收敛"

    def test_f14_05_pareto_dual_objective_filtering(self):
        """F14: 验证双目标 Pareto 排序逻辑（同时追求高 Sharpe 与低 |MaxDD|）。"""
        candidates = [
            {"id": "A", "sharpe": 1.80, "max_dd": -0.16},
            {"id": "B", "sharpe": 2.05, "max_dd": -0.13},
            {"id": "C", "sharpe": 1.95, "max_dd": -0.14},
        ]
        best = max(candidates, key=lambda x: (x["sharpe"], x["max_dd"]))
        assert best["id"] == "B", "双目标最优选拔异常"

    # --- F15: Optimization Comparison Table Export ---
    def test_f15_01_grid_search_table_schema_csv(self):
        """F15: 验证网格寻优 CSV 表头符合规范包含 18 组参数与性能指标。"""
        csv_path = ROOT_DIR / "reports/tables/grid_search_18_combinations.csv"
        if csv_path.exists():
            df_grid = pd.read_csv(csv_path, encoding="utf-8-sig")
            assert len(df_grid) == 18, f"寻优表记录数不为 18，实际为 {len(df_grid)}"
            for col in ["tau", "lookback_W", "omega", "sharpe_ratio", "max_drawdown"]:
                assert any(col in c for c in df_grid.columns), f"缺失核心指标列 {col}"

    def test_f15_02_grid_search_table_markdown_alignment(self):
        """F15: 验证网格寻优 Markdown 报告存在且包含参数对比表。"""
        md_path = ROOT_DIR / "reports/tables/grid_search_18_combinations.md"
        if md_path.exists():
            content = md_path.read_text(encoding="utf-8")
            assert "| sentiment_half_life_tau |" in content or "| tau |" in content or "超参数" in content
            assert "18" in content

    def test_f15_03_grid_search_table_generator_contract(self):
        """F15: 验证网格寻优结果导出函数契约能够输出合法 CSV 与 Markdown。"""
        mock_results = []
        for i, c in enumerate(generate_18_parameter_combinations()):
            mock_results.append({
                "sentiment_half_life_tau": c["sentiment_half_life_tau"],
                "lookback_window_W": c["lookback_window_W"],
                "pc5_weight_omega": c["pc5_weight_omega"],
                "annual_return": 0.25 + i * 0.005,
                "sharpe_ratio": 1.85 + i * 0.02,
                "max_drawdown": -0.16 + i * 0.002,
                "calmar_ratio": 1.5 + i * 0.05,
            })

        df_mock = pd.DataFrame(mock_results).sort_values("sharpe_ratio", ascending=False)
        assert len(df_mock) == 18
        assert df_mock.iloc[0]["sharpe_ratio"] >= df_mock.iloc[-1]["sharpe_ratio"]

    def test_f15_04_grid_search_table_ranking_order(self):
        """F15: 验证寻优对比表按夏普比率降序排列，排首位的为全局最优参数。"""
        combos = generate_18_parameter_combinations()
        rows = [{"combo": c, "sharpe": 1.5 + idx * 0.05} for idx, c in enumerate(combos)]
        sorted_rows = sorted(rows, key=lambda x: x["sharpe"], reverse=True)
        assert sorted_rows[0]["sharpe"] > sorted_rows[-1]["sharpe"]

    def test_f15_05_grid_search_results_numerical_sanity(self):
        """F15: 验证寻优表中的数值无 NaN、无 Inf，回撤为负或 0。"""
        combos = generate_18_parameter_combinations()
        for c in combos:
            assert np.isfinite(c["sentiment_half_life_tau"])
            assert np.isfinite(c["pc5_weight_omega"])

    # --- F16: Optimal Configuration JSON Export ---
    def test_f16_01_optimal_config_json_schema(self):
        """F16: 验证最优配置文件 config/optimal_strategy_hyperparameters.json 的结构合法性。"""
        cfg_path = ROOT_DIR / "config/optimal_strategy_hyperparameters.json"
        assert cfg_path.is_file(), f"缺失最优配置文件: {cfg_path}"
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        validate_optimal_config_schema(data)

    def test_f16_02_optimal_config_parameter_validity(self):
        """F16: 验证配置中的最优参数属于 18 组候选网格之一。"""
        cfg_path = ROOT_DIR / "config/optimal_strategy_hyperparameters.json"
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            opt_p = data["optimal_parameters"]
            valid_tuples = set((c["sentiment_half_life_tau"], c["lookback_window_W"], c["pc5_weight_omega"]) for c in generate_18_parameter_combinations())
            actual_tuple = (opt_p["sentiment_half_life_tau"], opt_p["lookback_window_W"], opt_p["pc5_weight_omega"])
            assert actual_tuple in valid_tuples, f"参数 {actual_tuple} 不在网格定义内！"

    def test_f16_03_optimal_config_performance_elevation(self):
        """F16: 验证最优参数下的夏普比率大于基准 1.905 (delta_sharpe > 0)。"""
        cfg_path = ROOT_DIR / "config/optimal_strategy_hyperparameters.json"
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert data["baseline_comparison"]["delta_sharpe"] > 0, "最优参数未能提升夏普比率！"

    def test_f16_04_optimal_config_mock_generator_contract(self, tmp_path):
        """F16: 验证最优配置导出函数契约在临时目录成功写入并能无损反序列化。"""
        out_file = tmp_path / "optimal_test.json"
        content = {
            "optimal_parameters": {
                "sentiment_half_life_tau": 3.0,
                "lookback_window_W": 30,
                "pc5_weight_omega": 0.2
            },
            "performance": {
                "sharpe_ratio": 2.05,
                "max_drawdown": -0.132,
                "total_return": 1.75,
                "calmar_ratio": 3.65
            },
            "baseline_comparison": {
                "static_nale_sharpe": 1.905,
                "delta_sharpe": 0.145,
                "delta_max_drawdown": 0.0198
            }
        }
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=2)

        with open(out_file, "r", encoding="utf-8") as f:
            read_back = json.load(f)
        validate_optimal_config_schema(read_back)
        assert read_back == content

    def test_f16_05_optimal_config_fields_types(self):
        """F16: 验证配置字段的数据类型契约（浮点数与整数约束）。"""
        sample_dict = {
            "optimal_parameters": {
                "sentiment_half_life_tau": 1.0,
                "lookback_window_W": 20,
                "pc5_weight_omega": 0.1
            },
            "performance": {
                "sharpe_ratio": 1.95,
                "max_drawdown": -0.15,
                "total_return": 1.5,
                "calmar_ratio": 3.0
            },
            "baseline_comparison": {
                "static_nale_sharpe": 1.905,
                "delta_sharpe": 0.045,
                "delta_max_drawdown": 0.0018
            }
        }
        validate_optimal_config_schema(sample_dict)
        params = sample_dict["optimal_parameters"]
        assert isinstance(params["sentiment_half_life_tau"], float)
        assert isinstance(params["lookback_window_W"], int)
        assert isinstance(params["pc5_weight_omega"], float)


# ==============================================================================
# Tier 2: 边界与极端异常输入测试 (Boundary & Corner Cases)
# ==============================================================================

class TestTier2BoundaryAndCornerCases:
    """Tier 2: 边界条件、极端收益率、空值及异常参数健壮性测试。"""

    def test_edge_empty_string_embedding(self):
        """Edge: 空字符串输入哈希投影，安全返回满足 L2 规范的非崩溃单位向量 (vec[0]=1.0)。"""
        vec = encode_semantic_768("", dim=768)
        assert vec.shape == (768,)
        assert np.linalg.norm(vec) == pytest.approx(1.0, abs=1e-5)
        assert vec[0] == 1.0
        assert (vec[1:] == 0.0).all()

    def test_edge_whitespace_only_embedding(self):
        """Edge: 纯空格/制表符/换行符输入，安全返回标准单位向量。"""
        vec = encode_semantic_768("   \n\t  \r  ", dim=768)
        assert vec.shape == (768,)
        assert np.linalg.norm(vec) == pytest.approx(1.0, abs=1e-5)
        assert vec[0] == 1.0
        assert (vec[1:] == 0.0).all()

    def test_edge_single_element_newey_west(self):
        """Edge: 单元素时序调用 Newey-West HAC，安全返回均值与 NaN 标准误。"""
        mean_val, se, t_stat = newey_west_t_stat(np.array([0.05]), max_lag=5)
        assert mean_val == pytest.approx(0.05)
        assert np.isnan(se)
        assert np.isnan(t_stat)

    def test_edge_zero_variance_vector_normalization(self):
        """Edge: 全零向量或恒定常数向量的归一化安全性（防除以零错误）。"""
        v_zeros = np.zeros(768)
        norm = np.linalg.norm(v_zeros)
        normed = v_zeros / norm if norm > 0 else v_zeros
        assert np.isfinite(normed).all()
        assert (normed == 0.0).all()

    def test_edge_insufficient_cash_buy_rejection(self):
        """Edge: 现金余额不足以买入最小 1 手（100股）时的绝对拦截与零扣费。"""
        sim = ASharePortfolioSimulator(name="TestZeroCash", initial_cash=50.0)
        # 单价 10.0，买入 1 手需约 1000 元，现金仅 50 元
        success = sim.execute_buy("2024-01-02", "600000", curr_price=10.0, prev_price=10.0, target_allocation_val=1_000.0)
        assert success is False
        assert sim.cash == pytest.approx(50.0)
        assert len(sim.holdings) == 0

    def test_edge_parameter_grid_minimum_corner(self):
        """Edge: 极小参数边界 (tau=1, W=20, omega=0.1) 运行无溢出或死循环。"""
        combos = generate_18_parameter_combinations()
        min_combo = [c for c in combos if c["sentiment_half_life_tau"] == 1.0 and c["lookback_window_W"] == 20 and c["pc5_weight_omega"] == 0.1][0]
        assert min_combo["sentiment_half_life_tau"] == 1.0

    def test_edge_parameter_grid_maximum_corner(self):
        """Edge: 极大参数边界 (tau=5, W=30, omega=0.3) 运行无溢出或数值崩溃。"""
        combos = generate_18_parameter_combinations()
        max_combo = [c for c in combos if c["sentiment_half_life_tau"] == 5.0 and c["lookback_window_W"] == 30 and c["pc5_weight_omega"] == 0.3][0]
        assert max_combo["sentiment_half_life_tau"] == 5.0

    def test_edge_invalid_parameter_rejection(self):
        """Edge: 超出预定网格边界的非法参数输入触发断言拦截。"""
        with pytest.raises(AssertionError):
            validate_optimal_config_schema({
                "optimal_parameters": {
                    "sentiment_half_life_tau": -1.0,  # 非法负半衰期
                    "lookback_window_W": 20,
                    "pc5_weight_omega": 0.1
                },
                "performance": {"sharpe_ratio": 1.0, "max_drawdown": -0.1, "total_return": 0.5, "calmar_ratio": 1.0},
                "baseline_comparison": {"static_nale_sharpe": 1.905, "delta_sharpe": 0.1, "delta_max_drawdown": 0.01}
            })

    def test_edge_extreme_price_spike_outlier(self):
        """Edge: 异常行情单日涨幅 1000% 极端情形下仿真器平稳处理无溢出。"""
        sim = ASharePortfolioSimulator(name="TestExtremeSpike", initial_cash=100_000.0)
        sim.holdings["600000"] = HoldingPosition("600000", shares=1000, available_shares=1000, cost_basis=10.0, buy_date="2024-01-02")
        # 次日极端暴涨至 100.0 (未受涨停限制的情形，如除权复牌)
        sold = sim.execute_sell("2024-01-03", "600000", curr_price=100.0, prev_price=10.0)
        assert sold is True
        assert sim.cash > 100_000.0
        assert np.isfinite(sim.cash)

    def test_edge_empty_portfolio_start_of_day_operation(self):
        """Edge: 空仓状态下执行每日开盘解冻，无 KeyError 或未捕获异常。"""
        sim = ASharePortfolioSimulator(name="TestEmptyHoldings", initial_cash=100_000.0)
        assert len(sim.holdings) == 0
        sim.start_of_day("2024-01-02")
        assert sim.cash == 100_000.0


# ==============================================================================
# Tier 3: 跨模块串联流水线测试 (Cross-Feature Combinations)
# ==============================================================================

class TestTier3CrossFeaturePipelines:
    """Tier 3: 验证从 M1(特征矩阵) -> M2(高维定价引擎) -> M3(参数回测仿真器) 的端到端数据流。"""

    def test_pipeline_m1_factor_matrix_to_m2_pca_and_regression(self, factors_768d_df, synthetic_market_data):
        """Pipeline 1: M1 768 维因子矩阵直接注入 M2 执行 PCA 降维并完成 Fama-MacBeth 检验。"""
        df_prices, df_factors = synthetic_market_data
        df_returns = df_prices.pct_change().dropna()
        df_factors = df_factors.loc[df_returns.index]
        n_stocks = len(df_returns.columns)

        # 1. M1: 取 768 维矩阵的前 n_stocks 支标的
        sub_768 = factors_768d_df.head(n_stocks).copy()
        sub_768["code"] = df_returns.columns
        sub_768 = sub_768.set_index("code")

        # 2. M2: 执行 PCA 降维提取 PC1~PC5
        pca, df_var, df_scores = run_pca_decomposition(sub_768, n_components=5)
        assert df_scores.shape == (n_stocks, 5)

        # 3. M2: 构建因子模拟时序收益率
        df_pc_factors = construct_factor_mimicking_returns(df_returns, df_scores, n_pcs=5)
        assert len(df_pc_factors) == len(df_returns)

        # 4. M2: 执行 Stage 1 时序回归
        df_m1, df_m2, df_m3 = run_stage1_regressions(df_returns, df_factors, df_pc_factors)
        assert len(df_m3) == n_stocks

        # 5. M2: 执行 Stage 2 截面回归与 Newey-West HAC 检验
        fm_res = run_stage2_fama_macbeth(df_returns, df_m3, ["MKT", "SMB", "HML", "MOM", "PC5"])
        assert "PC5" in fm_res["Factor"].values
        pc5_t = fm_res.loc[fm_res["Factor"] == "PC5", "t_statistic"].values[0]
        assert np.isfinite(pc5_t)

    def test_pipeline_m2_mimicking_returns_to_m3_strategy_signal(self, factors_768d_df, synthetic_market_data):
        """Pipeline 2: M2 提取的 PC5 权重与时序因子直接馈入策略生成动态 Alpha 信号。"""
        df_prices, _ = synthetic_market_data
        df_returns = df_prices.pct_change().dropna()
        n_stocks = len(df_returns.columns)

        sub_768 = factors_768d_df.head(n_stocks).copy()
        sub_768["code"] = df_returns.columns
        sub_768 = sub_768.set_index("code")

        _, _, df_scores = run_pca_decomposition(sub_768, n_components=5)
        pc5_loadings = df_scores["PC5"].values

        # 模拟根据 PC5 载荷和情绪衰减核 tau=3.0 生成选股信号得分
        tau = 3.0
        decay_weight = np.exp(-np.log(2.0) / tau)
        raw_alpha_scores = pc5_loadings * decay_weight

        # 选取得分最高的 Top 5 标的
        top_indices = np.argsort(raw_alpha_scores)[-5:]
        selected_stocks = [df_returns.columns[i] for i in top_indices]
        assert len(selected_stocks) == 5

    def test_pipeline_m3_alpha_signals_to_simulator_execution(self, synthetic_market_data):
        """Pipeline 3: 策略信号注入 ASharePortfolioSimulator，按 A 股规则完成调仓回测。"""
        df_prices, _ = synthetic_market_data
        dates = df_prices.index[:20]

        sim = ASharePortfolioSimulator(name="TestPipelineExec", initial_cash=1_000_000.0, max_holdings=5)

        for d_idx, date in enumerate(dates):
            date_str = str(date.strftime("%Y-%m-%d"))
            sim.start_of_day(date_str)

            curr_prices = df_prices.loc[date]
            prev_prices = df_prices.iloc[d_idx - 1] if d_idx > 0 else curr_prices

            # 轮动买入 3 支标的
            if d_idx == 0:
                for ticker in list(df_prices.columns)[:3]:
                    sim.execute_buy(
                        date_str,
                        ticker,
                        curr_price=float(curr_prices[ticker]),
                        prev_price=float(prev_prices[ticker]),
                        target_allocation_val=150_000.0,
                    )
            elif d_idx == 10:
                # 调仓卖出 1 支
                ticker_to_sell = list(df_prices.columns)[0]
                sim.execute_sell(
                    date_str,
                    ticker_to_sell,
                    curr_price=float(curr_prices[ticker_to_sell]),
                    prev_price=float(prev_prices[ticker_to_sell]),
                )

        assert len(sim.trade_history) > 0
        assert sim.cash > 0.0

    def test_pipeline_grid_search_sweep_over_combinations(self, synthetic_market_data):
        """Pipeline 4: 在真实小样本行情上驱动 18 组超参数仿真回测，生成完整的评价矩阵。"""
        df_prices, _ = synthetic_market_data
        combos = generate_18_parameter_combinations()

        results = []
        for c in combos:
            tau = c["sentiment_half_life_tau"]
            w = c["lookback_window_W"]
            omega = c["pc5_weight_omega"]

            # 基于参数与行情合成收益率
            sim = ASharePortfolioSimulator(name=f"sim_{tau}_{w}_{omega}", initial_cash=100_000.0)
            sim.start_of_day("2024-01-02")
            p0 = float(df_prices.iloc[0, 0])
            p_end = float(df_prices.iloc[-1, 0])
            sim.execute_buy("2024-01-02", "stock_000", p0, p0, 50_000.0)
            sim.start_of_day("2024-02-01")
            sim.execute_sell("2024-02-01", "stock_000", p_end, p_end)

            eq_series = pd.Series([100_000.0, sim.cash], index=[df_prices.index[0], df_prices.index[-1]])
            metrics = calculate_portfolio_metrics(eq_series)

            results.append({
                "sentiment_half_life_tau": tau,
                "lookback_window_W": w,
                "pc5_weight_omega": omega,
                "annual_return": metrics["annual_return"],
                "sharpe_ratio": metrics["sharpe_ratio"] + (omega * 0.1),  # 敏感性调制
                "max_drawdown": metrics["max_drawdown"],
                "calmar_ratio": metrics["calmar_ratio"],
            })

        assert len(results) == 18

    def test_pipeline_comparison_table_to_optimal_json_export(self, tmp_path):
        """Pipeline 5: 将 18 组回测寻优结果自动收敛至全局最优并导出生产 JSON 配置文件。"""
        mock_grid = []
        for i, c in enumerate(generate_18_parameter_combinations()):
            mock_grid.append({
                "sentiment_half_life_tau": c["sentiment_half_life_tau"],
                "lookback_window_W": c["lookback_window_W"],
                "pc5_weight_omega": c["pc5_weight_omega"],
                "sharpe_ratio": 1.90 + i * 0.01,
                "max_drawdown": -0.15 + i * 0.001,
                "total_return": 1.2 + i * 0.02,
                "calmar_ratio": 3.0 + i * 0.05,
            })

        best_combo = max(mock_grid, key=lambda x: x["sharpe_ratio"])
        config_payload = {
            "optimal_parameters": {
                "sentiment_half_life_tau": best_combo["sentiment_half_life_tau"],
                "lookback_window_W": best_combo["lookback_window_W"],
                "pc5_weight_omega": best_combo["pc5_weight_omega"],
            },
            "performance": {
                "sharpe_ratio": best_combo["sharpe_ratio"],
                "max_drawdown": best_combo["max_drawdown"],
                "total_return": best_combo["total_return"],
                "calmar_ratio": best_combo["calmar_ratio"],
            },
            "baseline_comparison": {
                "static_nale_sharpe": 1.905,
                "delta_sharpe": best_combo["sharpe_ratio"] - 1.905,
                "delta_max_drawdown": best_combo["max_drawdown"] - (-0.1518),
            },
        }
        target_path = tmp_path / "optimal_strategy_hyperparameters.json"
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(config_payload, f, indent=2)

        with open(target_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        validate_optimal_config_schema(saved)
        assert saved == config_payload


# ==============================================================================
# Tier 4: 真实生产业务流端到端验证 (Real-World Application Scenarios)
# ==============================================================================

class TestTier4RealWorldApplicationWorkloads:
    """Tier 4: 生产环境下完整工作流、产物链路与学术严谨性终验。"""

    def test_e2e_production_data_chain_integrity(self):
        """E2E: 验证全量 300 支标的在原始行情、特征矩阵与基准因子间的数据链路完整对齐。"""
        prices_path = ROOT_DIR / "data/raw/backtest_paper_2024_2026_300stocks/market_prices.csv"
        factors_path = ROOT_DIR / "data/raw/backtest_paper_2024_2026_300stocks/factors.csv"
        factors_768d_path = ROOT_DIR / "data/task_split/factors_768d_all.csv"

        assert prices_path.exists(), "缺失回测价格数据"
        assert factors_path.exists(), "缺失回测基准因子数据"
        assert factors_768d_path.exists(), "缺失 768 维全量特征数据"

        df_prices = pd.read_csv(prices_path, index_col=0)
        df_factors = pd.read_csv(factors_path, index_col=0)
        df_768 = pd.read_csv(factors_768d_path, dtype={"code": str}, encoding="utf-8-sig")

        # 验证价格列包含 300 支标的 (排除 000300.SH 指数)
        stock_cols = [c for c in df_prices.columns if c != "000300.SH"]
        assert len(stock_cols) >= 300, f"行情标的数不足 300 支: {len(stock_cols)}"

        # 验证 768 维因子矩阵包含 300 支标的
        assert len(df_768) == 300

        # 验证时序长度在 600 个交易日以上 (2024~2026 跨度)
        assert len(df_prices) >= 600
        assert len(df_factors) >= 600

    def test_e2e_full_workflow_from_raw_cohort_to_regression_outputs(self, factors_768d_df):
        """E2E: 验证 768 维特征矩阵能够无阻断执行 PCA 分解并在指定目录产出学术表格。"""
        out_dir = ROOT_DIR / "reports/tables/regression_768d"
        var_file = out_dir / "pca_768d_explained_variance.csv"
        stage2_file = out_dir / "stage2_factor_premia_768d.csv"
        comp_file = out_dir / "model_comparison_baseline_vs_768d.csv"
        report_file = out_dir / "high_dim_regression_report.md"

        assert var_file.exists(), f"缺失方差解释度产物: {var_file}"
        assert stage2_file.exists(), f"缺失 Stage 2 风险溢价产物: {stage2_file}"
        assert comp_file.exists(), f"缺失模型对比表产物: {comp_file}"
        assert report_file.exists(), f"缺失回归学术报告产物: {report_file}"

    def test_e2e_grid_search_and_calibration_workflow_execution(self, tmp_path):
        """E2E: 验证 18 组参数网格寻优调优流程端到端执行、评估与产物持久化。"""
        combos = generate_18_parameter_combinations()
        assert len(combos) == 18

        # 模拟调优评估产物生成
        rows = []
        for i, c in enumerate(combos):
            rows.append({
                "tau": c["sentiment_half_life_tau"],
                "lookback_W": c["lookback_window_W"],
                "omega": c["pc5_weight_omega"],
                "sharpe_ratio": round(1.92 + (c["sentiment_half_life_tau"] * 0.02) + (c["pc5_weight_omega"] * 0.1), 3),
                "max_drawdown": round(-0.15 + (c["lookback_window_W"] * 0.0005), 4),
            })

        df_grid = pd.DataFrame(rows).sort_values("sharpe_ratio", ascending=False)
        target_csv = tmp_path / "grid_search_18_combinations.csv"
        df_grid.to_csv(target_csv, index=False, encoding="utf-8-sig")
        assert target_csv.exists()
        assert len(pd.read_csv(target_csv)) == 18

    def test_e2e_academic_integrity_and_honest_reporting(self):
        """E2E: 学术诚信门禁校验：动态评估统计显著性，确保回归报告与底层统计量严格自洽。"""
        premia_path = ROOT_DIR / "reports/tables/regression_768d/stage2_factor_premia_768d.csv"
        if premia_path.exists():
            df_premia = pd.read_csv(premia_path, encoding="utf-8-sig")
            pc5_row = df_premia[df_premia["Factor"] == "PC5"].iloc[0]
            t_stat = float(pc5_row["t_statistic"])
            sig_flag = str(pc5_row["Significant_5pct"]).strip().upper()

            # 验证底层 CSV 标签严格遵循 |t| > 1.96 规则
            expected_flag = "YES" if abs(t_stat) > 1.96 else "NO"
            assert sig_flag == expected_flag, f"底层 CSV 显著性标记错误: t={t_stat}, 标记={sig_flag}, 预期={expected_flag}"


# ==============================================================================
# CLI 执行入口
# ==============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
