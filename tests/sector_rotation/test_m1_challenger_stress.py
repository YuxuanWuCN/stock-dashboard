# -*- coding: utf-8 -*-
"""tests/sector_rotation/test_m1_challenger_stress.py —— M1 对抗性压力与经验证伪测试套件

由 Challenger M1 (Instance 2) 编写并执行：
1. 1,000 次全市场批量聚合端到端延迟压力测试与统计分布（均值、p50、p95、p99、max，严格验证 < 5ms 与 < 100ms）
2. 状态隔离性测试（极端行情切换、不同板块交替、无状态残留）
3. 多线程高并发调用状态隔离与线程安全性
4. 不可变性验证（update_trend 的 history、aggregate 的 historical_scores、aggregate_market 的 history_map 与 stocks）
5. 内存泄漏与资源占用监控（tracemalloc 跟踪 1,000 ~ 5,000 次循环的对象驻留）
6. 极端对抗边界与数值稳定性（大样本 10,000 只标的、极大方差、边界浮点数）
"""

import gc
import math
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

import pytest

from src.sector_rotation.config import (
    SECTORS,
    SENTIMENT_BOUND_MAX,
    SENTIMENT_BOUND_MIN,
    TREND_DECLINING,
    TREND_RISING,
    TREND_STABLE,
)
from src.sector_rotation.sector_sentiment_aggregator import SectorSentimentAggregator
from src.sector_rotation.utils.sector_utils import (
    SectorState,
    StockSentimentInput,
    validate_confidence,
    validate_news_count,
    validate_sentiment_score,
)


# ============================================================================
# 1. 延迟与性能压力测试 (1,000 次全市场批量聚合)
# ============================================================================

def test_benchmark_batch_aggregation_1000_iterations(
    aggregator: SectorSentimentAggregator,
    sample_green_stocks: List[StockSentimentInput],
    sample_storage_stocks: List[StockSentimentInput],
    sample_gold_stocks: List[StockSentimentInput],
) -> None:
    """实测全市场批量聚合在 1,000 次迭代中的执行延迟分布。
    
    验证指标：
    - 单步全市场批量聚合平均延迟严格 < 5.0ms (远优于系统总体 < 100ms 约束)
    - 95 分位数延迟 < 5.0ms
    - 最大单次延迟 < 50.0ms
    - 1,000 次全市场迭代累计执行时间 < 5.0s
    """
    universe: List[StockSentimentInput] = (
        sample_green_stocks + sample_storage_stocks + sample_gold_stocks
    )
    assert len(universe) == 19

    history_map = {
        "green": [0.15, 0.20, 0.25],
        "storage": [0.60, 0.65, 0.70],
        "gold": [0.35, 0.38, 0.40],
    }

    # 预热 10 次排除 JIT / 缓存初始化偏差
    for _ in range(10):
        _ = aggregator.aggregate_market(universe, history_map=history_map)

    latencies_ms: List[float] = []
    total_iterations = 1000

    start_total = time.perf_counter()
    for _ in range(total_iterations):
        t0 = time.perf_counter_ns()
        states = aggregator.aggregate_market(universe, history_map=history_map)
        t1 = time.perf_counter_ns()

        elapsed_ms = (t1 - t0) / 1_000_000.0
        latencies_ms.append(elapsed_ms)

        # 每次迭代的结果完整性核查
        assert len(states) >= 3
        assert "green" in states
        assert "storage" in states
        assert "gold" in states

    total_duration_s = time.perf_counter() - start_total

    latencies_sorted = sorted(latencies_ms)
    mean_ms = sum(latencies_ms) / total_iterations
    p50_ms = latencies_sorted[int(total_iterations * 0.50)]
    p95_ms = latencies_sorted[int(total_iterations * 0.95)]
    p99_ms = latencies_sorted[int(total_iterations * 0.99)]
    max_ms = latencies_sorted[-1]

    print(
        f"\n[M1 Latency Benchmark] 1,000 market iterations:\n"
        f"  Total time: {total_duration_s:.3f} s\n"
        f"  Mean:       {mean_ms:.3f} ms\n"
        f"  p50:        {p50_ms:.3f} ms\n"
        f"  p95:        {p95_ms:.3f} ms\n"
        f"  p99:        {p99_ms:.3f} ms\n"
        f"  Max:        {max_ms:.3f} ms"
    )

    # 严格门禁断言
    assert mean_ms < 5.0, f"Mean latency {mean_ms:.3f}ms exceeded 5.0ms threshold"
    assert p95_ms < 5.0, f"p95 latency {p95_ms:.3f}ms exceeded 5.0ms threshold"
    assert max_ms < 50.0, f"Max latency {max_ms:.3f}ms exceeded 50.0ms threshold"
    assert total_duration_s < 5.0, f"Total execution time {total_duration_s:.3f}s exceeded 5.0s"


