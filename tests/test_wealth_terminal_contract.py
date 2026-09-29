# -*- coding: utf-8 -*-
"""tests/test_wealth_terminal_contract.py

银发普惠养老金融终端 (docs/index_wealth.html) 与互跳集成静态契约测试。
严格固化 R1-R6 与 AC 1 - AC 4 验收标准：
1. 视觉设计系统与主题 Token (米白 #F6F8FA、16px 圆角卡片、大字号等宽数字)
2. 双模切换系统 (普惠理财通 ⇄ 机构量化研报抽屉)
3. 核心资产体检与守护盾牌 (AAA 极高防御、跑赢大盘 +5.82%、最大回撤 < 3.77%)
4. ECharts 平滑累积收益走势图 (双曲线对齐、自愈容灾、通俗卡片)
5. 产业链“避险小卫士”动态消息流 (NALE 拓扑风控平民化)
6. 稳健资产配置环形图与交互问答 (35% 绿电、25% 硬科技、40% 现金)
7. 单文件零构建架构与现有服务零侵入互跳集成 (index.html 无 data-page 污染)
"""

from pathlib import Path
import re
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEALTH_PAGE = PROJECT_ROOT / "docs" / "index_wealth.html"
INDEX_PAGE = PROJECT_ROOT / "docs" / "index.html"


def _read_wealth_html() -> str:
    assert WEALTH_PAGE.exists(), f"Target file does not exist: {WEALTH_PAGE}"
    return WEALTH_PAGE.read_text(encoding="utf-8")


def _read_index_html() -> str:
    assert INDEX_PAGE.exists(), f"Target file does not exist: {INDEX_PAGE}"
    return INDEX_PAGE.read_text(encoding="utf-8")


# ==============================================================================
# AC 1: 界面呈现与视觉质感 (Design System & Anti-Anxiety)
# ==============================================================================

def test_wealth_terminal_file_exists_and_non_empty():
    """验证 docs/index_wealth.html 存在且非空。"""
    assert WEALTH_PAGE.is_file()
    assert WEALTH_PAGE.stat().st_size > 5000, "文件大小过小，可能缺少自包含内容"


def test_wealth_terminal_zero_build_tool_execution():
    """AC 1.1: 验证不依赖任何重型前端打包构建工具，纯 HTML5 + ES6 + ECharts CDN。"""
    html = _read_wealth_html()
    assert "<!DOCTYPE html>" in html
    assert "https://fastly.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js" in html
    assert "webpack" not in html.lower()
    assert "vite" not in html.lower()
    assert "process.env" not in html


def test_wealth_terminal_color_palette_tokens():
    """AC 1.2: 验证温润米白背景、纯白卡片、16px圆角与金色/蓝色/绿色 Token。"""
    html = _read_wealth_html()
    assert "--wealth-bg: #F6F8FA" in html
    assert "--wealth-card-bg: #FFFFFF" in html
    assert "--wealth-card-radius: 16px" in html
    assert "0 4px 20px rgba(0, 0, 0, 0.04)" in html
    assert "--wealth-gold: #C59B27" in html
    assert "--wealth-blue: #1677FF" in html
    assert "--wealth-green: #10B981" in html
    assert "--wealth-benchmark: #94A3B8" in html


def test_wealth_terminal_anti_anxiety_no_candlestick_charts():
    """AC 1.3: 验证去焦虑化设计，严禁密集K线图与高频红绿撞色。"""
    html = _read_wealth_html()
    assert "candlestick" not in html.lower()
    assert "kline" not in html.lower()
    assert "成交量柱状图" not in html


def test_wealth_terminal_typography_large_numbers():
    """AC 1.4: 验证核心净值及收益指标采用超大字号 (28px~36px) 与等宽数字。"""
    html = _read_wealth_html()
    assert "clamp(28px" in html or "font-size: 28px" in html
    assert "tabular-nums" in html
    assert "line-height: 1.6" in html


def test_wealth_terminal_plain_language_badges():
    """AC 1.5: 验证通俗防守徽章完整存在。"""
    html = _read_wealth_html()
    required_badges = [
        "本金安全级",
        "自动避险中",
        "超低波动",
        "AAA 极高防御",
        "跑赢大盘 +5.82%",
        "无需盯盘",
        "自动防御大跌",
        "零未来函数实测",
    ]
    for badge in required_badges:
        assert badge in html, f"缺少必要徽章或说明文案: {badge}"


# ==============================================================================
# AC 2: 双模平滑切换 (Dual Mode Drawer System)
# ==============================================================================

def test_dual_mode_toggle_controls_present():
    """AC 2.1: 验证右上角存在清晰的双模切换控件与抽屉标记。"""
    html = _read_wealth_html()
    assert 'id="mode-toggle-btn"' in html
    assert 'id="institutional-drawer"' in html
    assert 'id="drawer-backdrop"' in html
    assert 'id="drawer-close-btn"' in html
    assert "机构量化研报模式" in html
    assert "普惠理财通" in html


