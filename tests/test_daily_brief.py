"""v2.10 明日重点关注 AI 总结单元测试。

- 候选池：策略信号优先 + 排行榜补齐
- LLM 可用：DeepSeek 返回合法 JSON → 保存 deepseek_api 元数据
- LLM 不可用 / 返回垃圾 / 文件缺失 → 模板降级且不抛错
- 前端契约：首页有摘要区、渲染函数与样式
"""

import json

import pytest

import src.strategies.daily_brief as db
from src.strategies.daily_brief import build_candidates, generate_daily_brief

MODEL = "deepseek-v4-flash"


class FakeAdapter:
    """可注入返回文本的假 DeepSeek 适配器。"""

    def __init__(self, raw: str = "", available: bool = True, reason: str = ""):
        self._raw = raw
        self._available = available
        self._reason = reason

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def backend(self) -> str:
        return "deepseek"

    @property
    def model(self) -> str:
        return MODEL

    @property
    def unavailable_reason(self) -> str:
        return self._reason

    def complete(self, system_prompt, user_prompt, max_tokens=None, temperature=0.3):
        return self._raw


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _selection_with_signal(code="600519", name="贵州茅台"):
    return {
        "results": {
            "MorningStarStrategy": [{
                "code": code,
                "name": name,
                "signals": [{"date": "2026-08-07", "reasons": ["超跌背景", "阳线确认"]}],
            }],
        }
    }


def _hunting_for(code="600519"):
    return {
        "hunting_ground": {
            "MorningStarStrategy": [{
                "code": code,
                "name": "贵州茅台",
                "support_method": "ma20",
                "buy_judge": {
                    "support_price": 1298.0, "current_price": 1309.22,
                    "distance_pct": 0.86, "action": "buy_zone", "in_buy_zone": True,
                },
            }],
        }
    }


def _ranking(n=3):
    return {
        "trade_date": "2026-08-07",
        "items": [
            {
                "rank": i + 1, "code": f"60000{i}", "name": f"股票{i}",
                "type": "stock", "total_score": 60.0 - i,
                "risk": {"label": "低风险"},
                "technical": {"trend": "uptrend"},
                "forecast": {"up_probability_3d_pct": 55.0, "return_3d_pct": 1.0},
                "reasons": [{"title": "中短期趋势向上"}],
            }
            for i in range(n)
        ],
    }


def _temperature():
    return {"temperature": 69.5, "status": "正常", "position_ratio": 0.8}


def _setup_data_dir(tmp_path, with_signal=True, n_rank=3):
    data = tmp_path / "data"
    strategy = data / "strategy"
    analysis = data / "analysis"
    _write_json(strategy / "selection.json", _selection_with_signal() if with_signal else {"results": {}})
    _write_json(strategy / "hunting_ground.json", _hunting_for() if with_signal else {"hunting_ground": {}})
    _write_json(strategy / "market_temperature.json", _temperature())
    _write_json(analysis / "ranking.json", _ranking(n_rank))
    _write_json(data / "summary.json", {"items": []})
    _write_json(data / "meta.json", {"trade_date": "2026-08-07"})
    return data


# ------------------------------------------------------------
# 候选池构建
# ------------------------------------------------------------

def test_candidates_strategy_priority():
    """策略命中排在最前，且带支撑位信息。"""
    selection = _selection_with_signal()
    hunting = _hunting_for()
    ranking = _ranking(3)
    cands = build_candidates(selection, hunting, ranking, None, top_k=3)
    assert cands[0]["code"] == "600519"
    assert cands[0]["source"] == "strategy"
    assert cands[0]["buy_judge"]["action"] == "buy_zone"
    assert cands[0]["signals"] == ["超跌背景", "阳线确认"]


def test_candidates_fill_from_ranking():
    """无策略信号时用排行榜补齐 top_k。"""
    selection = {"results": {}}
    hunting = {"hunting_ground": {}}
    ranking = _ranking(3)
    cands = build_candidates(selection, hunting, ranking, None, top_k=2)
    assert [c["code"] for c in cands] == ["600000", "600001"]
    assert all(c["source"] == "ranking" for c in cands)


