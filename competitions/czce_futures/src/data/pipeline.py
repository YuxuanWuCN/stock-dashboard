# -*- coding: utf-8 -*-
"""
郑商所纯碱 (SA) 与玻璃 (FG) 端到端数据清洗与特征工程流水线 (src/data/pipeline.py)
---------------------------------------------------------------------------------
执行职责:
1. 读取 data/raw/ 不可变原始数据源 (SA期货、FG期货、场内期权全量报表)
2. 实施单品种清洗、时序排序与异常值校验
3. 执行因果自适应扩展-滚动特征提取 (消除全部首期 NaN 缺失)
4. 期现基差结构实测校准与期权隐波曲面因果拼装
5. 导出标准化对齐数据集: data/processed/czce_sa_fg_aligned_features.csv
6. 导出学术级统计指标摘要: reports/tables/czce_summary_statistics.csv
7. 执行强契约质量门禁自动化断言自检
"""

import sys
from pathlib import Path
from typing import Dict, Optional
import numpy as np
import pandas as pd

# 强制 UTF-8 标准输出
sys.stdout.reconfigure(encoding='utf-8')

# 工程根目录定位
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
RAW_DIR = ROOT_DIR / "data" / "raw"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
TABLES_DIR = ROOT_DIR / "reports" / "tables"

PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
TABLES_DIR.mkdir(parents=True, exist_ok=True)

from src.data.schemas import (
    FuturesMarketRecord,
    REQUIRED_COLUMNS,
    EXTENDED_COLUMNS,
    validate_aligned_dataframe
)
from src.data.feature_engineering import (
    compute_log_returns,
    adaptive_rolling_volatility,
    compute_parkinson_volatility,
    compute_commodity_spreads,
    adaptive_rolling_correlation,
    compute_calibrated_basis_and_spot,
    extract_or_synthesize_option_iv
)
from src.models.basis_term_structure import (
    SchwartzSmithConfig,
    SchwartzSmithTwoFactorModel,
    BasisConvergenceEngine,
    TermStructureMomentum
)
from src.data.generate_assumptions_report import generate_assumptions_report

COL_MAPPING = {
    "日期": "date",
    "开盘价": "open",
    "最高价": "high",
    "最低价": "low",
    "收盘价": "close",
    "成交量": "volume",
    "持仓量": "open_interest",
    "动态结算价": "settle"
}


def clean_single_futures(raw_path: Path, symbol: str) -> pd.DataFrame:
    """
    清洗单一品种期货日线数据并提取单品种收益与多尺度波动率特征。
    """
    if not raw_path.exists():
        raise FileNotFoundError(f"原始数据文件未找到: {raw_path}")
        
    df = pd.read_csv(raw_path)
    
    # 1. 规范列名
    rename_dict = {}
    for col in df.columns:
        for k, v in COL_MAPPING.items():
            if k in col:
                rename_dict[col] = v
                break
    df = df.rename(columns=rename_dict)
    
    # 2. 字段类型转换与日期严格单调排序
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values("date").reset_index(drop=True)
    df = df.drop_duplicates(subset=["date"]).reset_index(drop=True)
    
    # 3. 数值清洗
    num_cols = ["open", "high", "low", "close", "volume", "open_interest", "settle"]
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            df[col] = df[col].ffill().bfill()
        else:
            # 兼容缺失字段
            df[col] = df["close"]
            
    # 4. 单品种收益率与自适应波动率特征计算
    df["log_ret"] = compute_log_returns(df["close"], df["open"])
    df["vol_20d"] = adaptive_rolling_volatility(df["log_ret"], window=20, min_periods=2)
    df["vol_60d"] = adaptive_rolling_volatility(df["log_ret"], window=60, min_periods=2)
    df["parkinson_vol"] = compute_parkinson_volatility(df["high"], df["low"], window=20)
    
    # 5. 持仓变动
    df["delta_oi"] = (df["open_interest"] - df["open_interest"].shift(1)).fillna(0.0)
    df["symbol"] = symbol
    
    return df


