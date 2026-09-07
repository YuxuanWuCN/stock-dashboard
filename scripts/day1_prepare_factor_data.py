#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/day1_prepare_factor_data.py - Week 1 Day 1: 因子数据清洗与准备脚本

功能:
1. 从回测数据提取多因子矩阵（支持绿色电力、半导体存储、黄金等各板块）。
2. 面板数据单标的隔离清洗：若包含多只标的（ticker），按标的独立执行 forward-fill 和 backward-fill，
   坚决防止不同股票之间的数据串扰与污染。
3. 质量门禁校验：
   - 缺失值/无穷值检查
   - 因子数量 >= 5（满足 PC5 提取硬性要求）
   - 样本周期 >= 60 交易日
4. 导出交付物至 data/week1_pca/：
   - factors_for_pca.csv (清洗后的因子矩阵，行=日期，列=因子)
   - factors_stats.csv (因子描述性统计)
   - metadata.json (数据溯源与质量指标)

负责人: IMIS 数据架构师 + 算法团队
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("day1_prepare_factor")

# 默认数据源配置
AVAILABLE_DATASETS: Dict[str, Path] = {
    "green": Path("data/raw/backtest_green_2025q3_2026q3/factors.csv"),
    "storage": Path("data/raw/backtest_storage_2025q2_2026q3/factors.csv"),
    "gold": Path("data/raw/backtest_gold_2025q3_2026q8/factors.csv"),
}


def load_raw_dataset(path: Path) -> pd.DataFrame:
    """加载原始数据文件，进行初步格式识别。"""
    if not path.exists():
        raise FileNotFoundError(f"未找到原始数据文件: {path}")

    logger.info(f"正在加载数据文件: {path}")
    df = pd.read_csv(path)
    logger.info(f"原始数据形状: {df.shape}, 列名: {list(df.columns)}")
    return df


def clean_macro_factors(df: pd.DataFrame, max_missing_ratio: float = 0.20) -> pd.DataFrame:
    """清洗宏观/市场多因子时间序列（单时间序列格式）。

    期望格式:
    第一列为日期（如 'Unnamed: 0' 或 'date'），其余为各因子列。
    """
    df = df.copy()

    # 识别日期列
    date_col = None
    for candidate in ["Unnamed: 0", "date", "trade_date", "Date"]:
        if candidate in df.columns:
            date_col = candidate
            break

    if date_col is not None:
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.sort_values(date_col).set_index(date_col)
        df.index.name = "date"
    else:
        # 如果第一列看起来像日期字符串
        first_col_sample = str(df.iloc[0, 0])
        if any(sep in first_col_sample for sep in ["-", "/"]) and len(first_col_sample) >= 8:
            first_col_name = df.columns[0]
            df[first_col_name] = pd.to_datetime(df[first_col_name])
            df = df.sort_values(first_col_name).set_index(first_col_name)
            df.index.name = "date"

    # 只保留数值列
    numeric_df = df.select_dtypes(include=[np.number]).copy()
    initial_cols = list(numeric_df.columns)

    # 检查缺失比例
    missing_ratio = numeric_df.isnull().sum() / len(numeric_df)
    valid_cols = missing_ratio[missing_ratio <= max_missing_ratio].index.tolist()
    dropped_cols = [c for c in initial_cols if c not in valid_cols]
    if dropped_cols:
        logger.warning(f"剔除缺失率高于 {max_missing_ratio:.0%} 的因子: {dropped_cols}")

    cleaned = numeric_df[valid_cols].copy()

    # 时间序列前向填充，再后向填充（处理首日缺失），若仍有缺失填0
    cleaned = cleaned.ffill().bfill().fillna(0.0)

    return cleaned


