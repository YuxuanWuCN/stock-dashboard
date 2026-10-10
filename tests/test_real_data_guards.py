# -*- coding: utf-8 -*-
"""tests/test_real_data_guards.py —— Milestone M1: 反作弊与真实数据守卫体系全量测试

测试范围涵盖：
1. 异常定义：MissingRealDataError 与 SyntheticDataRejectedError。
2. StorageBacktestRunner：
   - 封禁 backtest_paper_2024_2026_300stocks 目录读取；
   - 缺少真实数据时默认抛出 MissingRealDataError；
   - 显式开启 allow_synthetic=True 时输出标记 data_source='synthetic'；
   - 正式回测 run_walk_forward_backtest 遇到合成数据时若 allow_synthetic=False 抛出 SyntheticDataRejectedError。
3. StorageSupercycleBacktester：
   - 样本观测不足 MIN_OBS_DAYS (250 天) 时，严禁虚假注入 alpha=0.0015 / IR=7.14，返回 status='insufficient_data'；
   - 严格执行 p < 0.05 且 ir >= 0.30 的计量门控；
   - 无预测样本时 Brier Score 返回 None，状态标为 'no_predictions'。
4. 因子提供者与技能插件反作弊：
   - KennethFrenchFactorProvider 默认抛出 MissingRealDataError；
   - EastMoneyMiaoXiangSkill 默认抛出 MissingRealDataError；
   - 开启 allow_synthetic 时标记 data_source='synthetic'，且绝对不污染 factor_daily 数据库；
   - UnifiedDataAdapter 严格遵循真实优先与合成拒绝门控。
5. StorageGoldJointEngine：
   - 封禁伪造目录并拒绝合成回测；
   - 废除硬编码 3.82，采用真实 Newey-West HAC 滚动估计。
"""

import sqlite3
import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from src.data.exceptions import MissingRealDataError, SyntheticDataRejectedError
from src.analysis.storage_backtest_runner import StorageBacktestRunner
from src.strategies.storage_supercycle_backtest import StorageSupercycleBacktester
from src.analysis import config
from src.analysis.factor_providers import KennethFrenchFactorProvider
from src.skills.eastmoney_miaoxiang_skill import EastMoneyMiaoXiangSkill
from src.data.adapter import UnifiedDataAdapter
from src.analysis.storage_gold_joint_runner import StorageGoldJointEngine


# =========================================================================
# 1. 异常类型层级结构测试
# =========================================================================

def test_data_guard_exceptions_hierarchy():
    """验证数据守卫异常继承关系。"""
    assert issubclass(MissingRealDataError, Exception)
    assert issubclass(SyntheticDataRejectedError, Exception)

    err1 = MissingRealDataError("item", "Custom missing real data message")
    err2 = SyntheticDataRejectedError("source", "Custom synthetic rejected message")

    assert "Custom missing real data message" in str(err1)
    assert "Custom synthetic rejected message" in str(err2)


# =========================================================================
# 2. StorageBacktestRunner 反作弊门禁测试
# =========================================================================

def test_storage_backtest_runner_blocks_paper_300stocks(tmp_path):
    """验证封禁旧造假目录 backtest_paper_2024_2026_300stocks。"""
    fake_paper_dir = tmp_path / "backtest_paper_2024_2026_300stocks"
    fake_paper_dir.mkdir()

    with pytest.raises(SyntheticDataRejectedError, match="deprecated synthetic dataset"):
        StorageBacktestRunner(raw_data_dir=fake_paper_dir, allow_synthetic=False)


def test_storage_backtest_runner_raises_on_missing_tickers(tmp_path):
    """当真实数据不完整且未授权 allow_synthetic 时，load_isolated_raw_data 必须抛出 MissingRealDataError。"""
    empty_raw = tmp_path / "empty_raw"
    empty_raw.mkdir()
    pd.DataFrame({"date": ["2025-01-01"], "000300.SH": [10.0]}).to_csv(empty_raw / "market_prices.csv")
    pd.DataFrame().to_csv(empty_raw / "nowcasting_spot.csv")
    pd.DataFrame().to_csv(empty_raw / "factors.csv")

    runner = StorageBacktestRunner(raw_data_dir=empty_raw, allow_synthetic=False)
    with pytest.raises(MissingRealDataError, match="Missing required real market prices"):
        runner.load_isolated_raw_data()


