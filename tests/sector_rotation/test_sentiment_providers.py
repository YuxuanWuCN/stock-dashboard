# -*- coding: utf-8 -*-
"""tests/sector_rotation/test_sentiment_providers.py —— 回测情绪 provider 契约与 as-of 复核

覆盖：
- Proxy provider：分数范围、可手算截面标准化+宽度合成、sentiment_source 标注、
  修改"未来"价格不影响历史输出（无未来函数）
- LLM provider：注入 mock 离线可复现、as-of 过滤未来新闻
- Fixture provider：report_usable=False（禁入报告路径）
- sector_daily_return 等权口径与缺失降级
"""

from types import SimpleNamespace

import pytest

from src.sector_rotation.backtest.sentiment_providers import (
    FrozenFixturesSentimentProvider,
    KlineStore,
    LLMReplaySentimentProvider,
    ProxyBreadthSentimentProvider,
    sector_daily_return,
)

DAYS = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08",
        "2026-01-09", "2026-01-12"]


def _mk_store(a_prices, b_prices):
    return KlineStore.from_dict({
        "A": dict(zip(DAYS, a_prices)),
        "B": dict(zip(DAYS, b_prices)),
    })


SECTORS_STUB = {"alpha": SimpleNamespace(tickers=("A", "B"))}


class TestKlineStore:
    def test_common_dates_and_bounds(self):
        store = _mk_store([100] * 6, [100] * 6)
        # common_dates 为闭区间 [start, end]
        assert store.common_dates("2026-01-06", "2026-01-09") == DAYS[1:5]

    def test_missing_code_excluded(self):
        store = KlineStore.from_dict({"A": {"2026-01-05": 100.0}})
        assert not store.has("B")


class TestSectorDailyReturn:
    def test_equal_weight_hand_computed(self):
        # A: 100->110 (+10%), B: 200->190 (-5%) -> 等权均值 = +2.5%
        store = _mk_store([100, 110], [200, 190])
        r = sector_daily_return(store, ("A", "B"), "2026-01-06", "2026-01-05")
        assert r == pytest.approx(0.025)

    def test_missing_ticker_skipped(self):
        # B 无当日价格 -> 仅 A 计: +10%
        store = KlineStore.from_dict({"A": {"2026-01-05": 100.0, "2026-01-06": 110.0},
                                       "B": {"2026-01-05": 200.0}})
        r = sector_daily_return(store, ("A", "B"), "2026-01-06", "2026-01-05")
        assert r == pytest.approx(0.10)

    def test_all_missing_returns_none(self):
        store = KlineStore.from_dict({"A": {"2026-01-05": 100.0}})
        assert sector_daily_return(store, ("A",), "2026-01-06", "2026-01-05") is None


class TestProxyProvider:
    def test_hand_computed_scores(self):
        # A 每日上涨、B 每日下跌（return_window=2, breadth_window=1）
        # T=DAYS[2] 的 as-of 为 DAYS[1]：
        #   A: r=102/100-1>0 上涨 -> rank_score=+1, breadth_up=True
        #   B: r=98/100-1<0  下跌 -> rank_score=-1, breadth_up=False
        #   breadth = 2*(1/2)-1 = 0
        #   单票分：A=0.5*1+0.5*0=0.5, B=0.5*(-1)+0.5*0=-0.5
        #   板块分 = 等权均值 = 0.0
        store = _mk_store([100, 101, 102, 103, 104, 105],
                          [100, 99, 98, 97, 96, 95])
        provider = ProxyBreadthSentimentProvider(store, DAYS, return_window=2,
                                                 breadth_window=1, sectors=SECTORS_STUB)
        state = provider.get_sector_states(DAYS[2])["alpha"]
        assert state.sentiment_score == pytest.approx(0.0, abs=1e-4)
        assert state.stock_count == 2
        # 板块波动率 = std([0.5,-0.5], ddof=1) = sqrt(0.5) ≈ 0.7071
        assert state.volatility == pytest.approx(0.7071, abs=1e-3)
        # 置信度全链路可复核：0.5 * sqrt(2/6) * max(0.2, 1-0.5*0.7071) ≈ 0.1866
        assert state.confidence == pytest.approx(0.1866, abs=2e-3)

    def test_score_bounds(self):
        # 单边行情下板块分数仍必须被裁剪在 [-1,1]
        store = _mk_store([100, 110, 121, 133, 146, 160],
                          [100, 110, 121, 133, 146, 160])
        provider = ProxyBreadthSentimentProvider(store, DAYS, return_window=2,
                                                 breadth_window=1, sectors=SECTORS_STUB)
        for day in DAYS[1:]:
            s = provider.get_sector_states(day)["alpha"].sentiment_score
            assert -1.0 <= s <= 1.0

    def test_no_lookahead_change_past_scores(self):
        """修改日历最后一天的价格，此前所有日的输出必须逐位一致（严格 as-of）。"""
        base_prices = [100, 101, 102, 103, 104, 105]
        past_moved = [100, 101, 102, 103, 104, 999]  # "未来"价格剧烈变动
        p1 = ProxyBreadthSentimentProvider(_mk_store(base_prices, [100] * 6), DAYS,
                                          return_window=2, sectors=SECTORS_STUB)
        p2 = ProxyBreadthSentimentProvider(_mk_store(past_moved, [100] * 6), DAYS,
                                          return_window=2, sectors=SECTORS_STUB)
        for day in DAYS[:-1]:
            s1 = p1.get_sector_states(day)["alpha"]
            s2 = p2.get_sector_states(day)["alpha"]
            assert s1.sentiment_score == pytest.approx(s2.sentiment_score)
            assert s1.confidence == pytest.approx(s2.confidence)

    def test_provenance_label(self):
        store = _mk_store([100] * 6, [100] * 6)
        provider = ProxyBreadthSentimentProvider(store, DAYS, sectors=SECTORS_STUB)
        assert provider.sentiment_source == "price_breadth_proxy"
        assert provider.report_usable is False
        d = provider.to_dict()
        assert d["sentiment_source"] == "price_breadth_proxy"

    def test_first_day_neutral(self):
        # 日历首日无 T-1 数据 -> 必须中性（score 0, confidence 0）而非外推
        store = _mk_store([100] * 6, [100] * 6)
        provider = ProxyBreadthSentimentProvider(store, DAYS, sectors=SECTORS_STUB)
        s = provider.get_sector_states(DAYS[0])["alpha"]
        assert s.sentiment_score == 0.0 and s.confidence == 0.0

    def test_unknown_date_raises(self):
        store = _mk_store([100] * 6, [100] * 6)
        provider = ProxyBreadthSentimentProvider(store, DAYS, sectors=SECTORS_STUB)
        with pytest.raises(KeyError):
            provider.get_sector_states("2099-01-01")


