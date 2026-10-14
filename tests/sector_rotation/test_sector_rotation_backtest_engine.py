# -*- coding: utf-8 -*-
"""tests/sector_rotation/test_backtest_engine.py —— 回测引擎主循环行为复核

全部使用合成 K 线与夹具情绪（外部请求为零，可离线复现），断言均为手算口径：
- 净值 = 持仓板块等权成分日收益复利 + 步进日扣成本
- 轮动全周期：day5 决策 -> day6/7/8 以 50/30/20 渐进切换
- 成本超限 -> CostLimitExceededError 中断并撤销计划
- 防御降级、advisor 复核回填、for_report 拒绝代理源、产物禁止覆盖
"""

from types import SimpleNamespace

import pytest

from src.sector_rotation.backtest.backtest_engine import BacktestEngine
from src.sector_rotation.backtest.sentiment_providers import (
    FrozenFixturesSentimentProvider,
    KlineStore,
    ProxyBreadthSentimentProvider,
)

DAYS = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09",
        "2026-01-12", "2026-01-13", "2026-01-14", "2026-01-15", "2026-01-16",
        "2026-01-19", "2026-01-20"]

SECTORS_STUB = {
    "alpha": SimpleNamespace(tickers=("A1", "A2")),
    "beta": SimpleNamespace(tickers=("B1", "B2")),
    "gamma": SimpleNamespace(tickers=("G1", "G2")),
}


def _flat_store():
    return KlineStore.from_dict({c: {d: 100.0 for d in DAYS}
                                 for c in ("A1", "A2", "B1", "B2", "G1", "G2")})


def _st(score, trend="stable", conf=0.9):
    return {"sentiment_score": score, "sentiment_trend": trend,
            "volatility": 0.0, "stock_count": 2, "confidence": conf}


def _fixture(states_per_sector_by_day):
    """{day: {sid: state_dict}} -> FrozenFixturesSentimentProvider"""
    return FrozenFixturesSentimentProvider(states_per_sector_by_day)


def _all_days(states_fn):
    return {d: states_fn(i, d) for i, d in enumerate(DAYS)}


def _declining_alpha():
    """alpha 持续下沉、beta 强势、gamma 中性 -> idx>=5 应触发向 beta 轮动"""
    return _all_days(lambda i, d: {
        "alpha": _st(-0.6, "declining"), "beta": _st(0.8), "gamma": _st(0.0)})


class TestEngineValuation:
    def test_flat_prices_nav_constant(self):
        # 全 flat 价 + 健康情绪 -> 零轮动、nav 恒为初始资金、基准恒为 1.0
        provider = _fixture(_all_days(
            lambda i, d: {"alpha": _st(0.5), "beta": _st(0.4), "gamma": _st(0.3)}))
        engine = BacktestEngine(_flat_store(), sectors=SECTORS_STUB)
        res = engine.run(DAYS[0], DAYS[-1], provider, initial_sector="alpha")
        assert res.nav == pytest.approx([1_000_000.0] * len(DAYS))
        assert res.benchmark_nav == pytest.approx([1.0] * len(DAYS))
        assert res.trades == []
        assert len(res.decisions) == len(DAYS)
        assert res.metrics["strategy"]["rotations"] == 0

    def test_daily_return_uses_yesterday_weights(self):
        # 持仓 gamma 且 G1 day1 涨 10%（等权成分 -> +5%）：nav[1]=1,050,000 手算
        store = KlineStore.from_dict({
            "A1": {d: 100.0 for d in DAYS}, "A2": {d: 100.0 for d in DAYS},
            "B1": {d: 100.0 for d in DAYS}, "B2": {d: 100.0 for d in DAYS},
            "G1": {DAYS[0]: 100.0, **{d: 110.0 for d in DAYS[1:]}},
            "G2": {d: 50.0 for d in DAYS},
        })
        provider = _fixture(_all_days(
            lambda i, d: {"alpha": _st(0.1), "beta": _st(0.1), "gamma": _st(0.1)}))
        engine = BacktestEngine(store, sectors=SECTORS_STUB)
        res = engine.run(DAYS[0], DAYS[-1], provider, initial_sector="gamma")
        assert res.nav[1] == pytest.approx(1_050_000.0)
        assert res.nav[2:] == pytest.approx([1_050_000.0] * (len(DAYS) - 2))
        # 基准 = 3 板块等权：day1 收益 (0 + 0 + 5%)/3
        assert res.benchmark_nav[1] == pytest.approx(1.0 + 0.05 / 3)

    def test_empty_states_day_skips_decision(self):
        # fixture 缺第 3 天 -> KeyError 被捕获 -> 该日无决策行（不外推、不造假）
        days_with = {d: {"alpha": _st(0.5)} for d in DAYS if d != DAYS[2]}
        provider = _fixture(days_with)
        engine = BacktestEngine(_flat_store(), sectors=SECTORS_STUB)
        res = engine.run(DAYS[0], DAYS[-1], provider, initial_sector="alpha")
        assert len(res.decisions) == len(DAYS) - 1


