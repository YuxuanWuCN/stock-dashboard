# tools/paper_portfolio.py —— 模拟盘组合绩效跟踪（每日收盘后自动记录）
#
# 用法：
#   python tools/paper_portfolio.py report    # 读取组合 + 最新summary，记录今日绩效
#
# 输出：
#   docs/data/paper/performance.json  历史绩效（按 trade_date 去重）

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DATA_DIR
from src.utils import beijing_date_str, beijing_datetime_str

PORTFOLIO_PATH = os.path.join(DATA_DIR, "paper", "portfolio.json")
PERFORMANCE_PATH = os.path.join(DATA_DIR, "paper", "performance.json")
SUMMARY_PATH = os.path.join(DATA_DIR, "summary.json")
RANKING_PATH = os.path.join(DATA_DIR, "analysis", "ranking.json")
BENCHMARK_PATH = os.path.join(DATA_DIR, "paper", "benchmark.json")
KLINE_DIR = os.path.join(DATA_DIR, "kline")


def _load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None




def _portfolio_files():
    """扫描 paper 目录下所有组合文件（portfolio*.json）。"""
    paper_dir = os.path.join(DATA_DIR, "paper")
    if not os.path.isdir(paper_dir):
        return []
    return sorted(
        os.path.join(paper_dir, f)
        for f in os.listdir(paper_dir)
        if f.startswith("portfolio") and f.endswith(".json") and f != "performance.json"
    )


def _performance_path_for(portfolio_path: str) -> str:
    """由组合文件推导绩效文件：portfolio.json -> performance.json；portfolio_aggressive.json -> performance_aggressive.json。"""
    name = os.path.splitext(os.path.basename(portfolio_path))[0]
    suffix = name[len("portfolio"):]
    return os.path.join(DATA_DIR, "paper", f"performance{suffix}.json")

def report(portfolio_path: str = None) -> int:
    portfolio = _load_json(portfolio_path or PORTFOLIO_PATH)
    summary = _load_json(SUMMARY_PATH)
    ranking = _load_json(RANKING_PATH)
    pred_map = {}
    if ranking:
        for it in ranking.get("items", []):
            fc = it.get("forecast") or {}
            pred_map[it.get("code")] = {
                "up3": fc.get("up_probability_3d_pct"),
                "ret3": fc.get("return_3d_pct"),
                "up5": fc.get("up_probability_5d_pct"),
                "ret5": fc.get("return_5d_pct"),
            }
    if not portfolio or not summary:
        print("缺少 portfolio.json 或 summary.json")
        return 1

    items_map = {i["code"]: i for i in summary.get("items", [])}
    # 记录日期用数据实际交易日（summary 多数股票的最后日期），避免把旧数据记成今天
    from collections import Counter
    _dates = [i.get("last_date") for i in summary.get("items", []) if i.get("last_date")]
    today = Counter(_dates).most_common(1)[0][0] if _dates else beijing_date_str()

    # 组合收益 = Σ(权重% × 涨跌%)，现金部分按 0
    rows = []
    valid_changes = []
    skipped = []
    total_weight = 0.0
    weighted_return = 0.0
    for item in portfolio.get("items", []):
        code = item["code"]
        pct = item.get("pct", 0)
        row = items_map.get(code)
        if row is None or row.get("status") == "failed" or row.get("status") == "stale":
            skipped.append({"code": code, "name": item.get("name"), "reason": (row or {}).get("status", "missing")})
            rows.append({"code": code, "name": item.get("name"), "change_pct": None, "note": "无有效数据"})
            continue
        chg = row.get("change_pct")
        if chg is None:
            skipped.append({"code": code, "name": item.get("name"), "reason": "no_change"})
            rows.append({"code": code, "name": item.get("name"), "change_pct": None, "note": "无涨跌数据"})
            continue
        p = pred_map.get(code, {})
        rows.append({"code": code, "name": item.get("name"), "change_pct": chg, "pred_up3": p.get("up3"), "pred_ret3": p.get("ret3"), "pred_up5": p.get("up5"), "pred_ret5": p.get("ret5")})
        total_weight += pct
        weighted_return += pct * chg
        valid_changes.append(chg)

    cash_pct = portfolio.get("cash_pct", 0)
    total_weight += cash_pct  # 现金权重
    weighted_return_pct = weighted_return / 100.0 if total_weight else 0.0  # 组合总收益（含现金，%）
    equal_weight_pct = (sum(valid_changes) / len(valid_changes)) if valid_changes else None  # 等权基准（不含现金）

    entry = {
        "recorded_at": beijing_datetime_str(),
        "trade_date": today,
        "portfolio_return_pct": round(weighted_return_pct, 2),
        "equal_weight_return_pct": round(equal_weight_pct, 2) if equal_weight_pct is not None else None,
        "valid_count": len(valid_changes),
        "skipped": skipped,
        "items": rows,
    }

    performance_path = _performance_path_for(portfolio_path or PORTFOLIO_PATH)
    perf = _load_json(performance_path)
    if perf is None:
        perf = {"schema_version": "1.0", "portfolio_name": portfolio.get("name"), "records": []}
    # 同一天去重（覆盖当天记录）
    perf["records"] = [r for r in perf.get("records", []) if r.get("trade_date") != today]
    perf["records"].append(entry)
    os.makedirs(os.path.dirname(performance_path), exist_ok=True)
    with open(performance_path, "w", encoding="utf-8") as f:
        json.dump(perf, f, ensure_ascii=False, indent=2)

    print(f"[{today}] 组合收益 {weighted_return_pct:.2f}% | 等权基准 {equal_weight_pct:.2f}% | 有效 {len(valid_changes)} 只")
    for r in rows:
        chg = "无数据" if r.get("change_pct") is None else f"{r['change_pct']}%"
        print(f"  {r['code']} {r['name']}: {chg}")
    return 0