def test_candidates_dedup_strategy_and_ranking():
    """排行榜不会重复收录策略已命中的代码。"""
    selection = _selection_with_signal("600000", "股票0")
    hunting = _hunting_for("600000")
    ranking = _ranking(3)
    cands = build_candidates(selection, hunting, ranking, None, top_k=5)
    codes = [c["code"] for c in cands]
    assert codes.count("600000") == 1
    assert len(cands) == 3  # 策略1只 + 排行榜去重后2只


def test_candidates_empty_when_no_data():
    """全部数据缺失时返回空列表（不抛错）。"""
    assert build_candidates(None, None, None, None, top_k=5) == []


# ------------------------------------------------------------
# 模板降级
# ------------------------------------------------------------

def test_template_when_llm_disabled(tmp_path, monkeypatch):
    """--no-llm 或 LLM 不可用时生成模板，mode=template，不抛错。"""
    data = _setup_data_dir(tmp_path)
    out = tmp_path / "brief.json"
    payload = generate_daily_brief(data_dir=str(data), use_llm=False, output_path=str(out))
    assert payload["mode"] == "template"
    assert payload["llm_metadata"] is None
    assert payload["trade_date"] == "2026-08-07"
    assert len(payload["focus"]) == 4  # 策略1只 + 排行榜补齐3只
    assert payload["focus"][0]["code"] == "600519"
    assert "仓位参考 80%" in payload["position_hint"]


def test_template_when_adapter_unavailable(tmp_path, monkeypatch):
    """DeepSeek 不可用时降级模板，不抛错。"""
    monkeypatch.setattr(db, "FinGPTDeepSeekAdapter", lambda: FakeAdapter(available=False, reason="missing_api_key"))
    data = _setup_data_dir(tmp_path)
    out = tmp_path / "brief.json"
    payload = generate_daily_brief(data_dir=str(data), use_llm=True, output_path=str(out))
    assert payload["mode"] == "template"
    assert payload["llm_metadata"] is None


def test_template_when_llm_returns_garbage(tmp_path, monkeypatch):
    """LLM 返回垃圾文本时降级模板，不抛错。"""
    monkeypatch.setattr(db, "FinGPTDeepSeekAdapter", lambda: FakeAdapter(raw="抱歉，我无法生成 JSON"))
    data = _setup_data_dir(tmp_path)
    out = tmp_path / "brief.json"
    payload = generate_daily_brief(data_dir=str(data), use_llm=True, output_path=str(out))
    assert payload["mode"] == "template"


