# -*- coding: utf-8 -*-
"""tests/test_storage_supercycle_pipeline.py —— 2025-2026 半导体存储超级周期回测流水线综合测试

验证《Backtesting Specification: The 2025-2026 Semiconductor Storage Supercycle》核心规则：
1. Layer 1 SCNU-RAG FOI 解析与供应链卡位评分 (CS >= 12) 与对抗性修饰符
2. Layer 2 Fama-MacBeth 两阶段回归 + Newey-West HAC 与 Alpha Gate (p < 0.05, IR >= 0.3)
3. Layer 3 纯因果 ZigZag 艾略特波浪与 Trend Gate 布尔执行器
4. Table 2 标杆参考用例：
   - BIWIN (688525): 2026-Q2~2026-Q4 C 浪拦截强制现金清仓，MaxDD < 17%
   - MU (美光): 2025-H2~2026-Q1 0.618 支撑位买入，Sharpe > 1.70
   - Brier Score 预测校准度
"""

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.analysis import factor_db, fama_macbeth
from src.analysis.alpha_gate import evaluate_gate, VERDICT_PASS
from src.llm.scnu_rag_filter import SCNURAGFilter, CS_HARD_GATE_THRESHOLD
from src.strategies.trend_gate import evaluate_boolean_trend_gate
from src.strategies.zigzag_wave import NonForwardLookingZigZag
from src.strategies.storage_supercycle_backtest import StorageSupercycleBacktester


# ============================================================================
# 1. Layer 1: SCNU-RAG 定性过滤测试
# ============================================================================

def test_scnu_rag_foi_parsing():
    filter_engine = SCNURAGFilter()
    sample_text = (
        "[FACT:customs] 2025-H1 华强北 DDR5 现货均价上涨 18%；"
        "[OPINION:morgan_stanley] 分析师上调目标价至 120 美元；"
        "[INFERENCE:capex_cycle] 由此推导下游厂商将提前锁定下半年晶圆产能。"
    )
    evidence = filter_engine.parse_foi(sample_text)
    assert len(evidence) == 3
    cats = [e.category for e in evidence]
    assert "FACT" in cats
    assert "OPINION" in cats
    assert "INFERENCE" in cats


def test_scnu_rag_chokepoint_score_and_gate():
    filter_engine = SCNURAGFilter()

    # 1. 龙头原厂 IDM (Micron MU): CS = 20 >= 12 -> 通行
    mu_report = filter_engine.evaluate_chokepoint_score("MU", "美光科技", "HBM3E 先进制程与全产业链原厂产能保障")
    assert mu_report["chokepoint_score"] == 20
    assert mu_report["passed_gate"] is True

    # 2. 低卡位伪题材股 (Low CS): CS = 6 < 12 -> 拦截剪枝
    low_cs_report = filter_engine.evaluate_chokepoint_score(
        "000001", "概念散户股", "无自主制程与主控芯片，纯贸易分销",
        custom_scores={f"Q{i}": 0 for i in range(1, 11)}
    )
    assert low_cs_report["chokepoint_score"] < CS_HARD_GATE_THRESHOLD
    assert low_cs_report["passed_gate"] is False


def test_scnu_rag_adversarial_scaling_rules():
    filter_engine = SCNURAGFilter()

    # 规则 1: 单一来源 -> 仓位上限 50%
    r1_feed = "[FACT:single_source] 独家传闻某厂商获得大单；"
    r1_res = filter_engine.evaluate_chokepoint_score("688525", "佰维存储", r1_feed)
    assert r1_res["adversarial_modifier"]["position_cap"] == 0.50

    # 规则 2: 样品测试 -> 基础权重减半 (0.5x)
    r2_feed = "[FACT:low_confidence] 新产品处于送样验证阶段与小批量试产；"
    r2_res = filter_engine.evaluate_chokepoint_score("688525", "佰维存储", r2_feed)
    assert r2_res["adversarial_modifier"]["weight_multiplier"] == 0.50

    # 规则 3: 资本开支不匹配 -> 触发 AR 交叉检验
    r3_feed = "预付款剧增但应收账款高企，资本开支不匹配"
    r3_res = filter_engine.evaluate_chokepoint_score("688525", "佰维存储", r3_feed)
    assert r3_res["adversarial_modifier"]["ar_check_required"] is True