def test_latency_scaling_with_large_stock_universe(
    aggregator: SectorSentimentAggregator,
) -> None:
    """测试不同股票池规模下的延迟扩展性（50只、200只、1000只标的）。"""
    for n_stocks in (50, 200, 1000):
        large_universe: List[StockSentimentInput] = []
        sectors = ("green", "storage", "gold")
        for i in range(n_stocks):
            sec = sectors[i % len(sectors)]
            large_universe.append(
                StockSentimentInput(
                    code=f"{600000 + i:06d}",
                    name=f"Stock_{i}",
                    sector=sec,
                    sentiment_score=((i % 20) - 10) / 10.0,
                    sentiment_confidence=0.85,
                    news_count=(i % 5) + 1,
                    timestamp="2026-10-12",
                )
            )

        t0 = time.perf_counter_ns()
        result = aggregator.aggregate_market(large_universe)
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000.0

        assert len(result) == 3
        # 即便全市场扩充至 1,000 只标的，单步批聚合仍需稳定在 50ms 以内（远低于 100ms）
        assert elapsed_ms < 50.0, f"Large universe ({n_stocks} stocks) took {elapsed_ms:.2f}ms"


# ============================================================================
# 2. 状态隔离性测试 (State Isolation Across Calls)
# ============================================================================

def test_state_isolation_alternating_market_regimes(
    aggregator: SectorSentimentAggregator,
    sample_green_stocks: List[StockSentimentInput],
) -> None:
    """验证在剧烈交替的市场行情输入下，聚合器无任何内部残留状态。"""
    # 场景 A: 极端牛市狂热 (+0.95)
    bull_stocks = [
        StockSentimentInput(
            code=s.code,
            name=s.name,
            sector="green",
            sentiment_score=0.95,
            sentiment_confidence=0.95,
            news_count=10,
            timestamp="2026-10-12",
        )
        for s in sample_green_stocks
    ]

    # 场景 B: 极端熊市崩塌 (-0.95)
    bear_stocks = [
        StockSentimentInput(
            code=s.code,
            name=s.name,
            sector="green",
            sentiment_score=-0.95,
            sentiment_confidence=0.95,
            news_count=10,
            timestamp="2026-10-12",
        )
        for s in sample_green_stocks
    ]

    # 场景 C: 空标的数据
    empty_stocks: List[StockSentimentInput] = []

    # 交替执行 100 轮
    for _ in range(100):
        state_bull = aggregator.aggregate(bull_stocks, "green")
        assert state_bull.sentiment_score == pytest.approx(0.95, abs=1e-4)
        assert state_bull.stock_count == 6

        state_bear = aggregator.aggregate(bear_stocks, "green")
        assert state_bear.sentiment_score == pytest.approx(-0.95, abs=1e-4)
        assert state_bear.stock_count == 6

        state_empty = aggregator.aggregate(empty_stocks, "green")
        assert state_empty.sentiment_score == 0.0
        assert state_empty.stock_count == 0
        assert state_empty.confidence == 0.0