def test_institutional_drawer_academic_quant_data():
    """AC 2.2: 验证机构模式抽屉包含 CSMAR 因子、Soft-Spearman Rank IC 和 NALE 拓扑矩阵。"""
    html = _read_wealth_html()
    # CSMAR 因子与回归
    assert "Fama-MacBeth" in html
    assert "FF_MKT_Daily" in html
    assert "FF_SMB_Daily" in html
    assert "FF_HML_Daily" in html
    assert "sz_rf_rate" in html or "TRD_Nrrate" in html
    # Rank IC 跨周期收敛指标
    assert "Soft-Spearman Rank IC" in html
    assert "0.0206" in html  # T+5
    assert "0.0477" in html  # T+10
    assert "0.0334" in html  # T+15
    assert "+13.5%" in html  # T+15 lift
    assert "390" in html     # 390 次事件
    assert "46.9%" in html   # 命中率
    assert "+6.7%" in html   # 精度提升
    # NALE 非对称拓扑矩阵
    assert "S_NALE = (1 - α)" in html
    assert "长江电力" in html
    assert "三峡能源" in html
    assert "黄金ETF" in html
    assert "深科技" in html
    assert "银华日利" in html
    assert "Placebo" in html
    assert "Z = 2.45" in html


# ==============================================================================
# AC 3: 图表与数据韧性 (Hero Card, Curves, Donut & Self-Healing)
# ==============================================================================

def test_hero_card_metrics():
    """验证置顶 Hero Card 核心指标数据契约。"""
    html = _read_wealth_html()
    assert "AAA 极高防御" in html
    assert "+5.82%" in html
    assert "-5.42%" in html
    assert "< 3.77%" in html or "&lt; 3.77%" in html
    assert "3.45%" in html
    assert "当前市场微澜，防御系统处于最佳防御姿态" in html


def test_echarts_cumulative_returns_two_curves():
    """AC 3.1: 验证 ECharts 累积收益曲线配置包含金线与沪深300灰色虚线。"""
    html = _read_wealth_html()
    assert 'id="wealth-return-chart"' in html
    assert "'#C59B27'" in html or '"#C59B27"' in html
    assert "'#94A3B8'" in html or '"#94A3B8"' in html
    assert "dashed" in html
    assert "defensiveCurve" in html
    assert "benchmarkCurve" in html


def test_risk_parity_donut_chart_proportions():
    """AC 3.3: 验证环形甜甜圈图配比为 35% 绿电、25% 硬科技、40% 现金。"""
    html = _read_wealth_html()
    assert 'id="wealth-donut-chart"' in html
    assert "稳健绿电龙头" in html
    assert "硬科技低波防御" in html
    assert "高流动性现金管理" in html
    assert "35" in html
    assert "25" in html
    assert "40" in html
    # 问答交互卡片
    assert "qa-card-cash" in html
    assert "qa-card-green" in html
    assert "qa-card-tech" in html
    assert "为什么留高达 40% 现金储备？" in html or "为什么留高达 40% 的现金储备？" in html


def test_self_healing_fallback_resilience():
    """AC 3.4: 验证自包含完整静态 fallback 数据集，脱机与 file:// 下零报错。"""
    html = _read_wealth_html()
    assert "WEALTH_FALLBACK_DATA" in html
    assert "window.location.protocol === 'file:'" in html
    assert "renderSvgVectorFallback" in html
    assert "tryHydrateRemoteData" in html


# ==============================================================================
# AC 4: 响应式布局与互跳集成 (Responsive & Cross-Page Integration)
# ==============================================================================

def test_responsive_css_breakpoints():
    """AC 4.1 & 4.2: 验证适配 375px/393px 移动端至 1920px 大屏。"""
    html = _read_wealth_html()
    assert "@media (max-width: 900px)" in html
    assert "@media (max-width: 600px)" in html
    assert "@media (max-width: 393px)" in html
    assert "@media (min-width: 1440px)" in html
    assert "@media (min-width: 1920px)" in html
    assert "overflow-x: hidden" in html


def test_reciprocal_navigation_in_index_html():
    """AC 4.3: 验证 docs/index.html 成功注入 index_wealth.html 互跳入口且未污染 data-page。"""
    index_html = _read_index_html()
    assert 'href="index_wealth.html"' in index_html
    assert "银发普惠" in index_html

    # 严格确保 index_wealth.html 的链接绝对没有携带 data-page（防止 SPA 路由器误劫持）
    matches = re.findall(r'<a[^>]+href=["\']index_wealth\.html["\'][^>]*>', index_html)
    assert len(matches) >= 1, "未在 docs/index.html 找到指向 index_wealth.html 的 <a> 链接"
    for tag in matches:
        assert "data-page" not in tag, f"禁止在外部页面跳转链接上设置 data-page: {tag}"


def test_wealth_html_links_back_to_main_terminal():
    """验证 docs/index_wealth.html 具有返回 index.html 及其他研究页面的互跳链接。"""
    html = _read_wealth_html()
    assert 'href="index.html"' in html
    assert 'href="portfolio.html"' in html
    assert 'href="papers/Rainbow_FinGPT_v2_Paper.html"' in html
