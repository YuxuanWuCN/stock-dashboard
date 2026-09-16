#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/merge_300_factors_768d.py

全池 300 标的 768 维因子主表融合与校验脚本 (Milestone 3 Core Merger)。

本脚本执行以下核心工作：
1. 分别加载三大组员的 768D 特征文件：
   - data/task_split/factors_768d_student_A.csv (科技制造 100 支)
   - data/task_split/factors_768d_student_B.csv (新能源周期 100 支)
   - data/task_split/factors_768d_student_C.csv (金融消费 100 支)
2. 严苛质量门禁与契约校验：
   - 每组严格为 100 行 x 780 列；
   - 12 元数据列 + 768 特征维度 (dim_000 ~ dim_767)；
   - 证券代码保持严格 6 位字符串且保留前导零 (zfill(6))；
   - 绝无 'local_semantic' 伪造特征来源（全部为真实抽取）；
   - 全字段零 NaN / 零空值 / 零 Inf；
   - 768 维特征向量严格通过 L2 范数单位归一化 (||v||_2 = 1.0)；
   - 三大组员证券代码互斥且并集严格等于 Universe 300 标的池。
3. 融合生成 master 大表：data/task_split/factors_768d_all.csv (严格 300 行 x 780 列)。
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Set

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
TASK_SPLIT_DIR = ROOT_DIR / "data" / "task_split"

# 12 个元数据列规范
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

# 768 维特征列
DIMENSION_COLUMNS: List[str] = [f"dim_{i:03d}" for i in range(768)]
EXPECTED_780_COLUMNS: List[str] = METADATA_COLUMNS + DIMENSION_COLUMNS

RE_STOCK_CODE = re.compile(r"^\d{6}$")
RE_SHA256_HEX = re.compile(r"^[a-f0-9]{64}$")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("merge_300_factors_768d")


def validate_cohort_df(df: pd.DataFrame, cohort_key: str) -> None:
    """对单组因子 DataFrame 进行严苛契约校验。"""
    assert len(df) == 100, f"{cohort_key} 标的数量不等于 100: 实际 {len(df)}"
    assert df["code"].nunique() == 100, f"{cohort_key} 证券代码存在重复"
    assert list(df.columns) == EXPECTED_780_COLUMNS, f"{cohort_key} 列结构不匹配 780 列规范"

    # 代码前导零
    for idx, code in enumerate(df["code"]):
        assert isinstance(code, str) and len(code) == 6 and RE_STOCK_CODE.match(code), (
            f"{cohort_key} 行 {idx} 证券代码格式非法: '{code}'"
        )

    # 杜绝 local_semantic
    fake_mask = df["feature_source"].astype(str).str.lower().str.contains("local_semantic")
    assert fake_mask.sum() == 0, f"{cohort_key} 存在 {fake_mask.sum()} 条 local_semantic 伪造记录"

    # 零 NaN
    null_count = df.isna().sum().sum()
    assert null_count == 0, f"{cohort_key} 包含 {null_count} 个缺失值"

    # 公告数 > 0
    non_pos_ann = (df["announcement_count"] <= 0).sum()
    assert non_pos_ann == 0, f"{cohort_key} 包含 {non_pos_ann} 个公告数 <= 0 的标的"

    # SHA256 合规
    for idx, sha in enumerate(df["input_sha256"]):
        assert isinstance(sha, str) and len(sha) == 64 and RE_SHA256_HEX.match(sha), (
            f"{cohort_key} 行 {idx} SHA256 格式非法: '{sha}'"
        )

    # 特征矩阵 L2 范数归一化
    mat = df[DIMENSION_COLUMNS].to_numpy(dtype=np.float64)
    assert not np.isnan(mat).any(), f"{cohort_key} 特征矩阵存在 NaN"
    assert not np.isinf(mat).any(), f"{cohort_key} 特征矩阵存在 Inf"
    norms = np.linalg.norm(mat, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-4), (
        f"{cohort_key} L2 范数未归一化至 1.0, 最大偏差: {np.max(np.abs(norms - 1.0)):.6e}"
    )


def merge_and_save() -> Path:
    """读取 A、B、C 三组因子，验证后合并写出全池 factors_768d_all.csv。"""
    cohort_files = {
        "student_A": TASK_SPLIT_DIR / "factors_768d_student_A.csv",
        "student_B": TASK_SPLIT_DIR / "factors_768d_student_B.csv",
        "student_C": TASK_SPLIT_DIR / "factors_768d_student_C.csv",
    }

    dfs: List[pd.DataFrame] = []
    codes_seen: Set[str] = set()

    for cohort_key, path in cohort_files.items():
        assert path.exists(), f"因子文件不存在: {path}"
        logger.info(f"读取并校验 {cohort_key} 因子文件: {path}")
        df = pd.read_csv(path, dtype={"code": str}, encoding="utf-8-sig")
        # 强制确保 6 位前导零代码
        df["code"] = df["code"].astype(str).str.zfill(6)
        validate_cohort_df(df, cohort_key)

        cohort_codes = set(df["code"])
        assert codes_seen.isdisjoint(cohort_codes), (
            f"{cohort_key} 与前面组别存在重复代码: {codes_seen & cohort_codes}"
        )
        codes_seen.update(cohort_codes)
        dfs.append(df)

    # 校验 Universe 300 并集完备性
    universe_path = TASK_SPLIT_DIR / "universe_300_assigned.csv"
    if universe_path.exists():
        u_df = pd.read_csv(universe_path, dtype={"code": str}, encoding="utf-8-sig")
        u_codes = set(u_df["code"].astype(str).str.zfill(6))
        assert codes_seen == u_codes, (
            f"融合代码集与 universe_300 不一致! 缺失: {u_codes - codes_seen}, 多余: {codes_seen - u_codes}"
        )
        logger.info(f"✅ 与 universe_300_assigned.csv 300 支标的严格一致且无缝完备覆盖")

    df_all = pd.concat(dfs, ignore_index=True)
    assert df_all.shape == (300, 780), f"合并后形状异常: {df_all.shape}"
    assert df_all["code"].nunique() == 300, "合并后代码非 300 唯一"
    assert df_all.isna().sum().sum() == 0, "合并后存在缺失值"

    out_file = TASK_SPLIT_DIR / "factors_768d_all.csv"
    logger.info(f"写出全池因子大表: {out_file} (300 行 x 780 列)")
    df_all.to_csv(out_file, index=False, encoding="utf-8-sig")

    # 二次加载校验
    df_reloaded = pd.read_csv(out_file, dtype={"code": str}, encoding="utf-8-sig")
    assert df_reloaded.shape == (300, 780), f"重新加载形状异常: {df_reloaded.shape}"
    assert (df_reloaded["code"].str.len() == 6).all(), "重新加载存在非 6 位代码"
    assert not df_reloaded["feature_source"].str.contains("local_semantic").any(), "包含 local_semantic"
    assert df_reloaded.isna().sum().sum() == 0, "重新加载包含 NaN"

    logger.info(f"✅ 全池 300 标的 768D 因子主表融合校验 100% 通过！")
    return out_file


if __name__ == "__main__":
    merge_and_save()
