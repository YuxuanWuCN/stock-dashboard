# tools/reconstruct_summary.py —— 从 K线重建历史交易日快照
#
# 背景（B 修复）：8/11 与 8/12 的 daily_local 任务部分失败，summary.json 中
# 大量股票被标成 stale（旧涨跌），导致随机对照组（tools/random_control.py）
# 的有效池只有 52/148 只。K线文件（docs/data/kline/*.json）保存了完整历史，
# 可以重建任意交易日的"当日涨跌"快照，修复对照组的样本完整性。
#
# 原理：对指定交易日 D，
#   - 涨跌幅 = (D 收盘价 - D 前一交易日收盘价) / 前收盘 * 100
#   - 若 K线无 D 数据（休市/缺失），该股票当日视为无有效涨跌
#
# 用法：
#   python tools/reconstruct_summary.py --date 2026-08-11   # 重建单日
#   python tools/reconstruct_summary.py --date 2026-08-11 --date 2026-08-12
#   python tools/reconstruct_summary.py --all               # 重建全部记录日
#
# 输出：docs/data/paper/daily_snapshots/{trade_date}.json
#   {"trade_date": "...", "items": [{code, name, type, change_pct, last_close}...]}

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DATA_DIR

KLINE_DIR = os.path.join(DATA_DIR, "kline")
OUT_DIR = os.path.join(DATA_DIR, "paper", "daily_snapshots")
SUMMARY_PATH = os.path.join(DATA_DIR, "summary.json")


def _load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _meta_for(code):
    """从 summary 取名称与类型（K线文件里通常没有 name/type）。"""
    pass


def build_snapshot(trade_date: str) -> dict:
    """从全部 K线重建指定交易日的涨跌快照。"""
    items = []
    summary = _load_json(SUMMARY_PATH)
    meta_map = {}
    if summary:
        for it in summary.get("items", []):
            meta_map[it.get("code")] = it

    files = sorted(f for f in os.listdir(KLINE_DIR) if f.endswith(".json"))
    for fname in files:
        code = fname[:-5]
        d = _load_json(os.path.join(KLINE_DIR, fname))
        if not d:
            continue
        dates = d.get("dates", [])
        kline = d.get("kline", [])
        if trade_date not in dates:
            continue
        i = dates.index(trade_date)
        if i < 1:
            continue
        prev_close = kline[i - 1][1]
        cur_close = kline[i][1]
        if not prev_close or not cur_close or prev_close <= 0:
            continue
        meta = meta_map.get(code, {})
        items.append({
            "code": code,
            "name": meta.get("name", code),
            "type": meta.get("type", "stock"),
            "last_close": cur_close,
            "change_pct": round((cur_close - prev_close) / prev_close * 100.0, 2),
            "last_date": trade_date,
            "status": "ok",
        })

    items.sort(key=lambda x: x["code"])
    return {"trade_date": trade_date, "total": len(items), "items": items}


def main():
    parser = argparse.ArgumentParser(description="从 K线重建历史交易日快照")
    parser.add_argument("--date", action="append", dest="dates", help="要重建的交易日")
    parser.add_argument("--all", action="store_true", help="重建全部绩效记录中的交易日")
    args = parser.parse_args()

    dates = list(args.dates or [])
    if args.all:
        perf_dir = os.path.join(DATA_DIR, "paper")
        seen = set()
        for fname in os.listdir(perf_dir):
            if not fname.startswith("performance") or not fname.endswith(".json"):
                continue
            perf = _load_json(os.path.join(perf_dir, fname))
            if not perf:
                continue
            for rec in perf.get("records", []):
                if rec.get("trade_date"):
                    seen.add(rec["trade_date"])
        dates = sorted(seen)

    if not dates:
        print("用法: --date YYYY-MM-DD 或 --all")
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)
    for d in dates:
        snap = build_snapshot(d)
        out = os.path.join(OUT_DIR, f"{d}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        print(f"✅ {d}: {snap['total']} 只有效涨跌 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