class TestEngineRotation:
    def test_rotation_full_cycle_50_30_20(self):
        # day5(idx>=5) 触发 -> day6/7/8 三步完成；flat 价 -> nav = 初始 - 总成本
        provider = _fixture(_declining_alpha())
        engine = BacktestEngine(_flat_store(), sectors=SECTORS_STUB)
        res = engine.run(DAYS[0], DAYS[-1], provider, initial_sector="alpha")

        steps = [t for t in res.trades if "step_ratio" in t]
        assert len(steps) == 3, "50/30/20 渐进切换应为 3 个执行日"
        assert [s["step_ratio"] for s in steps] == pytest.approx([0.5, 0.3, 0.2])
        # 权重演进：to_sector 累计 50% -> 80% -> 100%
        betas = [s["executed_weights"].get("beta", 0.0) for s in steps]
        assert betas == pytest.approx([0.5, 0.8, 1.0], abs=1e-4)
        assert steps[-1]["is_complete"] is True
        # 手算成本：每步 nav*ratio*(buy+sell=0.003)，nav 近似恒定 -> 总成本≈0.3%
        total_cost = sum(s["cost"] for s in steps)
        assert total_cost == pytest.approx(1_000_000.0 * 0.003, rel=0.01)
        assert res.nav[-1] == pytest.approx(1_000_000.0 - total_cost, rel=1e-9)
        assert res.metrics["strategy"]["rotations"] == 1

    def test_rotation_triggers_from_day_index_5_only(self):
        # 门禁：idx<5 holding_days<5 全部不轮动；idx==5 才首次 should_rotate
        provider = _fixture(_declining_alpha())
        engine = BacktestEngine(_flat_store(), sectors=SECTORS_STUB)
        res = engine.run(DAYS[0], DAYS[-1], provider, initial_sector="alpha")
        first_rotate_idx = [j for j, r in enumerate(res.decisions)
                            if r["should_rotate"]][0]
        assert first_rotate_idx == 5

    def test_cost_limit_exceeded_aborts_and_keeps_sector(self):
        # 成本上限压到 0.01% -> 首步即超限 -> 撤销计划，持仓停留在 alpha
        provider = _fixture(_declining_alpha())
        engine = BacktestEngine(_flat_store(), sectors=SECTORS_STUB)
        res = engine.run(DAYS[0], DAYS[-1], provider, initial_sector="alpha",
                         params={"max_total_rotation_cost": 0.0001})
        aborts = [t for t in res.trades
                  if t.get("event") == "cost_limit_exceeded_aborted"]
        assert len(aborts) >= 1
        assert not [t for t in res.trades if "executed_weights" in t]
        # 从未成功切换：净值无成本损耗（flat 价 -> 恒为初始）
        assert res.nav == pytest.approx([1_000_000.0] * len(DAYS))
        segs = [s for s in res.segments]
        assert all(s["sector"] != "beta" for s in segs)

    def test_defensive_fallback_when_no_candidate(self):
        # 全部板块下沉且无 score>0.5 候选 -> 防御降级至 gamma（is_fallback=True）
        provider = _fixture(_all_days(lambda i, d: {
            "alpha": _st(-0.6, "declining"), "beta": _st(-0.4, "declining"),
            "gamma": _st(0.0)}))
        engine = BacktestEngine(_flat_store(), sectors=SECTORS_STUB)
        res = engine.run(DAYS[0], DAYS[-1], provider, initial_sector="alpha",
                         params={"defensive_sector": "gamma"})
        fb = [r for r in res.decisions if r["should_rotate"] and r["is_fallback"]]
        assert fb and all(r["target_sector"] == "gamma" for r in fb)
        steps = [t for t in res.trades if "step_ratio" in t]
        assert steps and steps[-1]["executed_weights"].get("gamma") == pytest.approx(1.0, abs=1e-4)

    def test_advisor_hook_fills_llm_validation(self):
        class _MockAdvisor:
            def __init__(self):
                self.calls = 0

            def validate_decision(self, quantitative_decision, sector_data,
                                  current_sector):
                self.calls += 1
                quantitative_decision.llm_validation = {
                    "status": "approved", "current_sector": current_sector}
                return quantitative_decision

        advisor = _MockAdvisor()
        provider = _fixture(_declining_alpha())
        engine = BacktestEngine(_flat_store(), sectors=SECTORS_STUB)
        res = engine.run(DAYS[0], DAYS[-1], provider, initial_sector="alpha",
                         advisor=advisor)
        rot_rows = [r for r in res.decisions if r["should_rotate"]]
        assert rot_rows and all(r["llm_validation"] for r in rot_rows)
        assert advisor.calls == len(rot_rows) >= 1


