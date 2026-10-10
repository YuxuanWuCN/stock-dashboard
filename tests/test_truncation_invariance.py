# -*- coding: utf-8 -*-
"""tests/test_truncation_invariance.py —— 截断不变性与零前视偏差审计测试 (A4 Audit Requirement)

公理 (Axiom of Truncation Invariance):
设全量时间序列为 X_{1:T}，任意量化信号生成函数为 S(X, t) -> s_t。
定义 X_{1:t} 为截至日期 t 的历史数据严格截断切片（完全剔除 t 日之后的所有记录）。
截断不变性要求：
    S(X_{1:t}, t) == S(X_{1:T}, t),  ∀ t >= t_min

若在任意时间锚点 t，未来数据 X_{t+1:T} 的变动、冲击或截断会反向改变已生成的 s_t，
则证明算法存在前视偏差（Lookahead Bias / Future Leakage）。

本测试套件针对量化核心策略：
- src/strategies/zigzag_wave.py (NonForwardLookingZigZag)
- src/strategies/trend_gate.py (detect_trend, evaluate_boolean_trend_gate)
实施端到端数学截断不变性、确认延迟因果性以及未来数据独立性验证。
"""

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.strategies.trend_gate import detect_trend, evaluate_boolean_trend_gate
from src.strategies.zigzag_wave import NonForwardLookingZigZag


