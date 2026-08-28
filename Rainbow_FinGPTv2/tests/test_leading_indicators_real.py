"""tests/test_leading_indicators_real.py —— 领先指标真实数据抓取（005 融合 US1）单元测试。"""

import src.analysis.leading_indicators as li_mod
from src.analysis.leading_indicators import LeadingIndicatorEngine


def test_fetch_real_success_returns_akshare_source(monkeypatch):
    """真实源返回序列时 data_source=akshare 且拐点正确。"""
    fake_series = [100, 95, 90, 88, 92, 98, 105, 110]  # V 型反转
    monkeypatch.setattr(li_mod, "_fetch_akshare_series_cached", lambda cat: fake_series)
    engine = LeadingIndicatorEngine()
    sig = engine.fetch_real_leading_signal("semiconductor")
    assert sig["data_source"] == "akshare"
    assert sig["momentum_metrics"]["inflection_flag"] == "positive_reversal"
    assert sig["series"] == fake_series


def test_fetch_real_failure_falls_back_to_synthetic(monkeypatch):
    """真实源返回 None 时降级合成。"""
    monkeypatch.setattr(li_mod, "_fetch_akshare_series_cached", lambda cat: None)
    engine = LeadingIndicatorEngine()
    sig = engine.fetch_real_leading_signal("semiconductor")
    assert sig["data_source"] == "synthetic_fallback"
    assert "momentum_metrics" in sig


def test_fetch_general_category_falls_back():
    """无真实源映射的类别（general）直接降级合成。"""
    engine = LeadingIndicatorEngine()
    sig = engine.fetch_real_leading_signal("general")
    assert sig["data_source"] == "synthetic_fallback"


def test_fetch_akshare_series_unknown_category_returns_none():
    assert li_mod._fetch_akshare_series("general") is None


def test_fetch_akshare_series_returns_none_without_akshare(monkeypatch):
    """akshare 导入失败时返回 None 不抛异常。"""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "akshare":
            raise ImportError("no akshare")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert li_mod._fetch_akshare_series("semiconductor") is None
