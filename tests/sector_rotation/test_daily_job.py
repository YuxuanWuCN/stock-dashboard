# -*- coding: utf-8 -*-
"""tests/sector_rotation/test_daily_job.py —— 每日轮动决策与归档（阶段5 任务 5.1）

覆盖：
- infer_portfolio_state 纯函数可手算复核（AGENTS.md 第3条）
- run_daily 产物 schema、历史追加、情绪来源标注与降级说明
- LLM 复核不可用时不阻断主链路、不推翻量化结论
- /api/sector_rotation 缺数据返回明确状态而非 500
所有外部请求均被隔离（注入合成 K 线 + 新闻夹具 + mock 分析器），离线可复现。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.sector_rotation import daily_job
from src.sector_rotation.backtest.sentiment_providers import KlineStore
from src.sector_rotation.config import DEFENSIVE_SECTOR, SECTORS, get_all_tickers
from src.sector_rotation.daily_job import (
    LATEST_NAME,
    HISTORY_NAME,
    append_history,
    build_provider,
    infer_portfolio_state,
    load_history,
    run_daily,
)


# ============================================================================
# 夹具
# ============================================================================

def _trading_dates(n: int, start: str = "2026-03-02") -> list[str]:
    """从 start 起生成 n 个工作日（跳过周末）作为合成交易日历。"""
    from datetime import date, timedelta

    d = date.fromisoformat(start)
    out: list[str] = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


@pytest.fixture
def calendar() -> list[str]:
    return _trading_dates(30)


@pytest.fixture
def store(calendar: list[str]) -> KlineStore:
    """合成 K 线：每个板块整体漂移不同（storage 涨、green 平、gold 跌），
    板块内个股按代码序号有小幅分化，使代理截面分数可复现。"""
    sector_drift = {"green": 0.000, "storage": 0.004, "gold": -0.003}
    raw: dict[str, dict[str, float]] = {}
    for sector_id, cfg in SECTORS.items():
        for idx, code in enumerate(cfg.tickers):
            drift = sector_drift[sector_id] + idx * 0.0004
            prices: dict[str, float] = {}
            p = 100.0
            for day in calendar:
                p = p * (1.0 + drift)
                prices[day] = round(p, 4)
            raw[code] = prices
    return KlineStore.from_dict(raw)


@pytest.fixture
def news_file(tmp_path: Path) -> Path:
    """含新闻的夹具文件（覆盖全部成分股，发布于倒数第二个交易日）。"""
    asof = _trading_dates(30)[-2]
    payload = {
        code: [{"title": f"{code} 高景气利好", "content": "业绩超预期", "publish_time": asof}]
        for code in get_all_tickers()
    }
    path = tmp_path / "news.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def empty_news_file(tmp_path: Path) -> Path:
    path = tmp_path / "news_empty.json"
    path.write_text("{}", encoding="utf-8")
    return path


class _StubAnalyzer:
    """mock 情绪分析器：恒定正分，避免外部 LLM 请求。"""

    def analyze_batch(self, texts):
        from types import SimpleNamespace

        return [SimpleNamespace(score=0.7, source="llm") for _ in texts]


# ============================================================================
# 1. infer_portfolio_state —— 纯函数手算复核
# ============================================================================

def test_infer_portfolio_state_first_run():
    state = infer_portfolio_state([], "2026-04-01")
    assert state["current_sector"] == DEFENSIVE_SECTOR
    assert state["holding_days"] >= 5
    assert state["monthly_rotations"] == 0
    assert state["days_since_last_rotation"] >= 7


def test_infer_portfolio_state_holding_days_and_since_rotation():
    history = [
        {"trade_date": "2026-04-01", "holding_sector": "gold", "should_rotate": False},
        {"trade_date": "2026-04-02", "holding_sector": "gold", "should_rotate": True,
         "target_sector": "storage"},
        {"trade_date": "2026-04-03", "holding_sector": "storage", "should_rotate": False},
        {"trade_date": "2026-04-07", "holding_sector": "storage", "should_rotate": False},
    ]
    state = infer_portfolio_state(history, "2026-04-08")
    # 末行无轮动 -> 持仓沿用 storage；storage 连续 3 行 -> 持仓天数 3
    assert state["current_sector"] == "storage"
    assert state["holding_days"] == 3
    # 最近一次轮动在 idx=1，其后 2 行 + 当日 = 3
    assert state["days_since_last_rotation"] == 3
    # 2026-04 内只有 1 次 should_rotate
    assert state["monthly_rotations"] == 1


def test_infer_portfolio_state_no_rotation_uses_permissive_cooldown():
    history = [
        {"trade_date": "2026-05-0" + str(i), "holding_sector": "green", "should_rotate": False}
        for i in range(1, 6)
    ]
    state = infer_portfolio_state(history, "2026-05-06")
    assert state["current_sector"] == "green"
    assert state["days_since_last_rotation"] >= 7
    assert state["monthly_rotations"] == 0


# ============================================================================
# 2. run_daily —— 产物 schema 与数据诚实性
# ============================================================================

def test_run_daily_proxy_writes_artifacts(store, calendar, tmp_path):
    out_dir = tmp_path / "sector_rotation"
    payload = run_daily(
        sentiment_mode="proxy", out_dir=out_dir, store=store,
        history_rows=[],
    )
    assert payload["trade_date"] == calendar[-1]
    assert payload["sentiment_source"] == "price_breadth_proxy"
    assert payload["report_usable"] is False
    # 未通过 S2 覆盖门槛前恒为 False（前端卡片据此标注"仅作决策参考"）
    assert payload["strategy_validated"] is False
    assert set(payload["sectors"]) == set(SECTORS)
    assert payload["decision"]["current_sector"] == DEFENSIVE_SECTOR
    assert payload["audit"]["portfolio_state_used"]["holding_days"] >= 5

    latest = out_dir / LATEST_NAME
    assert latest.exists()
    on_disk = json.loads(latest.read_text(encoding="utf-8"))
    assert on_disk["generated_at"] and on_disk["schema_version"]

    history_row = json.loads((out_dir / HISTORY_NAME).read_text(encoding="utf-8").strip())
    assert history_row["trade_date"] == calendar[-1]
    assert history_row["sentiment_source"] == "price_breadth_proxy"
    assert set(history_row["sector_scores"]) == set(SECTORS)


def test_run_daily_auto_downgrades_to_proxy_when_news_missing(
    store, calendar, tmp_path, empty_news_file
):
    payload = run_daily(
        sentiment_mode="auto", news_fixture=empty_news_file, out_dir=tmp_path,
        store=store, history_rows=[],
    )
    assert payload["sentiment_source"] == "price_breadth_proxy"
    assert any("降级" in note for note in payload["notes"])
    assert payload["report_usable"] is False


def test_run_daily_llm_mode_with_fixture_and_stub_analyzer(
    store, calendar, tmp_path, news_file
):
    payload = run_daily(
        sentiment_mode="llm", news_fixture=news_file, analyzer=_StubAnalyzer(),
        out_dir=tmp_path, store=store, history_rows=[],
    )
    assert payload["sentiment_source"] == "llm_news_replay"
    assert payload["report_usable"] is True
    # 全部板块由 stub 给出一致正分 -> 无下沉、不触发轮动
    assert payload["decision"]["should_rotate"] is False


def test_run_daily_history_append_and_reread(store, calendar, tmp_path):
    out_dir = tmp_path / "rot"
    run_daily(sentiment_mode="proxy", out_dir=out_dir, store=store, history_rows=[])
    run_daily(sentiment_mode="proxy", out_dir=out_dir, store=store,
              history_rows=load_history(out_dir / HISTORY_NAME))
    rows = load_history(out_dir / HISTORY_NAME)
    assert len(rows) == 2  # 追加而非覆盖
    state = infer_portfolio_state(rows, calendar[-1])
    assert state["holding_days"] == 2


def test_load_history_skips_corrupted_lines(tmp_path):
    path = tmp_path / HISTORY_NAME
    path.write_text('{"trade_date": "2026-04-01"}\nnot-json\n\n{"trade_date": "2026-04-02"}\n',
                    encoding="utf-8")
    rows = load_history(path)
    assert [r["trade_date"] for r in rows] == ["2026-04-01", "2026-04-02"]


def test_append_history_creates_parent_dir(tmp_path):
    path = tmp_path / "nested" / HISTORY_NAME
    append_history({"trade_date": "2026-04-01"}, path)
    assert path.exists()


# ============================================================================
# 3. LLM 复核不可用 —— 不阻断主链路、不推翻量化结论
# ============================================================================

def test_run_daily_advisor_unavailable_preserves_quant(store, calendar, tmp_path):
    payload = run_daily(
        sentiment_mode="proxy", out_dir=tmp_path / "adv", store=store,
        history_rows=[], use_advisor=True,
    )
    validation = payload["llm_validation"]
    assert validation is not None
    # 未注入 llm_client 的 advisor 必然降级 -> 标记 unavailable
    assert validation["status"] == "unavailable"
    assert payload["decision"]["should_rotate"] is False
    # 未注入 llm_client 的 advisor 会记录一条降级审计（success=False + 降级原因）
    audit = payload["audit"]["advisor_audit"]
    assert isinstance(audit, dict), "advisor 审计必须落盘，禁止静默吞掉降级"
    assert audit["success"] is False
    assert audit["fallback_reason"]


def test_build_provider_rejects_unknown_mode(store, calendar):
    with pytest.raises(ValueError):
        build_provider("bogus", store, calendar)


# ============================================================================
# 4. /api/sector_rotation —— 缺数据不 500
# ============================================================================

def _server_app():
    pytest.importorskip("flask")
    from src import server

    return server


def test_api_sector_rotation_missing_file_returns_200(tmp_path, monkeypatch):
    server = _server_app()
    monkeypatch.setattr(server, "_SECTOR_ROTATION_DIR", str(tmp_path / "nowhere"))
    resp = server.app.test_client().get("/api/sector_rotation")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "missing"
    assert body["data"] is None


def test_api_sector_rotation_serves_payload(tmp_path, monkeypatch, store, calendar):
    server = _server_app()
    out_dir = tmp_path / "rot"
    run_daily(sentiment_mode="proxy", out_dir=out_dir, store=store, history_rows=[])
    monkeypatch.setattr(server, "_SECTOR_ROTATION_DIR", str(out_dir))
    resp = server.app.test_client().get("/api/sector_rotation")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] in ("ok", "stale")
    assert body["sentiment_source"] == "price_breadth_proxy"
    assert body["strategy_validated"] is False
    assert body["data"]["trade_date"] == calendar[-1]


def test_api_sector_rotation_corrupt_file_returns_error_status(tmp_path, monkeypatch):
    server = _server_app()
    out_dir = tmp_path / "rot"
    out_dir.mkdir(parents=True)
    (out_dir / LATEST_NAME).write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(server, "_SECTOR_ROTATION_DIR", str(out_dir))
    resp = server.app.test_client().get("/api/sector_rotation")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "error"


def test_weekdays_between_helper_matches_manual_count():
    server = _server_app()
    from datetime import date

    # 2026-04-06(周一) -> 2026-04-10(周五)：中间工作日 周二/三/四/五 = 4
    assert server._weekdays_between(date(2026, 4, 6), date(2026, 4, 10)) == 4
    assert server._weekdays_between(date(2026, 4, 10), date(2026, 4, 6)) == 0
    assert server._weekdays_between(date(2026, 4, 10), date(2026, 4, 10)) == 0


def test_run_daily_requires_non_empty_calendar(tmp_path):
    empty_store = KlineStore.from_dict({"688525": {}})
    with pytest.raises(ValueError):
        run_daily(sentiment_mode="proxy", out_dir=tmp_path, store=empty_store,
                  history_rows=[])


def test_run_daily_uses_last_calendar_day_for_non_trading_date(store, calendar, tmp_path):
    payload = run_daily(
        trade_date="2099-12-25",  # 不在日历内 -> 回落到最近交易日
        sentiment_mode="proxy", out_dir=tmp_path / "fallback", store=store,
        history_rows=[],
    )
    assert payload["trade_date"] == calendar[-1]
    assert payload["requested_trade_date"] == "2099-12-25"


def test_daily_job_module_exposes_default_paths():
    assert daily_job.OUT_DIR.parts[-3:] == ("docs", "data", "sector_rotation")
    assert Path(daily_job.KLINE_DIR).name == "kline"