def clean_panel_factors(
    df: pd.DataFrame,
    date_col: str = "date",
    ticker_col: str = "ticker",
    max_missing_ratio: float = 0.20
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """清洗多标的面板因子数据（如存储板块）。

    严格隔离各标的：
    1. 针对每一个 ticker 单独按时间排序并进行前向/后向填充，决不跨股票串流。
    2. 返回两份数据：
       - clean_panel: 扁平的面板数据 (date, ticker, factors...)
       - factor_matrix_wide: 透视后的宽表因子矩阵 (date x [factor_ticker...])
    """
    df = df.copy()
    if date_col not in df.columns or ticker_col not in df.columns:
        raise ValueError(f"面板数据必须包含 '{date_col}' 和 '{ticker_col}' 列")

    df[date_col] = pd.to_datetime(df[date_col])
    tickers = sorted(df[ticker_col].unique())
    logger.info(f"检测到面板数据包含 {len(tickers)} 只标的: {tickers}")

    # 识别因子列
    factor_cols = [
        c for c in df.select_dtypes(include=[np.number]).columns
        if c not in [ticker_col, "Unnamed: 0"]
    ]
    logger.info(f"识别到的因子列: {factor_cols}")

    # 逐标的清洗，防止数据串扰
    cleaned_group_list = []
    for ticker in tickers:
        sub_df = df[df[ticker_col] == ticker].sort_values(date_col).copy()
        
        # 针对各因子列前向+后向填充
        sub_df[factor_cols] = sub_df[factor_cols].ffill().bfill().fillna(0.0)
        cleaned_group_list.append(sub_df)

    clean_panel = pd.concat(cleaned_group_list, ignore_index=True)
    clean_panel = clean_panel.sort_values([date_col, ticker_col])

    # 生成宽表因子矩阵 (以日期为索引，各股票因子作为多列)
    wide_blocks = []
    for f in factor_cols:
        pivot_f = clean_panel.pivot(index=date_col, columns=ticker_col, values=f)
        pivot_f.columns = [f"{f}_{t}" for t in pivot_f.columns]
        wide_blocks.append(pivot_f)

    wide_df = pd.concat(wide_blocks, axis=1)
    wide_df.index.name = "date"

    return clean_panel, wide_df


def validate_factor_matrix(factors_df: pd.DataFrame, min_factors: int = 5, min_days: int = 60):
    """执行质量门禁与断言复核。"""
    n_days, n_factors = factors_df.shape

    logger.info("=" * 60)
    logger.info("执行数据质量门禁复核:")
    logger.info(f"  - 样本交易日数: {n_days} (标准: >= {min_days})")
    logger.info(f"  - 因子数量: {n_factors} (标准: >= {min_factors})")
    logger.info(f"  - 日期跨度: {factors_df.index.min()} ~ {factors_df.index.max()}")
    logger.info("=" * 60)

    # 1. 维度断言
    if n_factors < min_factors:
        raise AssertionError(
            f"因子数量不足: 当前仅 {n_factors} 个，提取 PC5 至少需要 {min_factors} 个因子！"
        )
    if n_days < min_days:
        raise AssertionError(
            f"样本天数不足: 当前仅 {n_days} 天，建议至少 {min_days} 个交易日以保证统计稳定性！"
        )

    # 2. 缺失值与无穷值断言
    nan_count = factors_df.isna().sum().sum()
    inf_count = np.isinf(factors_df.values).sum()
    if nan_count > 0:
        raise AssertionError(f"清洗后因子矩阵仍存在 {nan_count} 个 NaN 缺失值！")
    if inf_count > 0:
        raise AssertionError(f"清洗后因子矩阵存在 {inf_count} 个 Inf 无穷值！")

    # 3. 零方差常数因子检查
    stds = factors_df.std(axis=0)
    zero_variance_cols = stds[stds < 1e-8].index.tolist()
    if zero_variance_cols:
        logger.warning(f"⚠️ 发现零方差常量因子（PCA中贡献为0）: {zero_variance_cols}")

    logger.info("✅ 数据质量门禁全部通过！")


def run_day1_pipeline(
    dataset_key: str = "green",
    output_dir: Path = Path("data/week1_pca"),
    force: bool = False
) -> Dict[str, str]:
    """执行 Day 1 完整数据准备流水线。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = AVAILABLE_DATASETS.get(dataset_key)
    if not raw_path:
        raise ValueError(f"未知数据集: {dataset_key}，可选: {list(AVAILABLE_DATASETS.keys())}")

    raw_df = load_raw_dataset(raw_path)

    # 判断是否为面板数据 (含有 ticker 列)
    if "ticker" in raw_df.columns:
        logger.info("检测为标的面板数据 (Multi-ticker panel)，执行独立隔离清洗...")
        clean_panel, wide_df = clean_panel_factors(raw_df)
        factors_clean = wide_df
        
        # 额外保存面板数据
        panel_output = output_dir / "factors_panel_clean.csv"
        clean_panel.to_csv(panel_output, index=False)
        logger.info(f"已保存多标的面板清洗结果: {panel_output}")
    else:
        logger.info("检测为板块/市场因子时间序列，执行多因子清洗...")
        factors_clean = clean_macro_factors(raw_df)

    # 质量校验
    validate_factor_matrix(factors_clean, min_factors=5, min_days=60)

    # 保存清洗后的主要因子矩阵
    factors_file = output_dir / "factors_for_pca.csv"
    factors_clean.to_csv(factors_file)
    logger.info(f"✅ 因子矩阵已保存: {factors_file} (形状: {factors_clean.shape})")

    # 保存描述性统计
    stats_df = factors_clean.describe().T
    stats_file = output_dir / "factors_stats.csv"
    stats_df.to_csv(stats_file)
    logger.info(f"✅ 统计报告已保存: {stats_file}")

    # 保存元数据
    metadata = {
        "dataset_key": dataset_key,
        "source_file": str(raw_path).replace("\\", "/"),
        "n_trading_days": int(factors_clean.shape[0]),
        "n_factors": int(factors_clean.shape[1]),
        "date_start": str(factors_clean.index.min()),
        "date_end": str(factors_clean.index.max()),
        "factors": list(factors_clean.columns),
        "clean_strategy": "isolated_forward_backward_fill",
        "has_nan": bool(factors_clean.isna().any().any()),
        "has_inf": bool(np.isinf(factors_clean.values).any()),
    }
    meta_file = output_dir / "metadata.json"
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    logger.info(f"✅ 数据元数据已保存: {meta_file}")

    return {
        "factors_csv": str(factors_file),
        "stats_csv": str(stats_file),
        "metadata_json": str(meta_file),
    }


def main():
    parser = argparse.ArgumentParser(description="Week 1 Day 1: 因子数据清洗与准备")
    parser.add_argument(
        "--dataset",
        choices=["green", "storage", "gold", "all"],
        default="green",
        help="选择数据源板块 (green: 绿色电力, storage: 半导体存储面板, gold: 黄金, all: 全量处理)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/week1_pca",
        help="清洗结果输出目录"
    )
    args = parser.parse_args()

    out_path = Path(args.output_dir)

    if args.dataset == "all":
        for ds in ["green", "storage", "gold"]:
            logger.info(f"\n{'='*30} 处理板块: {ds} {'='*30}")
            sub_dir = out_path if ds == "green" else out_path / ds
            run_day1_pipeline(ds, sub_dir)
    else:
        run_day1_pipeline(args.dataset, out_path)

    logger.info("\n🎉 Day 1 因子数据清洗全流程执行完毕！")


if __name__ == "__main__":
    main()
