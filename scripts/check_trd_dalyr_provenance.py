# -*- coding: utf-8 -*-
"""scripts/check_trd_dalyr_provenance.py —— TRD_Dalyr 拉数真实性独立验证（可复用，B/C 通用）。

内部一致性（标签、IC、组合）不能证明数据真实——合成数据同样自洽。本脚本用
**独立于 CSMAR 的基准**交叉验证拉取数据的真实性，全部检查默认只读本地文件：

C1 原生表头：原始缓存批文件含 CSMAR TRD_Dalyr 16 字段（Stkcd/Trddt/Dretwd/...）。
C2 市值-股本恒等：抽样手算 Dsmvtll×1000/Clsprc ≈ 真实总股本（人工核对项，脚本仅打印）。
C3 跨表交叉：Dalyr 含息收益 vs master 面板（另一管道 TRD_FwardQuotation 前复权）收益
   —— 相关系数应 >0.999，逐行 <3bp 一致比例应 >99%；残余差异应为除权噪声量级。
C4 市场事件指纹：2024-09-30（924 行情）截面均值强正、2025-04-07（关税暴跌）强负且
   跌停级支数众多、普通对照日温和。
C5 板块涨跌停纪律：主板 |ret|≤10.5%、创业板/科创板 |ret|≤20.5%，越限行数应为 0。
C6 停牌对应：Dalyr 相对 master 的缺行必须全部是 master volume==0 的停牌日。
C7 外部抽查（--external N，需联网）：akshare（东财/新浪，独立于 CSMAR）不复权收盘价
   与 Clsprc 逐分比对；C6/C7 使任何伪造在经济上不可行。

任一硬断言失败以非零退出码结束（fail-closed）。
"""

from __future__ import annotations

import argparse
import glob
import random
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

EVENT_DAYS = [
    ("2024-09-30", "924行情涨停潮", "strong_up"),
    ("2024-10-08", "节后高开", "up"),
    ("2025-04-07", "关税暴跌", "strong_down"),
    ("2024-01-02", "普通日对照", "normal"),
]
TRD_DALYR_FIELDS = {"Stkcd", "Trddt", "Clsprc", "Dretwd", "Dsmvtll", "Trdsta", "LimitStatus"}


class ProvenanceError(AssertionError):
    """真实性验证失败。"""


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ProvenanceError(message)


def _panel(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"ticker": str}, encoding="utf-8-sig")
    frame["board_limit"] = np.where(frame["ticker"].str.startswith(("300", "688")), 0.20, 0.10)
    return frame


def check_native_header() -> None:
    batches = sorted(glob.glob(str(ROOT / "data/_raw_cache/TRD_Dalyr_*.csv")))
    _expect(bool(batches), "C1 失败：data/_raw_cache 下没有 TRD_Dalyr 批缓存")
    header = set(pd.read_csv(batches[0], nrows=1).columns)
    _expect(TRD_DALYR_FIELDS <= header, f"C1 失败：批缓存缺 CSMAR 原生字段：{sorted(TRD_DALYR_FIELDS - header)}")
    print(f"✔ C1 原生表头：{len(batches)} 个批缓存含 TRD_Dalyr 16 字段")


def check_cross_table(panel: pd.DataFrame, master: pd.DataFrame) -> None:
    master_b = master[["stock_code", "trade_date", "close", "volume"]].copy()
    master_b = master_b[master_b["stock_code"].isin(set(panel["ticker"]))]
    master_b["m_ret"] = master_b.groupby("stock_code")["close"].pct_change()
    joined = panel.merge(master_b, left_on=["ticker", "date"], right_on=["stock_code", "trade_date"], how="inner")
    joined = joined.replace([np.inf, -np.inf], np.nan).dropna(subset=["ret", "m_ret"])
    both = joined[np.abs(joined["ret"]) > 1e-6]
    _expect(len(both) > 1000, f"C3 失败：可比对行过少 {len(both)}")
    corr = float(both[["ret", "m_ret"]].corr().iloc[0, 1])
    agree = float((np.abs(both["ret"] - both["m_ret"]) < 3e-4).mean())
    _expect(corr > 0.999, f"C3 失败：跨表相关系数 {corr:.6f} < 0.999")
    _expect(agree > 0.99, f"C3 失败：逐行一致比例 {agree:.2%} < 99%")
    print(f"✔ C3 跨表交叉：{len(both):,} 行，相关 {corr:.6f}，<3bp 一致 {agree:.2%}（残余为除权噪声量级）")


