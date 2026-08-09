"""v2.11 自选股分区前端契约测试。

- 自选股页必须有分区筛选标签（全部/A股/港股/美股/韩股/基金）
- app.js 必须有分区渲染与筛选函数
- 渲染函数必须对空分区有保护
- CSS 必须有分区样式
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


def test_html_has_watchlist_filter():
    html = _read("docs/index.html")
    assert 'id="watchlist-filter"' in html
    for region in ["all", "stock", "hk", "us", "kr", "etf"]:
        assert f'data-region="{region}"' in html


def test_js_has_region_render_logic():
    app = _read("docs/assets/app.js")
    assert "function initWatchlistFilter" in app
    assert "watchlist-section-title" in app
    assert "state.watchlistRegion" in app
    assert "renderStockList();" in app


def test_js_region_labels_cover_hk():
    app = _read("docs/assets/app.js")
    assert "hk: '港股'" in app
    assert "type === 'hk' ? '港股'" in app


def test_js_empty_region_guard():
    app = _read("docs/assets/app.js")
    assert "该分区暂无股票" in app


def test_css_has_filter_styles():
    css = _read("docs/assets/style.css")
    assert ".watchlist-filter" in css
    assert ".watchlist-filter-btn.active" in css
    assert ".watchlist-section-title" in css