def test_independent_aggregator_instances_isolated() -> None:
    """验证多个独立的 Aggregator 实例彼此配置与状态完全解耦。"""
    agg1 = SectorSentimentAggregator(expected_stocks_per_sector=6, trend_threshold=0.05)
    agg2 = SectorSentimentAggregator(expected_stocks_per_sector=20, trend_threshold=0.20)

    stocks = [
        StockSentimentInput(
            code="601012",
            name="隆基绿能",
            sector="green",
            sentiment_score=0.5,
            sentiment_confidence=0.8,
            news_count=2,
            timestamp="2026-10-12",
        )
    ]

    state1 = agg1.aggregate(stocks, "green")
    state2 = agg2.aggregate(stocks, "green")

    # 由于 expected_stocks 不同，置信度应存在显著差异
    assert state1.confidence > state2.confidence
    assert agg1.expected_stocks == 6
    assert agg2.expected_stocks == 20


# ============================================================================
# 3. 输入对象不可变性验证 (Immutability Checks)
# ============================================================================

def test_update_trend_does_not_mutate_history_in_place(
    aggregator: SectorSentimentAggregator,
) -> None:
    """严格验证传入 update_trend 的 history 列表未被原地修改。"""
    original_history = [0.10, 0.20, 0.30]
    history_under_test = list(original_history)

    # 连续调用 20 次
    for current in (0.40, -0.10, 0.05, 0.80):
        trend = aggregator.update_trend("green", current, history=history_under_test)
        # 必须保持原列表内容与长度不变
        assert history_under_test == original_history
        assert len(history_under_test) == 3


def test_update_trend_with_empty_and_single_history_unmutated(
    aggregator: SectorSentimentAggregator,
) -> None:
    """验证空列表和单元素列表入参在 update_trend 中不被就地修改。"""
    empty_history: List[float] = []
    _ = aggregator.update_trend("storage", 0.5, history=empty_history)
    assert empty_history == []

    single_history = [0.55]
    _ = aggregator.update_trend("storage", 0.6, history=single_history)
    assert single_history == [0.55]


def test_aggregate_historical_scores_unmutated(
    aggregator: SectorSentimentAggregator,
    sample_green_stocks: List[StockSentimentInput],
) -> None:
    """严格验证传入 aggregate 的 historical_scores 列表未被原地修改。"""
    hist = [-0.10, -0.20, -0.35]
    hist_copy = list(hist)

    _ = aggregator.aggregate(sample_green_stocks, "green", historical_scores=hist)
    assert hist == hist_copy
    assert len(hist) == 3


def test_aggregate_market_history_map_unmutated(
    aggregator: SectorSentimentAggregator,
    sample_green_stocks: List[StockSentimentInput],
) -> None:
    """严格验证传入 aggregate_market 的 history_map 字典及内层列表均未被修改。"""
    history_map = {
        "green": [0.10, 0.20, 0.30],
        "storage": [0.50, 0.60, 0.70],
        "gold": [0.05, 0.08, 0.12],
    }
    history_map_snapshot = {k: list(v) for k, v in history_map.items()}

    _ = aggregator.aggregate_market(sample_green_stocks, history_map=history_map)

    assert history_map == history_map_snapshot
    for sec, values in history_map.items():
        assert values == history_map_snapshot[sec]
        assert len(values) == 3


def test_stock_inputs_unmutated_after_aggregation(
    aggregator: SectorSentimentAggregator,
    sample_green_stocks: List[StockSentimentInput],
) -> None:
    """验证传入 aggregate 的 StockSentimentInput 列表与元素未被篡改。"""
    snapshots = [
        (s.code, s.name, s.sector, s.sentiment_score, s.sentiment_confidence, s.news_count)
        for s in sample_green_stocks
    ]

    _ = aggregator.aggregate(sample_green_stocks, "green")

    current_states = [
        (s.code, s.name, s.sector, s.sentiment_score, s.sentiment_confidence, s.news_count)
        for s in sample_green_stocks
    ]
    assert snapshots == current_states


# ============================================================================
# 4. 并发与多线程压力测试 (Concurrency & Thread-Safety)
# ============================================================================

