"""tests/test_assert_scanner_false_positives.py —— 锁定弱断言扫描器的两类假阳性回归.

背景：`tools/quality_gate.py verdict` 当前的 `block` 判定由两条 **error 级假阳性**驱动
（`tests/test_nale_alpha_pit_panel.py:43` 与 `tests/test_nale_alpha_selection.py:34`）。
本文件用合成样本钉死修复，并同时守住"真缺陷仍须报出"的正向能力，
防止把扫描器改成"什么都不报"的假绿灯。

夹具写在 `scratch/` 下而非系统临时目录：本仓库历史 bug（BUG-0016~0020）显示
Windows 临时目录 ACL 会让 `tmp_path` 整批 setup 失败，那属于环境噪声而非被测缺陷。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "scratch" / "assert_scanner_fixtures"

import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
import assert_scanner  # noqa: E402

FRAME_EQUAL_ONLY = """
import pandas as pd


def test_frame_equal_only():
    left = pd.DataFrame({"x": [1, 2]})
    right = pd.DataFrame({"x": [1, 2]})
    pd.testing.assert_frame_equal(left, right)
"""

SERIES_EQUAL_ONLY = """
import pandas as pd


def test_series_equal_only():
    left = pd.Series([1, 2], name="x")
    right = pd.Series([1, 2], name="x")
    pd.testing.assert_series_equal(left, right)
"""

ARRAY_EQUAL_CONTROL = """
import numpy as np


def test_array_equal_control():
    left = np.array([1, 2])
    right = np.array([1, 2])
    np.testing.assert_array_equal(left, right)
"""

NESTED_TEST_HELPER = """
def test_outer_uses_local_helper():
    calls = []

    def test_runner(settings):
        calls.append(settings)
        return {"phase": "test"}

    assert test_runner({})["phase"] == "test"
    assert calls == [{}]
"""

GENUINE_NO_ASSERT = """
def test_really_has_no_assertion():
    value = 1 + 1
    print(value)
"""

GENUINE_WEAK_ASSERT = """
import unittest


class TestWeak(unittest.TestCase):
    def test_bare_true(self):
        flag = compute()
        self.assertTrue(flag)

    def compute():
        return True
"""

CLASS_LEVEL_TEST = """
import unittest


class TestCollected(unittest.TestCase):
    def test_class_method_counts(self):
        assert 2 == 1 + 1
