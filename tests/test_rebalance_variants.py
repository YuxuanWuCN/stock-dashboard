"""
策略进化衍生变体调仓与绩效跟踪单元测试
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.rebalance_variants as rv
import tools.paper_portfolio as pp


def test_select_variant_holdings_confidence_filter():
    """测试变体置信度过滤：只保留概率达到阈值的标的。"""
    scan_list = [
        {"code": "A", "name": "A股", "aggressive_score": 90, "up3": 80, "return_20d_pct": 5},
        {"code": "B", "name": "B股", "aggressive_score": 85, "up3": 50, "return_20d_pct": 4},
        {"code": "C", "name": "C股", "aggressive_score": 80, "up3": 65, "return_20d_pct": 3},
    ]
    changes = {"预测置信度阈值": "0.6"}  # >= 60%
    items, cash_pct = rv.select_variant_holdings("aggressive", changes, scan_list, [])
    codes = [it["code"] for it in items]
    assert "A" in codes
    assert "C" in codes
    assert "B" not in codes
    assert cash_pct == 0.0


def test_select_variant_holdings_weight_scheme():
    """测试变体头部加权分配机制。"""
    scan_list = [
        {"code": f"S{i}", "name": f"Stock{i}", "aggressive_score": 100 - i, "up3": 70, "return_20d_pct": 5}
        for i in range(4)
    ]
    changes = {"权重分配方式": "按预测收益排名加权（Top10%权重翻倍）", "top_n": 4}
    items, cash_pct = rv.select_variant_holdings("aggressive", changes, scan_list, [])
    assert len(items) == 4
    # 前两只权重高于后两只
    assert items[0]["pct"] > items[2]["pct"]
    assert items[1]["pct"] > items[3]["pct"]
    assert round(sum(it["pct"] for it in items) + cash_pct, 1) == 100.0


def test_select_variant_holdings_risk_control_tag():
    """测试变体止损止盈风控参数标记。"""
    scan_list = [
        {"code": "A", "name": "A股", "aggressive_score": 90, "up3": 80, "return_20d_pct": 5},
    ]
    changes = {"止损线": "-5%", "止盈线": "+15%"}
    items, _ = rv.select_variant_holdings("aggressive", changes, scan_list, [])
    assert len(items) == 1
    assert "风控[损-5% 盈+15%]" in items[0]["reason"]


def test_paper_portfolio_discovers_variants(tmp_path, monkeypatch):
    """测试 paper_portfolio.py 能正确扫描并识别 strategy_variants 目录中的组合。"""
    data = tmp_path / "data"
    paper_dir = data / "paper"
    var_dir = paper_dir / "strategy_variants"
    var_dir.mkdir(parents=True, exist_ok=True)

    # 写入一个基础组合与一个变体组合
    base_portfolio = {"name": "激进组合", "risk_profile": "aggressive", "items": []}
    var_portfolio = {"name": "置信度增强", "parent_strategy": "aggressive", "items": []}

    (paper_dir / "portfolio_aggressive.json").write_text(json.dumps(base_portfolio), encoding="utf-8")
    (var_dir / "portfolio_aggressive_v1.json").write_text(json.dumps(var_portfolio), encoding="utf-8")

    monkeypatch.setattr(pp, "DATA_DIR", str(data))
    monkeypatch.setattr(pp, "MANIFEST_PATH", str(paper_dir / "manifest.json"))
    monkeypatch.setattr(pp, "BENCHMARK_PATH", str(paper_dir / "benchmark.json"))

    files = pp._portfolio_files()
    assert any("portfolio_aggressive.json" in f for f in files)
    assert any("portfolio_aggressive_v1.json" in f for f in files)

    # 测试 manifest 生成
    assert pp.manifest() == 0
    manifest = json.loads((paper_dir / "manifest.json").read_text(encoding="utf-8"))
    keys = [p["key"] for p in manifest["portfolios"]]
    assert "aggressive" in keys
    assert "aggressive_v1" in keys
    v1_entry = next(p for p in manifest["portfolios"] if p["key"] == "aggressive_v1")
    assert v1_entry["is_variant"] is True
    assert v1_entry["parent_strategy"] == "aggressive"
