"""v2.13 自选股交互体验契约测试：双击跳转个股分析 + 单击高亮选中 + 键盘无障碍。

测试覆盖：
- HTML 自选股提示文案明确提示双击与回车跳转
- app.js 绑定 dblclick 双击事件并调用 jumpToDetail / selectTrackedStock
- app.js 绑定 keydown 键盘 Enter/Space 事件并支持快捷跳转
- app.js 在自选股卡片上提供直接跳转按钮 (.stock-item-jump-btn)
- app.js 在桌面端单击保持自选股页面停驻并高亮选中与静默预载
- CSS 包含跳转按钮与焦点可见性样式
"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_project_file(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


def test_html_watchlist_tip_mentions_dblclick():
    """自选股头部提示文案必须说明双击或回车跳转个股深度分析。"""
    html = _read_project_file("docs/index.html")
    assert "双击任意股票" in html
    assert "个股深度分析" in html


def test_js_binds_dblclick_to_jump_detail():
    """自选股卡片必须绑定 dblclick 双击事件，且调用 jumpToDetail 跳转个股分析。"""
    app = _read_project_file("docs/assets/app.js")
    assert "card.addEventListener('dblclick'" in app
    assert "jumpToDetail" in app
    assert "selectTrackedStock(item.code, true)" in app


def test_js_binds_keyboard_accessibility():
    """自选股卡片必须具备 tabIndex、role 并支持 Enter/Space 键盘跳转。"""
    app = _read_project_file("docs/assets/app.js")
    assert "card.tabIndex = 0" in app
    assert "card.setAttribute('role', 'button')" in app
    assert "card.addEventListener('keydown'" in app
    assert "e.key === 'Enter'" in app


def test_js_has_direct_jump_button():
    """自选股卡片必须渲染直接跳转按钮，供单触/单击直达。"""
    app = _read_project_file("docs/assets/app.js")
    assert "stock-item-jump-btn" in app
    assert "分析 ➔" in app
    assert "e.target.closest('.stock-item-jump-btn')" in app


def test_js_desktop_click_selects_and_preloads_without_navigation():
    """桌面端卡片单击高亮选中并静默预载数据，不离开自选股页面。"""
    app = _read_project_file("docs/assets/app.js")
    assert "state.suppressDetailNavigation = true" in app
    assert "items.forEach(c => c.classList.toggle('active', c.dataset.code === item.code))" in app


def test_css_has_action_row_and_jump_btn():
    """样式表必须定义操作行与跳转按钮。"""
    css = _read_project_file("docs/assets/style.css")
    assert ".stock-item-action-row" in css
    assert ".stock-item-jump-btn" in css
    assert ".stock-item:focus-visible" in css
