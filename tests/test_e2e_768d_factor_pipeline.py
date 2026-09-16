# -*- coding: utf-8 -*-
"""
tests/test_e2e_768d_factor_pipeline.py

R-FinGPTv2 端到端 768 维量化因子提取与高维资产定价黑盒验收测试套件
(E2E 768D Factor Pipeline & Asset Pricing Opaque-Box Acceptance Test Suite)

权威依据：
- .agents/ORIGINAL_REQUEST.md (§ 2026-09-08T15:31:38Z)
- PROJECT.md (§ Interface Contracts, § Feature Inventory)
- data/task_split/student_b/SUBMISSION_SCOPE.md (基准规范)

分层架构 (Tiers 1-4):
- Tier 1: 功能契约覆盖 (Feature Coverage)
- Tier 2: 边界与异常防御 (Boundary & Anti-Slop Defensive Tests)
- Tier 3: 跨模块协同流水线 (Cross-Feature Combinations & Consistency)
- Tier 4: 全链路生产终验与学术诚信 (Real-World Acceptance & Academic Integrity)
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Dict, List, Set

import numpy as np
import pandas as pd
import pytest

# 项目根目录与核心数据目录
ROOT_DIR = Path(__file__).resolve().parents[1]
TASK_SPLIT_DIR = ROOT_DIR / "data" / "task_split"
REGRESSION_DIR = ROOT_DIR / "reports" / "tables" / "regression_768d"

# 12 个元数据列名规范
METADATA_COLUMNS: List[str] = [
    "code",
    "name",
    "sub_industry",
    "sector",
    "cohort_key",
    "feature_source",
    "embedding_source",
    "news_count",
    "announcement_count",
    "input_sha256",
    "retrieved_at_utc",
    "llm_summary",
]

# 768 维特征列名规范 (dim_000 ~ dim_767)
DIMENSION_COLUMNS: List[str] = [f"dim_{i:03d}" for i in range(768)]

# 完整 780 列契约
EXPECTED_780_COLUMNS: List[str] = METADATA_COLUMNS + DIMENSION_COLUMNS

# 正则表达式契约
RE_STOCK_CODE = re.compile(r"^\d{6}$")
RE_SHA256_HEX = re.compile(r"^[a-f0-9]{64}$")
RE_ISO8601_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)

# 标的清单文件路径
COHORT_LIST_FILES: Dict[str, Path] = {
    "student_A": TASK_SPLIT_DIR / "student_A_tech_manufacturing_100.csv",
    "student_B": TASK_SPLIT_DIR / "student_B_energy_materials_100.csv",
    "student_C": TASK_SPLIT_DIR / "student_C_finance_consumer_100.csv",
}

# 因子产物 CSV 文件路径
COHORT_FACTOR_FILES: Dict[str, Path] = {
    "student_A": TASK_SPLIT_DIR / "factors_768d_student_A.csv",
    "student_B": TASK_SPLIT_DIR / "factors_768d_student_B.csv",
    "student_C": TASK_SPLIT_DIR / "factors_768d_student_C.csv",
}

# 溯源存证 JSON 文件路径
COHORT_PROVENANCE_FILES: Dict[str, Path] = {
    "student_A": TASK_SPLIT_DIR / "factors_768d_student_A_provenance.json",
    "student_B": TASK_SPLIT_DIR / "factors_768d_student_B_provenance.json",
    "student_C": TASK_SPLIT_DIR / "factors_768d_student_C_provenance.json",
}

ALL_FACTORS_FILE = TASK_SPLIT_DIR / "factors_768d_all.csv"
UNIVERSE_300_FILE = TASK_SPLIT_DIR / "universe_300_assigned.csv"


# ==============================================================================
# Helper Functions
# ==============================================================================

def load_factor_csv(csv_path: Path) -> pd.DataFrame:
    """以严格代码字符串格式加载因子 CSV 文件。"""
    assert csv_path.exists(), f"因子文件不存在: {csv_path}"
    return pd.read_csv(csv_path, dtype={"code": str}, encoding="utf-8-sig")


def load_target_codes(list_path: Path) -> Set[str]:
    """加载标的清单中的 6 位代码集合。"""
    assert list_path.exists(), f"标的清单文件不存在: {list_path}"
    df = pd.read_csv(list_path, dtype={"code": str}, encoding="utf-8-sig")
    return set(df["code"].astype(str).str.zfill(6))


# ==============================================================================
# Tier 1: 功能契约覆盖 (Feature Coverage)
# ==============================================================================

class TestTier1FeatureCoverage:
    """Tier 1: 验证 A 组与 C 组标的覆盖率、证券代码规整度、780 列大表结构与 L2 归一化。"""

    def test_tier1_student_a_coverage_100(self):
        """【Tier 1.1】验证同学 A（科技制造）768D 因子文件 100/100 标的全量覆盖且无重复。"""
        csv_path = COHORT_FACTOR_FILES["student_A"]
        df = load_factor_csv(csv_path)

        assert len(df) == 100, f"同学 A 标的数量不等于 100: 实际 {len(df)}"
        assert df["code"].nunique() == 100, "同学 A 证券代码存在重复"

        target_codes = load_target_codes(COHORT_LIST_FILES["student_A"])
        actual_codes = set(df["code"])
        missing_codes = target_codes - actual_codes
        extra_codes = actual_codes - target_codes

        assert len(missing_codes) == 0, f"同学 A 缺失目标标的: {missing_codes}"
        assert len(extra_codes) == 0, f"同学 A 包含未知多余标的: {extra_codes}"
        assert (df["cohort_key"] == "student_A").all(), "cohort_key 列存在非 student_A 记录"

    def test_tier1_student_c_coverage_100(self):
        """【Tier 1.2】验证同学 C（金融消费）768D 因子文件 100/100 标的全量覆盖且无重复。"""
        csv_path = COHORT_FACTOR_FILES["student_C"]
        df = load_factor_csv(csv_path)

        assert len(df) == 100, f"同学 C 标的数量不等于 100: 实际 {len(df)}"
        assert df["code"].nunique() == 100, "同学 C 证券代码存在重复"

        target_codes = load_target_codes(COHORT_LIST_FILES["student_C"])
        actual_codes = set(df["code"])
        missing_codes = target_codes - actual_codes
        extra_codes = actual_codes - target_codes

        assert len(missing_codes) == 0, f"同学 C 缺失目标标的: {missing_codes}"
        assert len(extra_codes) == 0, f"同学 C 包含未知多余标的: {extra_codes}"
        assert (df["cohort_key"] == "student_C").all(), "cohort_key 列存在非 student_C 记录"

    def test_tier1_student_b_reference_coverage_100(self):
        """【Tier 1.3】参考基准复核：验证同学 B 已就绪文件覆盖 100/100 标的。"""
        csv_path = COHORT_FACTOR_FILES["student_B"]
        df = load_factor_csv(csv_path)

        assert len(df) == 100, f"同学 B 标的数量不等于 100: 实际 {len(df)}"
        assert df["code"].nunique() == 100, "同学 B 证券代码存在重复"
        target_codes = load_target_codes(COHORT_LIST_FILES["student_B"])
        assert set(df["code"]) == target_codes, "同学 B 标的集合与清单不一致"

    @pytest.mark.parametrize("cohort_key", ["student_A", "student_B", "student_C"])
    def test_tier1_stock_codes_6digit_zero_padded(self, cohort_key: str):
        """【Tier 1.4】验证三组标的代码严格为 6 位数字字符串格式，无前导零截断。"""
        csv_path = COHORT_FACTOR_FILES[cohort_key]
        df = load_factor_csv(csv_path)

        for idx, code in enumerate(df["code"]):
            assert isinstance(code, str), f"行 {idx} code 不是字符串: {type(code)}"
            assert len(code) == 6, f"行 {idx} code 长度不为 6: '{code}'"
            assert RE_STOCK_CODE.match(code), f"行 {idx} code 不符合 6 位数字正则: '{code}'"

    @pytest.mark.parametrize("cohort_key", ["student_A", "student_B", "student_C"])
    def test_tier1_csv_schema_exact_780_columns(self, cohort_key: str):
        """【Tier 1.5】验证因子宽表严格符合 780 列规范（12 元数据列 + 768 特征维度）。"""
        csv_path = COHORT_FACTOR_FILES[cohort_key]
        df = load_factor_csv(csv_path)

        actual_cols = list(df.columns)
        assert len(actual_cols) == 780, (
            f"{cohort_key} 总列数不等于 780: 实际 {len(actual_cols)} (元数据 12 + 特征 768)"
        )
        assert actual_cols[:12] == METADATA_COLUMNS, (
            f"{cohort_key} 前 12 个元数据列名或顺序不匹配:\n"
            f"预期: {METADATA_COLUMNS}\n实际: {actual_cols[:12]}"
        )
        assert actual_cols[12:] == DIMENSION_COLUMNS, (
            f"{cohort_key} 768 个特征维度列名不符合 dim_000 ~ dim_767 规范"
        )

    @pytest.mark.parametrize("cohort_key", ["student_A", "student_B", "student_C"])
    def test_tier1_matrix_finite_float64_zero_nan(self, cohort_key: str):
        """【Tier 1.6】验证 768 维特征矩阵数值均为有限 float64 浮点数，严格零 NaN/Inf。"""
        csv_path = COHORT_FACTOR_FILES[cohort_key]
        df = load_factor_csv(csv_path)

        feature_matrix = df[DIMENSION_COLUMNS].to_numpy(dtype=np.float64)
        assert feature_matrix.shape == (100, 768), f"特征矩阵形状异常: {feature_matrix.shape}"
        assert not np.isnan(feature_matrix).any(), f"{cohort_key} 768 维矩阵中包含 NaN 缺失值"
        assert not np.isinf(feature_matrix).any(), f"{cohort_key} 768 维矩阵中包含 Inf 无穷大值"

    @pytest.mark.parametrize("cohort_key", ["student_A", "student_B", "student_C"])
    def test_tier1_l2_norm_normalization(self, cohort_key: str):
        """【Tier 1.7】验证每支标的 768 维特征行向量严格满足 L2 范数单位归一化 (||v||_2 = 1.0 ± 1e-4)。"""
        csv_path = COHORT_FACTOR_FILES[cohort_key]
        df = load_factor_csv(csv_path)

        feature_matrix = df[DIMENSION_COLUMNS].to_numpy(dtype=np.float64)
        norms = np.linalg.norm(feature_matrix, axis=1)

        deviations = np.abs(norms - 1.0)
        max_dev = deviations.max()
        assert np.allclose(norms, 1.0, atol=1e-4), (
            f"{cohort_key} L2 范数未严格归一化至 1.0, 最大偏差: {max_dev:.6f}, "
            f"min={norms.min():.6f}, max={norms.max():.6f}"
        )


# ==============================================================================
# Tier 2: 边界与异常防御 (Boundary & Defensive Tests)
# ==============================================================================

class TestTier2BoundaryAndCornerCases:
    """Tier 2: 验证前导零边界股票、公告数正数、SHA256 哈希与 ISO 时间戳规范。"""

    def test_tier2_leading_zeros_preservation_boundary_stocks(self):
        """【Tier 2.1】重点边界校验：含有前导零的典型股票在各组中保持完整字符串形式。"""
        # 典型前导零标的抽样
        key_stocks = {
            "student_A": ["002594", "002415", "000021", "000063", "000725"],  # 比亚迪、海康威视等
            "student_B": ["000591", "001289"],                                  # 太阳能、豫能控股
            "student_C": ["000001", "000002", "002142", "000858", "000568"],  # 平安银行、万科A等
        }

        for cohort_key, test_codes in key_stocks.items():
            csv_path = COHORT_FACTOR_FILES[cohort_key]
            df = load_factor_csv(csv_path)
            codes_in_df = set(df["code"])

            for expected_code in test_codes:
                assert expected_code in codes_in_df, (
                    f"{cohort_key} 中未找到典型前导零代码 '{expected_code}'"
                )
                row = df[df["code"] == expected_code]
                assert len(row) == 1, f"代码 '{expected_code}' 存在多行或未找到"
                code_val = row["code"].values[0]
                assert code_val.startswith("0"), f"代码 '{code_val}' 前导零丢失"
                assert len(code_val) == 6, f"代码 '{code_val}' 长度非 6 位"

    @pytest.mark.parametrize("cohort_key", ["student_A", "student_B", "student_C"])
    def test_tier2_positive_announcement_count(self, cohort_key: str):
        """【Tier 2.2】真实语料门禁：每支标的的 announcement_count 必须严格大于 0。"""
        csv_path = COHORT_FACTOR_FILES[cohort_key]
        df = load_factor_csv(csv_path)

        assert "announcement_count" in df.columns, f"{cohort_key} 缺失 announcement_count 列"
        counts = df["announcement_count"].to_numpy()

        assert np.issubdtype(counts.dtype, np.integer), (
            f"{cohort_key} announcement_count 必须为整数类型: 实际 {counts.dtype}"
        )
        non_positive = df[df["announcement_count"] <= 0]
        assert len(non_positive) == 0, (
            f"{cohort_key} 存在公告数 <= 0 的标的（违反真实源准入契约）:\n"
            f"{non_positive[['code', 'name', 'announcement_count']]}"
        )

    @pytest.mark.parametrize("cohort_key", ["student_A", "student_B", "student_C"])
    def test_tier2_sha256_lowercase_hex_format(self, cohort_key: str):
        """【Tier 2.3】存证哈希格式：input_sha256 必须为长度 64 位的小写十六进制字符串。"""
        csv_path = COHORT_FACTOR_FILES[cohort_key]
        df = load_factor_csv(csv_path)

        assert "input_sha256" in df.columns, f"{cohort_key} 缺失 input_sha256 列"

        for idx, h in enumerate(df["input_sha256"]):
            assert isinstance(h, str), f"行 {idx} input_sha256 不是字符串: {type(h)}"
            assert len(h) == 64, f"行 {idx} input_sha256 长度不等于 64: '{h}'"
            assert RE_SHA256_HEX.match(h), f"行 {idx} input_sha256 不符合小写 16 进制: '{h}'"
            assert h != "0" * 64, f"行 {idx} input_sha256 为全零占位符"
            assert "local_semantic" not in h.lower(), f"行 {idx} input_sha256 包含伪造字符串"

    @pytest.mark.parametrize("cohort_key", ["student_A", "student_B", "student_C"])
    def test_tier2_retrieved_at_utc_iso8601(self, cohort_key: str):
        """【Tier 2.4】时间戳合规性：retrieved_at_utc 必须符合 ISO 8601 UTC 时间格式。"""
        csv_path = COHORT_FACTOR_FILES[cohort_key]
        df = load_factor_csv(csv_path)

        assert "retrieved_at_utc" in df.columns, f"{cohort_key} 缺失 retrieved_at_utc 列"

        for idx, ts in enumerate(df["retrieved_at_utc"]):
            assert isinstance(ts, str), f"行 {idx} 时间戳不是字符串: {type(ts)}"
            assert RE_ISO8601_UTC.match(ts), f"行 {idx} 时间戳不符合 ISO 8601 格式: '{ts}'"
            # 验证 datetime.fromisoformat 可安全解析
            try:
                dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                assert dt.year >= 2024, f"行 {idx} 时间戳年份异常: {dt.year}"
            except Exception as e:
                pytest.fail(f"行 {idx} 时间戳无法解析为 datetime: {ts} ({e})")

    @pytest.mark.parametrize("cohort_key", ["student_A", "student_B", "student_C"])
    def test_tier2_non_degenerate_embedding_space(self, cohort_key: str):
        """【Tier 2.5】表征质量检查：768 维特征矩阵不得退化为常量向量或一对一完全共线。"""
        csv_path = COHORT_FACTOR_FILES[cohort_key]
        df = load_factor_csv(csv_path)

        matrix = df[DIMENSION_COLUMNS].to_numpy(dtype=np.float64)

        # 检查方差：各维度的跨股票方差总和必须显著大于 0
        variances = np.var(matrix, axis=0)
        assert variances.sum() > 1e-4, f"{cohort_key} 特征方差接近 0，疑似退化常数矩阵"

        # 检查任意两支相邻股票之间的余弦相似度必须严格 < 0.9999
        sample_cosines = []
        for i in range(min(10, len(matrix) - 1)):
            v1 = matrix[i]
            v2 = matrix[i + 1]
            cos_sim = float(np.dot(v1, v2))
            sample_cosines.append(cos_sim)
            assert cos_sim < 0.9999, (
                f"{cohort_key} 股票 {df['code'].iloc[i]} 与 {df['code'].iloc[i+1]} "
                f"余弦相似度达到 {cos_sim:.6f}，疑似退化重复向量"
            )


# ==============================================================================
# Tier 3: 跨模块协同流水线 (Cross-Feature Combinations & Consistency)
# ==============================================================================

class TestTier3CrossFeatureCombinations:
    """Tier 3: 验证 CSV 与 JSON 存证镜像一致性、标的池三分完备性以及高维回归统计单调性。"""

    @pytest.mark.parametrize("cohort_key", ["student_A", "student_B", "student_C"])
    def test_tier3_csv_and_json_provenance_sync(self, cohort_key: str):
        """【Tier 3.1】存证双向一致性：CSV 元数据与 JSON 存证文件逐股 1:1 镜像同步。"""
        json_path = COHORT_PROVENANCE_FILES[cohort_key]
        assert json_path.exists(), f"存证 JSON 文件缺失: {json_path}"

        with open(json_path, "r", encoding="utf-8") as f:
            prov_data = json.load(f)

        assert prov_data.get("schema_version") == 1, "存证 JSON schema_version 不为 1"
        assert prov_data.get("cohort") == cohort_key, f"存证 cohort 与期望不符: {prov_data.get('cohort')}"
        assert prov_data.get("stocks") == 100, f"存证 stocks 数量不等于 100: {prov_data.get('stocks')}"
        assert "provenance" in prov_data, "存证缺少 provenance 列表"

        prov_list = prov_data["provenance"]
        assert len(prov_list) == 100, f"provenance 列表长度不等于 100: 实际 {len(prov_list)}"

        # 映射到字典
        prov_map = {item["code"]: item for item in prov_list}
        assert len(prov_map) == 100, "provenance 列表中存在重复 code"

        csv_path = COHORT_FACTOR_FILES[cohort_key]
        df = load_factor_csv(csv_path)

        for _, row in df.iterrows():
            code = row["code"]
            assert code in prov_map, f"CSV 中的股票代码 '{code}' 在存证 JSON 中未找到"
            p_item = prov_map[code]

            # 严格核对四项存证字段
            assert row["input_sha256"] == p_item["input_sha256"], (
                f"标的 {code} 的 input_sha256 在 CSV 与 JSON 中不一致: "
                f"CSV='{row['input_sha256']}', JSON='{p_item['input_sha256']}'"
            )
            assert int(row["announcement_count"]) == int(p_item["announcement_count"]), (
                f"标的 {code} 的 announcement_count 在 CSV 与 JSON 中不一致"
            )
            assert int(row["news_count"]) == int(p_item["news_count"]), (
                f"标的 {code} 的 news_count 在 CSV 与 JSON 中不一致"
            )
            assert row["retrieved_at_utc"] == p_item["retrieved_at_utc"], (
                f"标的 {code} 的 retrieved_at_utc 在 CSV 与 JSON 中不一致"
            )

    def test_tier3_cohort_triplet_disjointness_and_universe_union(self):
        """【Tier 3.2】集合完备性数学检验：A/B/C 三组两两互斥且并集严格等于 Universe 300。"""
        codes_a = load_target_codes(COHORT_LIST_FILES["student_A"])
        codes_b = load_target_codes(COHORT_LIST_FILES["student_B"])
        codes_c = load_target_codes(COHORT_LIST_FILES["student_C"])
        universe_codes = load_target_codes(UNIVERSE_300_FILE)

        assert len(codes_a) == 100, f"A 组清单非 100 支: {len(codes_a)}"
        assert len(codes_b) == 100, f"B 组清单非 100 支: {len(codes_b)}"
        assert len(codes_c) == 100, f"C 组清单非 100 支: {len(codes_c)}"
        assert len(universe_codes) == 300, f"Universe 300 清单非 300 支: {len(universe_codes)}"

        # 两两互斥
        assert codes_a.isdisjoint(codes_b), f"A 组与 B 组存在交集: {codes_a & codes_b}"
        assert codes_b.isdisjoint(codes_c), f"B 组与 C 组存在交集: {codes_b & codes_c}"
        assert codes_a.isdisjoint(codes_c), f"A 组与 C 组存在交集: {codes_a & codes_c}"

        # 完备覆盖并集
        union_abc = codes_a | codes_b | codes_c
        assert union_abc == universe_codes, (
            f"A/B/C 并集与 Universe 300 不一致: "
            f"缺失={universe_codes - union_abc}, 多余={union_abc - universe_codes}"
        )

    def test_tier3_all_table_factor_fusion_cross_sync(self):
        """【Tier 3.3】大表聚合一致性：factors_768d_all.csv 精确包含 A/B/C 三组所有标的与特征。"""
        df_all = load_factor_csv(ALL_FACTORS_FILE)
        assert len(df_all) == 300, f"all 大表行数不为 300: 实际 {len(df_all)}"

        for cohort_key in ["student_A", "student_B", "student_C"]:
            csv_path = COHORT_FACTOR_FILES[cohort_key]
            sub_df = load_factor_csv(csv_path)

            all_sub = df_all[df_all["cohort_key"] == cohort_key]
            assert len(all_sub) == 100, f"all 大表中 {cohort_key} 数量不等于 100: 实际 {len(all_sub)}"

            # 校验代码集完全相同
            assert set(sub_df["code"]) == set(all_sub["code"]), (
                f"all 大表中 {cohort_key} 代码集与子表不一致"
            )

    def test_tier3_econometric_regression_consistency(self):
        """【Tier 3.4】资产定价一致性：Model 3 (4F + PC5) 相对 Model 1 具备增量 R^2 与 GRS 收敛。"""
        comparison_csv = REGRESSION_DIR / "model_comparison_baseline_vs_768d.csv"
        assert comparison_csv.exists(), f"回归对比表缺失: {comparison_csv}"

        df = pd.read_csv(comparison_csv, encoding="utf-8")
        assert "Metric" in df.columns, "对比表缺失 Metric 列"

        metric_map = df.set_index("Metric").to_dict(orient="index")

        # 1. 验证 R^2 增量提升 (Delta R^2 > 0)
        r2_key = [k for k in metric_map.keys() if "Average R²" in k or "R²" in k][0]
        m1_r2 = float(metric_map[r2_key]["Model_1 (Carhart 4F Baseline)"])
        m3_r2 = float(metric_map[r2_key]["Model_3 (Carhart 4F + PC5_768d)"])
        assert m3_r2 > m1_r2, f"Model 3 R^2 ({m3_r2}) 未高于 Model 1 ({m1_r2})"

        # 2. 验证 GRS 统计量收敛或平抑 (M3 <= M1)
        grs_key = [k for k in metric_map.keys() if "Gibbons-Ross-Shanken" in k or "GRS" in k][0]
        m1_grs = float(metric_map[grs_key]["Model_1 (Carhart 4F Baseline)"])
        m3_grs = float(metric_map[grs_key]["Model_3 (Carhart 4F + PC5_768d)"])
        assert m3_grs <= m1_grs, f"Model 3 GRS 统计量 ({m3_grs}) 未小于等于 Model 1 ({m1_grs})"


# ==============================================================================
# Tier 4: 全链路生产终验与学术诚信 (Real-World Acceptance)
# ==============================================================================

class TestTier4RealWorldAcceptance:
    """Tier 4: 验证 300 标的全池大表生产就绪、取缔 local_semantic、学术产物完整与客观披露。"""

    def test_tier4_merged_master_table_integrity(self):
        """【Tier 4.1】全量大表验收：factors_768d_all.csv 结构为严格 300 行 × 780 列。"""
        df = load_factor_csv(ALL_FACTORS_FILE)

        assert df.shape == (300, 780), f"全池大表形状不符合 300x780: 实际 {df.shape}"
        assert df["code"].nunique() == 300, "全池大表存在重复股票代码"
        assert list(df.columns) == EXPECTED_780_COLUMNS, "全池大表列名及顺序不符合 780 列契约"

        # 验证组别各占 100 支
        counts = df["cohort_key"].value_counts().to_dict()
        expected_counts = {"student_A": 100, "student_B": 100, "student_C": 100}
        assert counts == expected_counts, f"全池大表各组别数量分配异常: {counts}"

        # 验证 300 支特征矩阵无 NaN/Inf 且严格归一化
        matrix = df[DIMENSION_COLUMNS].to_numpy(dtype=np.float64)
        assert not np.isnan(matrix).any(), "全池大表特征矩阵存在 NaN"
        assert not np.isinf(matrix).any(), "全池大表特征矩阵存在 Inf"
        norms = np.linalg.norm(matrix, axis=1)
        assert np.allclose(norms, 1.0, atol=1e-4), "全池大表存在未满足 L2 归一化的向量"

    def test_tier4_absence_of_local_semantic_pseudohash(self):
        """【Tier 4.2】零伪造终审门禁：全池 300 标的中严禁包含 'local_semantic' 伪造哈希。"""
        df = load_factor_csv(ALL_FACTORS_FILE)

        # 1. 检查 feature_source
        fake_mask = df["feature_source"].astype(str).str.lower().str.contains("local_semantic")
        fake_count = fake_mask.sum()
        assert fake_count == 0, (
            f"全池大表中仍残留 {fake_count} 支标的包含 'local_semantic' 伪造特征来源！\n"
            f"{df[fake_mask][['code', 'name', 'cohort_key', 'feature_source']]}"
        )

        # 2. 检查 input_sha256 无缺失与空值
        nan_sha_mask = df["input_sha256"].isna() | (df["input_sha256"] == "")
        nan_sha_count = nan_sha_mask.sum()
        assert nan_sha_count == 0, (
            f"全池大表中仍有 {nan_sha_count} 支标的缺失 input_sha256 溯源哈希"
        )

        # 3. 检查 announcement_count 全量 > 0
        zero_ann_mask = df["announcement_count"].isna() | (df["announcement_count"] <= 0)
        assert zero_ann_mask.sum() == 0, (
            f"全池大表中存在 {zero_ann_mask.sum()} 支标的公告篇数 <= 0"
        )

    def test_tier4_seven_regression_artifacts_exist_and_valid(self):
        """【Tier 4.3】计量报告就绪：reports/tables/regression_768d/ 下 7 项学术产物完备且非空。"""
        required_artifacts = [
            ("pca_768d_explained_variance.csv", 10),                 # 10 个主成分
            ("stage1_time_series_regression_summary.csv", 300),      # 300 支标的
            ("stage1_stock_betas_768d.csv", 300),                    # 300 支标的
            ("stage2_factor_premia_768d.csv", 6),                    # 截距 + 5 个因子 (MKT, SMB, HML, MOM, PC5)
            ("ridge_cross_sectional_top_factors.csv", 768),          # 768 个全量因子排序
            ("model_comparison_baseline_vs_768d.csv", 6),            # 6 行关键统计指标
            ("high_dim_regression_report.md", None),                 # 学术报告 Markdown
        ]

        for filename, expected_min_rows in required_artifacts:
            file_path = REGRESSION_DIR / filename
            assert file_path.exists(), f"学术回归产物缺失: {file_path}"
            assert file_path.stat().st_size > 100, f"学术回归产物文件过小或为空: {file_path}"

            if expected_min_rows is not None:
                sub_df = pd.read_csv(file_path, encoding="utf-8")
                assert len(sub_df) >= expected_min_rows, (
                    f"产物 {filename} 行数不足: 预期 >= {expected_min_rows}, 实际 {len(sub_df)}"
                )

    def test_tier4_academic_integrity_significance_audit(self):
        """【Tier 4.4】学术诚信门禁：严格根据 Newey-West t 统计量动态判定，杜绝假性显著性声明。"""
        premia_file = REGRESSION_DIR / "stage2_factor_premia_768d.csv"
        report_file = REGRESSION_DIR / "high_dim_regression_report.md"

        assert premia_file.exists(), f"风险溢价表缺失: {premia_file}"
        assert report_file.exists(), f"回归报告缺失: {report_file}"

        premia_df = pd.read_csv(premia_file, encoding="utf-8")
        pc5_rows = premia_df[premia_df["Factor"] == "PC5"]
        assert len(pc5_rows) == 1, "未在 stage2_factor_premia_768d.csv 中找到 PC5 因子"

        pc5_row = pc5_rows.iloc[0]
        t_stat = float(pc5_row["t_statistic"])
        sig_5pct = str(pc5_row["Significant_5pct"]).strip().upper()

        report_content = report_file.read_text(encoding="utf-8")

        # AGENTS.md 红线规则：若 |t| <= 1.96，则 5% 检验必须为 NO，且报告不得宣称显著
        if abs(t_stat) <= 1.96:
            assert sig_5pct == "NO", f"|t|={abs(t_stat):.2f} <= 1.96，但 Significant_5pct 标记为 '{sig_5pct}'"
            assert "当前未达 5% 显著水平" in report_content or "未达 5% 显著" in report_content, (
                "PC5 未达显著水平时，报告中未如实客观披露 '当前未达 5% 显著水平'"
            )
            assert "严格遵循 AGENTS.md 质量门禁准则，不伪造统计显著性" in report_content, (
                "学术报告必须明确阐述学术诚信与不伪造显著性的原则"
            )
        else:
            assert sig_5pct == "YES", f"|t|={abs(t_stat):.2f} > 1.96，但 Significant_5pct 标记为 '{sig_5pct}'"
