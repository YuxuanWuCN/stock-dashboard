# -*- coding: utf-8 -*-
"""增量刷新郑商所纯碱/玻璃主力连续日线（只更新期货，跳过慢速期权下载）。

用法: python -m src.trading.refresh_market_data
"""

import sys
from pathlib import Path

import akshare as ak
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
RAW_DIR = ROOT_DIR / "data" / "raw"

SYMBOLS = {
    "SA0": "czce_sa_futures_daily_raw.csv",
    "FG0": "czce_fg_futures_daily_raw.csv",
}


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for sym, filename in SYMBOLS.items():
        path = RAW_DIR / filename
        old_last = None
        if path.exists():
            old = pd.read_csv(path)
            old_last = str(old["日期"].max())
        print("[刷新] %s ..." % sym)
        try:
            df = ak.futures_main_sina(symbol=sym)
            if df is None or df.empty:
                print("  警告: 返回为空，保留原文件")
                continue
            new_last = str(df["日期"].max())
            df.to_csv(path, index=False, encoding="utf-8-sig")
            added = 0
            if old_last:
                added = int((df["日期"].astype(str) > old_last).sum())
            print("  -> %s: %d 行 | 原最后日期 %s -> 新最后日期 %s（新增 %d 个交易日）"
                  % (sym, len(df), old_last, new_last, added))
        except Exception as exc:
            print("  错误: %s" % exc)


if __name__ == "__main__":
    main()
