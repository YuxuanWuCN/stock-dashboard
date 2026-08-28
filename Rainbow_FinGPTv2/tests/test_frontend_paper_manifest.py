"""v2.13 模拟盘动态清单前端契约测试。

- app.js 必须按 manifest.json 动态加载全部组合
- 卡片/曲线/表格必须支持任意数量组合
- 必须保留基准线标记
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


def test_js_loads_manifest():
    app = _read("docs/assets/app.js")
    assert "data/paper/manifest.json" in app
    assert "function loadPaperSeries" in app
    assert "state.paperSeries" in app


def test_js_dynamic_render():
    app = _read("docs/assets/app.js")
    assert "renderPaperCurve(portfolios)" in app
    assert "portfolios.map(function (s)" in app
    assert "thead.innerHTML" in app


def test_js_benchmark_flag():
    app = _read("docs/assets/app.js")
    assert "is_benchmark" in app
    assert "isBenchmark" in app


def test_html_has_dynamic_table():
    html = _read("docs/index.html")
    assert 'id="paper-compare-tbody"' in html
    assert 'id="paper-cards"' in html
    assert 'id="paper-curve"' in html