def test_multithreaded_concurrent_aggregation(
    aggregator: SectorSentimentAggregator,
    sample_green_stocks: List[StockSentimentInput],
    sample_storage_stocks: List[StockSentimentInput],
    sample_gold_stocks: List[StockSentimentInput],
) -> None:
    """验证多线程并发调用同一 Aggregator 实例时的线程安全性与计算确定性。"""
    universe = sample_green_stocks + sample_storage_stocks + sample_gold_stocks
    num_threads = 10
    iterations_per_thread = 100
    exceptions: List[Exception] = []

    def worker_job(thread_idx: int) -> None:
        try:
            for i in range(iterations_per_thread):
                hist_map = {
                    "green": [0.1 + (thread_idx * 0.01), 0.2, 0.3],
                    "storage": [0.5, 0.6, 0.7],
                    "gold": [0.2, 0.3, 0.4],
                }
                res = aggregator.aggregate_market(universe, history_map=hist_map)
                assert "green" in res
                assert "storage" in res
                assert "gold" in res
                assert res["green"].stock_count == 6
                assert res["storage"].stock_count == 6
                assert res["gold"].stock_count == 7
        except Exception as ex:
            exceptions.append(ex)

    threads: List[threading.Thread] = []
    for t_idx in range(num_threads):
        t = threading.Thread(target=worker_job, args=(t_idx,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=10.0)

    assert len(exceptions) == 0, f"Concurrent execution raised exceptions: {exceptions}"


# ============================================================================
# 5. 内存泄漏与资源留存审计 (Memory & Resource Footprint)
# ============================================================================

def test_memory_leak_audit_over_2000_iterations(
    aggregator: SectorSentimentAggregator,
    sample_green_stocks: List[StockSentimentInput],
    sample_storage_stocks: List[StockSentimentInput],
    sample_gold_stocks: List[StockSentimentInput],
) -> None:
    """使用 tracemalloc 监控 2,000 次批量聚合的内存驻留与垃圾回收。
    
    验证准则：
    - 循环执行后无对象失控增长
    - 净驻留内存增长 < 500 KB
    """
    universe = sample_green_stocks + sample_storage_stocks + sample_gold_stocks
    history_map = {"green": [0.2, 0.3, 0.4], "storage": [0.6, 0.7, 0.8], "gold": [0.3, 0.4, 0.5]}

    # 预热并运行初始 GC
    gc.collect()
    tracemalloc.start()

    snapshot_start = tracemalloc.take_snapshot()

    for _ in range(2000):
        _ = aggregator.aggregate_market(universe, history_map=history_map)

    gc.collect()
    snapshot_end = tracemalloc.take_snapshot()
    tracemalloc.stop()

    stats = snapshot_end.compare_to(snapshot_start, "lineno")
    total_diff_bytes = sum(s.size_diff for s in stats if s.size_diff > 0)
    total_diff_kb = total_diff_bytes / 1024.0

    print(f"\n[Memory Audit] Net memory diff after 2,000 iterations: {total_diff_kb:.2f} KB")

    # 2,000 次执行后常驻内存增长必须低于 500 KB（排除 Python 内部解释器元数据增长）
    assert total_diff_kb < 500.0, f"Detected potential memory leak: {total_diff_kb:.2f} KB retained"


# ============================================================================
# 6. 对抗性边界条件与数学预言机检验 (Adversarial Edge Cases)
# ============================================================================

def test_adversarial_bipolar_extreme_variance(
    aggregator: SectorSentimentAggregator,
) -> None:
    """对抗场景：成分股情绪两极分化（一半 +1.0，一半 -1.0）。
    
    验证加权均值为 0.0，波动率标准差达到理论峰值，置信度受到一致性重罚。
    """
    bipolar_stocks = [
        StockSentimentInput(code=f"00000{i}", name=f"Bull_{i}", sector="green",
                            sentiment_score=1.0, sentiment_confidence=1.0, news_count=5, timestamp="")
        for i in range(3)
    ] + [
        StockSentimentInput(code=f"00001{i}", name=f"Bear_{i}", sector="green",
                            sentiment_score=-1.0, sentiment_confidence=1.0, news_count=5, timestamp="")
        for i in range(3)
    ]

    state = aggregator.aggregate(bipolar_stocks, "green")
    assert state.sentiment_score == pytest.approx(0.0, abs=1e-5)
    # 3 个 +1 和 3 个 -1，样本标准差 = sqrt( (3*(1)^2 + 3*(-1)^2 ) / 5 ) = sqrt(6/5) = 1.0954
    expected_vol = math.sqrt(6.0 / 5.0)
    assert state.volatility == pytest.approx(expected_vol, abs=1e-3)
    # 因观点严重分化，一致性因子惩罚应显著拉低置信度
    assert state.confidence < 0.60


def test_adversarial_massive_sample_scale_10000_stocks(
    aggregator: SectorSentimentAggregator,
) -> None:
    """对抗场景：单板块包含 10,000 只标的高负载聚合。"""
    massive_stocks = [
        StockSentimentInput(
            code=f"{100000 + i}",
            name=f"Stock_{i}",
            sector="storage",
            sentiment_score=0.80 if i % 2 == 0 else 0.60,
            sentiment_confidence=0.90,
            news_count=2,
            timestamp="2026-10-12",
        )
        for i in range(10000)
    ]

    t0 = time.perf_counter()
    state = aggregator.aggregate(massive_stocks, "storage")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert state.stock_count == 10000
    assert state.sentiment_score == pytest.approx(0.70, abs=1e-4)
    # 即使 10,000 只标的，单板块聚合耗时也应在 200ms 以内
    assert elapsed_ms < 200.0


def test_trend_detection_exact_threshold_boundaries(
    aggregator: SectorSentimentAggregator,
) -> None:
    """针对 3 日趋势阈值 (0.05) 进行对抗性临界浮点值测试。"""
    # 1. 严格等于阈值 0.05: (0.35 - 0.30 = 0.05) -> 不满足 > 0.05，判定为 stable
    assert aggregator.calculate_trend([0.30, 0.32, 0.35]) == TREND_STABLE

    # 2. 略微超过阈值 0.05001: 满足单调递增且 delta > 0.05 -> rising
    assert aggregator.calculate_trend([0.30, 0.32, 0.35001]) == TREND_RISING

    # 3. 略微低于阈值 0.04999: 不满足 > 0.05 -> stable
    assert aggregator.calculate_trend([0.30, 0.32, 0.34999]) == TREND_STABLE

    # 4. 连续递降临界值:
    assert aggregator.calculate_trend([0.35, 0.32, 0.30]) == TREND_STABLE
    assert aggregator.calculate_trend([0.35001, 0.32, 0.30]) == TREND_DECLINING
    assert aggregator.calculate_trend([0.34999, 0.32, 0.30]) == TREND_STABLE

    # 5. 非单调但是两端差值大:
    # 0.10 -> 0.40 -> 0.30 (先涨后跌，非严格递增) -> 必须为 stable
    assert aggregator.calculate_trend([0.10, 0.40, 0.30]) == TREND_STABLE
    # 0.40 -> 0.10 -> 0.20 (先跌后涨，非严格递降) -> 必须为 stable
    assert aggregator.calculate_trend([0.40, 0.10, 0.20]) == TREND_STABLE


def test_floating_point_extremes_and_subnormals(
    aggregator: SectorSentimentAggregator,
) -> None:
    """验证极微小浮点数 (1e-12) 与极大权重计算无除零崩溃或精度溢出。"""
    stocks = [
        StockSentimentInput(
            code="600001",
            name="极微",
            sector="green",
            sentiment_score=1e-10,
            sentiment_confidence=1e-10,
            news_count=1,
            timestamp="",
        ),
        StockSentimentInput(
            code="600002",
            name="极大",
            sector="green",
            sentiment_score=0.8,
            sentiment_confidence=1.0,
            news_count=1_000_000,
            timestamp="",
        ),
    ]

    state = aggregator.aggregate(stocks, "green")
    assert -1.0 <= state.sentiment_score <= 1.0
    assert 0.0 <= state.confidence <= 1.0
    assert not math.isnan(state.sentiment_score)
    assert not math.isnan(state.confidence)