# ============================================================================
# 2. Layer 2: Fama-MacBeth 两阶段回归与 Alpha Gate 测试
# ============================================================================

def test_fama_macbeth_rolling_and_newey_west():
    np.random.seed(42)
    n = 252
    dates = pd.date_range("2025-01-01", periods=n, freq="B").strftime("%Y-%m-%d")
    mkt = np.random.normal(0.0005, 0.01, n)
    smb = np.random.normal(0.0001, 0.005, n)
    hml = np.random.normal(-0.0001, 0.005, n)
    mom = np.random.normal(0.0002, 0.006, n)
    rf = np.full(n, 0.0001)

    factors_df = pd.DataFrame({
        "date": dates, "MKT": mkt, "SMB": smb, "HML": hml, "MOM": mom, "rf": rf,
    })

    # 构造真 Alpha = 0.002 (年化 ~ 50%), 残差波动 = 0.003 -> IR ~ 0.67 >= 0.3
    eps = np.random.normal(0, 0.003, n)
    r_stock = rf + 0.002 + 1.2 * mkt + 0.3 * smb - 0.2 * hml + 0.5 * mom + eps

    res = fama_macbeth.regress_one(factors_df, r_stock, min_obs_days=100)
    assert res["status"] == "ok"
    assert res["converged"] is True
    assert res["alpha"] > 0
    assert res["alpha_p_value"] < 0.05
    assert res["information_ratio"] >= 0.3

    gate_res = evaluate_gate(res)
    assert gate_res["verdict"] == VERDICT_PASS


def test_fama_macbeth_stage2_newey_west_t_stat():
    dates = [f"2025-01-{i+1:02d}" for i in range(25)]
    factors_df = pd.DataFrame({
        "date": dates, "MKT": [0.01]*25, "SMB": [0.002]*25, "HML": [-0.001]*25, "MOM": [0.003]*25, "rf": [0.0001]*25
    })
    panel_returns = {f"stk_{i}": [0.01 + 0.001 * i]*25 for i in range(25)}
    panel_betas = {f"stk_{i}": {"MKT": 1.0, "SMB": 0.5, "HML": -0.2, "MOM": 0.1} for i in range(25)}

    stage2_res = fama_macbeth.fama_macbeth_stage2(factors_df, panel_returns, panel_betas, min_cross_section=5)
    assert stage2_res["n_periods"] == 25
    assert "lambda_t_stat" in stage2_res
    assert "MKT" in stage2_res["lambda_t_stat"]


# ============================================================================
# 3. Layer 3: ZigZag 艾略特波浪与 Trend Gate 测试
# ============================================================================

def test_zigzag_wave_and_fibonacci_support():
    # 模拟主升 3 浪 (从 10 涨到 20) -> 回调至 0.618 支撑位 (20 - 0.618*10 = 13.82)
    prices = [10.0, 11.5, 13.0, 15.0, 17.5, 20.0, 18.0, 16.0, 14.5, 13.9, 13.85]
    vols = [1000] * 10 + [600]  # 最后一天缩量 40% (Volume <= 0.8 * MA20)
    dates = [f"2025-01-{i+1:02d}" for i in range(len(prices))]

    df = pd.DataFrame({"date": dates, "close": prices, "high": prices, "low": prices, "volume": vols})
    zigzag = NonForwardLookingZigZag(reversal_pct=10.0)
    wave_res = zigzag.analyze_wave_structure(df)

    assert wave_res.fib_0_500 is not None
    assert wave_res.fib_0_618 is not None
    assert wave_res.in_fib_support_zone is True
    assert wave_res.volume_contracted_20pct is True
    assert wave_res.hunting_ground_entry is True