def test_storage_backtest_runner_tags_synthetic_when_allowed(tmp_path):
    """当明确设置 allow_synthetic=True 时，生成数据并明确标记 data_source='synthetic'。"""
    empty_raw = tmp_path / "empty_raw"
    empty_raw.mkdir()
    pd.DataFrame({"date": ["2025-01-01"], "000300.SH": [10.0]}).to_csv(empty_raw / "market_prices.csv")
    pd.DataFrame().to_csv(empty_raw / "nowcasting_spot.csv")
    pd.DataFrame().to_csv(empty_raw / "factors.csv")

    runner = StorageBacktestRunner(raw_data_dir=empty_raw, allow_synthetic=True)
    prices, _, _ = runner.load_isolated_raw_data()
    assert prices.attrs.get("data_source") == "synthetic"


def test_storage_backtest_runner_rejects_synthetic_in_formal_run(tmp_path):
    """当 DataFrame 标记为 synthetic 但回测器 allow_synthetic=False 时，必须阻断回测。"""
    empty_raw = tmp_path / "empty_raw"
    empty_raw.mkdir()

    runner = StorageBacktestRunner(raw_data_dir=empty_raw, allow_synthetic=False)

    dates = pd.date_range("2025-07-01", periods=30, freq="B")
    mock_df = pd.DataFrame({"000300.SH": [10.0] * 30, "512760.SH": [1.0] * 30}, index=dates)
    for t in runner.STORAGE_TICKERS:
        mock_df[t] = 10.0
    mock_df.attrs["data_source"] = "synthetic"

    runner.load_isolated_raw_data = lambda: (mock_df, pd.DataFrame(index=dates), pd.DataFrame(index=dates))

    with pytest.raises(SyntheticDataRejectedError, match="Formal backtest rejects synthetic price data"):
        runner.run_walk_forward_backtest()


# =========================================================================
# 3. StorageSupercycleBacktester 真实计量门控测试
# =========================================================================

def test_supercycle_alpha_gate_insufficient_data():
    """当样本观测天数 < 250 天时，必须返回 insufficient_data，严禁虚假注入 alpha/IR。"""
    short_kline = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=100, freq="B"),
        "open": np.linspace(10, 20, 100),
        "close": np.linspace(10, 20, 100),
        "low": np.linspace(9, 19, 100),
        "high": np.linspace(11, 21, 100),
        "volume": [100000] * 100,
    })
    dummy_factors = pd.DataFrame({
        "trade_date": ["20250101"],
        "mkt_rf": [0.0],
        "smb": [0.0],
        "hml": [0.0],
        "mom": [0.0],
    })

    bt = StorageSupercycleBacktester(
        klines={"688525": short_kline},
        factors_df=dummy_factors,
    )

    eval_res = bt.evaluate_alpha_gate("688525", short_kline)
    assert eval_res["alpha_gate_status"] == "insufficient_data"
    assert eval_res["passes_alpha"] is False
    assert eval_res["alpha_val"] is None
    assert eval_res["alpha_ir"] is None


def test_supercycle_brier_score_empty_predictions():
    """当无预测样本时，Brier Score 必须为 None 且状态为 no_predictions，拒绝虚假 0.185。"""
    bt = StorageSupercycleBacktester(klines={}, factors_df=pd.DataFrame())

    perf = bt._evaluate_performance(
        trades=[],
        equity_history=[1000000.0, 1005000.0],
        daily_returns=[0.005],
        brier_predictions=[],
        brier_outcomes=[],
        dates=["2025-07-21", "2025-07-22"],
    )

    assert perf["brier_score"] is None
    assert perf["brier_status"] == "no_predictions"


def test_supercycle_brier_score_real_calculation():
    """当存在有效预测样本时，真实计算标准平方误差均值。"""
    bt = StorageSupercycleBacktester(klines={}, factors_df=pd.DataFrame())

    preds = [0.8, 0.2, 0.6]
    outcomes = [1, 0, 1]
    # (0.8-1)^2 + (0.2-0)^2 + (0.6-1)^2 = 0.04 + 0.04 + 0.16 = 0.24 / 3 = 0.08
    perf = bt._evaluate_performance(
        trades=[],
        equity_history=[1000000.0],
        daily_returns=[],
        brier_predictions=preds,
        brier_outcomes=outcomes,
        dates=["2025-07-21"],
    )

    assert perf["brier_score"] == 0.08
    assert perf["brier_status"] == "ok"


# =========================================================================
# 4. 因子提供者与技能插件反作弊测试
# =========================================================================

def test_kenneth_french_provider_raises_missing_real_data(tmp_path, monkeypatch):
    """Kenneth-French 因子提供者在无网络且无本地缓存时，默认抛出 MissingRealDataError。"""
    provider = KennethFrenchFactorProvider(
        cache_dir=tmp_path / "kc",
        allow_synthetic=False,
    )
    def fail_fetch():
        raise ConnectionError("Simulated offline")
    monkeypatch.setattr(provider, "_fetch_and_parse_online", fail_fetch)

    with pytest.raises(MissingRealDataError):
        provider.get_daily_factors("2024-01-01", "2024-01-10")


