"""pytest 收集配置的回归测试（BUG-0016）。

验证防回归护栏仍在：
1. testpaths = tests：裸 pytest -q 只从 tests/ 收集，根目录下 ACL 损坏的沙箱
   残留目录（股票分析项目.pytest_tmp 等，无法删除）不会被扫描到，
   tools/ 下再出现 test_*.py 也不会引发 import file mismatch；
2. norecursedirs 继续排除已知坏 ACL 目录，防止显式传入根目录时误入。
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pytest_ini_guards_collection_against_broken_tmp_dirs_and_tool_tests() -> None:
    """Keep the BUG-0016 collection guards in place."""
    ini = (PROJECT_ROOT / "pytest.ini").read_text(encoding="utf-8")

    # 裸 pytest -q 只收集 tests/，根目录坏 ACL 目录与 tools/ 同名模块均不再误入
    assert "testpaths = tests" in ini
    # ACL 损坏、无法删除的历史残留目录必须持续排除
    assert "norecursedirs =" in ini
    assert "股票分析项目.pytest_tmp" in ini
    assert ".pytest_tmp_win11" in ini
