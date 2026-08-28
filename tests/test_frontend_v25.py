"""v2.5 前端契约测试：今日可买置顶 + 市场温度条 + 老年友好。

静态检查 docs/index.html 与 docs/assets/app.js 的契约：
- "今日可以关注"区必须位于排行榜之前（置顶）
- 市场温度条必须存在
- 渲染函数必须存在且做空数据保护
- 风险声明与"研究参考"文案必须存在
- 大字号/高对比 CSS 必须存在
"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_project_file(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_buy_today_section_precedes_ranking():
    """'今日可以关注'必须位于排行榜之前（置顶）。"""
    html = _read_project_file("docs/index.html")
    assert html.index('id="buy-today-section"') < html.index("ranking-section")
    assert html.index('id="market-temp-bar"') < html.index("ranking-section")


def test_buy_today_has_research_disclaimer():
    """今日可买必须带研究参考声明（不构成买卖建议）。"""
    html = _read_project_file("docs/index.html")
    assert "研究参考，不构成买卖建议" in html


def test_app_js_loads_strategy_data():
    """app.js 必须并行加载三个 v2.5 数据文件。"""
    app = _read_project_file("docs/assets/app.js")
    assert "data/strategy/selection.json" in app
    assert "data/strategy/hunting_ground.json" in app
    assert "data/strategy/market_temperature.json" in app


def test_app_js_has_render_functions_with_empty_guards():
    """渲染函数存在且对空数据有保护（不抛错）。"""
    app = _read_project_file("docs/assets/app.js")
    assert "function renderMarketTemperature" in app
    assert "function renderBuyToday" in app
    # 空数据保护：无数据时直接 return 保持 hidden
    assert "el.marketTempBar.hidden = false" in app
    assert "el.buyTodaySection.hidden = false" in app
    # 点击卡片选中股票
    assert "selectTrackedStock(code)" in app


def test_buy_today_escapes_user_content():
    """策略名称/原因必须经过 HTML 转义（防注入）。"""
    app = _read_project_file("docs/assets/app.js")
    assert "escapeHtml(item.name)" in app
    assert "escapeHtml(reasonText)" in app


def test_elderly_friendly_css_exists():
    """老年友好样式存在：大字号与高对比。"""
    css = _read_project_file("docs/assets/style.css")
    assert ".buy-today-card-name" in css
    assert "font-size: 22px" in css  # 卡片名称大字号
    assert ".market-temp-value" in css
    assert "font-size: 28px" in css  # 温度大字号
    assert ".buy-today-zone-hot" in css  # 买入区间高对比红底
