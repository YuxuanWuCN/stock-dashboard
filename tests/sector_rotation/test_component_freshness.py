# -*- coding: utf-8 -*-
"""tests/sector_rotation/test_component_freshness.py —— 轮动日历与成分股新鲜度回归。

## 事故背景（2026-11-02）

`docs/data/sector_rotation/latest_rotation.json` 的 `trade_date` 连续多日停在
`2026-08-27`，而监控报告全绿。两层根因：

1. `daily_job.run_daily` 用 `KlineStore.common_dates`（所有成分股的**日期交集**）
   当交易日历。黄金板块 6 只成分股（600547/601899/600489/002155/000975/600988）
   不在 `watchlist.csv` 里，K 线停在 2026-08-27，于是整个日历被拖回 8-27。
   剔除 gold 板块后交集是 2026-11-02，确认无误。
2. `monitoring.check_freshness` 拿**同一份被截断的日历**做基准，
   `calendar_last == rotation_trade_date`，lag 恒为 0，告警永远不触发。

本文件钉住修复后的语义：
- 每日决策用 `market_dates`（容忍个别标的缺失），不再被陈旧成分股绑架；
- `common_dates` 的回测语义保持不变（回测确实要求全成分股对齐）；
- 成分股陈旧由 `check_component_freshness` 独立暴露，且 severity 随滞后升级。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.sector_rotation.backtest.sentiment_providers import KlineStore
from src.sector_rotation.monitoring import (
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    check_component_freshness,
)

# 市场日历：6 个连续交易日
FRESH = ["2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02",
         "2026-11-03", "2026-11-04"]
STALE = ["2026-10-28", "2026-10-29", "2026-10-30"]  # 停在 10-30，滞后 2 日


def _store_with(stale_codes: tuple[str, ...] = (), missing_codes: tuple[str, ...] = ()):
    """构造 3 只成分股的 store：A/B 新鲜，C 按参数设为陈旧或缺失。"""
    raw: dict[str, dict[str, float]] = {
        "A": {d: 100.0 for d in FRESH},
        "B": {d: 100.0 for d in FRESH},
        "C": {d: 100.0 for d in FRESH},
    }
    for code in stale_codes:
        raw[code] = {d: 100.0 for d in STALE}
    for code in missing_codes:
        raw.pop(code, None)
    return KlineStore.from_dict(raw)


SECTORS_STUB = {"alpha": SimpleNamespace(tickers=("A", "B", "C"))}


class TestMarketDatesToleratesStaleComponents:
    """每日决策的交易日历不能被个别陈旧成分股拖回旧日期。"""

    def test_common_dates_is_dragged_back_by_one_stale_ticker(self):
        """反向守卫：钉住事故机理——交集语义确实会被单只陈旧标的截断。"""

        store = _store_with(stale_codes=("C",))
        # 回测语义：所有标的都有价格的日期 -> 只剩到 10-30
        assert store.common_dates("2000-01-01", "2099-12-31") == STALE

    def test_market_dates_keeps_the_real_latest_trading_day(self):
        """市场日历只看覆盖度，单只陈旧不影响最近交易日。"""

        store = _store_with(stale_codes=("C",))
        calendar = store.market_dates("2000-01-01", "2099-12-31")
        assert calendar == FRESH
        assert calendar[-1] == "2026-11-04"

    def test_market_dates_drops_days_below_coverage(self):
        """覆盖率不足的日期不进日历：3 只里只有 1 只有 11-03/11-04，低于 50%。"""

        store = KlineStore.from_dict({
            "A": {d: 100.0 for d in FRESH},
            "B": {d: 100.0 for d in FRESH[:3]},
            "C": {d: 100.0 for d in FRESH[:3]},
        })
        calendar = store.market_dates("2000-01-01", "2099-12-31")
        # 11-03/11-04 只有 A 有 -> 1/3 < 0.5，被剔除
        assert calendar == FRESH[:3]

    def test_market_dates_empty_store_returns_empty(self):
        assert KlineStore.from_dict({}).market_dates("2000-01-01", "2099-12-31") == []

    def test_market_dates_respects_bounds(self):
        store = _store_with()
        assert store.market_dates("2026-10-29", "2026-11-03") == FRESH[1:5]

    def test_last_date_reports_per_ticker_staleness(self):
        store = _store_with(stale_codes=("C",))
        assert store.last_date("A") == "2026-11-04"
        assert store.last_date("C") == "2026-10-30"
        assert store.last_date("ZZZ") is None


class TestComponentFreshnessAlerts:
    """成分股陈旧必须独立暴露，不能因为基准日历退化了就消失。"""

    def test_all_fresh_produces_no_alert(self):
        store = _store_with()
        assert check_component_freshness(store, FRESH, sectors=SECTORS_STUB) == []

    def test_stale_component_is_reported_as_warning(self):
        store = _store_with(stale_codes=("C",))
        alerts = check_component_freshness(store, FRESH, sectors=SECTORS_STUB)

        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.check == "freshness.components"
        assert alert.severity == SEVERITY_WARNING
        assert alert.detail["sector"] == "alpha"
        # C 停在 10-30，市场日历末日 11-04，中间还有 11-02/11-03 -> 滞后 3 日
        assert alert.detail["worst_lag"] == 3
        assert [s["code"] for s in alert.detail["stale"]] == ["C"]
        assert "2026-10-30" in alert.message

    def test_large_lag_escalates_to_critical(self):
        """黄金板块那种「停在两个多月前」的滞后必须升级为 critical。"""

        long_stale = KlineStore.from_dict({
            "A": {d: 100.0 for d in FRESH},
            "B": {d: 100.0 for d in FRESH},
            "C": {d: 100.0 for d in FRESH[:1]},  # 停在 10-28，滞后 5 日
        })
        alerts = check_component_freshness(long_stale, FRESH, sectors=SECTORS_STUB,
                                           critical_lag=5)
        assert alerts[0].severity == SEVERITY_CRITICAL

    def test_missing_kline_file_is_reported(self):
        """完全没有 K 线文件的成分股也要报，不能静默当作「没有数据」。"""

        store = _store_with(missing_codes=("C",))
        alerts = check_component_freshness(store, FRESH, sectors=SECTORS_STUB)

        assert len(alerts) == 1
        assert alerts[0].detail["missing"] == ["C"]
        assert alerts[0].detail["stale"] == []
        assert "缺失 K 线 1 只" in alerts[0].message

    def test_date_outside_calendar_is_treated_as_stale(self):
        """末日不在市场日历内（停牌/缺口）按陈旧处理，而不是当作新鲜。"""

        odd = KlineStore.from_dict({
            "A": {d: 100.0 for d in FRESH},
            "B": {d: 100.0 for d in FRESH},
            "C": {"2026-10-30": 100.0, "2026-12-31": 100.0},  # 末日不在日历内
        })
        alerts = check_component_freshness(odd, FRESH, sectors=SECTORS_STUB)
        assert len(alerts) == 1
        assert alerts[0].detail["stale"][0]["lag"] is None

    def test_empty_calendar_yields_no_alerts(self):
        store = _store_with()
        assert check_component_freshness(store, [], sectors=SECTORS_STUB) == []

    def test_only_affected_sector_is_reported(self):
        """多个板块时，只报有问题的那个，不制造噪音。"""

        sectors = {
            "alpha": SimpleNamespace(tickers=("A", "B")),
            "beta": SimpleNamespace(tickers=("C",)),
        }
        store = _store_with(stale_codes=("C",))
        alerts = check_component_freshness(store, FRESH, sectors=sectors)

        assert len(alerts) == 1
        assert alerts[0].detail["sector"] == "beta"


class TestDailyJobUsesMarketCalendar:
    """daily_job 必须用 market_dates；否则真实数据下决策日会被钉死。"""

    def test_run_daily_advances_past_stale_component(self, tmp_path, monkeypatch):
        """复刻真实事故形态：green 新鲜、gold 陈旧，决策日必须前进到最新交易日。

        用 monkeypatch 换掉模块级 ``SECTORS``，因为 run_daily 内部通过
        ``get_all_tickers()`` / provider 默认值读取全局板块表。
        """
        from src.sector_rotation import daily_job
        from src.sector_rotation import config as sr_config

        sectors = {
            "green": SimpleNamespace(tickers=("A", "B")),
            "gold": SimpleNamespace(tickers=("C",)),
        }
        monkeypatch.setattr(sr_config, "SECTORS", sectors)
        monkeypatch.setattr(
            sr_config, "get_all_tickers", lambda: ["A", "B", "C"]
        )

        store = KlineStore.from_dict({
            "A": {d: 100.0 + i for i, d in enumerate(FRESH)},
            "B": {d: 100.0 + i for i, d in enumerate(FRESH)},
            "C": {d: 100.0 for d in STALE},
        })

        payload = daily_job.run_daily(
            sentiment_mode="proxy",
            out_dir=tmp_path,
            store=store,
            history_rows=[],
        )

        assert payload["trade_date"] == "2026-11-04"
        assert payload["requested_trade_date"] == "2026-11-04"


def test_monitoring_uses_market_calendar_so_lag_is_visible(tmp_path):
    """端到端守卫：监控基准若退化成交集，lag 恒为 0，告警永远不触发。"""

    from src.sector_rotation import monitoring

    kline_dir = tmp_path / "kline"
    kline_dir.mkdir()
    import json

    for code, days in (("A", FRESH), ("B", FRESH), ("C", STALE)):
        (kline_dir / f"{code}.json").write_text(
            json.dumps({
                "dates": days,
                "kline": [[100.0, 100.0, 100.0, 100.0] for _ in days],
            }),
            encoding="utf-8",
        )

    store = KlineStore.from_dir(kline_dir, ["A", "B", "C"])

    # 交集语义（旧行为）：日历被拖回 10-30，基准末日 == 陈旧末日
    assert store.common_dates("2000-01-01", "2099-12-31")[-1] == "2026-10-30"
    # 市场日历语义（新行为）：基准末日仍是 11-04
    assert store.market_dates("2000-01-01", "2099-12-31")[-1] == "2026-11-04"

    # 用旧基准检查，滞后为 0（这正是事故中监控全绿的原因）
    calendar_old = store.common_dates("2000-01-01", "2099-12-31")
    alerts_old = check_component_freshness(store, calendar_old, sectors=SECTORS_STUB)
    assert all(a.detail.get("worst_lag") in (None, 0) for a in alerts_old), (
        "交集基准下滞后被抹平，这正是需要修复的盲区"
    )

    # 用新基准检查，陈旧成分股被正确暴露
    calendar_new = store.market_dates("2000-01-01", "2099-12-31")
    alerts_new = check_component_freshness(store, calendar_new, sectors=SECTORS_STUB)
    assert len(alerts_new) == 1
    assert alerts_new[0].detail["worst_lag"] == 3
