"""v2.12 自选股搜索前端契约测试。

- 自选股页必须有搜索输入框与清空按钮
- app.js 必须有搜索初始化与名称/代码过滤逻辑
- 空结果必须有明确提示
- CSS 必须有搜索样式
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


def test_html_has_search_input():
    html = _read("docs/index.html")
    assert 'id="watchlist-search-input"' in html
    assert 'id="watchlist-search-clear"' in html
    assert 'placeholder="搜索名称或代码"' in html


def test_js_has_search_init():
    app = _read("docs/assets/app.js")
    assert "function initWatchlistSearch" in app
    assert "initWatchlistSearch();" in app
    assert "state.watchlistSearch" in app


def test_js_search_filters_by_name_and_code():
    app = _read("docs/assets/app.js")
    # 名称或代码包含即命中，且与分区筛选组合生效
    assert "toLowerCase().includes(searchQ)" in app
    assert "没有找到匹配的股票" in app


def test_js_search_clear_restores():
    app = _read("docs/assets/app.js")
    assert "watchlistSearchClear.addEventListener('click'" in app
    assert "state.watchlistSearch = '';" in app


def test_css_has_search_styles():
    css = _read("docs/assets/style.css")
    assert ".watchlist-search-input" in css
    assert ".watchlist-search-clear" in css