# -*- coding: utf-8 -*-
"""
数据清洗与特征加工管道: 对郑商所纯碱 (SA) 与玻璃 (FG) 进行时间对齐、缺失值校准与衍生品指标计算
保存路径: data/processed/ 及 reports/tables/
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

# 强制标准输出为 UTF-8
sys.stdout.reconfigure(encoding='utf-8')

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
RAW_DIR = ROOT_DIR / "data" / "raw"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
TABLES_DIR = ROOT_DIR / "reports" / "tables"

PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
TABLES_DIR.mkdir(parents=True, exist_ok=True)

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
    """清洗单一品种主力日线数据并生成波动率与收益率基础特征"""
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
    
    # 2. 字段类型转换与日期排序
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    
    # 3. 去重与空值检验
    df = df.drop_duplicates(subset=["date"]).reset_index(drop=True)
    
    num_cols = ["open", "high", "low", "close", "volume", "open_interest", "settle"]
    for col in num_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        # 前向填充极少数缺失价格
        df[col] = df[col].ffill().bfill()
        
    # 4. 衍生指标计算
    # 对数收益率
    df["log_ret"] = np.log(df["close"] / df["close"].shift(1))
    
    # 滚动年化已实现波动率 (20日短期、60日中期，假定每年250个交易日)
    df["vol_20d"] = df["log_ret"].rolling(window=20).std() * np.sqrt(250)
    df["vol_60d"] = df["log_ret"].rolling(window=60).std() * np.sqrt(250)
    
    # 持仓量增减变动
    df["delta_oi"] = df["open_interest"] - df["open_interest"].shift(1)
    
    # 5. 标明品种代码
    df["symbol"] = symbol
    
    return df

def generate_aligned_dataset(df_sa: pd.DataFrame, df_fg: pd.DataFrame) -> pd.DataFrame:
    """将纯碱 (SA) 与玻璃 (FG) 按交易日严密对齐，构建跨品种产业链对冲特征矩阵"""
    # 选取两品种共同存续的历史区间（纯碱于 2019 年 12 月上市）
    merged = pd.merge(
        df_sa, df_fg, 
        on="date", 
        suffixes=("_sa", "_fg"), 
        how="inner"
    )
    
    # 产业链相对价差与比价
    merged["spread_fg_sa"] = merged["close_fg"] - merged["close_sa"]
    merged["ratio_fg_sa"] = merged["close_fg"] / merged["close_sa"]
    
    # 滚动相关系数 (20日与60日时变联动性)
    merged["rolling_corr_20d"] = merged["log_ret_sa"].rolling(20).corr(merged["log_ret_fg"])
    merged["rolling_corr_60d"] = merged["log_ret_sa"].rolling(60).corr(merged["log_ret_fg"])
    
    # 价格变动绝对值与极差检验
    merged["sa_daily_range_pct"] = (merged["high_sa"] - merged["low_sa"]) / merged["close_sa"] * 100.0
    merged["fg_daily_range_pct"] = (merged["high_fg"] - merged["low_fg"]) / merged["close_fg"] * 100.0
    
    return merged

def run_pipeline() -> None:
    """执行端到端清洗与特征工程流水线"""
    print("=== 开始执行郑商所衍生品数据清洗流水线 ===")
    
    sa_raw_path = RAW_DIR / "czce_sa_futures_daily_raw.csv"
    fg_raw_path = RAW_DIR / "czce_fg_futures_daily_raw.csv"
    
    # 1. 单品种清洗
    print("-> 清洗纯碱 (SA) 历史数据...")
    df_sa_clean = clean_single_futures(sa_raw_path, "SA")
    sa_clean_path = PROCESSED_DIR / "czce_sa_futures_daily_clean.csv"
    df_sa_clean.to_csv(sa_clean_path, index=False, encoding="utf-8-sig")
    print(f"   [SA] 清洗完成: {len(df_sa_clean)} 交易日 ({df_sa_clean['date'].min().strftime('%Y-%m-%d')} 至 {df_sa_clean['date'].max().strftime('%Y-%m-%d')})")
    
    print("-> 清洗玻璃 (FG) 历史数据...")
    df_fg_clean = clean_single_futures(fg_raw_path, "FG")
    fg_clean_path = PROCESSED_DIR / "czce_fg_futures_daily_clean.csv"
    df_fg_clean.to_csv(fg_clean_path, index=False, encoding="utf-8-sig")
    print(f"   [FG] 清洗完成: {len(df_fg_clean)} 交易日 ({df_fg_clean['date'].min().strftime('%Y-%m-%d')} 至 {df_fg_clean['date'].max().strftime('%Y-%m-%d')})")
    
    # 2. 跨品种对齐
    print("-> 构建纯碱-玻璃产业链对齐特征工程数据集...")
    df_aligned = generate_aligned_dataset(df_sa_clean, df_fg_clean)
    aligned_path = PROCESSED_DIR / "czce_sa_fg_aligned_features.csv"
    df_aligned.to_csv(aligned_path, index=False, encoding="utf-8-sig")
    print(f"   [对齐特征] 完成: {len(df_aligned)} 共有交易日 -> {aligned_path}")
    
    # 3. 统计学指标摘要表输出
    print("-> 导出学术级统计指标摘要 (reports/tables/)...")
    summary_cols = [
        "close_sa", "close_fg", "spread_fg_sa", "ratio_fg_sa",
        "vol_20d_sa", "vol_20d_fg", "rolling_corr_20d"
    ]
    summary_df = df_aligned[summary_cols].describe().T
    summary_df["missing_rate_pct"] = df_aligned[summary_cols].isnull().mean() * 100.0
    summary_path = TABLES_DIR / "czce_summary_statistics.csv"
    summary_df.to_csv(summary_path, encoding="utf-8-sig")
    print(f"   [摘要表] 已输出至: {summary_path}")
    
    # 4. 流水线断言自检 (Smoke Test)
    assert not df_aligned.empty, "对齐特征数据集不能为空"
    assert df_aligned["close_sa"].min() > 0, "纯碱收盘价存在非正数异常"
    assert df_aligned["close_fg"].min() > 0, "玻璃收盘价存在非正数异常"
    assert (df_aligned["date"].diff().dt.total_seconds().dropna() > 0).all(), "日期序列必须单调严格递增"
    print("=== 流水线自检全部通过 (Smoke Test PASSED) ===")

if __name__ == "__main__":
    run_pipeline()