"""


def _scan(source: str, name: str) -> list[dict]:
    """把源码写成夹具文件并扫描，返回该文件的 findings。"""
    assert FIXTURE_DIR.is_dir(), "夹具目录须由 fixture 预先创建（本测试不得写到仓库外）"
    path = FIXTURE_DIR / f"test_{name}.py"
    path.write_text(source, encoding="utf-8")
    return [f for f in assert_scanner.scan_file(path) if f["severity"] == "error"]


@pytest.fixture(autouse=True)
def _fixture_dir() -> object:
    if FIXTURE_DIR.exists():
        shutil.rmtree(FIXTURE_DIR)
    FIXTURE_DIR.mkdir(parents=True)
    yield
    shutil.rmtree(FIXTURE_DIR, ignore_errors=True)


# --------------------------------------------------------------------------- 假阳性 1：pandas 断言不可见
def test_pandas_frame_equal_is_counted_and_not_flagged() -> None:
    errors = _scan(FRAME_EQUAL_ONLY, "frame_equal")
    assert errors == [], f"只用 pd.testing.assert_frame_equal 的测试被误报：{errors}"
    assert "assert_frame_equal" in assert_scanner._MODULE_ASSERT_METHODS


def test_pandas_series_equal_is_counted_and_not_flagged() -> None:
    errors = _scan(SERIES_EQUAL_ONLY, "series_equal")
    assert errors == [], f"只用 pd.testing.assert_series_equal 的测试被误报：{errors}"


def test_module_assert_methods_cover_pandas_and_numpy_families() -> None:
    """方法表必须同时覆盖 numpy 与 pandas 两族，缺一即回归。"""
    required = {
        "assert_array_equal",
        "assert_allclose",
        "assert_frame_equal",
        "assert_series_equal",
        "assert_index_equal",
    }
    missing = required - set(assert_scanner._MODULE_ASSERT_METHODS)
    assert missing == set(), f"扫描器漏认的模块级断言：{sorted(missing)}"


# --------------------------------------------------------------------------- 假阳性 2：嵌套 test_ 辅助函数
def test_nested_test_named_helper_is_not_a_case() -> None:
    errors = _scan(NESTED_TEST_HELPER, "nested_helper")
    assert errors == [], f"测试内部定义的 test_* 辅助函数被当作用例：{errors}"


# --------------------------------------------------------------------------- 正向能力不得退化
def test_genuine_assertion_free_test_still_reported() -> None:
    """真·无断言用例必须仍然报 error，否则本修复就成了假绿灯。"""
    errors = _scan(GENUINE_NO_ASSERT, "genuine_no_assert")
    assert [e["pattern"] for e in errors] == ["no-assert"], f"无断言用例未被报出：{errors}"
    # 源码以换行开头，故用例体首行是第 3 行；报告须指向该行而非静默吞掉
    assert errors[0]["line"] == 3, f"报告行号须指向用例体首行，实得 {errors[0]['line']}"


def test_class_level_unittest_case_still_scanned() -> None:
    """unittest 类方法须仍被收集：其内有断言时不得报 no-assert。"""
    path = FIXTURE_DIR / "test_class_probe.py"
    path.write_text(CLASS_LEVEL_TEST, encoding="utf-8")
    errors = [f for f in assert_scanner.scan_file(path) if f["severity"] == "error"]
    assert errors == [], f"类级用例被误报（其断言在类方法里）：{errors}"


def test_weak_assert_inside_class_method_still_warns() -> None:
    """类方法里的裸 assertTrue 仍须报 warn：修复只针对 error 级假阳性。"""
    path = FIXTURE_DIR / "test_class_weak.py"
    path.write_text(GENUINE_WEAK_ASSERT, encoding="utf-8")
    findings = assert_scanner.scan_file(path)
    warns = [f for f in findings if f["pattern"] == "assert-true-bare"]
    assert len(warns) == 1, f"类方法内裸 assertTrue 应报 1 条 warn，实得 {len(warns)}：{findings}"


def test_genuine_no_assert_class_method_still_reported() -> None:
    """类里真的没有断言的方法，仍须报 error。"""
    source = (
        "import unittest\n\n\n"
        "class TestEmpty(unittest.TestCase):\n"
        "    def test_nothing_checked(self):\n"
        "        value = 1 + 1\n"
        "        print(value)\n"
    )
    errors = _scan(source, "class_no_assert")
    assert [e["pattern"] for e in errors] == ["no-assert"], f"类内无断言用例未被报出：{errors}"


def test_denominator_counts_pandas_assertions() -> None:
    """分母必须包含 pandas 断言，否则弱断言占比被系统性低估。"""
    path = FIXTURE_DIR / "test_denominator.py"
    path.write_text(FRAME_EQUAL_ONLY + "\n" + ARRAY_EQUAL_CONTROL, encoding="utf-8")
    total_in_file = 0
    for name in ("test_denominator.py",):
        # count_total_asserts 以目录为粒度，故这里用整目录夹具单独统计
        single = FIXTURE_DIR / name
        before = assert_scanner.count_total_asserts(FIXTURE_DIR.parent / "__no_such_dir__")
        assert before == 0, "不存在的目录必须返回 0（fail-safe）"
        total_in_file = assert_scanner.count_total_asserts(FIXTURE_DIR)
    assert total_in_file == 2, f"两个模块级断言应计入分母，实得 {total_in_file}"
    repo_total = assert_scanner.count_total_asserts(ROOT / "tests")
    assert repo_total > 3000, f"全仓断言总数异常偏低：{repo_total}"