def _equal_weight_daily_from_kline(trade_date: str):
    """全池等权当日收益（回填用）：用每只票前收盘->当日收盘计算。"""
    import glob
    changes = []
    for path in glob.glob(os.path.join(KLINE_DIR, "*.json")):
        d = _load_json(path)
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
        if prev_close and cur_close and prev_close > 0:
            changes.append((cur_close - prev_close) / prev_close * 100.0)
    return (sum(changes) / len(changes)) if changes else None


def benchmark() -> int:
    """记录全池等权买入持有基准（对照组）：当日收益=全部有效自选股涨跌幅等权平均。"""
    summary = _load_json(SUMMARY_PATH)
    if not summary or not summary.get("items"):
        print("缺少 summary.json")
        return 1
    changes = []
    skipped = []
    dates = []
    for it in summary["items"]:
        d = it.get("last_date")
        if d:
            dates.append(d)
        chg = it.get("change_pct")
        if it.get("status") in ("failed", "stale") or chg is None:
            skipped.append({"code": it.get("code"), "name": it.get("name"),
                            "reason": it.get("status", "no_change")})
            continue
        changes.append(chg)
    if not changes:
        print("无有效涨跌数据")
        return 1
    from collections import Counter
    today = Counter(dates).most_common(1)[0][0] if dates else beijing_date_str()
    daily = sum(changes) / len(changes)

    data = _load_json(BENCHMARK_PATH) or {
        "schema_version": "1.0",
        "name": "全池等权基准（全部自选股买入持有）",
        "records": [],
    }
    records = data.get("records", [])
    records = [r for r in records if r.get("trade_date") != today]

    if not records:
        # 首次运行：用 kline 回填到模拟盘起点（performance.json 最早记录日），使曲线起点一致
        perf = _load_json(PERFORMANCE_PATH)
        start = None
        if perf and perf.get("records"):
            start = perf["records"][0].get("trade_date")
        if start and start != today:
            back = _equal_weight_daily_from_kline(start)
            if back is not None:
                records.append({
                    "recorded_at": beijing_datetime_str(),
                    "trade_date": start,
                    "daily_return_pct": round(back, 2),
                    "cumulative_return_pct": round(back, 2),
                    "valid_count": None,
                    "skipped": [],
                    "source": "kline_backfill",
                })

    prev_cum = records[-1].get("cumulative_return_pct", 0.0) if records else 0.0
    cum = (1 + prev_cum / 100.0) * (1 + daily / 100.0) - 1
    records.append({
        "recorded_at": beijing_datetime_str(),
        "trade_date": today,
        "daily_return_pct": round(daily, 2),
        "cumulative_return_pct": round(cum * 100.0, 2),
        "valid_count": len(changes),
        "skipped": skipped,
    })
    records.sort(key=lambda r: r["trade_date"])
    data["records"] = records
    os.makedirs(os.path.dirname(BENCHMARK_PATH), exist_ok=True)
    with open(BENCHMARK_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[{today}] 全池等权日收益 {daily:.2f}% | 累计 {cum * 100:.2f}% | 有效 {len(changes)} 只")
    return 0


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="模拟盘绩效跟踪")
    parser.add_argument("cmd", choices=["report", "benchmark"])
    args = parser.parse_args()
    if args.cmd == "benchmark":
        return benchmark()
    # 扫描全部组合（稳健 + 激进），逐个记录
    files = _portfolio_files()
    if not files:
        print("没有找到组合文件")
        return 1
    ok = 0
    for f in files:
        ok += report(f)
    return 0 if ok == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
