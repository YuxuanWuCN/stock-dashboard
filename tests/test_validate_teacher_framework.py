"""validate_teacher_framework.py 单元测试。

验证（对应 specs/001-teacher-framework-validation/spec.md 的 FR-001~FR-012）：
- 翻倍触发扫描：滚动 60 日低点口径，唯一触发点 2026-07-24（+100.8%）
- 三组操作对照：清仓/减至1/3/持有 的窗口收益与回撤
- 涨停事件聚簇：连板不重复计数（14 次涨停 → 6 簇）
- 回调统计：发生率、等待天数中位数、幅度中位数
- 四因子风险评分：0-100 范围、对连续跌停的预警检验
- 数据加载：K线列序 [开,收,低,高]、市场温度
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import validate_teacher_framework as vtf  # noqa: E402

KLINE = ROOT / "docs/data/kline/001258.json"
TEMP = ROOT / "docs/data/strategy/market_temperature.json"


# ------------------------------------------------------------
# 数据加载
# ------------------------------------------------------------

def test_load_kline_shape():
    df = vtf.load_kline(KLINE)
    assert len(df) >= 267  # 前复权数据会随除权调整，允许根数小幅变化
    assert list(df.columns) == ["date", "open", "close", "low", "high", "volume"]
    assert df["date"].is_monotonic_increasing
    # 列序 [开,收,低,高] 校验：low <= min(open,close) 且 high >= max(open,close)
    assert (df["low"] <= df[["open", "close"]].min(axis=1) + 1e-9).all()
    assert (df["high"] >= df[["open", "close"]].max(axis=1) - 1e-9).all()
    # 数据文件会随每日抓取刷新，断言"覆盖截止日"而非"恰好等于"（避免日期漂移）
    assert vtf.LAST_DATE in df["date"].dt.strftime("%Y-%m-%d").tolist()


def test_load_market_temperature():
    temp = vtf.load_market_temperature(TEMP)
    assert isinstance(temp, dict)
    assert "temperature" in temp
    assert 0 <= temp["temperature"] <= 100


def test_load_market_temperature_missing():
    assert vtf.load_market_temperature(ROOT / "nonexistent.json") == {}


# ------------------------------------------------------------
# Story 1: 翻倍事实核验
# ------------------------------------------------------------

def test_verify_doubling():
    df = vtf.load_kline(KLINE)
    d = vtf.verify_doubling(df)
    # 连板口径：07-16 收盘 → 07-28 盘中高，涨幅应约 +109%（前复权调整可小幅变化）
    assert d["peak_high"] == pytest.approx(15.73, abs=0.02)
    assert d["pullback_pct"] > 100
    # 滚动低点口径：07-13 低 6.49 → 07-24 收 13.03
    assert d["low_close"] == pytest.approx(6.49, abs=0.02)
    assert d["double_close"] == pytest.approx(13.03, abs=0.02)
    assert d["low_pct"] == pytest.approx(100.8, abs=1.0)


# ------------------------------------------------------------
# Story 2: 翻倍触发 + 三组操作
# ------------------------------------------------------------

def test_scan_double_triggers_unique():
    df = vtf.load_kline(KLINE)
    triggers = vtf.scan_double_triggers(df)
    # 状态机保证：同一起点不重复触发（基准点只前进不后退）
    assert len(triggers) == 1
    t = triggers[0]
    assert t["trigger_date"] == "2026-07-24"
    assert t["base_date"] == "2026-07-13"
    assert 100 < t["gain_pct"] < 102


def test_three_actions_windows():
    df = vtf.load_kline(KLINE)
    triggers = vtf.scan_double_triggers(df)
    ar = vtf.run_three_actions(df, triggers[0])
    assert ar["entry_date"] == "2026-07-27"
    assert ar["entry_price"] == pytest.approx(13.02, abs=0.02)
    for w in [5, 10, 20]:
        assert w in ar["windows"]
        r = ar["windows"][w]
        # 清仓 0%：A 组触发次日全部卖出后持币
        assert r["ret_a_pct"] == 0.0
        # 持有组最大回撤最大：对照组（不动）扛了连续跌停
        assert r["mdd_c_pct"] <= r["mdd_b_pct"]
    # 20 日窗口（未走满 20 天时截断至截止日）：冲高反弹，持有组收益高于减仓组
    r20 = ar["windows"][20]
    assert 0 < r20["ret_b_pct"] < r20["ret_c_pct"]
    assert r20["mdd_c_pct"] <= r20["mdd_b_pct"]


# ------------------------------------------------------------
# Story 3: 涨停聚簇 + 回调统计
# ------------------------------------------------------------

def test_limit_up_clustering():
    df = vtf.load_kline(KLINE)
    # 冻结到数据截止日（工具不变量：严禁未来数据泄漏），避免每日刷新导致断言漂移
    cutoff = df[df["date"].dt.strftime("%Y-%m-%d") <= vtf.LAST_DATE]
    events = vtf.list_limit_up_events(cutoff)
    # 14 次涨停聚簇为 6 簇
    assert len(events) == 6
    # 7 月连板簇（07-16~07-27）应聚为 1 簇且 n_limit=7
    jul = [e for e in events if e["date"].startswith("2026-07")]
    assert len(jul) == 1
    assert jul[0]["n_limit"] == 7


def test_pullback_stats():
    df = vtf.load_kline(KLINE)
    # 冻结到数据截止日（工具不变量：严禁未来数据泄漏），避免每日刷新导致断言漂移
    cutoff = df[df["date"].dt.strftime("%Y-%m-%d") <= vtf.LAST_DATE]
    events = vtf.list_limit_up_events(cutoff)
    stats = vtf.pullback_stats(cutoff, events)
    assert stats["n_events"] == 6
    assert stats["n_pullback"] >= 5
    assert stats["rate_pct"] >= 80
    assert stats["median_wait_days"] is not None
    assert stats["median_pullback_pct"] is not None
    # 08-11 后窗口未走完的簇不算回调（进行中，未验证）
    aug = [e for e in stats["events"] if e["date"].startswith("2026-08")]
    assert all(not e["pullback_occurred"] for e in aug)


# ------------------------------------------------------------
# Story 3.5: 数据截止日夹断（防未来数据泄漏 / 防口径漂移）
# ------------------------------------------------------------

def test_stats_are_clamped_to_last_date_even_if_file_grows():
    """行情文件每日追加新K线时，统计口径必须固定在 LAST_DATE，不得随之漂移。

    实测背景：`docs/data/kline/001258.json` 已由 252 根（2026-08-13）长到 268 根（2026-09-04）。
    未夹断时涨停聚簇 6 → 7、触发后 20 日收益 +17.28% → −3.46%；夹断后两者都回到文档化数值。
    """
    df = vtf.load_kline(KLINE)
    dates = df["date"].dt.strftime("%Y-%m-%d")
    assert (dates > vtf.LAST_DATE).any(), "夹具前提：文件已含截止日之后的行情"
    clamped = vtf.clamp_to_last_date(df)

    assert clamped["date"].max().strftime("%Y-%m-%d") == vtf.LAST_DATE
    assert len(clamped) < len(df)
    # 统计函数的输出必须与"只看夹断后数据"完全一致
    assert len(vtf.list_limit_up_events(df)) == len(vtf.list_limit_up_events(clamped))
    trigger = vtf.scan_double_triggers(df)[0]
    assert vtf.run_three_actions(df, trigger)["windows"][20]["ret_c_pct"] == pytest.approx(
        vtf.run_three_actions(clamped, trigger)["windows"][20]["ret_c_pct"], abs=1e-12
    )
    assert vtf.report_lookahead_drift(df) > 0


def test_clamp_rejects_data_without_the_declared_cutoff():
    """反向守卫：数据未覆盖 LAST_DATE 时必须报错，而不是悄悄用漂移数据出统计。"""
    df = vtf.load_kline(KLINE)
    truncated = df[df["date"].dt.strftime("%Y-%m-%d") < vtf.LAST_DATE].reset_index(drop=True)

    with pytest.raises(ValueError, match="数据截止日"):
        vtf.clamp_to_last_date(truncated)
    with pytest.raises(ValueError, match="为空"):
        vtf.clamp_to_last_date(df.iloc[0:0])


# ------------------------------------------------------------
# Story 4: 四因子风险评分 + 预警
# ------------------------------------------------------------

def test_risk_score_range():
    df = vtf.load_kline(KLINE)
    risk = vtf.compute_risk_score(df)
    assert risk["risk_score"].min() >= 0
    assert risk["risk_score"].max() <= 100
    assert {"fund_score", "emo_score", "size_industry_score"} <= set(risk.columns)


def test_warning_check():
    df = vtf.load_kline(KLINE)
    risk = vtf.compute_risk_score(df)
    w = vtf.warning_check(risk)
    assert w["all_mean"] is not None
    assert w["pre_crash_5d_mean"] is not None
    # 连续跌停前评分应显著高于全样本（预警能力）
    assert w["pre_vs_all_gap"] > 10
    assert len(w["crash_day_scores"]) == 2


# ------------------------------------------------------------
# 边界
# ------------------------------------------------------------

def test_scan_empty_df():
    import pandas as pd
    df = pd.DataFrame({"date": pd.to_datetime([]), "open": [], "close": [],
                       "low": [], "high": [], "volume": []})
    assert vtf.scan_double_triggers(df) == []
