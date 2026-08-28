"""多组合自动调仓的温度驱动联动单元测试。"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.rebalance_all_portfolios as rb


def test_position_ratio_tiers():
    """温度档位 → 仓位系数（与 market_temperature.py 的 STATUS_THRESHOLDS 一致）。"""
    assert rb.position_ratio_for_temperature(100) == 1.0
    assert rb.position_ratio_for_temperature(80) == 1.0
    assert rb.position_ratio_for_temperature(65) == 0.8
    assert rb.position_ratio_for_temperature(50) == 0.5
    assert rb.position_ratio_for_temperature(30) == 0.25
    assert rb.position_ratio_for_temperature(15) == 0.1
    assert rb.position_ratio_for_temperature(0) == 0.0
    assert rb.position_ratio_for_temperature(-5) == 0.0


def test_position_ratio_none_returns_full():
    """温度缺失（None）时兜底为满仓系数 1.0。"""
    assert rb.position_ratio_for_temperature(None) == 1.0


def test_portfolio_settings_linear_scaling():
    """持仓数 = max(min_size, round(max_size × 系数))。"""
    config = {'aggressive': {'enabled': True, 'max_size': 20, 'min_size': 5, 'base_ratio': 1.0}}
    # 温度 100 → 系数 1.0 → 20 只
    en, size, br = rb.portfolio_settings('aggressive', config, 100)
    assert (en, size, br) == (True, 20, 1.0)
    # 温度 65 → 系数 0.8 → 16 只
    en, size, br = rb.portfolio_settings('aggressive', config, 65)
    assert (en, size, br) == (True, 16, 1.0)
    # 温度 50 → 系数 0.5 → 10 只
    en, size, br = rb.portfolio_settings('aggressive', config, 50)
    assert (en, size, br) == (True, 10, 1.0)
    # 温度 15 → 系数 0.1 → 2 只但被 min_size 兜底到 5 只
    en, size, br = rb.portfolio_settings('aggressive', config, 15)
    assert (en, size, br) == (True, 5, 1.0)


def test_portfolio_settings_disabled_keeps_default_size():
    """enabled=False 时保持默认 size（向后兼容，不参与温度缩放）。"""
    config = {'aggressive': {'enabled': False}}
    en, size, br = rb.portfolio_settings('aggressive', config, 50,
                                         defaults={'size': 8, 'base_ratio': 1.0})
    assert (en, size, br) == (False, 8, 1.0)


def test_portfolio_settings_missing_config_disabled():
    """配置缺失该组合时保持默认 size，不启用温度联动。"""
    en, size, br = rb.portfolio_settings('aggressive', {}, 50,
                                         defaults={'size': 10, 'base_ratio': 1.0})
    assert (en, size, br) == (False, 10, 1.0)


def test_allocate_regions_sums_to_total():
    """区域分配总和等于总持仓数，比例与配置一致。"""
    counts = rb.allocate_regions(20, {'stock': 0.3, 'hk': 0.2, 'us': 0.3, 'kr': 0.2})
    assert sum(counts.values()) == 20
    assert counts == {'stock': 6, 'hk': 4, 'us': 6, 'kr': 4}
    counts = rb.allocate_regions(10, {'stock': 0.3, 'hk': 0.2, 'us': 0.3, 'kr': 0.2})
    assert sum(counts.values()) == 10
    assert counts == {'stock': 3, 'hk': 2, 'us': 3, 'kr': 2}
    counts = rb.allocate_regions(5, {'stock': 0.3, 'hk': 0.2, 'us': 0.3, 'kr': 0.2})
    assert sum(counts.values()) == 5


def test_allocate_regions_empty_or_zero():
    """空比例或零权重时不返回分配。"""
    assert rb.allocate_regions(10, {}) == {}
    assert rb.allocate_regions(10, {'stock': 0.0}) == {}


def test_load_market_temperature_missing_falls_back_full(tmp_path, monkeypatch):
    """温度文件缺失时兜底 (None, 1.0)，不阻塞调仓。"""
    monkeypatch.setattr(rb, "MARKET_TEMP_FILE", str(tmp_path / "missing.json"))
    temp, ratio = rb.load_market_temperature()
    assert temp is None and ratio == 1.0


def test_load_market_temperature_corrupt_falls_back_full(tmp_path, monkeypatch):
    """温度文件损坏（非法 JSON）时兜底 (None, 1.0)。"""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(rb, "MARKET_TEMP_FILE", str(bad))
    temp, ratio = rb.load_market_temperature()
    assert temp is None and ratio == 1.0


def test_load_market_temperature_ok(tmp_path, monkeypatch):
    """正常温度文件返回温度与仓位系数。"""
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"temperature": 68.0, "position_ratio": 0.8}), encoding="utf-8")
    monkeypatch.setattr(rb, "MARKET_TEMP_FILE", str(good))
    temp, ratio = rb.load_market_temperature()
    assert temp == 68.0 and ratio == 0.8


def test_rebalance_aggressive_temperature_scaling(tmp_path, monkeypatch):
    """激进组合在温度 50（系数 0.5）时：持仓 10 只、仓位 50%、现金 50%。"""
    scan = [{"code": f"C{i:03d}", "name": f"股票{i}", "aggressive_score": 100 - i,
             "up5": 50, "return_20d_pct": 1.0} for i in range(30)]
    out = tmp_path / "paper" / "portfolio_aggressive.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rb, "DATA_DIR", str(tmp_path))
    config = {'aggressive': {'enabled': True, 'max_size': 20, 'min_size': 5, 'base_ratio': 1.0}}
    rb.rebalance_aggressive(scan, dry_run=False, temperature=50, config=config)
    portfolio = json.loads(out.read_text(encoding="utf-8"))
    assert len(portfolio["items"]) == 10
    assert portfolio["cash_pct"] == 50.0
    # 每只仓位 = 50% / 10 = 5%
    assert abs(portfolio["items"][0]["pct"] - 5.0) < 0.01
    assert portfolio["temperature_ratio"] == 0.5


def test_rebalance_global_region_split(tmp_path, monkeypatch):
    """全球组合温度 100：20 只按 3:2:3:2 分配。"""
    ranking = []
    for i in range(20):
        ranking.append({"code": f"S{i}", "name": f"股{i}", "type": "stock", "score": 100 - i})
    for i in range(20):
        ranking.append({"code": f"H{i}", "name": f"港{i}", "type": "hk", "score": 100 - i})
    for i in range(20):
        ranking.append({"code": f"U{i}", "name": f"美{i}", "type": "us", "score": 100 - i})
    for i in range(15):
        ranking.append({"code": f"K{i}", "name": f"韩{i}", "type": "kr", "score": 100 - i})

    out = tmp_path / "paper" / "portfolio_global.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rb, "DATA_DIR", str(tmp_path))
    config = {'global': {'enabled': True, 'max_size': 20, 'min_size': 5, 'base_ratio': 1.0,
                         'regions': {'stock': 0.3, 'hk': 0.2, 'us': 0.3, 'kr': 0.2}}}
    rb.rebalance_global(ranking, dry_run=False, temperature=100, config=config)
    portfolio = json.loads(out.read_text(encoding="utf-8"))
    assert len(portfolio["items"]) == 20
    codes = [it["code"] for it in portfolio["items"]]
    cn = [c for c in codes if c.startswith("S")]
    hk = [c for c in codes if c.startswith("H")]
    us = [c for c in codes if c.startswith("U")]
    kr = [c for c in codes if c.startswith("K")]
    assert len(cn) == 6 and len(hk) == 4 and len(us) == 6 and len(kr) == 4
