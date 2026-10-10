# tests/integration/test_multi_asset_synthesis.py
"""
Rainbow-FinGPT v4.0 全域多资产投研中台端到端集成测试
End-to-End Tests for Multi-Asset Web Dashboards, Navigation Links, and OpenAPI v4 Endpoints.
"""

from pathlib import Path
import json
import pytest
from flask import Flask
from src.multi_asset_api import bp_v4

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCS_DIR = REPO_ROOT / "docs"


def test_web_dashboards_presence_and_cross_navigation():
    """验证三大全域核心交互看板存在且具备全局多资产置顶互通导航"""
    dashboards = [
        "index_wealth.html",     # 银发普惠理财门面
        "index.html",            # A 股学术计量看板
        "index_commodity.html"   # 郑商所期现套保看板
    ]
    
    for d in dashboards:
        path = DOCS_DIR / d
        assert path.exists(), f"Missing dashboard: {d}"
        content = path.read_text(encoding="utf-8")
        
        # 验证置顶中台导航栏与跨看板跳转链接
        assert "Rainbow-FinGPT v4.0" in content, f"{d} 缺少 v4.0 全域中台导航标头"
        assert "index_wealth.html" in content, f"{d} 缺少指向银发普惠看板的导航"
        assert "index.html" in content, f"{d} 缺少指向 A 股学术看板的导航"
        assert "index_commodity.html" in content, f"{d} 缺少指向郑商所套保看板的导航"


def test_offline_data_snapshots_integrity():
    """验证离线同构学术快照文件存在且 JSON 结构合法"""
    temp_file = DOCS_DIR / "data" / "strategy" / "market_temperature.json"
    commodity_file = DOCS_DIR / "data" / "commodity" / "ranking_cross_asset.json"
    
    assert temp_file.exists(), f"Missing {temp_file}"
    assert commodity_file.exists(), f"Missing {commodity_file}"
    
    with open(temp_file, "r", encoding="utf-8") as f:
        t_data = json.load(f)
        assert "temperature" in t_data or "date" in t_data
        
    with open(commodity_file, "r", encoding="utf-8") as f:
        c_data = json.load(f)
        assert "items" in c_data or "ranking" in c_data
        assert "updated_at" in c_data or "as_of_date" in c_data


def test_openapi_v4_routes_contract():
    """验证 /api/v4 蓝图端点返回数据契约符合规范"""
    app = Flask(__name__)
    app.register_blueprint(bp_v4)
    client = app.test_client()
    
    # 1. /api/v4/overview
    resp_overview = client.get("/api/v4/overview")
    assert resp_overview.status_code == 200
    d_over = resp_overview.get_json()
    assert "market_temperature" in d_over
    assert "EQUITY" in d_over["active_domains"]
    assert "COMMODITY" in d_over["active_domains"]
    
    # 2. /api/v4/equity/ranking
    resp_eq = client.get("/api/v4/equity/ranking")
    assert resp_eq.status_code == 200
    d_eq = resp_eq.get_json()
    assert d_eq["count"] > 0
    assert "stocks" in d_eq
    
    # 3. /api/v4/commodity/tes
    resp_tes = client.get("/api/v4/commodity/tes")
    assert resp_tes.status_code == 200
    d_tes = resp_tes.get_json()
    assert len(d_tes["items"]) > 0
    
    # 4. /api/v4/intelligence/chokepoint
    resp_cp = client.get("/api/v4/intelligence/chokepoint")
    assert resp_cp.status_code == 200
    d_cp = resp_cp.get_json()
    assert len(d_cp["nodes"]) >= 3
    assert len(d_cp["edges"]) >= 2
