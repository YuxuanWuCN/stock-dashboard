# -*- coding: utf-8 -*-
"""tests/test_storage_backtest_runner.py —— 存储市场物理隔离回测单元测试与 Smoke Test"""

import pytest
from pathlib import Path
from src.analysis.storage_backtest_runner import StorageBacktestRunner


def test_storage_backtest_runner_execution():
    """测试存储市场日频因果逐步推进回测执行与三级基准度量输出。"""
    raw_dir = Path("data/raw/backtest_storage_2025q2_2026q7")
    assert raw_dir.exists(), "必须先生成物理隔离原始数据"

    runner = StorageBacktestRunner(raw_data_dir=raw_dir)
    res = runner.run_walk_forward_backtest()

    assert "metrics" in res
    assert "snapshots" in res
    assert "nav_series" in res

    metrics = res["metrics"]
    strat_stats = metrics["strategy_stats"]
    storage_ew_stats = metrics["benchmark_storage_ew_stats"]

    # 1. 验证策略夏普比率与超额 Alpha 显著性
    assert strat_stats["sharpe_ratio"] > 1.0
    assert strat_stats["max_drawdown"] < 0.20  # Trend Gate 成功将最大回撤限制在 20% 以内
    
    # 2. 验证相比存储等权买入持有策略，策略组最大回撤大幅减少
    assert strat_stats["max_drawdown"] < storage_ew_stats["max_drawdown"]

    # 3. 验证快照数量
    assert len(res["snapshots"]) > 300


def test_storage_universe_expansion_and_chain_coverage():
    """验证存储全产业链标的池扩充至 12~15 只，且覆盖设计、模组、主控、封测关键环节。"""
    runner = StorageBacktestRunner()
    tickers = runner.STORAGE_TICKERS

    assert len(tickers) >= 12, "标的池规模必须达到 12 只以上存储产业链标的"
    assert len(tickers) <= 15, "标的池规模控制在 12~15 只范围内"

    # 验证关键环节代表标的存在
    key_stocks = ["603986", "688766", "688110", "300223", "688123", "000021"]
    for s in key_stocks:
        assert s in tickers, f"产业链标的 {s} 必须包含在候选池中"

    # 验证环节元数据
    segments = {runner.TICKER_METADATA[t]["segment"] for t in tickers if t in runner.TICKER_METADATA}
    assert any("模组" in seg for seg in segments)
    assert any("设计" in seg for seg in segments)
    assert any("主控" in seg for seg in segments)
    assert any("封测" in seg for seg in segments)


def test_storage_multi_asset_dynamic_selection_and_risk_constraints():
    """验证多选多组合动态配置：支持同时持有 3~5 只活跃标的，组合总权重与现金比例满足风控约束（无爆仓/负权重）。"""
    raw_dir = Path("data/raw/backtest_storage_2025q2_2026q7")
    runner = StorageBacktestRunner(raw_data_dir=raw_dir)
    res = runner.run_walk_forward_backtest()

    snapshots = res["snapshots"]
    active_counts = []

    for s in snapshots:
        holdings = s.active_holdings
        # 1. 验证无负权重
        for t, w in holdings.items():
            assert w >= -1e-6, f"{s.date} 标的 {t} 权重不能为负: {w}"

        # 2. 验证总仓位上限与现金比例风控约束
        total_w = sum(holdings.values())
        assert total_w <= 0.95 + 1e-4, f"{s.date} 股票总仓位超出风控上限: {total_w}"
        assert s.cash_ratio >= 0.05 - 1e-4, f"{s.date} 现金比例低于风控底线: {s.cash_ratio}"
        assert abs((total_w + s.cash_ratio) - 1.0) < 1e-4, f"{s.date} 仓位与现金和必须等于 1.0"

        active_n = sum(1 for w in holdings.values() if w > 0.02)
        active_counts.append(active_n)

    # 3. 验证在景气/常态期存在同时持有 3~5 只活跃标的的多选多组合配置
    has_3_to_5 = any(3 <= c <= 5 for c in active_counts)
    assert has_3_to_5, "组合必须支持在景气/常态期同时持有 3~5 只活跃标的"
    days_with_3_to_5 = sum(1 for c in active_counts if 3 <= c <= 5)
    assert days_with_3_to_5 >= 100, f"持有 3~5 只活跃标的的天数必须显著大于 100 天 (实际: {days_with_3_to_5})"


def test_storage_backtest_artifacts_export_and_sync():
    """验证回测成果落盘同步到 docs/data/quantitative/ 与 docs/data/paper/。"""
    raw_dir = Path("data/raw/backtest_storage_2025q2_2026q7")
    runner = StorageBacktestRunner(raw_data_dir=raw_dir)
    res = runner.run_walk_forward_backtest()
    saved = runner.save_artifacts(res)

    assert saved["quantitative_json"].exists()
    assert saved["paper_json"].exists()
    assert saved["table_md"].exists()

    import json
    with open(saved["quantitative_json"], "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "universe" in data
    assert data["universe_size"] >= 12
    assert "metrics" in data
    assert "strategy_stats" in data["metrics"]
    assert "nav_series" in data
    assert "snapshots" in data


def test_daily_routine_storage_backtest_integration():
    """验证 daily_routine.py 流水线集成存储回测运行节点并支持数据同步。"""
    daily_file = Path("tools/daily_routine.py")
    assert daily_file.exists(), "tools/daily_routine.py 必须存在"

    content = daily_file.read_text(encoding="utf-8")
    assert "src.analysis.storage_backtest_runner" in content, "流水线必须包含存储回测执行节点"
    assert "backtest_storage_*.json" in content, "sync_dashboard_data 必须包含存储回测成果文件同步"
    assert "--skip-storage" in content, "必须支持 --skip-storage 参数"

    # 执行同步函数验证落盘至 docs/data/quantitative/
    from tools.daily_routine import sync_dashboard_data
    sync_dashboard_data()

    quant_file = Path("docs/data/quantitative/backtest_storage_2025q2_2026q7.json")
    assert quant_file.exists(), "docs/data/quantitative/ 下必须存在同步后的存储回测成果"


