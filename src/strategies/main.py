"""v2.5 策略研究综合入口：选股 → 狩猎场 → 市场温度 → 回测。

产出 docs/data/strategy/ 下的 JSON 结果，供前端展示与每日自动化。

用法：
    python -m src.strategies.main --scope pool          # 只选股 + 狩猎场 + 温度
    python -m src.strategies.main --backtest            # 追加回测
    python -m src.strategies.main --scope watchlist
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# 允许以 python -m 方式运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.config import DATA_DIR
from src.strategies.hunting_ground import HuntingGround
from src.strategies.market_temperature import MarketTemperature, MarketTemperatureError

logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(DATA_DIR, "strategy")


def _load_stock_data_from_selection(selection_path: str):
    """从已保存的选股结果中恢复股票数据（每只重新抓取）。

    选股结果条目不含 type 字段，此处从 watchlist.csv / strategy_pool.csv
    反查标的类型（stock/us/kr/hk/etf），供 fetch_5y_data 使用。
    """
    from src.build_ranking import fetch_5y_data
    from src.fetch_data import read_watchlist as _read_watchlist

    type_map = {}
    for csv_path in ("watchlist.csv", "strategy_pool.csv"):
        if not os.path.exists(csv_path):
            continue
        try:
            for item in _read_watchlist(csv_path):
                type_map[item["code"]] = item.get("type", "stock")
        except Exception:
            continue

    with open(selection_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    items = []
    for strategy_name, entries in payload.get("results", {}).items():
        for entry in entries:
            items.append({
                "code": entry["code"],
                "name": entry.get("name", ""),
                "type": type_map.get(entry["code"], entry.get("type", "stock")),
            })
    stock_data = {}
    names = {}
    for item in items:
        df = fetch_5y_data(item)
        if df is not None and not df.empty:
            stock_data[item["code"]] = df
            names[item["code"]] = item["name"]
    return stock_data, names


def main() -> int:
    parser = argparse.ArgumentParser(description="v2.5 策略研究综合入口")
    parser.add_argument("--scope", choices=["all", "watchlist", "pool"], default="all")
    parser.add_argument("--backtest", action="store_true", help="执行策略回测")
    parser.add_argument("--backtest-start", default="2025-01-01", help="回测开始日期")
    parser.add_argument("--backtest-end", default="2026-08-01", help="回测结束日期")
    parser.add_argument("--output", default=None, help="输出目录（默认 docs/data/strategy）")
    parser.add_argument("--selection-file", default=None,
                        help="使用已保存的选股结果（跳过重新选股）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    out_dir = args.output or OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    generated_at = datetime.now().isoformat(timespec="seconds")

    # ---- 1. 选股 ----
    if args.selection_file:
        logger.info("使用已保存选股结果: %s", args.selection_file)
        with open(args.selection_file, "r", encoding="utf-8") as f:
            selection = json.load(f)
    else:
        from src.strategies.run_strategies import run_strategies
        logger.info("执行策略选股 (scope=%s)...", args.scope)
        selection = run_strategies(args.scope)
        with open(os.path.join(out_dir, "selection.json"), "w", encoding="utf-8") as f:
            json.dump(selection, f, ensure_ascii=False, indent=2)
        logger.info("选股结果: %s", selection["summary"])

    # ---- 2. 狩猎场 ----
    logger.info("构建狩猎场...")
    stock_data, names = _load_stock_data_from_selection(os.path.join(out_dir, "selection.json"))
    hg = HuntingGround()
    hunting = hg.build(selection, stock_data, current_prices=None)
    with open(os.path.join(out_dir, "hunting_ground.json"), "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": generated_at,
            "hunting_ground": hunting,
        }, f, ensure_ascii=False, indent=2)
    logger.info("狩猎场: %s", {k: len(v) for k, v in hunting.items()})

    # ---- 3. 市场温度 ----
    logger.info("计算市场温度...")
    try:
        temperature = MarketTemperature().calculate()
        with open(os.path.join(out_dir, "market_temperature.json"), "w", encoding="utf-8") as f:
            json.dump({"generated_at": generated_at, **temperature}, f,
                      ensure_ascii=False, indent=2)
        logger.info("市场温度: %.1f (%s, 仓位系数 %.2f)",
                    temperature["temperature"], temperature["status"], temperature["position_ratio"])
    except MarketTemperatureError as exc:
        logger.warning("市场温度计算失败（不影响选股结果）: %s", exc)

    # ---- 4. 回测（可选） ----
    if args.backtest:
        logger.info("执行策略回测...")
        from src.strategies.backtest_engine import BacktestEngine
        engine = BacktestEngine(stock_data=stock_data, stock_names=names,
                                initial_capital=300000.0)
        backtest_results = {}
        for strategy_name in selection.get("summary", {}):
            result = engine.run(strategy_name, {
                "start_date": args.backtest_start or "2025-01-01",
                "end_date": args.backtest_end or "2026-08-01",
            })
            backtest_results[strategy_name] = result.get("performance", result)
        with open(os.path.join(out_dir, "backtest.json"), "w", encoding="utf-8") as f:
            json.dump({"generated_at": generated_at, "results": backtest_results},
                      f, ensure_ascii=False, indent=2)
        logger.info("回测结果: %s", {k: v.get("total_return_pct") for k, v in backtest_results.items()})

    logger.info("v2.5 策略研究完成，输出目录: %s", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())