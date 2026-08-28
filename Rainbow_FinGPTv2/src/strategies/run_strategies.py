"""v2.5 策略选股主入口。

对自选股 + 扩展股票池（strategy_pool.csv）执行注册的策略，产出选股结果 JSON。

用法：
    python -m src.strategies.run_strategies            # 自选股 + 扩展池
    python -m src.strategies.run_strategies --pool-only # 只跑扩展池
    python -m src.strategies.run_strategies --scope watchlist
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

# 允许以 python -m src.strategies.run_strategies 方式运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.config import DATA_DIR
from src.fetch_data import read_watchlist as _fw
from src.strategies.strategy_registry import get_registry

logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(DATA_DIR, "strategy")
POOL_FILE = "strategy_pool.csv"


def load_pool(path: str = POOL_FILE) -> list:
    """读取扩展股票池 CSV（格式同 watchlist.csv）。"""
    if not os.path.exists(path):
        logger.warning("扩展股票池 %s 不存在，跳过", path)
        return []
    try:
        return _fw(path)
    except Exception as exc:
        logger.error("读取扩展股票池失败: %s", exc)
        return []


def run_strategies(scope: str = "all") -> dict:
    """执行全部策略，返回结果。"""
    from src.build_ranking import fetch_5y_data

    watchlist = _fw("watchlist.csv")
    pool = load_pool(POOL_FILE) if scope in ("all", "pool") else []

    items = []
    if scope in ("all", "watchlist"):
        items.extend(watchlist)
    if scope in ("all", "pool"):
        items.extend(pool)

    # 去重（按代码）
    seen = set()
    unique_items = []
    for item in items:
        if item["code"] not in seen:
            seen.add(item["code"])
            unique_items.append(item)

    registry = get_registry()
    registry.auto_register_from_directory()

    stock_data = {}
    failures = []
    for item in unique_items:
        df = fetch_5y_data(item)
        if df is None or df.empty:
            failures.append(item["code"])
            continue
        stock_data[item["code"]] = (item["name"], df)

    results = registry.run_all(stock_data)

    # 汇总
    summary = {}
    for strategy_name, signals in results.items():
        summary[strategy_name] = len(signals)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scope": scope,
        "pool_size": len(unique_items),
        "failures": failures,
        "summary": summary,
        "results": results,
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="v2.5 策略选股")
    parser.add_argument("--scope", choices=["all", "watchlist", "pool"], default="all",
                        help="选股范围：全部/仅自选股/仅扩展池")
    parser.add_argument("--output", default=None, help="输出 JSON 路径")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    payload = run_strategies(args.scope)

    out_path = args.output or os.path.join(OUTPUT_DIR, "selection.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"选股完成：{payload['pool_size']} 只标的，结果写入 {out_path}")
    for strategy_name, count in payload["summary"].items():
        print(f"  {strategy_name}: {count} 只命中")


if __name__ == "__main__":
    main()