class TestLLMReplayProvider:
    class _MockAnalyzer:
        def __init__(self, score):
            self._score = score

        def analyze_batch(self, texts):
            return [SimpleNamespace(score=self._score) for _ in texts]

    def _provider(self, news_map, calendar, lookback=7):
        def loader(code, trade_date):
            return list(news_map.get(code, []))
        return LLMReplaySentimentProvider(
            news_loader=loader, analyzer=self._MockAnalyzer(0.9),
            calendar=calendar, lookback_days=lookback, sectors=SECTORS_STUB,
        )

    def test_replays_news_within_window(self):
        news_map = {
            "A": [{"title": "利好", "content": "业绩大增", "publish_time": "2026-01-05 09:00"},
                  {"title": "B侧无关", "content": "", "publish_time": "2026-01-05 10:00"}],
            "B": [{"title": "利好", "content": "签大单", "publish_time": "2026-01-04 08:00"}],
        }
        provider = self._provider(news_map, DAYS)
        # T=DAYS[1] -> asof=DAYS[0]：仅 2026-01-05 及以前的新闻参与
        state = provider.get_sector_states(DAYS[1])["alpha"]
        assert state.stock_count == 2
        assert state.sentiment_score == pytest.approx(0.9, abs=1e-6)

    def test_future_news_excluded(self):
        # 新闻发布时间晚于 as-of（DAYS[0]）必须被过滤 -> 0 样本 -> 中性状态
        news_map = {"A": [{"title": "t", "content": "c", "publish_time": "2026-01-08 00:00"}],
                    "B": []}
        provider = self._provider(news_map, DAYS)
        state = provider.get_sector_states(DAYS[1])["alpha"]
        assert state.stock_count == 0
        assert state.sentiment_score == 0.0

    def test_provenance_label(self):
        provider = self._provider({}, DAYS)
        assert provider.sentiment_source == "llm_news_replay"
        assert provider.report_usable is True

    def test_first_day_neutral(self):
        provider = self._provider({"A": [{"title": "t", "content": "c",
                                          "publish_time": "2026-01-05"}]}, DAYS)
        s = provider.get_sector_states(DAYS[0])["alpha"]
        assert s.stock_count == 0 and s.sentiment_score == 0.0


class TestFrozenFixturesProvider:
    def test_lookup_and_label(self):
        states = {"2026-01-05": {"alpha": {"sector": "alpha", "sentiment_score": 0.3}}}
        provider = FrozenFixturesSentimentProvider(states)
        got = provider.get_sector_states("2026-01-05")["alpha"]
        assert got.sentiment_score == pytest.approx(0.3)
        assert provider.report_usable is False
        assert provider.sentiment_source == "fixture_only"
        with pytest.raises(KeyError):
            provider.get_sector_states("2026-01-06")
