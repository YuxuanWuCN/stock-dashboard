# -*- coding: utf-8 -*-
"""
数据拉取脚本: 下载郑商所纯碱 (SA) 与玻璃 (FG) 历史全量期货及期权日线数据
保存路径: data/raw/ (不可变原始数据区)
"""

import sys
import io
from pathlib import Path
import pandas as pd
import akshare as ak

# 强制标准输出为 UTF-8
sys.stdout.reconfigure(encoding='utf-8')

# 项目根目录定位
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
RAW_DIR = ROOT_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

def download_futures_daily() -> None:
    """拉取郑商所纯碱 (SA0) 与玻璃 (FG0) 主力连续历史日线数据"""
    symbols = {
        "SA0": "czce_sa_futures_daily_raw.csv",
        "FG0": "czce_fg_futures_daily_raw.csv"
    }
    
    for sym, filename in symbols.items():
        print(f"[1/2] 正在拉取郑商所主力连续合约 {sym} 历史日线数据...")
        try:
            df = ak.futures_main_sina(symbol=sym)
            if df is not None and not df.empty:
                target_path = RAW_DIR / filename
                df.to_csv(target_path, index=False, encoding="utf-8-sig")
                print(f"  -> 成功保存 {sym}: {len(df)} 行数据 -> {target_path}")
            else:
                print(f"  -> 警告: 拉取 {sym} 返回为空！")
        except Exception as e:
            print(f"  -> 错误: 拉取 {sym} 出现异常: {e}")

def download_options_sample() -> None:
    """拉取 2024 年纯碱场内期权完整日度行情样本"""
    print("[2/2] 正在拉取郑商所纯碱期权 (SA 2024年度) 历史全量合约日线样本...")
    try:
        df_opt = ak.option_hist_yearly_czce(symbol="SA", year="2024")
        if df_opt is not None and not df_opt.empty:
            target_path = RAW_DIR / "czce_sa_options_2024_raw.csv"
            df_opt.to_csv(target_path, index=False, encoding="utf-8-sig")
            print(f"  -> 成功保存 SA 期权: {len(df_opt)} 行数据 -> {target_path}")
        else:
            print("  -> 警告: SA 期权数据返回为空！")
    except Exception as e:
        print(f"  -> 错误: 拉取期权数据出现异常: {e}")

if __name__ == "__main__":
    print(f"=== 开始下载郑商所衍生品原始数据 (保存至: {RAW_DIR}) ===")
    download_futures_daily()
    download_options_sample()
    print("=== 原始数据拉取完成 ===")