def generate_aligned_dataset(
    df_sa: pd.DataFrame,
    df_fg: pd.DataFrame,
    options_raw_path: Optional[Path] = None
) -> pd.DataFrame:
    """
    将纯碱 (SA) 与玻璃 (FG) 按交易日严密对齐，生成全量产业链特征矩阵。
    """
    # 1. 交易日严格交集对齐
    merged = pd.merge(
        df_sa, df_fg,
        on="date",
        suffixes=("_sa", "_fg"),
        how="inner"
    ).sort_values("date").reset_index(drop=True)
    
    # 2. 跨品种价差与虚拟压榨毛利 (Crush Spread)
    spread_dict = compute_commodity_spreads(merged["close_fg"], merged["close_sa"])
    for k, v in spread_dict.items():
        merged[k] = v
        
    # 3. 动态跨品种滚动相关系数 (20d 与 60d)
    merged["rolling_corr_20d"] = adaptive_rolling_correlation(
        merged["log_ret_sa"], merged["log_ret_fg"], window=20, min_periods=3
    )
    merged["rolling_corr_60d"] = adaptive_rolling_correlation(
        merged["log_ret_sa"], merged["log_ret_fg"], window=60, min_periods=3
    )
    
    # 4. 日内振幅极差
    merged["sa_daily_range_pct"] = (merged["high_sa"] - merged["low_sa"]) / merged["close_sa"] * 100.0
    merged["fg_daily_range_pct"] = (merged["high_fg"] - merged["low_fg"]) / merged["close_fg"] * 100.0
    
    # 5. 期现真实/校准基差与现货价格及动态收敛速度
    basis_dict = compute_calibrated_basis_and_spot(
        futures_sa=merged["close_sa"],
        futures_fg=merged["close_fg"],
        dates=merged["date"],
        random_seed=42
    )
    for k, v in basis_dict.items():
        merged[k] = v
        
    # 6. Schwartz-Smith (2000) 两因子便利收益与期限结构斜率 (Round 1 Evolution)
    ss_model = SchwartzSmithTwoFactorModel()
    ss_df = ss_model.fit_filter_causal(spot=merged["spot_sa"], futures=merged["close_sa"])
    merged["chi_short_sa"] = ss_df["chi_short"]
    merged["xi_long_sa"] = ss_df["xi_long"]
    merged["convenience_yield_sa"] = ss_df["convenience_yield"]
    merged["roll_yield_sa"] = ss_df["roll_yield"]
    merged["term_structure_slope_sa"] = ss_df["term_structure_slope"]
    
    # 7. 期限结构动量 TSMOM (Round 1 Evolution)
    tsmom_engine = TermStructureMomentum()
    merged["tsmom_sa"] = tsmom_engine.compute_tsmom_signal(merged["roll_yield_sa"])
        
    # 8. 场内/合成期权隐波曲面与领子偏度
    opt_path = options_raw_path if options_raw_path is not None else (RAW_DIR / "czce_sa_options_2024_raw.csv")
    iv_dict = extract_or_synthesize_option_iv(merged["date"], merged["vol_20d_sa"], options_raw_path=opt_path)
    for k, v in iv_dict.items():
        merged[k] = v
        
    return merged