class TestEngineProvenance:
    def test_for_report_rejects_proxy_provider(self):
        engine = BacktestEngine(_flat_store(), sectors=SECTORS_STUB)
        proxy = ProxyBreadthSentimentProvider(
            _flat_store(), DAYS, sectors=SECTORS_STUB)
        with pytest.raises(ValueError, match="报告"):
            engine.run(DAYS[0], DAYS[-1], proxy, for_report=True)

    def test_for_report_rejects_fixture_provider(self):
        engine = BacktestEngine(_flat_store(), sectors=SECTORS_STUB)
        provider = _fixture(_all_days(lambda i, d: {"alpha": _st(0.5)}))
        with pytest.raises(ValueError):
            engine.run(DAYS[0], DAYS[-1], provider, for_report=True)

    def test_manifest_records_provenance(self):
        provider = _fixture(_all_days(
            lambda i, d: {"alpha": _st(0.5), "beta": _st(0.4), "gamma": _st(0.3)}))
        engine = BacktestEngine(_flat_store(), sectors=SECTORS_STUB)
        res = engine.run(DAYS[0], DAYS[-1], provider, initial_sector="alpha")
        m = res.manifest
        assert m["sentiment_source"] == "fixture_only"
        assert m["report_usable"] is False
        assert m["window"]["n_trading_days"] == len(DAYS)
        assert m["initial_sector"] == "alpha"
        assert m["advisor_enabled"] is False
        assert m["sector_universe"]["alpha"] == ["A1", "A2"]

    def test_rows_carry_sentiment_source(self):
        provider = _fixture(_declining_alpha())
        engine = BacktestEngine(_flat_store(), sectors=SECTORS_STUB)
        res = engine.run(DAYS[0], DAYS[-1], provider, initial_sector="alpha")
        assert all(r["sentiment_source"] == "fixture_only" for r in res.decisions)
        assert all(r["sentiment_source"] == "fixture_only" for r in res.states_rows)
        assert all(r["sentiment_source"] == "fixture_only" for r in res.trades
                   if "sentiment_source" in r)


class TestEngineNoLookahead:
    def test_prefix_decisions_identical_when_future_changes(self):
        # 两个 fixture 仅 idx>=6 的状态不同 -> 前 6 日决策必须逐行一致
        base = _declining_alpha()
        fut = _declining_alpha()
        for d in DAYS[6:]:
            fut[d] = {"alpha": _st(0.9), "beta": _st(-0.9, "declining"),
                      "gamma": _st(0.0)}
        engine = BacktestEngine(_flat_store(), sectors=SECTORS_STUB)
        r1 = engine.run(DAYS[0], DAYS[-1], _fixture(base), initial_sector="alpha")
        r2 = engine.run(DAYS[0], DAYS[-1], _fixture(fut), initial_sector="alpha")
        for j in range(6):
            a = {k: v for k, v in r1.decisions[j].items() if k != "execution_time_ms"}
            b = {k: v for k, v in r2.decisions[j].items() if k != "execution_time_ms"}
            assert a == b


class TestBacktestResultIO:
    def test_contract_allows_argless_construction_but_run_requires_store(self):
        # 既有 e2e 契约（test_e2e_tiers F21/F22/F24）要求无参可构造；
        # 但真实回测必须提供 store，否则拒绝而非静默使用空数据
        engine = BacktestEngine()
        assert hasattr(engine, "run")
        provider = _fixture(_all_days(lambda i, d: {"alpha": _st(0.5)}))
        with pytest.raises(ValueError, match="KlineStore"):
            engine.run(DAYS[0], DAYS[-1], provider)

    def test_save_writes_all_artifacts_and_blocks_overwrite(self, tmp_path):
        provider = _fixture(_all_days(
            lambda i, d: {"alpha": _st(0.5), "beta": _st(0.4), "gamma": _st(0.3)}))
        engine = BacktestEngine(_flat_store(), sectors=SECTORS_STUB)
        res = engine.run(DAYS[0], DAYS[-1], provider, initial_sector="alpha")
        out = res.save(tmp_path / "run1")
        for fname in ("nav.csv", "trades.csv", "decisions.csv",
                      "sector_states.csv", "metrics.json", "run_manifest.json"):
            assert (out / fname).exists(), fname
        with pytest.raises(FileExistsError):
            res.save(out)
        res.save(out, allow_overwrite=True)  # 显式放行才可覆盖

    def test_save_rejects_nonempty_dir(self, tmp_path):
        provider = _fixture(_all_days(lambda i, d: {"alpha": _st(0.5)}))
        engine = BacktestEngine(_flat_store(), sectors=SECTORS_STUB)
        res = engine.run(DAYS[0], DAYS[-1], provider, initial_sector="alpha")
        dirty = tmp_path / "dirty"
        dirty.mkdir()
        (dirty / "existing.json").write_text("{}", encoding="utf-8")
        with pytest.raises(FileExistsError):
            res.save(dirty)

    def test_short_window_raises(self):
        store = KlineStore.from_dict({"A1": {DAYS[0]: 100.0}, "A2": {DAYS[0]: 100.0},
                                       "B1": {DAYS[0]: 100.0}, "B2": {DAYS[0]: 100.0},
                                       "G1": {DAYS[0]: 100.0}, "G2": {DAYS[0]: 100.0}})
        engine = BacktestEngine(store, sectors=SECTORS_STUB)
        with pytest.raises(ValueError, match="日历"):
            engine.run(DAYS[0], DAYS[1],
                       _fixture({DAYS[0]: {"alpha": _st(0.0)}}))
