# -*- coding: utf-8 -*-
"""A/B 前端静态契约测试：可复现零构建、双模视觉、埋点字段与离线兜底。

与 tests/test_wealth_terminal_contract.py 同一思路：不启动浏览器，用源码断言固化
「页面必须提供的 id / 文案 / 可访问性 / 埋点契约」，防止后续改动悄悄破坏 #13 的采集。
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

PAGE = Path(__file__).resolve().parents[1] / "ab_webapp" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    assert PAGE.is_file(), f"缺少 A/B 前端：{PAGE}"
    return PAGE.read_text(encoding="utf-8")


def test_single_file_zero_build(html):
    assert PAGE.stat().st_size > 20_000
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert 'lang="zh-CN"' in html
    assert 'name="viewport"' in html
    assert "<script src=" not in html
    assert "<link rel=\"stylesheet\"" not in html
    assert "jsdelivr" not in html
    for forbidden in ("webpack", "vite", "process.env", "import("):
        assert forbidden not in html.lower() if forbidden.islower() else forbidden not in html


def test_wealth_design_tokens_are_reused(html):
    for token in (
        "--bg: #F6F8FA",
        "--card-radius: 16px",
        "--gold: #C59B27",
        "--blue: #1677FF",
        "--green: #10B981",
        "--benchmark: #94A3B8",
        "font-variant-numeric: tabular-nums",
        "line-height: 1.6",
        "clamp(28px",
    ):
        assert token in html, f"缺少设计 Token：{token}"
    assert "0 4px 20px rgba(0, 0, 0, 0.04)" in html


def test_accessibility_and_elderly_friendly_sizes(html):
    assert ":focus-visible" in html
    assert "prefers-reduced-motion: reduce" in html
    assert "min-height: 44px" in html
    assert "min-height: 56px" in html
    assert "aria-live" in html
    assert 'role="progressbar"' in html
    assert 'aria-valuenow="100"' in html
    assert "font-size: clamp(32px" in html  # 实验组大字
    for breakpoint in ("max-width: 393px", "max-width: 600px", "max-width: 900px",
                       "min-width: 1440px", "min-width: 1920px"):
        assert breakpoint in html, f"缺少响应式断点：{breakpoint}"


def test_control_arm_is_volatile_red_green(html):
    for marker in ('id="arm-a-panel"', 'id="a-trend-svg"', 'id="a-float-loss"',
                   'id="a-balance"', 'id="a-day-change"', "高频行情", "账面浮亏",
                   "红色为下跌", "3 秒刷新"):
        assert marker in html, f"对照组 A 缺少：{marker}"
    assert "stroke: var(--danger)" in html
    assert "--danger: #D92D20" in html
    assert "candlestick" not in html.lower()
    assert "kline" not in html.lower()


def test_treatment_arm_is_anti_anxiety(html):
    for marker in ('id="arm-b-panel"', 'id="b-thermometer-text"', 'id="b-safe-floor"',
                   'id="b-locked-progress"', 'id="b-locked-fill"', 'id="b-ratchet-note"',
                   "市场温度计", "单向棘轮", "只升不降", "养老安全垫", "--warm-bg"):
        assert marker in html, f"实验组 B 缺少：{marker}"
    assert "适老" in html


def test_entry_flow_requires_consent_and_age_group(html):
    for group in ('data-age-group="youth"', 'data-age-group="elder"',
                  'data-age-group="unspecified"'):
        assert group in html
    assert 'id="consent-checkbox"' in html
    assert 'id="start-btn"' in html
    assert "disabled" in html
    for cohort in ('value="campus"', 'value="community"', 'value="online"', 'value="lab"'):
        assert cohort in html
    assert "身份证号" in html  # 仅出现在“不采集”的知情同意说明中


def test_scenarios_match_logger_contract(html):
    for scenario in ('data-scenario="0"', 'data-scenario="-10"', 'data-scenario="-20"'):
        assert scenario in html
    assert '"0": { dd: 0' in html or '"0":{' in html
    assert '"-10": { dd: -10' in html
    assert '"-20": { dd: -20' in html
    assert 'id="decision-hold"' in html
    assert 'id="decision-redeem"' in html
    assert "panic_redeem_clicked" in html
    assert "decision_latency_ms" in html


def test_quiz_has_three_items_with_fixed_answer_key(html):
    for index in (1, 2, 3):
        assert f'data-quiz-index="{index}"' in html
    assert 'id="quiz-submit"' in html
    assert 'id="quiz-score"' in html
    assert 'var QUIZ_KEY = { 1: "B", 2: "A", 3: "B" }' in html
    assert "comprehension_score" in html


def test_offline_first_queue_and_exports(html):
    for marker in ('"rfof_ab_queue_v1"', '"rfof_ab_session_v1"', 'localStorage',
                   'flushQueue', 'id="export-json"', 'id="export-csv"',
                   'id="retry-sync"', 'id="queue-count"', "download("):
        assert marker in html, f"离线能力缺少：{marker}"
    assert "/api/events" in html
    assert "/api/session" in html
    assert "/api/survey" in html
    assert "event_uuid" in html
    assert "window.location.protocol === \"file:\"" in html


def test_participant_blinding_and_reviewer_mode(html):
    assert "评审模式" in html
    assert 'params.get("role")' in html
    assert 'id="reviewer-toggle"' in html
    assert "实验臂已隐藏" in html
    assert "组间设计" in html


def test_no_direct_identifier_inputs(html):
    inputs = re.findall(r"<input[^>]*>", html)
    types = {re.search(r'type="([^"]+)"', tag).group(1) for tag in inputs if 'type="' in tag}
    assert types <= {"checkbox", "radio"}, f"页面出现可疑输入控件类型：{types}"
    for forbidden in ('name="real_name"', 'name="phone"', "name=\"id_card\"", 'name="email"'):
        assert forbidden not in html
    assert "id_card" not in html.lower()


def test_no_dangerous_dom_sinks(html):
    assert "document.write(" not in html
    assert "eval(" not in html
    assert "new Function(" not in html


# ---------------------------------------------------------------------------
# 跨语言一致性：前端纯 JS SHA-256 必须与 Python 分组算法逐位一致
# ---------------------------------------------------------------------------
def _extract_block(html: str, marker: str) -> str:
    start = html.index(marker)
    brace = html.index("{", start)
    depth = 0
    for position in range(brace, len(html)):
        char = html[position]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return html[start:position + 1]
    raise AssertionError(f"无法闭合抽取：{marker}")


def _extract_iife(html: str, marker: str) -> str:
    """抽取 ``var NAME = (function () { ... })();`` 形式的完整 IIFE 源码。"""
    start = html.index(marker)
    end = html.index("})();", start) + len("})();")
    return html[start:end]


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_node(script: str) -> str:
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.skipif(not _node_available(), reason="未安装 node，跳过跨语言一致性校验")
def test_js_sha256_matches_hashlib(html):
    import hashlib

    sha_block = _extract_iife(html, "var SHA256 = (function () {")
    vectors = ["", "x", "0123456789abcdef0123456789abcdef", "养老安全垫"]
    script = sha_block + "\n" + "\n".join(
        f"console.log(SHA256({json.dumps(vector)}));" for vector in vectors
    )
    got = _run_node(script).split()
    expected = [hashlib.sha256(vector.encode("utf-8")).hexdigest() for vector in vectors]
    assert got == expected


@pytest.mark.skipif(not _node_available(), reason="未安装 node，跳过跨语言一致性校验")
def test_js_ab_group_matches_python_dao(html):
    from dao import assign_ab_group

    salt_block = re.search(r'var SALT = "([^"]+)";', html)
    assert salt_block is not None and salt_block.group(1) == "rfof-ab-v1:"
    sha_block = _extract_iife(html, "var SHA256 = (function () {")
    assign_block = _extract_block(html, "function assignAbGroup(sessionId) {")
    sessions = [f"{index:032x}" for index in range(40)] + ["a" * 32, "0123456789abcdef" * 2]
    script = (
        f'var SALT = "{salt_block.group(1)}";\n'
        + sha_block + "\n" + assign_block + "\n"
        + "console.log(JSON.stringify(SESSIONS.map(assignAbGroup)));".replace(
            "SESSIONS", json.dumps(sessions)
        )
    )
    got = json.loads(_run_node(script))
    assert got == [assign_ab_group(session) for session in sessions]

def test_demo_scenario_arithmetic_is_consistent(html):
    """界面演示数字必须自洽（本金 300k → 峰值 330k → 棘轮 85% → −10%/−20%）。

    这条断言防止“为了好看随手改数字”把答辩口径改出内部矛盾：
    峰值 × 0.85 = 安全垫；−10% 仍在安全垫之上；−20% 由防守层补足到安全垫。
    """
    block = re.search(r"var SCENARIO = \{(.*?)\n    \};", html, re.S)
    assert block is not None, "未找到 SCENARIO 配置"
    rows = {}
    for key, body in re.findall(r'"(-?\d+)": \{([^}]*)\}', block.group(1)):
        values = {}
        for name, number in re.findall(r"(\w+): (-?\d+)", body):
            values[name] = int(number)
        rows[int(key)] = values
    assert set(rows) == {0, -10, -20}
    peak = 330000
    floor = round(peak * 0.85)
    assert all(config["peak"] == peak for config in rows.values())
    assert all(config["floor"] == floor for config in rows.values())
    assert rows[0]["balance"] == peak
    assert rows[-10]["balance"] == round(peak * 0.9)
    assert rows[-20]["rawBalance"] == round(peak * 0.8)
    assert rows[-20]["balance"] == floor, "−20% 情景应展示防守层补足后的安全垫"
    floors = [rows[key]["floor"] for key in (0, -10, -20)]
    assert floors == sorted(floors), "安全垫必须单调不减（单向棘轮）"
    assert "本金 ¥300,000" in html and "账户 ¥330,000" in html