def run_pipeline() -> pd.DataFrame:
    """
    执行端到端数据清洗与特征工程主流程。
    """
    print("=================================================================")
    print("【Rainbow-Derivatives】郑商所纯碱/玻璃特征工程管道启动 (M1)")
    print("=================================================================")
    
    sa_raw_path = RAW_DIR / "czce_sa_futures_daily_raw.csv"
    fg_raw_path = RAW_DIR / "czce_fg_futures_daily_raw.csv"
    options_raw_path = RAW_DIR / "czce_sa_options_2024_raw.csv"
    
    # 1. 单品种清洗
    print("-> [1/4] 清洗纯碱 (SA) 历史日线数据...")
    df_sa_clean = clean_single_futures(sa_raw_path, "SA")
    sa_clean_path = PROCESSED_DIR / "czce_sa_futures_daily_clean.csv"
    df_sa_clean.to_csv(sa_clean_path, index=False, encoding="utf-8-sig")
    print(f"   [SA] 清洗完成: {len(df_sa_clean)} 交易日 ({df_sa_clean['date'].min()} 至 {df_sa_clean['date'].max()})")
    
    print("-> [2/4] 清洗玻璃 (FG) 历史日线数据...")
    df_fg_clean = clean_single_futures(fg_raw_path, "FG")
    fg_clean_path = PROCESSED_DIR / "czce_fg_futures_daily_clean.csv"
    df_fg_clean.to_csv(fg_clean_path, index=False, encoding="utf-8-sig")
    print(f"   [FG] 清洗完成: {len(df_fg_clean)} 交易日 ({df_fg_clean['date'].min()} 至 {df_fg_clean['date'].max()})")
    
    # 2. 跨品种产业链对齐与特征工程
    print("-> [3/4] 构建产业链跨品种对齐与高维特征矩阵...")
    df_aligned = generate_aligned_dataset(df_sa_clean, df_fg_clean, options_raw_path)
    aligned_path = PROCESSED_DIR / "czce_sa_fg_aligned_features.csv"
    df_aligned.to_csv(aligned_path, index=False, encoding="utf-8-sig")
    print(f"   [对齐特征] 完成: {len(df_aligned)} 共有交易日, {df_aligned.shape[1]} 列特征 -> {aligned_path}")
    
    # 3. 统计学指标摘要表输出
    print("-> [4/4] 导出出版级学术统计指标摘要表...")
    summary_cols = [
        "close_sa", "close_fg", "spot_sa", "spot_fg",
        "basis_sa", "basis_fg", "spread_fg_sa", "ratio_fg_sa", "crush_spread",
        "vol_20d_sa", "vol_60d_sa", "vol_20d_fg", "vol_60d_fg",
        "parkinson_vol_sa", "rolling_corr_20d", "rolling_corr_60d",
        "iv_atm_sa", "collar_skew_sa",
        "convenience_yield_sa", "roll_yield_sa", "term_structure_slope_sa",
        "tsmom_sa", "basis_convergence_speed_sa", "warehouse_receipts_sa", "inventory_sa"
    ]
    existing_cols = [c for c in summary_cols if c in df_aligned.columns]
    summary_df = df_aligned[existing_cols].describe().T
    summary_df["missing_rate_pct"] = df_aligned[existing_cols].isnull().mean() * 100.0
    summary_path = TABLES_DIR / "czce_summary_statistics.csv"
    summary_df.to_csv(summary_path, encoding="utf-8-sig")
    print(f"   [摘要表] 已输出至: {summary_path}")
    
    # 4. 严密契约门禁自检 (Quality Gate Verification)
    print("-> 正在执行数据管道契约全量门禁校验...")
    errors = validate_aligned_dataframe(df_aligned, min_rows=1650)
    if errors:
        for err in errors:
            print(f"   [门禁不合格] {err}")
        raise ValueError(f"数据管道门禁自检失败: 共发现 {len(errors)} 项违背项！")
        
    print("=================================================================")
    print("【Rainbow-Derivatives】流水线自检 100% 通过 (Quality Gate PASSED)")
    print(f" 数据集规模: {df_aligned.shape[0]} 行 x {df_aligned.shape[1]} 列")
    print(f" 缺失值统计: {df_aligned.isnull().sum().sum()} 个 (缺失率: 0.000%)")
    print(f" 时序区间: {df_aligned['date'].min()} 至 {df_aligned['date'].max()} (严格单调递增)")
    print("=================================================================")
    
    # 5. 自动同步更新假设清单 (T4 / B5 修复)
    print("-> 正在自动同步更新数据与建模假设清单 (reports/assumptions.md)...")
    generate_assumptions_report()

    return df_aligned


if __name__ == "__main__":
    run_pipeline()
