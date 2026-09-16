"""018 前端专业化重构静态契约测试：双主题一致性 / 金融数字排版 / 响应式断点。

本文件把 spec 018 中此前只写在文档里的要求固化为可执行断言。
全部为静态源码契约，不依赖浏览器渲染。

覆盖：
- 首屏主题引导必须先于样式表（防 FOUC），且容忍存储不可用
- 主题存储读写必须兜底，异常不得中断 DOMContentLoaded 后续逻辑
- 主题切换控件的可访问性状态与文案节点类名必须与真实标记一致
- 主题切换必须覆盖全部图表实例，且不得残留指向不存在实例的死引用
- 金融数据表粘性表头、等宽数字、缺失值占位与 token 化配色
- 响应式权威断点（393px / 1920px）
"""

import re
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]

PAGES = ["docs/index.html", "docs/portfolio.html"]
THEME_SCRIPTS = ["docs/assets/app.js", "docs/assets/portfolio.js"]


def _read(relative_path: str) -> str:
    """Read a UTF-8 frontend source file from the project root."""
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def _function_block(source: str, function_name: str, next_name: str) -> str:
    """Return source between two anchors, failing loudly when an anchor is gone."""
    start = source.index(function_name)
    end = source.index(next_name, start)
    return source[start:end]


# --------------------------------------------------------------------------
# 双主题一致性（US1）
# --------------------------------------------------------------------------


@pytest.mark.parametrize("page", PAGES)
def test_head_theme_bootstrap_runs_before_stylesheets(page: str) -> None:
    """引导脚本必须早于样式表，否则会先按默认暗色绘制一帧再被改写（FOUC）。"""
    html = _read(page)
    head = html[: html.index("</head>")]

    assert "fintech-theme" in head
    assert "document.documentElement.setAttribute('data-theme', theme)" in head
    assert head.index("fintech-theme") < head.index('<link rel="stylesheet"')


@pytest.mark.parametrize("page", PAGES)
def test_head_theme_bootstrap_tolerates_unavailable_storage(page: str) -> None:
    """隐私模式或被禁用时 localStorage 会抛错，引导脚本必须兜底而非中断。"""
    head = _read(page)
    head = head[: head.index("</head>")]

    assert "try {" in head
    assert "catch (error)" in head
    # 兜底值必须是可用的默认主题，避免 data-theme 缺失
    assert "var theme = 'dark'" in head


@pytest.mark.parametrize("script", THEME_SCRIPTS)
def test_theme_storage_access_is_guarded(script: str) -> None:
    """主题存储读写必须各自包裹在 try/catch 中，异常不得逃逸。"""
    source = _read(script)

    reader = _function_block(source, "function readStoredTheme", "function writeStoredTheme")
    writer = _function_block(source, "function writeStoredTheme", "function preferredTheme")

    assert "try {" in reader and "catch (error)" in reader
    assert "try {" in writer and "catch (error)" in writer

    # 裸读取必须已被封装函数取代
    assert "localStorage.getItem('fintech-theme')" not in source
    assert "localStorage.setItem('fintech-theme'" not in source


@pytest.mark.parametrize("script", THEME_SCRIPTS)
def test_theme_prefers_dom_state_over_second_guess(script: str) -> None:
    """初始化必须复用引导脚本写好的 data-theme，避免二次闪烁。"""
    source = _read(script)
    init_block = _function_block(source, "function initTheme", "function applyTheme")

    assert "getAttribute('data-theme')" in init_block
    assert "preferredTheme()" in init_block


@pytest.mark.parametrize("page", PAGES)
def test_theme_toggle_exposes_pressed_state(page: str) -> None:
    """切换控件必须暴露当前按压状态与可读名称，供读屏与键盘用户识别。"""
    html = _read(page)
    button = html[html.index('id="theme-toggle-btn"'):]
    button = button[: button.index(">")]

    assert 'aria-pressed=' in button
    assert 'aria-label=' in button


@pytest.mark.parametrize("script", THEME_SCRIPTS)
def test_apply_theme_updates_pressed_state(script: str) -> None:
    """切换后必须同步 aria-pressed，否则读屏状态会与视觉状态不一致。"""
    source = _read(script)
    apply_block = _function_block(source, "function applyTheme", "function getChartThemeTokens") \
        if "function getChartThemeTokens" in source else source[source.index("function applyTheme"):]

    assert "setAttribute('aria-pressed'" in apply_block


def test_theme_label_selector_matches_real_markup() -> None:
    """JS 查找的主题文案类名必须与 HTML 中真实存在的类名一致。

    历史缺陷：JS 查询 `.theme-text`，而标记里是 `.theme-toggle-text`，
    导致主题按钮文案永远不更新。
    """
    markup = _read("docs/index.html") + _read("docs/portfolio.html")

    for script in THEME_SCRIPTS:
        source = _read(script)
        match = re.search(r"querySelector\('\.(theme-[a-z-]+)'\)", source)
        assert match, f"{script} 未找到主题文案节点的类名查询"
        assert f'class="{match.group(1)}"' in markup, (
            f"{script} 查询 .{match.group(1)}，但标记中不存在该类名"
        )