def test_kenneth_french_provider_tags_synthetic_when_allowed(tmp_path, monkeypatch):
    """Kenneth-French 因子提供者在开启 allow_synthetic 时标记 synthetic。"""
    provider = KennethFrenchFactorProvider(
        cache_dir=tmp_path / "kc",
        allow_synthetic=True,
    )
    def fail_fetch():
        raise ConnectionError("Simulated offline")
    monkeypatch.setattr(provider, "_fetch_and_parse_online", fail_fetch)

    df = provider.get_daily_factors("2024-01-01", "2024-01-10")
    assert df.attrs.get("data_source") == "synthetic"
    assert len(df) > 0


def test_eastmoney_miaoxiang_skill_anti_cheat(tmp_path):
    """妙想 Skill 反作弊：默认报错，开启兜底时标记 synthetic，且严禁污染 factor_daily。"""
    test_db = tmp_path / "em.db"
    skill_strict = EastMoneyMiaoXiangSkill(
        cache_db=test_db,
        allow_synthetic=False,
    )
    with pytest.raises(MissingRealDataError):
        skill_strict.get_daily_factors_with_capital_flows("2024-01-01", "2024-01-10")

    skill_syn = EastMoneyMiaoXiangSkill(
        cache_db=test_db,
        allow_synthetic=True,
    )
    df = skill_syn.get_daily_factors_with_capital_flows("2024-01-01", "2024-01-10")
    assert df.attrs.get("data_source") == "synthetic"

    # 验证 factor_daily 表保持 0 行污染！
    with sqlite3.connect(test_db) as conn:
        row_count = conn.execute("SELECT COUNT(*) FROM factor_daily").fetchone()[0]
    assert row_count == 0, f"Synthetic factor data polluted SQLite factor_daily! Count: {row_count}"


def test_unified_data_adapter_anti_cheat(tmp_path, monkeypatch):
    """UnifiedDataAdapter 默认拒绝合成，仅在 allow_synthetic=True 时输出带标签合成数据。"""
    test_db = tmp_path / "u.db"
    adapter_strict = UnifiedDataAdapter(cache_db=test_db, allow_synthetic=False)
    adapter_strict.us_provider.cache_dir = tmp_path / "empty_cache"
    def fail_fetch():
        raise ConnectionError("Simulated offline")
    monkeypatch.setattr(adapter_strict.us_provider, "_fetch_and_parse_online", fail_fetch)

    with pytest.raises(MissingRealDataError):
        adapter_strict.get_market_factors("2024-01-01", "2024-01-10", market="US")

    adapter_syn = UnifiedDataAdapter(cache_db=test_db, allow_synthetic=True)
    adapter_syn.us_provider.cache_dir = tmp_path / "empty_cache"
    monkeypatch.setattr(adapter_syn.us_provider, "_fetch_and_parse_online", fail_fetch)
    df = adapter_syn.get_market_factors("2024-01-01", "2024-01-10", market="US")
    assert df.attrs.get("data_source") == "synthetic"


# =========================================================================
# 5. StorageGoldJointEngine 守卫与真实 Newey-West 检验
# =========================================================================

def test_storage_gold_joint_rejects_synthetic():
    """StorageGoldJointEngine 当 allow_synthetic=False 遇到合成数据时抛出 SyntheticDataRejectedError。"""
    dates = pd.date_range("2025-01-01", periods=10, freq="B")
    mock_df = pd.DataFrame({"000300.SH": [10.0] * 10}, index=dates)
    mock_df.attrs["data_source"] = "synthetic"

    engine = StorageGoldJointEngine.__new__(StorageGoldJointEngine)
    engine.allow_synthetic = False
    engine.prices_df = mock_df

    with pytest.raises(SyntheticDataRejectedError, match="Formal backtest rejected synthetic data"):
        engine.run_backtest()


def test_storage_gold_joint_computes_real_harvey_t():
    """StorageGoldJointEngine 当 allow_synthetic=True 时，harvey_alpha_t_stat 必须基于真实 Newey-West 计算。"""
    engine = StorageGoldJointEngine(allow_synthetic=True)
    res = engine.run_backtest()

    assert "harvey_alpha_t_stat" in res
    t_stat = res["harvey_alpha_t_stat"]
    assert isinstance(t_stat, (int, float))
    assert np.isfinite(t_stat)
