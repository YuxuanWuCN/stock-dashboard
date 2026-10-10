# -*- coding: utf-8 -*-
"""拉取郑商所纯碱 (SA) 官方真实注册仓单日线数据（郑商所 DFS 仓单日报口径）。

数据源：郑商所官方静态文件服务器 (CZCE DFS) 每日仓单 Excel 表格与东方财富期货仓单接口
输出：`data/raw/czce_warehouse_receipts.csv`
字段：date, warehouse_receipts_sa

本模块彻底替换 `BasisConvergenceEngine.simulate_dynamic_basis` 中的 OU 随机模拟仓单（缺陷 B2 / 任务 T2）。

用法:
    python -m src.data.fetch_real_warehouse_receipts            # 增量拉取/断点续传
    python -m src.data.fetch_real_warehouse_receipts --full     # 全量重拉
    python -m src.data.fetch_real_warehouse_receipts --workers 12
"""

import argparse
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import List, Optional

import pandas as pd
import requests

sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT_PATH = RAW_DIR / "czce_warehouse_receipts.csv"
SA_RAW = RAW_DIR / "czce_sa_futures_daily_raw.csv"

DEFAULT_WORKERS = 12
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def get_trading_days() -> List[pd.Timestamp]:
    """以纯碱期货原始日线的日期为交易日基准序列（2019-12-06 至今）。"""
    if not SA_RAW.exists():
        raise FileNotFoundError(f"未找到纯碱原始期货数据: {SA_RAW}")
    df = pd.read_csv(SA_RAW)
    dates = pd.to_datetime(df["日期"])
    return sorted(dates.unique())


def fetch_single_day_receipt(day: pd.Timestamp, max_retries: int = 3) -> Optional[float]:
    """抓取并解析单交易日 SA 官方在册仓单数量（张）。"""
    d_str = day.strftime("%Y%m%d")
    year = d_str[:4]
    ext = "xlsx" if int(d_str) >= 20260101 else "xls"
    url = f"http://www.czce.com.cn/cn/DFSStaticFiles/Future/{year}/{d_str}/FutureDataWhsheet.{ext}"

    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=12)
            if resp.status_code == 404:
                # 非交易日或当日未生成仓单日报，返回 0.0
                return 0.0
            if resp.status_code != 200:
                time.sleep(0.5 * (attempt + 1))
                continue

            content = resp.content
            df = pd.read_excel(BytesIO(content))
            if df is None or df.empty:
                return 0.0

            # 寻找 SA 品种所在的起始行
            first_col_str = df.iloc[:, 0].astype(str)
            sa_idx = df[first_col_str.str.contains("品种：SA|品种:SA|SA", regex=True)].index

            if len(sa_idx) == 0:
                # 早期未挂牌或未生成 SA 仓单
                return 0.0

            start_i = sa_idx[0]
            # 扫描后续 80 行以寻找该品种的总计行
            sub = df.iloc[start_i:start_i + 85]
            for idx, row in sub.iterrows():
                first_val = str(row.iloc[0]).strip()
                if "总计" in first_val or "合计" in first_val:
                    # 寻找第一个合法的非负数值作为仓单数量
                    for val in row.iloc[1:]:
                        try:
                            if pd.notna(val):
                                f_val = float(str(val).replace(",", "").strip())
                                if f_val >= 0:
                                    return f_val
                        except (ValueError, TypeError):
                            continue
                    return 0.0
                elif idx > start_i + 2 and ("品种：" in first_val or "品种:" in first_val):
                    # 进入下一品种且无总计行
                    break

            return 0.0
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
            else:
                return None
    return None


def fetch_real_warehouse_receipts(full: bool = False, max_workers: int = DEFAULT_WORKERS) -> pd.DataFrame:
    """并行抓取并缓存全量交易日纯碱真实注册仓单序列。"""
    days = get_trading_days()
    print(f"交易日总数: {len(days)} ({days[0].date()} 至 {days[-1].date()})")

    done_df = pd.DataFrame()
    fetched_dates = set()

    if OUT_PATH.exists() and not full:
        done_df = pd.read_csv(OUT_PATH)
        if not done_df.empty and "date" in done_df.columns:
            fetched_dates = set(done_df["date"].unique())
            print(f"已有仓单缓存: {len(done_df)} 行, 覆盖 {len(fetched_dates)} 个交易日 (最后日期 {done_df['date'].max()})")

    needed_days = [d for d in days if d.strftime("%Y-%m-%d") not in fetched_dates]
    print(f"需抓取交易日: {len(needed_days)} 个 (并发线程数: {max_workers})")

    if not needed_days:
        print("所有交易日仓单已全部缓存，无需重复拉取。")
        return done_df

    results = []
    t0 = time.time()
    completed_count = 0
    total_needed = len(needed_days)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(fetch_single_day_receipt, d): d for d in needed_days}
        for future in as_completed(future_map):
            completed_count += 1
            d = future_map[future]
            val = future.result()
            if val is not None:
                results.append({"date": d.strftime("%Y-%m-%d"), "warehouse_receipts_sa": float(val)})
            if completed_count % 100 == 0 or completed_count == total_needed:
                elapsed = time.time() - t0
                speed = completed_count / max(elapsed, 0.1)
                print(f"  进度: [{completed_count}/{total_needed}] ({completed_count/total_needed*100:.1f}%) | "
                      f"有效仓单: {len(results)} 日 | 耗时: {elapsed:.1f}s ({speed:.1f} 日/秒)", flush=True)

    if results:
        new_df = pd.DataFrame(results)
        if not done_df.empty:
            all_df = pd.concat([done_df, new_df], ignore_index=True)
        else:
            all_df = new_df
    else:
        all_df = done_df

    if all_df.empty:
        print("未获取到有效仓单数据！")
        return all_df

    all_df = all_df.drop_duplicates(subset=["date"], keep="last")
    all_df = all_df.sort_values(["date"]).reset_index(drop=True)

    # 缺失值前向/后向填充确保连续性
    all_df["warehouse_receipts_sa"] = all_df["warehouse_receipts_sa"].fillna(0.0)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    all_df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 70)
    print(f"【真实仓单数据缓存完成】已持久化至: {OUT_PATH}")
    print(f"总记录行数: {len(all_df)} 行 | 时间跨度: {all_df['date'].min()} 至 {all_df['date'].max()}")
    print(f"仓单统计: 均值 {all_df['warehouse_receipts_sa'].mean():.2f} 张 | "
          f"标准差 {all_df['warehouse_receipts_sa'].std():.2f} 张 | "
          f"极值 [{all_df['warehouse_receipts_sa'].min():.0f}, {all_df['warehouse_receipts_sa'].max():.0f}] 张")
    latest_row = all_df[all_df["date"] == "2026-09-28"]
    if not latest_row.empty:
        print(f"2026-09-28 最新在册仓单核验: {latest_row.iloc[0]['warehouse_receipts_sa']:.0f} 张 (基准期望值: 1851 张)")
    print("=" * 70)

    return all_df


def main() -> None:
    parser = argparse.ArgumentParser(description="拉取郑商所真实在册仓单数据")
    parser.add_argument("--full", action="store_true", help="忽略已有缓存全量重拉")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="并发线程数")
    args = parser.parse_args()

    fetch_real_warehouse_receipts(full=args.full, max_workers=args.workers)


if __name__ == "__main__":
    main()
