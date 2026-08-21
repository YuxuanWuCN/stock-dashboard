
import json
import sys
from datetime import datetime
from pathlib import Path
import pandas as pd

ROOT = Path(r"D:\股票分析项目\2.0版")
sys.path.insert(0, str(ROOT))

from src.fetch_data import read_watchlist
from src.strategies.strategy_registry import get_registry
from src.strategies.hunting_ground import HuntingGround

def load_cached_kline(code: str) -> pd.DataFrame:
    p = ROOT / "docs" / "data" / "kline" / f"{code}.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "dates" not in data:
            return None
        dates = data["dates"]
        kline = data.get("kline", [])
        volume = data.get("volume", [0] * len(dates))
        n = len(dates)
        rows = []
        for i in range(n):
            k = kline[i] if i < len(kline) else [None, None, None, None]
            rows.append({
                "date": dates[i],
                "open": k[0],
                "close": k[1],
                "low": k[2],
                "high": k[3],
                "volume": volume[i] if i < len(volume) else 0,
            })
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        for c in ["open", "close", "high", "low", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        return df if len(df) >= 30 else None
    except Exception:
        return None

def main():
    watchlist = read_watchlist(str(ROOT / "watchlist.csv"))
    print(f"读取自选股: {len(watchlist)}")

    registry = get_registry()
    registry.auto_register_from_directory()
    strategy_names = registry.list_strategies()
    print(f"注册策略: {strategy_names}")

    stock_data_dict = {}
    raw_df_dict = {}
    failures = []
    for item in watchlist:
        code = item["code"]
        name = item.get("name", code)
        df = load_cached_kline(code)
        if df is None:
            failures.append({"code": code, "name": name, "reason": "K线缓存不足"})
            continue
        stock_data_dict[code] = (name, df)
        raw_df_dict[code] = df
    print(f"有效 K 线: {len(stock_data_dict)} / 失败: {len(failures)}")

    results = registry.run_all(stock_data_dict)
    summary = {st: len(items) for st, items in results.items()}

    out_dir = ROOT / "docs" / "data" / "strategy"
    out_dir.mkdir(parents=True, exist_ok=True)
    now_str = datetime.now().isoformat(timespec="seconds")

    selection = {
        "generated_at": now_str,
        "scope": "watchlist",
        "pool_size": len(watchlist),
        "failures": failures,
        "summary": summary,
        "results": results,
    }
    (out_dir / "selection.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"selection.json 已更新: {summary}")

    hg = HuntingGround()
    hunting = hg.build(selection, raw_df_dict)
    hg_payload = {"generated_at": now_str, "hunting_ground": hunting}
    (out_dir / "hunting_ground.json").write_text(
        json.dumps(hg_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(v) for v in hunting.values())
    print(f"hunting_ground.json 已更新（wrapper 格式，共 {total} 条买点判断）")

    # 市场温度：保留旧值（需要全市场网络数据，离线不重算）
    print("market_temperature.json 保留旧值（需全市场实时行情）")

if __name__ == "__main__":
    main()
