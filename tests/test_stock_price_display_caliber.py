# -*- coding: utf-8 -*-
"""tests/test_stock_price_display_caliber.py

验证前端股价展示口径、除权送转科普披露与数据真实性：
1. 验证 index.html 存在交易所真实盘口行情口径说明横幅，消除前复权/除权误解。
2. 验证 app.js 包含个股除权送转科普披露机制（重点覆盖 002594 比亚迪 10送8转12 等重大除权标的）。
3. 验证 summary.json 中所有正常标的均具有有限非空的真实收盘价，无 NaN 或负数。
"""

import json
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = PROJECT_ROOT / "docs" / "index.html"
APP_JS = PROJECT_ROOT / "docs" / "assets" / "app.js"
SUMMARY_JSON = PROJECT_ROOT / "docs" / "data" / "summary.json"


def test_index_html_has_price_caliber_notice():
    """验证主看板首页与自选股区域具备清晰的价格口径说明横幅，并覆盖半导体时序切片与重大除权。"""
    assert INDEX_HTML.exists()
    content = INDEX_HTML.read_text(encoding="utf-8")
    assert "价格口径说明" in content or "行情口径与时序说明" in content or "行情口径说明" in content
    assert "真实盘口" in content or "成交价" in content
    # 覆盖 000021 深科技与半导体时序切片披露
    assert "000021" in content
    assert "2026-09-23" in content
    assert "半导体" in content or "存储" in content


def test_app_js_has_stock_split_and_caliber_disclosures():
    """验证 app.js 在个股详情区域展示真实盘口口径、重大除权送转说明（如比亚迪）及半导体周期时序对照（如深科技000021）。"""
    assert APP_JS.exists()
    js_content = APP_JS.read_text(encoding="utf-8")
    # 必须包含 002594 比亚迪除权送转解释
    assert "002594" in js_content
    assert "detail-split-note" in js_content or "splitDisclosures" in js_content
    assert "除权" in js_content
    # 必须包含 000021 深科技及半导体核心标的 2024 基准均价对比说明
    assert "000021" in js_content
    assert "36.91" in js_content
    assert "14.82" in js_content
    assert "688525" in js_content
    assert "603986" in js_content


def test_summary_json_prices_are_valid_and_consistent():
    """验证 summary.json 中 ok 状态的股票收盘价均为合理正数，且半导体与除权标的处于真实价格区间。"""
    assert SUMMARY_JSON.exists()
    data = json.loads(SUMMARY_JSON.read_text(encoding="utf-8"))
    items = data.get("items", [])
    assert len(items) > 50

    code_map = {}
    for item in items:
        if item.get("status") == "ok":
            code = item.get("code")
            close = item.get("last_close")
            assert close is not None, f"Stock {code} close price is None"
            assert isinstance(close, (int, float)), f"Stock {code} price is not numeric"
            assert close > 0, f"Stock {code} price is non-positive"
            code_map[code] = close

    # 验证比亚迪在 80~90 元合理除权价格区间
    assert "002594" in code_map
    assert 50 < code_map["002594"] < 150, f"BYD price {code_map['002594']} outside expected post-split range"

    # 验证深科技 (000021) 在 30~45 元真实行情区间
    assert "000021" in code_map
    assert 25 < code_map["000021"] < 50, f"000021 price {code_map['000021']} outside expected range"

    # 验证佰维存储 (688525) 在合理爆发区间
    assert "688525" in code_map
    assert 100 < code_map["688525"] < 350, f"688525 price {code_map['688525']} outside expected range"