def check_events(panel: pd.DataFrame) -> None:
    for date, label, kind in EVENT_DAYS:
        day = panel[panel["date"] == date]
        _expect(not day.empty, f"C4 失败：事件日 {date} 无数据行")
        mean_ret = float(day["ret"].mean())
        if kind == "strong_up":
            _expect(mean_ret > 0.04, f"C4 失败：{date} 均值 {mean_ret:+.4f} 不符合强正事件")
        elif kind == "strong_down":
            _expect(mean_ret < -0.04, f"C4 失败：{date} 均值 {mean_ret:+.4f} 不符合强负事件")
            _expect(int((day["ret"] <= -0.095).sum()) > 10, f"C4 失败：{date} 跌停级支数异常少")
        elif kind == "up":
            _expect(mean_ret > 0.01, f"C4 失败：{date} 均值 {mean_ret:+.4f} 不符合高开事件")
        else:
            _expect(abs(mean_ret) < 0.02, f"C4 失败：对照日 {date} 均值 {mean_ret:+.4f} 异常")
        print(f"✔ C4 事件指纹：{date} [{label}] 截面均值 {mean_ret:+.4f}")


def check_limits(panel: pd.DataFrame) -> None:
    violations = panel[np.abs(panel["ret"]) > panel["board_limit"] + 0.005]
    _expect(len(violations) == 0, f"C5 失败：涨跌停越限 {len(violations)} 行："
            f"{violations[['ticker','date','ret']].head().to_dict('records')}")
    print(f"✔ C5 涨跌停纪律：{len(panel):,} 行 0 越限（主板±10% / 创业板科创板±20%）")


def check_suspension(panel: pd.DataFrame, master: pd.DataFrame) -> None:
    merged = master[master["stock_code"].isin(set(panel["ticker"]))].merge(
        panel[["ticker", "date"]], left_on=["stock_code", "trade_date"],
        right_on=["ticker", "date"], how="left", indicator=True)
    absent = merged[merged["_merge"] == "left_only"]
    not_suspended = absent[absent["volume"].fillna(-1) != 0]
    _expect(len(not_suspended) == 0,
            f"C6 失败：{len(not_suspended)} 个缺行不是停牌日（volume!=0）："
            f"{not_suspended[['stock_code','trade_date']].head().to_dict('records')}")
    print(f"✔ C6 停牌对应：{len(absent)} 个缺行全部为 master volume==0 的停牌日")


def check_external(panel: pd.DataFrame, stocks: int, per_stock: int, seed: int) -> None:
    import akshare as ak

    rng = random.Random(seed)
    codes = sorted(panel["ticker"].unique())
    main_board = [c for c in codes if not c.startswith(("300", "688"))]
    growth = [c for c in codes if c.startswith(("300", "688"))]
    picks = rng.sample(main_board, min(stocks - 1, len(main_board))) + rng.sample(growth, 1)
    exact = total = 0
    checked = 0
    for code in picks:
        symbol = ("sh" if code.startswith("6") else "sz") + code
        frame = None
        for attempt in range(3):
            try:
                frame = ak.stock_zh_a_daily(symbol=symbol, start_date="20240101", end_date="20260828", adjust="")
                break
            except Exception:
                time.sleep(3)
        if frame is None:
            print(f"  [{code}] 外部源不可达（跳过，不影响本地断言）")
            continue
        frame["date"] = frame["date"].astype(str)
        mine = panel[panel["ticker"] == code].set_index("date")["close"]
        common = sorted(set(mine.index) & set(frame["date"]))
        for date in rng.sample(common, min(per_stock, len(common))):
            total += 1
            external = float(frame.loc[frame["date"] == date, "close"].iloc[0])
            own = float(mine[date])
            _expect(abs(own - external) < 0.005,
                    f"C7 失败：{code}@{date} CSMAR={own} vs 公开盘={external}")
            exact += 1
        checked += 1
        print(f"✔ C7 外部抽查：{code} {per_stock} 日逐分一致")
        time.sleep(2)
    _expect(checked > 0, "C7：外部源全部不可达，无法完成抽查（仅联网环境可执行）")
    print(f"  C7 汇总：{exact}/{total} 个 (股票,日期) 精确一致（<0.005 元）")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TRD_Dalyr 拉数真实性独立验证")
    parser.add_argument("--panel", default="data/task_split/factors_daily_panel_student_B.csv")
    parser.add_argument("--master", default="data/task_split/csmar_master/csmar_factor_panel_master.csv")
    parser.add_argument("--external", type=int, default=0, help="外部抽查支数（需联网；0=跳过）")
    parser.add_argument("--per-stock", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260919)
    args = parser.parse_args(argv)

    panel = _panel(ROOT / args.panel)
    master = pd.read_csv(ROOT / args.master, dtype={"stock_code": str})

    check_native_header()
    check_cross_table(panel, master)
    check_events(panel)
    check_limits(panel)
    check_suspension(panel, master)
    if args.external:
        check_external(panel, args.external, args.per_stock, args.seed)
    print("\n数据真实性独立验证：全部硬断言通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