def test_theme_storage_key_shared_across_pages() -> None:
    """两个页面必须使用同一存储键，否则跨页主题会不一致。"""
    for script in THEME_SCRIPTS:
        source = _read(script)
        assert re.search(r"THEME_STORAGE_KEY\s*=\s*'fintech-theme'", source), script


def test_chart_theme_refresh_covers_every_instance() -> None:
    """主题切换必须遍历全部图表实例，否则会出现局部配色残留。"""
    app = _read("docs/assets/app.js")

    registry = _function_block(app, "function themedChartInstances", "function refreshChartThemes")
    assert "state.chart" in registry
    assert "state.indexChart" in registry
    # 已销毁实例必须跳过，避免对空实例 setOption
    assert "isDisposed" in registry

    refresh = _function_block(app, "function refreshChartThemes", "const PAGE_IDS")
    assert "themedChartInstances().forEach" in refresh


def test_no_dead_chart_instance_reference() -> None:
    """`state.paperCurveChart` 从未被赋值，引用它等于该分支永不执行。"""
    app = _read("docs/assets/app.js")
    assert "state.paperCurveChart" not in app


def test_paper_curve_svg_colors_are_token_driven() -> None:
    """模拟盘净值曲线为内联 SVG，颜色须由 CSS Token 驱动才能随主题换肤。"""
    app = _read("docs/assets/app.js")
    assert 'stroke="#e5e7eb"' not in app
    assert 'fill="#6b7280"' not in app
    assert 'class="paper-curve-grid"' in app
    assert 'class="paper-curve-label"' in app

    css = _read("docs/assets/style.css")
    assert ".paper-curve-grid { stroke: var(--border-color)" in css
    assert ".paper-curve-label { fill: var(--text-muted)" in css


# --------------------------------------------------------------------------
# 金融数据排版与表格（US4）
# --------------------------------------------------------------------------


def test_sticky_table_header_is_defined() -> None:
    """粘性表头必须真正声明，而不是只写在注释里。"""
    css = _read("docs/assets/style.css")

    assert ".ranking-table thead th," in css
    assert ".paper-table thead th," in css

    block = css[css.index(".ranking-table thead th,"):]
    block = block[: block.index("}")]

    assert "position: sticky" in block
    assert "top: 0" in block
    # 粘性单元格必须有底色，否则会透出下层滚动内容
    assert "background: var(--surface-hover)" in block


def test_table_wrappers_are_scrollports() -> None:
    """容器需同时具备横滚与纵滚，粘性表头才有生效的 scrollport。"""
    css = _read("docs/assets/style.css")
    block = css[css.index(".ranking-table-wrap,\n.paper-table-wrap"):]
    block = block[: block.index("}")]

    assert "overflow-x: auto" in block
    assert "overflow-y: auto" in block
    assert "max-height" in block


def test_tabular_nums_covers_financial_tables() -> None:
    """排行榜与模拟盘表格的数值列必须使用等宽数字。"""
    css = _read("docs/assets/style.css")

    block = css[css.index(".ranking-table th, .ranking-table td,"):]
    block = block[: block.index("}")]

    assert "font-variant-numeric: tabular-nums" in block


def test_missing_value_placeholder_keeps_column_alignment() -> None:
    """缺失值占位须与等宽数字同宽，避免列对齐抖动。"""
    css = _read("docs/assets/style.css")

    block = css[css.index(".ranking-table td .val-missing,"):]
    block = block[: block.index("}")]

    assert "font-variant-numeric: tabular-nums" in block
    assert "font-family: var(--font-mono)" in block


def test_paper_components_use_design_tokens() -> None:
    """paper-* 组件此前硬编码浅色，暗色主题下会留下白色色块。"""
    css = _read("docs/assets/style.css")

    assert ".paper-card-value { font-weight: 700; color: var(--text-primary)" in css
    assert ".paper-table th { background: var(--surface-hover); color: var(--text-secondary);" in css
    assert ".paper-table-wrap { overflow-x: auto" in css
    assert "background: var(--card-bg);" in css
    assert "background: var(--card-bg-elevated);" in css


# --------------------------------------------------------------------------
# 响应式与多端（plan §2：393px ~ 1920px）
# --------------------------------------------------------------------------


def test_responsive_authority_breakpoints_are_declared() -> None:
    """plan 声明 393px~1920px，两端此前都没有对应断点。"""
    css = _read("docs/assets/style.css")

    assert "Responsive Authority" in css
    assert "@media (max-width: 393px)" in css
    assert "@media (min-width: 1440px)" in css
    assert "@media (min-width: 1920px)" in css


def test_narrow_screen_keeps_elderly_font_contract() -> None:
    """窄屏收紧留白，但不得下调老年友好大字号契约。"""
    css = _read("docs/assets/style.css")
    block = css[css.index("@media (max-width: 393px)"):]
    block = block[: block.index("@media (min-width: 1440px)")]

    assert ".container {" in block
    # 大字号契约值只允许出现在基础层，不允许在窄屏被覆盖
    assert "font-size: 22px" not in block
    assert "font-size: 28px" not in block
