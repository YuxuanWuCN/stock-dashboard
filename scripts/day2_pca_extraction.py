#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/day2_pca_extraction.py - Week 1 Day 2: PCA降维与PC5特征提取

功能:
1. 加载 Day 1 准备好的干净因子矩阵 data/week1_pca/factors_for_pca.csv。
2. 调用 src.pricing.factor_orthogonalization.pca_factor_reduction 进行标准化与 PCA 正交降维。
3. 提取 PC5（第5主成分）并分析其在各原始因子上的载荷（Loadings）。
4. 导出交付物至 data/week1_pca/：
   - pc5_raw.csv (PC5 原始时间序列)
   - all_pcs.csv (全部主成分时间序列)
   - pca_loadings.csv (因子载荷矩阵)

负责人: CS 算法成员 + 算法团队
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import sys
from pathlib import Path

# 添加项目根目录到 Python 搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from src.pricing.factor_orthogonalization import pca_factor_reduction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("day2_pca")


def run_pca_pipeline(
    input_file: Path = Path("data/week1_pca/factors_for_pca.csv"),
    output_dir: Path = Path("data/week1_pca"),
    n_components: int = 5
):
    """运行 PCA 降维流水线。"""
    if not input_file.exists():
        raise FileNotFoundError(
            f"未找到输入因子文件: {input_file}。请先运行 Day 1 脚本: python scripts/day1_prepare_factor_data.py"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("Day 2: PCA 因子降维与 PC5 提取")
    logger.info("=" * 60)

    # 1. 读取数据
    factors_df = pd.read_csv(input_file, index_col=0, parse_dates=True)
    logger.info(f"读取因子矩阵: {factors_df.shape} (行=日期, 列=因子)")
    logger.info(f"因子列表: {list(factors_df.columns)}")

    # 2. 检查因子数量
    max_k = factors_df.shape[1]
    k = min(n_components, max_k)
    logger.info(f"准备提取前 {k} 个主成分 (样本数={len(factors_df)}, 因子数={max_k})")

    # 3. 执行 PCA 降维
    pcs_df, loadings_df = pca_factor_reduction(
        factors_df,
        n_components=k,
        standardize=True,
        return_loadings=True
    )
    logger.info(f"PCA 降维完成，主成分形状: {pcs_df.shape}")

    # 4. 提取 PC5 或指定成分
    target_pc = f"PC{k}" if f"PC{n_components}" not in pcs_df.columns else f"PC{n_components}"
    pc_series = pcs_df[target_pc].rename("PC5_raw")
    logger.info(f"提取目标主成分: {target_pc} -> 别名 PC5_raw")

    # 5. 统计特性检验
    logger.info("=" * 60)
    logger.info("PC5 统计特征:")
    logger.info(f"  - 均值 (期望~0): {pc_series.mean():.4f}")
    logger.info(f"  - 标准差 (期望~1): {pc_series.std():.4f}")
    logger.info(f"  - 偏度 (Skew): {pc_series.skew():.4f}")
    logger.info(f"  - 峰度 (Kurtosis): {pc_series.kurt():.4f}")
    logger.info(f"  - 最值区间: [{pc_series.min():.4f}, {pc_series.max():.4f}]")
    logger.info("=" * 60)

    # 6. 分析 PC5 因子载荷
    if target_pc in loadings_df.columns:
        loadings = loadings_df[target_pc].sort_values(key=abs, ascending=False)
        logger.info(f"{target_pc} 在各因子的载荷绝对值排序:")
        for factor_name, weight in loadings.items():
            logger.info(f"    {factor_name:<25}: {weight:+.4f}")

    # 7. 保存产物
    pc5_path = output_dir / "pc5_raw.csv"
    pcs_path = output_dir / "all_pcs.csv"
    loadings_path = output_dir / "pca_loadings.csv"

    pc_series.to_csv(pc5_path, header=True)
    pcs_df.to_csv(pcs_path)
    loadings_df.to_csv(loadings_path)

    logger.info(f"\n✅ 产物已保存:")
    logger.info(f"  1. PC5 原始序列: {pc5_path}")
    logger.info(f"  2. 全部主成分:   {pcs_path}")
    logger.info(f"  3. 因子载荷矩阵: {loadings_path}")


def main():
    parser = argparse.ArgumentParser(description="Week 1 Day 2: PCA降维与PC5特征提取")
    parser.add_argument(
        "--input",
        type=str,
        default="data/week1_pca/factors_for_pca.csv",
        help="输入因子矩阵 CSV 路径"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/week1_pca",
        help="输出产物目录"
    )
    parser.add_argument(
        "--n-components",
        type=int,
        default=5,
        help="提取的主成分数量 (默认5，提取PC1~PC5)"
    )
    args = parser.parse_args()

    run_pca_pipeline(
        input_file=Path(args.input),
        output_dir=Path(args.output_dir),
        n_components=args.n_components
    )


if __name__ == "__main__":
    main()
