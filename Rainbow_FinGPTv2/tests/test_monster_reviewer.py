"""monster_reviewer.py 单元测试。

验证（对应 specs/002-monster-reviewer/spec.md 的 FR-001~FR-010）：
- 触发筛选规则（10日涨幅/波动率分位/涨停次数）
- 规则降级质疑与收敛结论（LLM 不可用时）
- LLM 响应容错解析（非法 JSON、围栏、字段缺失）
- 两轮对话的 prompt 组装（mock LLM）
- 报告章节渲染（含无候选占位）
- 边界（空候选、调用限额）
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from llm.monster_reviewer import (  # noqa: E402
    Challenge,
    MAX_DAILY_LLM_CALLS,
    MonsterCandidate,
    MonsterReviewer,
    Response,
    ReviewReport,
    Verdict,
    parse_challenges,
    parse_responses,
    parse_verdict,
    render_review_section,
    select_monster_candidates,
    _rule_challenges,
    _rule_verdict,
)


def _cand(**kw):
    defaults = dict(code="001258", name="立新能源", gain_10d_pct=112.0,
                    volatility_5d_pct=8.5, volatility_pctile=99.5,
                    limit_up_5d=7, reasons=["10日涨幅 112.0% 超阈值 30%"])
    defaults.update(kw)
    return MonsterCandidate(**defaults)


# ------------------------------------------------------------
# 触发筛选（FR-001）
# ------------------------------------------------------------

def test_select_candidates_trigger_by_gain():
    ranking = [
        {"code": "A", "name": "甲", "gain_10d": 35.0, "volatility_5d": 2.0, "limit_up_5d": 0},
        {"code": "B", "name": "乙", "gain_10d": 5.0, "volatility_5d": 2.0, "limit_up_5d": 0},
    ]
    cands = select_monster_candidates(ranking, {"A": 50.0, "B": 50.0})
    assert len(cands) == 1
    assert cands[0].code == "A"
    assert "10日涨幅" in cands[0].reasons[0]


def test_select_candidates_trigger_by_volatility():
    ranking = [{"code": "A", "name": "甲", "gain_10d": 5.0, "volatility_5d": 9.0, "limit_up_5d": 0}]
    cands = select_monster_candidates(ranking, {"A": 96.0})
    assert len(cands) == 1
    assert "波动率" in cands[0].reasons[0]


def test_select_candidates_trigger_by_limit_up():
    ranking = [{"code": "A", "name": "甲", "gain_10d": 5.0, "volatility_5d": 2.0, "limit_up_5d": 3}]
    cands = select_monster_candidates(ranking, {"A": 50.0})
    assert len(cands) == 1
    assert "涨停" in cands[0].reasons[0]


def test_select_candidates_none():
    ranking = [{"code": "A", "name": "甲", "gain_10d": 5.0, "volatility_5d": 2.0, "limit_up_5d": 0}]
    assert select_monster_candidates(ranking, {"A": 50.0}) == []


# ------------------------------------------------------------
# 规则降级（FR-005）
# ------------------------------------------------------------

def test_rule_challenges_high_severity():
    c = _cand(gain_10d_pct=112.0, volatility_pctile=99.5)
    ch = _rule_challenges(c)
    assert any(x.severity == "high" for x in ch)
    assert all(x.point for x in ch)


def test_rule_challenges_medium_only():
    c = _cand(gain_10d_pct=35.0, volatility_pctile=96.0, limit_up_5d=0)
    ch = _rule_challenges(c)
    assert all(x.severity in ("medium", "low") for x in ch)


def test_rule_verdict_warning():
    c = _cand()
    ch = [Challenge("x", "y", "high")]
    assert _rule_verdict(c, ch).attention == "warning"


def test_rule_verdict_normal():
    c = _cand(gain_10d_pct=31.0, volatility_pctile=95.0, limit_up_5d=0)
    ch = _rule_challenges(c)
    assert _rule_verdict(c, ch).attention in ("normal", "downgrade")


# ------------------------------------------------------------
# LLM 响应容错解析（FR-006）
# ------------------------------------------------------------

def test_parse_challenges_valid():
    text = '[{"point": "涨幅过大", "evidence": "10日+100%", "severity": "high"}]'
    ch = parse_challenges(text)
    assert len(ch) == 1
    assert ch[0].point == "涨幅过大"
    assert ch[0].severity == "high"


def test_parse_challenges_fenced():
    text = '```json\n[{"point": "波动异常", "evidence": "分位99", "severity": "medium"}]\n```'
    ch = parse_challenges(text)
    assert len(ch) == 1
    assert ch[0].point == "波动异常"


def test_parse_challenges_invalid_json():
    assert parse_challenges("这不是 JSON") == []
    assert parse_challenges("") == []


def test_parse_challenges_extra_text():
    text = '好的，以下是质疑：\n[{"point": "回调风险", "evidence": "涨幅高", "severity": "low"}]'
    ch = parse_challenges(text)
    assert len(ch) == 1
    assert ch[0].point == "回调风险"


def test_parse_challenges_bad_severity_defaults_medium():
    text = '[{"point": "x", "evidence": "y", "severity": "extreme"}]'
    ch = parse_challenges(text)
    assert ch[0].severity == "medium"


def test_parse_responses_valid():
    text = '[{"challenge": "涨幅过大", "stance": "support", "reason": "确实偏高"}]'
    rs = parse_responses(text)
    assert len(rs) == 1
    assert rs[0].stance == "support"


def test_parse_verdict_valid():
    v = parse_verdict('{"attention": "warning", "summary": "风险高"}')
    assert v is not None
    assert v.attention == "warning"


def test_parse_verdict_invalid():
    assert parse_verdict("垃圾") is None


# ------------------------------------------------------------
# 审查主流程（mock LLM）
# ------------------------------------------------------------

class _MockLLM:
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls = []

    def is_available(self):
        return True

    def complete(self, system, user, **kw):
        self.calls.append(user)
        if not self.scripts:
            raise RuntimeError("unexpected call")
        return self.scripts.pop(0)


def test_review_llm_path():
    mock = _MockLLM([
        '[{"point": "涨幅过大", "evidence": "+112%", "severity": "high"}]',
        '[{"challenge": "涨幅过大", "stance": "support", "reason": "数据支持"}]',
        '{"attention": "warning", "summary": "建议警示"}',
    ])
    reviewer = MonsterReviewer(client=mock)
    r = reviewer.review(_cand())
    assert r.mode == "llm"
    assert r.verdict.attention == "warning"
    assert len(r.challenges) == 1
    assert len(r.responses) == 1
    assert r.responses[0].stance == "support"


def test_review_fallback_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr("llm.monster_reviewer.LLM_ENABLED", False)
    reviewer = MonsterReviewer()
    r = reviewer.review(_cand())
    assert r.mode == "rule_fallback"
    assert r.fallback_reason == "llm_unavailable"
    assert all(x.severity in ("high", "medium", "low") for x in r.challenges)


def test_review_fallback_when_llm_output_invalid():
    mock = _MockLLM(["这不是 JSON"])
    reviewer = MonsterReviewer(client=mock)
    r = reviewer.review(_cand())
    # LLM 输出非法 → 降级规则质疑
    assert r.mode == "rule_fallback"
    assert len(r.challenges) >= 1


def test_daily_call_limit():
    mock = _MockLLM([""] * 10)
    reviewer = MonsterReviewer(client=mock, max_daily_calls=2)
    reviewer._llm_available()
    # 3 次审查（每次 3 次调用）会触发限额 → 降级
    reports = [reviewer.review(_cand()) for _ in range(3)]
    assert any(r.mode == "rule_fallback" for r in reports)


# ------------------------------------------------------------
# 报告渲染（FR-007）
# ------------------------------------------------------------

def test_render_section_with_reports():
    c = _cand()
    ch = [Challenge("涨幅过大", "依据", "high")]
    rs = [Response("涨幅过大", "support", "确实")]
    v = Verdict("warning", "建议警示")
    r = ReviewReport("001258", "立新能源", c, ch, rs, v)
    section = render_review_section([r])
    assert "妖股风险审查" in section
    assert "立新能源" in section
    assert "建议警示" in section
    assert "不构成投资建议" in section


def test_render_section_empty():
    section = render_review_section([])
    assert "今日无高波动标的" in section


# ------------------------------------------------------------
# 边界
# ------------------------------------------------------------

def test_review_all_empty():
    reviewer = MonsterReviewer()
    assert reviewer.review_all([]) == []
