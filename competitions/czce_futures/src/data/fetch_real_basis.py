# -*- coding: utf-8 -*-
"""拉取郑商所纯碱 (SA) 与玻璃 (FG) 真实期现基差与官方现货价序列（交易所与生意社口径）。

数据源：akshare `futures_spot_price`（逐交易日并行抓取生意社/郑商所公布现货价与主力/近月基差）
输出：`data/raw/czce_real_spot_basis.csv`
字段：date, symbol, spot_price, near_contract, near_contract_price,
      dominant_contract, dominant_contract_price, near_basis, dom_basis,
      near_basis_rate, dom_basis_rate

本模块彻底替换 `BasisConvergenceEngine.simulate_dynamic_basis` 的随机模拟路径（缺陷 B1 / 任务 T1）。

用法:
    python -m src.data.fetch_real_basis            # 增量拉取/断点续传
    python -m src.data.fetch_real_basis --full     # 全量重拉
    python -m src.data.fetch_real_basis --workers 16
"""

import argparse
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional

import akshare as ak
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT_PATH = RAW_DIR / "czce_real_spot_basis.csv"
SA_RAW = RAW_DIR / "czce_sa_futures_daily_raw.csv"

SYMBOLS = ["SA", "FG"]
DEFAULT_WORKERS = 16


def get_trading_days() -> List[pd.Timestamp]:
    """以纯碱期货原始日线的日期为交易日基准序列（2019-12-06 至今）。"""
    if not SA_RAW.exists():
        raise FileNotFoundError(f"未找到纯碱原始期货数据: {SA_RAW}")
    df = pd.read_csv(SA_RAW)
    dates = pd.to_datetime(df["日期"])
    return sorted(dates.unique())


def fetch_single_day(day: pd.Timestamp, max_retries: int = 3) -> Optional[pd.DataFrame]:
    """抓取单交易日 SA 与 FG 现货价与基差数据。"""
    d_str = day.strftime("%Y%m%d")
    for attempt in range(max_retries):
        try:
            df = ak.futures_spot_price(d_str)
            if df is None or df.empty:
                return None
            df["symbol"] = df["symbol"].astype(str).str.strip()
            sub = df[df["symbol"].isin(SYMBOLS)].copy()
            if sub.empty:
                return None
            sub["date"] = day.strftime("%Y-%m-%d")
            # 字段规范化
            num_cols = [
                "spot_price", "near_contract_price", "dominant_contract_price",
                "near_basis", "dom_basis", "near_basis_rate", "dom_basis_rate"
            ]
            for col in num_cols:
                if col in sub.columns:
                    sub[col] = pd.to_numeric(sub[col], errors="coerce")
            return sub
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
            else:
                return None
    return None


def fetch_real_basis(full: bool = False, max_workers: int = DEFAULT_WORKERS) -> pd.DataFrame:
    """并行抓取并缓存全量交易日 SA/FG 真实基差与现货价格。"""
    days = get_trading_days()
    print(f"交易日总数: {len(days)} ({days[0].date()} 至 {days[-1].date()})")

    done_df = pd.DataFrame()
    fetched_dates = set()

    if OUT_PATH.exists() and not full:
        done_df = pd.read_csv(OUT_PATH)
        if not done_df.empty and "date" in done_df.columns:
            # 记录已经成功获取到数据的日期
            fetched_dates = set(done_df["date"].unique())
            print(f"已有缓存: {len(done_df)} 行, 覆盖 {len(fetched_dates)} 个交易日 (最后日期 {done_df['date'].max()})")

    needed_days = [d for d in days if d.strftime("%Y-%m-%d") not in fetched_dates]
    print(f"需抓取交易日: {len(needed_days)} 个 (并发线程数: {max_workers})")

    if not needed_days:
        print("所有交易日已全部缓存，无需重复拉取。")
        return done_df

    results = []
    t0 = time.time()
    completed_count = 0
    total_needed = len(needed_days)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(fetch_single_day, d): d for d in needed_days}
        for future in as_completed(future_map):
            completed_count += 1
            res = future.result()
            if res is not None and not res.empty:
                results.append(res)
            if completed_count % 100 == 0 or completed_count == total_needed:
                elapsed = time.time() - t0
                speed = completed_count / max(elapsed, 0.1)
                print(f"  进度: [{completed_count}/{total_needed}] ({completed_count/total_needed*100:.1f}%) | "
                      f"抓取成功: {len(results)} 日 | 耗时: {elapsed:.1f}s ({speed:.1f} 日/秒)", flush=True)

    if results:
        new_df = pd.concat(results, ignore_index=True)
        if not done_df.empty:
            all_df = pd.concat([done_df, new_df], ignore_index=True)
        else:
            all_df = new_df
    else:
        all_df = done_df

    if all_df.empty:
        print("未获取到有效数据！")
        return all_df

    # 去重与排序
    all_df = all_df.drop_duplicates(subset=["date", "symbol"], keep="last")
    all_df = all_df.sort_values(["date", "symbol"]).reset_index(drop=True)

    # 规范保存
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    all_df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 70)
    print(f"【真实基差数据缓存完成】已持久化至: {OUT_PATH}")
    print(f"总记录行数: {len(all_df)} 行 | 时间跨度: {all_df['date'].min()} 至 {all_df['date'].max()}")
    sa = all_df[all_df["symbol"] == "SA"]
    fg = all_df[all_df["symbol"] == "FG"]
    print(f"SA 记录: {len(sa)} 行 | 覆盖率: {len(sa)/len(days)*100:.1f}% ({len(sa)}/{len(days)})")
    print(f"FG 记录: {len(fg)} 行 | 覆盖率: {len(fg)/len(days)*100:.1f}% ({len(fg)}/{len(days)})")
    if not sa.empty:
        print(f"SA 真实主力基差: 均值 {sa['dom_basis'].mean():.2f} | 标准差 {sa['dom_basis'].std():.2f} | "
              f"极值 [{sa['dom_basis'].min():.2f}, {sa['dom_basis'].max():.2f}]")
        print(f"SA 真实基差率%: 均值 {sa['dom_basis_rate'].mean()*100:.2f}% | "
              f"极值 [{sa['dom_basis_rate'].min()*100:.2f}%, {sa['dom_basis_rate'].max()*100:.2f}%]")
    if not fg.empty:
        print(f"FG 真实主力基差: 均值 {fg['dom_basis'].mean():.2f} | 标准差 {fg['dom_basis'].std():.2f} | "
              f"极值 [{fg['dom_basis'].min():.2f}, {fg['dom_basis'].max():.2f}]")
    print("=" * 70)

    return all_df


def main() -> None:
    parser = argparse.ArgumentParser(description="拉取郑商所真实期现基差数据")
    parser.add_argument("--full", action="store_true", help="忽略已有缓存全量重拉")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="并发线程数")
    args = parser.parse_args()

    fetch_real_basis(full=args.full, max_workers=args.workers)


if __name__ == "__main__":
    main()