def test_boolean_trend_gate_c_wave_defense():
    # 模拟 C 浪杀跌走势（破位 + 均线死叉）
    prices = [20.0, 22.0, 21.0, 19.0, 17.0, 15.0, 14.0, 12.0, 11.0, 10.0] * 3
    dates = pd.date_range("2026-06-01", periods=len(prices), freq="B").strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({"date": dates, "close": prices, "high": prices, "low": prices, "volume": [1000]*len(prices)})

    gate_res = evaluate_boolean_trend_gate(df, wave_phase="Phase_C")
    # WavePhase == Phase_C 必须导致 GatePass == 0
    assert gate_res["gate_pass"] == 0
    assert gate_res["cond_not_wave_c"] is False


# ============================================================================
# 4. Table 2 标杆参考用例验证 (BIWIN MaxDD < 17%, Micron Sharpe > 1.70)
# ============================================================================

def _load_stock_kline(code: str) -> pd.DataFrame:
    root = Path(__file__).resolve().parent.parent
    path = root / "docs" / "data" / "kline" / f"{code}.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    dates = data["dates"]
    rows = data["kline"]
    volume = data.get("volume", [100000] * len(dates))
    return pd.DataFrame({
        "date": dates,
        "open": [r[0] for r in rows],
        "close": [r[1] for r in rows],
        "low": [r[2] for r in rows],
        "high": [r[3] for r in rows],
        "volume": volume,
    })


def test_table2_biwin_maxdd_suppression_and_micron_sharpe():
    # 读取真实 K 线与因子库
    df_biwin = _load_stock_kline("688525")
    df_mu = _load_stock_kline("MU")

    db_path = str(factor_db.default_db_path())
    factors_df = factor_db.query_range(db_path, "2021-01-01", "2026-12-31")

    klines = {"688525": df_biwin, "MU": df_mu}
    backtester = StorageSupercycleBacktester(klines=klines, factors_df=factors_df)

    # 1. 验证 BIWIN 2026-Q2 ~ 2026-Q4 下跌周期防御：Trend Gate 拦截 C 浪，最大回撤压制在 < 17%
    biwin_test = StorageSupercycleBacktester(
        klines={"688525": df_biwin},
        factors_df=factors_df,
        initial_capital=500000.0,
    )
    biwin_res = biwin_test.run_backtest(start_date="2026-03-01", end_date="2026-08-24")
    biwin_perf = biwin_res["performance"]

    assert biwin_perf["max_drawdown_pct"] < 17.0, f"BIWIN MaxDD {biwin_perf['max_drawdown_pct']}% exceeds 17% target"

    # 2. 验证 Micron MU 2025-H2 ~ 2026-Q1 主升支撑入场：夏普比率 > 1.70
    mu_test = StorageSupercycleBacktester(
        klines={"MU": df_mu},
        factors_df=factors_df,
        initial_capital=500000.0,
    )
    mu_res = mu_test.run_backtest(start_date="2025-07-17", end_date="2026-04-01")
    mu_perf = mu_res["performance"]

    assert mu_perf["sharpe_ratio"] > 1.70, f"MU Sharpe {mu_perf['sharpe_ratio']} does not meet > 1.70 target"
    assert mu_perf["brier_score"] <= 0.25, f"Brier score {mu_perf['brier_score']} calibration failure"


def test_full_storage_supercycle_backtest_pipeline():
    # 全池全周期端到端运行
    df_biwin = _load_stock_kline("688525")
    df_mu = _load_stock_kline("MU")
    db_path = str(factor_db.default_db_path())
    factors_df = factor_db.query_range(db_path, "2021-01-01", "2026-12-31")

    backtester = StorageSupercycleBacktester(
        klines={"688525": df_biwin, "MU": df_mu},
        factors_df=factors_df,
        initial_capital=1000000.0,
    )
    result = backtester.run_backtest(start_date="2025-07-21", end_date="2026-08-24")
    perf = result["performance"]

    assert perf["total_return_pct"] > 0
    assert perf["sharpe_ratio"] > 1.0
    assert perf["max_drawdown_pct"] < 20.0
    assert perf["brier_score"] < 0.25
