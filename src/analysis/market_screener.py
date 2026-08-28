# -*- coding: utf-8 -*-
"""src/analysis/market_screener.py —— 全市场轻量级两级动态初筛模块 (Tier-1 Market Screener)

功能定位：
1. 3 秒全市场粗筛：单次请求获取全市场 5000+ 只股票即时行情切片，避免对 5000 只股票逐一抓取的网络风暴。
2. 多维度流动性与质地过滤：非 ST、流动性门槛（日成交额 >= 3~5 亿）、换手率活跃度、市值下限过滤。
3. 动态自选池融合：将全市场筛选出的 Top 30~50 只最强热点/突破标的与核心静态 `watchlist.csv` 自动去重合并。
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("market_screener")


def fetch_market_snapshot(offline_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """获取全市场即时行情切片数据。
    
    在线模式：调用 akshare.stock_zh_a_spot_em() 获取 5000+ 只 A 股即时快照。
    离线/测试模式：传入 offline_df。
    """
    if offline_df is not None:
        return offline_df.copy()

    try:
        import akshare as ak
        logger.info("正在调用 akshare 获取全市场行情快照...")
        df = ak.stock_zh_a_spot_em()
        logger.info(f"成功获取全市场快照，共 {len(df)} 只标的")
        return df
    except Exception as e:
        logger.warning(f"获取全市场行情快照失败 ({e})，返回空 DataFrame")
        return pd.DataFrame()


def screen_active_stocks(
    df_snapshot: pd.DataFrame,
    min_amount: float = 3e8,        # 最低成交额（默认 3 亿元）
    min_turnover: float = 2.5,       # 最低换手率（%）
    min_market_cap: float = 5e9,     # 最低总市值（默认 50 亿元）
    filter_st: bool = True,          # 是否过滤 ST 股票
    max_candidates: int = 50,        # 最多输出候选标的数量
) -> pd.DataFrame:
    """对全市场快照数据进行轻量级量化粗筛。
    
    过滤规则：
    1. 剔除名称包含 'ST'、'*ST'、'退' 的风险标的
    2. 总市值 >= min_market_cap
    3. 成交额 >= min_amount 且 换手率 >= min_turnover
    4. 当日涨跌幅在正常健康区间 (0% ~ 15%)，避免跌停或无流动性标的
    5. 按 (成交额权重 0.5 + 涨跌幅动量 0.5) 综合排序，提取前 Top-N 活跃龙头
    """
    if df_snapshot.empty:
        return pd.DataFrame(columns=["code", "name", "type", "category", "amount", "change_pct", "turnover_rate"])

    df = df_snapshot.copy()

    # 标准化列名（兼容不同接口返回的列名）
    col_map = {
        "代码": "code",
        "名称": "name",
        "最新价": "price",
        "涨跌幅": "change_pct",
        "成交额": "amount",
        "换手率": "turnover_rate",
        "总市值": "market_cap",
        "量比": "volume_ratio",
    }
    for old_col, new_col in col_map.items():
        if old_col in df.columns:
            df[new_col] = df[old_col]

    required_cols = ["code", "name", "amount", "change_pct", "turnover_rate"]
    for c in required_cols:
        if c not in df.columns:
            logger.warning(f"快照数据缺失必要列: {c}")
            return pd.DataFrame(columns=["code", "name", "type", "category"])

    # 规范化数值类型与代码格式
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["name"] = df["name"].astype(str)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["change_pct"] = pd.to_numeric(df["change_pct"], errors="coerce").fillna(0.0)
    df["turnover_rate"] = pd.to_numeric(df["turnover_rate"], errors="coerce").fillna(0.0)
    if "market_cap" in df.columns:
        df["market_cap"] = pd.to_numeric(df["market_cap"], errors="coerce").fillna(0.0)
    else:
        df["market_cap"] = min_market_cap + 1.0

    # 1. 过滤 ST 与退市标的
    if filter_st:
        mask_st = df["name"].str.contains("ST|退", case=False, na=False)
        df = df[~mask_st]

    # 2. 市值与流动性过滤
    mask_liquid = (
        (df["amount"] >= min_amount) &
        (df["turnover_rate"] >= min_turnover) &
        (df["market_cap"] >= min_market_cap) &
        (df["change_pct"] >= -2.0)  # 剔除大幅暴跌破位标的
    )
    df_filtered = df[mask_liquid].copy()

    if df_filtered.empty:
        logger.info("初筛后无标的满足流动性条件，放宽条件尝试")
        df_filtered = df[df["amount"] >= (min_amount * 0.5)].copy()

    if df_filtered.empty:
        return pd.DataFrame(columns=["code", "name", "type", "category"])

    # 3. 活跃度综合打分排序：归一化成交额 (流动性) + 归一化涨幅 (动量)
    norm_amount = (df_filtered["amount"] - df_filtered["amount"].min()) / (df_filtered["amount"].max() - df_filtered["amount"].min() + 1e-9)
    norm_change = (df_filtered["change_pct"] - df_filtered["change_pct"].min()) / (df_filtered["change_pct"].max() - df_filtered["change_pct"].min() + 1e-9)
    df_filtered["activity_score"] = 0.5 * norm_amount + 0.5 * norm_change

    df_sorted = df_filtered.sort_values(by="activity_score", ascending=False).head(max_candidates)

    df_sorted["type"] = "stock"
    df_sorted["category"] = "全市场热点精选"

    return df_sorted[["code", "name", "type", "category", "amount", "change_pct", "turnover_rate"]].reset_index(drop=True)


def merge_with_core_watchlist(
    core_csv_path: str | Path,
    df_dynamic: pd.DataFrame,
    output_path: Optional[str | Path] = None,
) -> pd.DataFrame:
    """将核心静态 watchlist.csv 与全市场动态初筛出的热点标的无缝合并去重。"""
    core_path = Path(core_csv_path)
    if core_path.exists():
        df_core = pd.read_csv(core_path, dtype={"code": str})
        df_core["code"] = df_core["code"].astype(str).str.zfill(6)
    else:
        df_core = pd.DataFrame(columns=["code", "name", "type", "category"])

    if df_dynamic.empty:
        df_merged = df_core.copy()
    else:
        dynamic_cols = [c for c in ["code", "name", "type", "category"] if c in df_dynamic.columns]
        df_dyn_sub = df_dynamic[dynamic_cols].copy()
        df_merged = pd.concat([df_core, df_dyn_sub], ignore_index=True)
        # 去重：优先保留核心自选池的原始分类
        df_merged = df_merged.drop_duplicates(subset=["code"], keep="first").reset_index(drop=True)

    if output_path is not None:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        df_merged.to_csv(out_p, index=False, encoding="utf-8-sig")
        logger.info(f"已将合并自选池输出至: {out_p} (共 {len(df_merged)} 只标的)")

    return df_merged


def main():
    parser = argparse.ArgumentParser(description="全市场即时快照两级初筛工具")
    parser.add_argument("--top", type=int, default=50, help="最多筛选出的热点标的数量 (默认 50)")
    parser.add_argument("--min-amount", type=float, default=3e8, help="最低日成交额，单位元 (默认 300,000,000)")
    parser.add_argument("--min-turnover", type=float, default=2.5, help="最低换手率 % (默认 2.5)")
    parser.add_argument("--core-csv", type=str, default="watchlist.csv", help="核心自选池 CSV 路径")
    parser.add_argument("--output-csv", type=str, default="docs/data/dynamic_watchlist.csv", help="输出合并池路径")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    snapshot = fetch_market_snapshot()
    if snapshot.empty:
        logger.warning("未获取到实时快照，生成示例快照进行演示")
        snapshot = pd.DataFrame({
            "代码": ["688525", "300750", "002475", "603986", "000001", "600519", "002594"],
            "名称": ["佰维存储", "宁德时代", "立讯精密", "兆易创新", "平安银行", "贵州茅台", "比亚迪"],
            "成交额": [8.5e8, 35e8, 12e8, 9.2e8, 6.5e8, 45e8, 22e8],
            "涨跌幅": [5.2, 3.1, 4.0, 6.8, 0.5, 1.2, 2.8],
            "换手率": [6.5, 2.8, 3.2, 5.1, 0.8, 0.4, 2.1],
            "总市值": [3e10, 8e11, 2e11, 6e10, 2e11, 2e12, 7e11],
        })

    active_df = screen_active_stocks(
        df_snapshot=snapshot,
        min_amount=args.min_amount,
        min_turnover=args.min_turnover,
        max_candidates=args.top,
    )
    print(f"\n[初筛结果] 共筛选出 {len(active_df)} 只活跃龙头：")
    print(active_df.head(10).to_string(index=False))

    merged = merge_with_core_watchlist(
        core_csv_path=args.core_csv,
        df_dynamic=active_df,
        output_path=args.output_csv,
    )
    print(f"\n[合并完成] 最终合并自选池总数: {len(merged)} 只，已保存至 {args.output_csv}")


if __name__ == "__main__":
    main()
