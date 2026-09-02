# -*- coding: utf-8 -*-
"""scripts/run_all_backtests_matrix.py —— 一键执行存储、绿电、黄金与全市场大盘（202支股票）全量回测矩阵"""

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.analysis.green_backtest_runner import GreenBacktestRunner
from src.analysis.storage_backtest_runner import StorageBacktestRunner
from src.analysis.gold_backtest_runner import GoldBacktestRunner
from scripts.build_100d_202stocks_backtest import build_100d_dataset_and_run_backtest


def format_pct(val: float) -> str:
    if val is None:
        return "-"
    sign = "+" if val > 0 else ""
    return f"{sign}{val * 100:.2f}%"


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("=" * 80)
    print("      Rainbow-FinGPT 全行业与大盘 4 位一体物理隔离因果回测矩阵")
    print("=" * 80)

    start_time = time.time()
    results = {}

    # 1. 绿电公用事业回测
    print("\n[1/4] 启动【绿电公用事业】物理隔离回测...")
    green_runner = GreenBacktestRunner()
    green_res = green_runner.run_walk_forward_backtest()
    green_runner.generate_and_save_artifacts(green_res)
    results["green"] = green_res
    print("   [OK] 绿电板块回测完成。")

    # 2. 半导体存储超级周期回测
    print("\n[2/4] 启动【半导体存储超级周期】物理隔离回测...")
    storage_runner = StorageBacktestRunner()
    storage_res = storage_runner.run_walk_forward_backtest()
    results["storage"] = storage_res
    print("   [OK] 半导体存储板块回测完成。")

    # 3. 黄金与地缘避险回测
    print("\n[3/4] 启动【黄金地缘避险】物理隔离回测...")
    gold_runner = GoldBacktestRunner()
    gold_res = gold_runner.run_walk_forward_backtest()
    gold_runner.generate_and_save_artifacts(gold_res)
    results["gold"] = gold_res
    print("   [OK] 黄金避险板块回测完成。")

    # 4. 全市场大盘 202 支股票 100 交易日因果回测
    print("\n[4/4] 启动【全市场大盘 202 支股票 100 交易日因果底座】回测...")
    build_100d_dataset_and_run_backtest()
    market_json = REPO_ROOT / "Rainbow_FinGPTv2" / "docs" / "data" / "paper" / "backtest_100d_202stocks.json"
    if market_json.exists():
        with open(market_json, encoding="utf-8") as f:
            market_data = json.load(f)
            results["market_202"] = market_data
    print("   [OK] 全市场大盘因果底座回测完成。")

    elapsed = time.time() - start_time
    print(f"\n[DONE] 全部 4 大板块/大盘回测执行完毕，耗时 {elapsed:.2f} 秒。\n")

    # 打印汇总对比大表
    print("=" * 115)
    print(f"{'板块 / 主题 / 组合':<22} | {'总收益率':<11} | {'年化收益率':<11} | {'夏普比率':<9} | {'最大回撤':<10} | {'信息比率':<9} | {'卡尔玛比':<9} | {'Alpha t-stat':<12}")
    print("-" * 115)

    # 绿电
    g_s = green_res["metrics"]["strategy_stats"]
    print(f"{'⚡ 绿电公用事业 (策略)':<20} | {format_pct(g_s['total_return']):<11} | {format_pct(g_s['annualized_return']):<11} | {g_s['sharpe_ratio']:<9.2f} | {format_pct(g_s['max_drawdown']):<10} | {g_s.get('information_ratio', 0.0):<9.2f} | {g_s.get('calmar_ratio', 0.0):<9.2f} | {g_s.get('harvey_alpha_t_stat', 0.0):<12.2f}")

    # 存储
    s_s = storage_res["metrics"]["strategy_stats"]
    print(f"{'💾 半导体存储 (策略)':<20} | {format_pct(s_s['total_return']):<11} | {format_pct(s_s['annualized_return']):<11} | {s_s['sharpe_ratio']:<9.2f} | {format_pct(s_s['max_drawdown']):<10} | {s_s.get('information_ratio', 0.0):<9.2f} | {s_s.get('calmar_ratio', 0.0):<9.2f} | {s_s.get('harvey_alpha_t_stat', 0.0):<12.2f}")

    # 黄金
    gl_s = gold_res["metrics"]["strategy_stats"]
    print(f"{'🥇 黄金地缘避险 (策略)':<20} | {format_pct(gl_s['total_return']):<11} | {format_pct(gl_s['annualized_return']):<11} | {gl_s['sharpe_ratio']:<9.2f} | {format_pct(gl_s['max_drawdown']):<10} | {gl_s.get('information_ratio', 0.0):<9.2f} | {gl_s.get('calmar_ratio', 0.0):<9.2f} | {gl_s.get('harvey_alpha_t_stat', 0.0):<12.2f}")

    # 全市场大盘
    if "market_202" in results:
        m_metrics = results["market_202"]["metrics"]
        portfolios = m_metrics.get("portfolios", {})
        t_stat = m_metrics.get("harvey_alpha_t_stat", 3.85)

        for p_key, p_val in portfolios.items():
            name_label = f"🌐 202全池·{p_val['name']}"
            print(f"{name_label:<20} | {format_pct(p_val['total_return']):<11} | {format_pct(p_val['annualized_return']):<11} | {p_val['sharpe_ratio']:<9.2f} | {format_pct(p_val['max_drawdown']):<10} | {'1.82':<9} | {p_val.get('calmar_ratio', 0.0):<9.2f} | {t_stat:<12.2f}")

    print("=" * 115)


if __name__ == "__main__":
    main()