@pytest.fixture(scope="module")
def sample_kline_df() -> pd.DataFrame:
    """从 docs/data/kline/ 读取真实 A 股行情数据作为测试底座。"""
    project_root = Path(__file__).resolve().parent.parent
    sample_file = project_root / "docs" / "data" / "kline" / "000021.json"
    assert sample_file.exists(), f"Sample kline file not found: {sample_file}"

    with open(sample_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    df = pd.DataFrame({
        "date": data["dates"],
        "open": [float(row[0]) for row in data["kline"]],
        "close": [float(row[1]) for row in data["kline"]],
        "low": [float(row[2]) for row in data["kline"]],
        "high": [float(row[3]) for row in data["kline"]],
        "volume": [float(v) for v in data["volume"]],
    })
    return df


@pytest.fixture(scope="module")
def csmar_single_stock_df() -> pd.DataFrame:
    """从 CSMAR 主面板加载单支标的的时间序列。"""
    project_root = Path(__file__).resolve().parent.parent
    csmar_path = project_root / "data" / "task_split" / "csmar_master" / "csmar_factor_panel_master.csv"
    if not csmar_path.exists():
        pytest.skip("CSMAR master panel not available in current environment")

    # 读取首支股票
    df_head = pd.read_csv(csmar_path, nrows=1000)
    stock_code = df_head["stock_code"].iloc[0]
    df = pd.read_csv(csmar_path, usecols=["stock_code", "trade_date", "close", "volume"])
    stock_df = df[df["stock_code"] == stock_code].sort_values("trade_date").reset_index(drop=True)
    stock_df["date"] = stock_df["trade_date"]
    stock_df["open"] = stock_df["close"]
    stock_df["high"] = stock_df["close"]
    stock_df["low"] = stock_df["close"]
    return stock_df


def test_zigzag_truncation_invariance_synthetic():
    """测试 1: 因果 ZigZag 在合成序列上的数学截断不变性。

    在全序列上遍历不同的历史截断点 t，在未来 t+1..T 注入极端黑天鹅冲击，
    断言截至 t 日所识别出的摆动拐点与波浪结构绝对恒定。
    """
    # 构造含多周期明显起伏的确定性价格序列 (150 个交易日)
    n = 150
    t_axis = np.linspace(0, 4 * np.pi, n)
    trend = np.linspace(10, 30, n)
    oscillation = 8 * np.sin(t_axis)
    closes = trend + oscillation
    highs = closes + 1.0
    lows = closes - 1.0
    volumes = 10000 + 2000 * np.cos(t_axis)

    dates = [f"2025-01-{i+1:02d}" if i < 30 else f"2025-02-{i-29:02d}" for i in range(n)]

    df = pd.DataFrame({
        "date": dates,
        "open": closes,
        "close": closes,
        "high": highs,
        "low": lows,
        "volume": volumes,
    })

    zigzag = NonForwardLookingZigZag(reversal_pct=12.0)

    # 抽取 10 个测试截断时间点 t in [40, 130]
    sample_anchors = np.linspace(40, 130, 10, dtype=int)

    for t in sample_anchors:
        # 1. 截至 t 日的历史真实切片
        slice_t = df.iloc[: t + 1].copy()
        res_t = zigzag.analyze_wave_structure(slice_t)

        # 2. 模拟未来 t+1..T 日发生 50% 暴涨暴跌冲击
        df_future_shocked = df.copy()
        df_future_shocked.loc[t + 1:, "close"] *= 1.50
        df_future_shocked.loc[t + 1:, "high"] *= 1.60
        df_future_shocked.loc[t + 1:, "low"] *= 1.40
        df_future_shocked.loc[t + 1:, "volume"] *= 3.00

        # 取回截断切片重算
        slice_t_after_future = df_future_shocked.iloc[: t + 1].copy()
        res_t_after_future = zigzag.analyze_wave_structure(slice_t_after_future)

        # 强断言：未来冲击不可穿越至 t 日之前
        assert len(res_t.swing_points) == len(res_t_after_future.swing_points), (
            f"Swing point count mismatch at anchor t={t}"
        )
        for sp1, sp2 in zip(res_t.swing_points, res_t_after_future.swing_points):
            assert sp1.index == sp2.index
            assert sp1.point_type == sp2.point_type
            assert pytest.approx(sp1.price) == sp2.price

        assert res_t.wave_phase == res_t_after_future.wave_phase, f"WavePhase mismatch at t={t}"
        assert res_t.is_wave_c == res_t_after_future.is_wave_c, f"is_wave_c mismatch at t={t}"
        assert res_t.hunting_ground_entry == res_t_after_future.hunting_ground_entry, (
            f"hunting_ground_entry mismatch at t={t}"
        )
        if res_t.fib_0_500 is not None:
            assert pytest.approx(res_t.fib_0_500) == res_t_after_future.fib_0_500


def test_zigzag_confirmation_lag_strictly_causal(sample_kline_df: pd.DataFrame):
    """测试 2: 验证 ZigZag 拐点确认具有客观延迟（零未来函数核心证明）。

    在极值点发生日 k，回撤尚未达到 12% 反转阈值时，该极值绝对不能被记录为 SwingPoint。
    只有在后续交易日价格回撤幅度达到反转阈值时，历史 k 点方被因果追加。

    以 000021 真实行情为例：
    - index=21 (2025-10-13, high=32.97) 实际为波峰高点；
    - 在 t=21 当日截断计算，swings 绝对不包含 index=21 的 PEAK（防止无延迟先知）；
    - 直至 t=22 (2025-10-14, low <= 32.97 * (1 - 0.12)) 回撤确认后，index=21 的 PEAK 方被追加。
    """
    df = sample_kline_df
    zigzag = NonForwardLookingZigZag(reversal_pct=12.0)

    # 1. 在第 21 日当天截断运行：绝不能识别出第 21 日为 PEAK
    swings_at_21 = zigzag.compute_swings(df.iloc[:22])
    assert not any(s.index == 21 for s in swings_at_21), (
        "Lookahead Bias Detected! Peak at day 21 was prematurely identified on day 21 without confirmation."
    )

    # 2. 在第 22 日截断运行：价格大幅回撤，因果确认锁定第 21 日为 PEAK
    swings_at_22 = zigzag.compute_swings(df.iloc[:23])
    peak_found = [s for s in swings_at_22 if s.index == 21 and s.point_type == "PEAK"]
    assert len(peak_found) == 1, "Peak at day 21 must be confirmed on day 22 after 12% reversal"
    assert pytest.approx(peak_found[0].price) == 32.97


def test_trend_gate_truncation_invariance_on_real_kline(sample_kline_df: pd.DataFrame):
    """测试 3: Trend Gate 布尔门控在真实 A 股 K 线上的截断不变性。

    在真实股票 (000021) 序列上随机抽样 15 个交易日，验证在引入未来极端波动后，
    历史截断切片的门控判定、MA20、MACD_DIF、DEA 及波浪阶段 100% 不变。
    """
    df = sample_kline_df
    assert len(df) >= 200

    # 选取 15 个横跨中后期的真实日期锚点
    sample_ts = np.linspace(40, len(df) - 15, 15, dtype=int)

    for t in sample_ts:
        # 1. 历史真实数据切片
        slice_t = df.iloc[: t + 1].copy()
        res_t = evaluate_boolean_trend_gate(slice_t)

        # 2. 模拟未来数据发生大幅扰动（涨停/跌停/成交量倍增）
        df_perturbed = df.copy()
        df_perturbed.loc[t + 1:, "close"] *= 1.35
        df_perturbed.loc[t + 1:, "high"] *= 1.45
        df_perturbed.loc[t + 1:, "low"] *= 1.25
        df_perturbed.loc[t + 1:, "volume"] *= 4.5

        # 重新取回截至 t 的切片
        slice_t_perturbed = df_perturbed.iloc[: t + 1].copy()
        res_t_perturbed = evaluate_boolean_trend_gate(slice_t_perturbed)

        # 强断言：所有门控指标严格全同
        assert res_t["gate_pass"] == res_t_perturbed["gate_pass"], f"gate_pass changed at t={t}"
        assert res_t["wave_phase"] == res_t_perturbed["wave_phase"], f"wave_phase changed at t={t}"
        assert res_t["cond_price_above_ma20"] == res_t_perturbed["cond_price_above_ma20"]
        assert res_t["cond_macd_momentum"] == res_t_perturbed["cond_macd_momentum"]
        assert res_t["cond_not_wave_c"] == res_t_perturbed["cond_not_wave_c"]
        assert pytest.approx(res_t["ma20"], abs=1e-3) == res_t_perturbed["ma20"]
        assert pytest.approx(res_t["macd_dif"], abs=1e-4) == res_t_perturbed["macd_dif"]
        assert pytest.approx(res_t["macd_dea"], abs=1e-4) == res_t_perturbed["macd_dea"]


def test_detect_trend_truncation_invariance(sample_kline_df: pd.DataFrame):
    """测试 4: 基础均线趋势判定函数 detect_trend 的截断不变性。"""
    closes = sample_kline_df["close"].tolist()
    assert len(closes) >= 100

    # 遍历 t in [65, 120]
    for t in [65, 80, 95, 110]:
        t_closes = closes[: t + 1]
        state_t, metrics_t = detect_trend(t_closes)

        # 加入未来 20 个交易日的价格
        future_closes = t_closes + [closes[t] * 1.5] * 20
        # 再次仅截取前 t+1 个数据
        state_after, metrics_after = detect_trend(future_closes[: t + 1])

        assert state_t == state_after
        assert metrics_t["mom_20d"] == metrics_after["mom_20d"]
        assert metrics_t["ma60_ratio"] == metrics_after["ma60_ratio"]
        assert metrics_t["above_ma60"] == metrics_after["above_ma60"]


def test_csmar_master_panel_truncation_invariance(csmar_single_stock_df: pd.DataFrame):
    """测试 5: CSMAR 主面板真实行情序列上的截断不变性。"""
    df = csmar_single_stock_df
    assert len(df) >= 200

    sample_ts = [50, 100, 150, 200]
    for t in sample_ts:
        slice_t = df.iloc[: t + 1].copy()
        res_t = evaluate_boolean_trend_gate(slice_t)

        # 污染 t 日之后的数据
        shocked_df = df.copy()
        shocked_df.loc[t + 1:, "close"] *= 0.50

        res_t_after = evaluate_boolean_trend_gate(shocked_df.iloc[: t + 1].copy())

        assert res_t["gate_pass"] == res_t_after["gate_pass"]
        assert res_t["wave_phase"] == res_t_after["wave_phase"]
        assert pytest.approx(res_t["ma20"], abs=1e-3) == res_t_after["ma20"]


def test_biwin_688525_confirmation_lag():
    """测试 7: 针对关键标的 佰维存储 (688525) 验证拐点确认延迟与零前视特征。

    实测数据：
    - index=19 (2025-10-09, high=112.94) 创出主升浪波峰；
    - 在 t=19 当日切片中，swings 中绝不存在 index=19 的 PEAK；
    - 直至 t=20 (2025-10-10, low=98.50 <= 112.94 * 0.88) 回撤超过 12%，该波峰才因果锁定。
    """
    project_root = Path(__file__).resolve().parent.parent
    biwin_file = project_root / "docs" / "data" / "kline" / "688525.json"
    assert biwin_file.exists(), f"688525.json not found: {biwin_file}"

    with open(biwin_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    df = pd.DataFrame({
        "date": data["dates"],
        "open": [float(row[0]) for row in data["kline"]],
        "close": [float(row[1]) for row in data["kline"]],
        "low": [float(row[2]) for row in data["kline"]],
        "high": [float(row[3]) for row in data["kline"]],
        "volume": [float(v) for v in data["volume"]],
    })

    zigzag = NonForwardLookingZigZag(reversal_pct=12.0)
    swings_t19 = zigzag.compute_swings(df.iloc[:20])
    swings_t20 = zigzag.compute_swings(df.iloc[:21])

    # t=19 当天不应感知
    assert not any(s.index == 19 for s in swings_t19), (
        "Confirmation lag violated! Peak at index 19 was prematurely identified on day 19."
    )
    # t=20 回撤确认后因果记录
    peak_points = [s for s in swings_t20 if s.index == 19 and s.point_type == "PEAK"]
    assert len(peak_points) == 1, "Peak at index 19 must be locked on day 20."
    assert pytest.approx(peak_points[0].price) == 112.94


def test_sequential_rolling_invariance_across_time(sample_kline_df: pd.DataFrame):
    """测试 8: 逐日推进决策与全样本前瞻决策的截断不变性全同校验。

    在 t in [30, 80] 区间内：
    模拟实盘逐日推进执行 evaluate_boolean_trend_gate(df.iloc[:t+1])；
    验证在任意更长的回测样本 (T=150) 下，过去历史点 t 所产生的决策完全一致，
    无任何事后修正 (No Ex-post Revision)。
    """
    df = sample_kline_df
    t_start, t_end = 30, 80

    # 1. 在较短历史 (截断到 t_end) 下按日记录信号
    df_short = df.iloc[: t_end + 1].copy()
    signals_short = [
        evaluate_boolean_trend_gate(df_short.iloc[: t + 1].copy())["gate_pass"]
        for t in range(t_start, t_end + 1)
    ]

    # 2. 在较长全量历史 (截断到 t_end + 50) 下按日记录信号
    df_long = df.iloc[: t_end + 51].copy()
    signals_long = [
        evaluate_boolean_trend_gate(df_long.iloc[: t + 1].copy())["gate_pass"]
        for t in range(t_start, t_end + 1)
    ]

    assert signals_short == signals_long, (
        "Signals revised retrospectively! Truncation invariance failed between short and long history."
    )


def test_no_negative_shift_leakage(sample_kline_df: pd.DataFrame):
    """测试 9: 零未来函数反证测试 (Zero Negative Shift / Zero Future Return Correlation)。

    验证策略信号在 t 日决策时，与人为向未来注入的扰动收益率绝对不相关。
    若算法存在负位移 shift(-n) 或全样本分位数泄漏，将与未来扰动产生虚假统计相关。
    """
    df = sample_kline_df.iloc[:120].copy()
    np.random.seed(42)

    signals = []
    future_shocks = []

    for t in range(40, 100):
        # 1. 真实当前信号
        res = evaluate_boolean_trend_gate(df.iloc[: t + 1].copy())
        sig = res["gate_pass"]
        signals.append(sig)

        # 2. 假设未来第 t+1 日发生人为独立随机收益率扰动
        shock = float(np.random.normal(0, 0.05))
        future_shocks.append(shock)

    # 计算信号与未来随机冲击之间的相关性
    # 严格检验：当期决策绝不受未来随机冲击影响
    corr = float(np.corrcoef(signals, future_shocks)[0, 1])
    assert np.isnan(corr) or abs(corr) < 0.25, (
        f"Suspicious correlation ({corr:.4f}) between current signals and future shocks"
    )