def test_template_when_llm_raises(tmp_path, monkeypatch):
    """LLM 调用抛异常时降级模板，不抛错。"""

    class BoomAdapter(FakeAdapter):
        def complete(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(db, "FinGPTDeepSeekAdapter", lambda: BoomAdapter(raw="x"))
    data = _setup_data_dir(tmp_path)
    out = tmp_path / "brief.json"
    payload = generate_daily_brief(data_dir=str(data), use_llm=True, output_path=str(out))
    assert payload["mode"] == "template"
    assert payload["focus"][0]["code"] == "600519"


def test_missing_files_graceful(tmp_path):
    """数据文件全部缺失时仍生成模板且不报错。"""
    out = tmp_path / "brief.json"
    payload = generate_daily_brief(data_dir=str(tmp_path / "nope"), use_llm=False, output_path=str(out))
    assert payload["mode"] == "template"
    assert payload["focus"] == []
    assert payload["summary"]


# ------------------------------------------------------------
# LLM 成功路径
# ------------------------------------------------------------

def _llm_ok_json():
    return json.dumps({
        "title": "明日重点关注",
        "summary": "明日重点留意白酒与科技方向，策略信号标的回踩支撑位可观察。",
        "focus": [
            {"code": "600519", "name": "贵州茅台", "reason": "今日策略命中，回踩支撑位", "risk": "注意支撑位得失"},
        ],
        "position_hint": "仓位参考 80%，分批关注。",
        "disclaimer": "仅供参考，不构成投资建议。",
    }, ensure_ascii=False)


def test_llm_valid_json_saved(tmp_path, monkeypatch):
    """DeepSeek 返回合法 JSON 时保存 deepseek_api 元数据。"""
    monkeypatch.setattr(db, "FinGPTDeepSeekAdapter", lambda: FakeAdapter(raw=_llm_ok_json()))
    data = _setup_data_dir(tmp_path)
    out = tmp_path / "brief.json"
    payload = generate_daily_brief(data_dir=str(data), use_llm=True, output_path=str(out))
    assert payload["mode"] == "deepseek_api"
    assert payload["llm_metadata"]["model"] == MODEL
    assert payload["llm_metadata"]["mode"] == "deepseek_api"
    assert payload["focus"][0]["code"] == "600519"
    assert "仓位参考 80%" in payload["position_hint"]


def test_llm_json_with_code_fence(tmp_path, monkeypatch):
    """容忍 ```json 代码围栏包裹。"""
    raw = "```json\n" + _llm_ok_json() + "\n```"
    monkeypatch.setattr(db, "FinGPTDeepSeekAdapter", lambda: FakeAdapter(raw=raw))
    data = _setup_data_dir(tmp_path)
    payload = generate_daily_brief(data_dir=str(data), use_llm=True, output_path=str(tmp_path / "b.json"))
    assert payload["mode"] == "deepseek_api"


def test_llm_invented_code_filtered(tmp_path, monkeypatch):
    """LLM 编造候选外的代码会被过滤，且最终仍保存（summary 存在）。"""
    raw = json.dumps({
        "title": "x", "summary": "摘要",
        "focus": [{"code": "999999", "name": "不存在", "reason": "r", "risk": "k"}],
        "position_hint": "p", "disclaimer": "d",
    }, ensure_ascii=False)
    monkeypatch.setattr(db, "FinGPTDeepSeekAdapter", lambda: FakeAdapter(raw=raw))
    data = _setup_data_dir(tmp_path)
    payload = generate_daily_brief(data_dir=str(data), use_llm=True, output_path=str(tmp_path / "b.json"))
    assert payload["mode"] == "deepseek_api"
    assert payload["focus"] == []


# ------------------------------------------------------------
# 前端契约
# ------------------------------------------------------------

def test_frontend_html_has_brief_section():
    html = (db_path("docs/index.html"))
    assert 'id="daily-brief-section"' in html
    assert "明日重点关注" in html


def test_frontend_js_has_brief_render():
    app = db_path("docs/assets/app.js")
    assert "data/strategy/daily_brief.json" in app
    assert "function renderDailyBrief" in app
    assert "el.dailyBriefSection.hidden = false" in app


def test_frontend_css_has_brief_styles():
    css = db_path("docs/assets/style.css")
    assert ".daily-brief-section" in css
    assert ".daily-brief-focus" in css


def db_path(relative):
    from pathlib import Path
    return (Path(__file__).resolve().parents[1] / relative).read_text(encoding="utf-8")
def test_next_trade_date_fields():
    """payload 必须带下一个交易日（跳过周末）：8/7 周五 -> 8/10 周一。"""
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    data = _setup_data_dir(tmp)
    payload = generate_daily_brief(data_dir=str(data), use_llm=False, output_path=str(tmp / "b.json"))
    assert payload["trade_date"] == "2026-08-07"
    assert payload["next_trade_date"] == "2026-08-10"
    assert payload["next_trade_label"] == "周一"


def test_frontend_shows_analysis_and_recommend_dates():
    app = db_path("docs/assets/app.js")
    assert "基于 " in app and "收盘分析" in app
    assert "next_trade_label" in app
    assert "重点关注" in app

def test_candidates_exclude_stale():
    """排行榜中标记 stale（数据过期）的股票不进入候选池。"""
    ranking = {
        "trade_date": "2026-08-07",
        "items": [
            {"rank": 1, "code": "000001", "name": "平安银行", "type": "stock",
             "total_score": 67.6, "risk": {"label": "低风险"},
             "technical": {"trend": "uptrend"},
             "forecast": {"up_probability_3d_pct": 50.0}, "reasons": []},
            {"rank": 2, "code": "00011", "name": "恒生银行", "type": "hk",
             "total_score": 67.2, "risk": {"label": "低风险"},
             "technical": {"trend": "uptrend"},
             "forecast": {"up_probability_3d_pct": 63.3}, "reasons": [],
             "stale": True},
        ],
    }
    cands = build_candidates({"results": {}}, {"hunting_ground": {}}, ranking, None, top_k=5)
    codes = [c["code"] for c in cands]
    assert "000001" in codes
    assert "00011" not in codes
