"""pytest.ini 的 basetemp 配置必须在全新检出下可用。

pytest 在 _pytest/tmpdir.py 中以 `basetemp.mkdir(mode=0o700)`（不带 parents/exist_ok）
创建 basetemp，因此 basetemp 的**父目录必须已经存在**。仓库根始终存在，
`.pytest_cache` 则随时可能被删或根本不存在。
"""

import os
import subprocess
import sys
from configparser import ConfigParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_TIMEOUT_SECONDS = 180

PROBE_TEST = """
def test_probe_uses_basetemp(tmp_path):
    (tmp_path / "probe.txt").write_text("ok", encoding="utf-8")
    assert (tmp_path / "probe.txt").read_text(encoding="utf-8") == "ok"
"""


def _configured_basetemp() -> str:
    parser = ConfigParser()
    parser.read(REPO_ROOT / "pytest.ini", encoding="utf-8")
    addopts = parser.get("pytest", "addopts")
    tokens = addopts.split()
    for index, token in enumerate(tokens):
        if token == "--basetemp":
            return tokens[index + 1]
        if token.startswith("--basetemp="):
            return token.split("=", 1)[1]
    raise AssertionError(f"pytest.ini 的 addopts 未配置 --basetemp，实际值：{addopts!r}")


def _run_pytest_in_clean_project(tmp_path: Path, basetemp: str) -> subprocess.CompletedProcess[str]:
    """在不含 .pytest_cache 的全新目录里跑 pytest，等价于 fresh clone。"""
    project = tmp_path / "project"
    project.mkdir()
    (project / "pytest.ini").write_text(f"[pytest]\naddopts = --basetemp={basetemp}\n", encoding="utf-8")
    (project / "test_probe.py").write_text(PROBE_TEST, encoding="utf-8")
    # Windows 控制台默认 GBK，不显式指定 UTF-8 解码会在读线程里 UnicodeDecodeError。
    child_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-c", "pytest.ini", "test_probe.py"],
        cwd=project,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env,
        timeout=RUN_TIMEOUT_SECONDS,
    )


def test_repo_basetemp_survives_missing_pytest_cache(tmp_path):
    """当前配置在没有任何缓存目录的全新工程里必须跑通。"""
    result = _run_pytest_in_clean_project(tmp_path, _configured_basetemp())
    combined = result.stdout + result.stderr
    assert result.returncode == 0, f"basetemp={_configured_basetemp()} 在全新检出下失败：\n{combined}"
    assert "FileNotFoundError" not in combined


def test_basetemp_nested_under_absent_parent_reproduces_failure(tmp_path):
    """钉住失败机理：父目录缺失时 pytest 直接 FileNotFoundError，不允许静默通过。"""
    result = _run_pytest_in_clean_project(tmp_path, ".pytest_cache/tmp")
    combined = result.stdout + result.stderr
    assert result.returncode != 0, f"嵌套 basetemp 本应失败却通过了：\n{combined}"
    assert "FileNotFoundError" in combined, f"失败原因不是父目录缺失，机理可能已变化：\n{combined}"
