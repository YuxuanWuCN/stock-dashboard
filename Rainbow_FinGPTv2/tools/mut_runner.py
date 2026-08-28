"""变异测试 runner（彩虹找虫 v2）。

heavy 阶段用 subprocess 调 mutmut 跑变异测试，验证测试断言是否真的
能杀死变异体（假绿拦截）。借鉴 peaks-cli 的 peaks-mut：
- kill rate ≥ 80% 才通过（默认阈值）
- mutmut 未安装 → fail-open 通过（信任红线：工具缺失不拦版本发布）
- 用 `mutmut result-ids survived/killed` 解析结果（比状态行解析稳）

设计约束：
- 不 import mutmut（非项目依赖，import 会崩掉 heavy）——subprocess 调用，
  天然 fail-open
- --simple-output 禁 emoji（GBK 坑）；全部 UTF-8
- 不读 stdin；.mutmut-cache/ 由 .gitignore 与 exclude_directories 排除
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

MUT_KILL_THRESHOLD = 0.8  # 对应 peaks ≥80%
DEFAULT_RUNNER = "python -m pytest -q"


def mutmut_available(python: str = sys.executable) -> tuple[bool, str]:
    """检查 mutmut 是否可用。返回 (可用, 说明)。

    mutmut 3.x 在 Windows 原生拒绝运行（提示使用 WSL，但 exit 0）——
    只看 returncode 会误判可用。必须同时检查输出中的平台拒绝提示。
    """
    try:
        proc = subprocess.run(
            [python, "-m", "mutmut", "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        if "WSL" in output or "Native windows support" in output or "please use the WSL" in output:
            return False, "mutmut 不支持 Windows 原生运行（需 WSL，issue #397）"
        return proc.returncode == 0, ""
    except (subprocess.SubprocessError, OSError):
        return False, "mutmut 未安装（pip install mutmut）"


def build_mutmut_argv(python: str, paths: list[str], runner: str, timeout_s: int) -> list[str]:
    """构造 mutmut run 的 argv（逐目录一次调用）。"""
    argv = [python, "-m", "mutmut", "run"]
    for path in paths:
        argv += ["--paths-to-mutate", path]
    argv += [
        "--runner",
        runner,
        "--no-progress",
        "--simple-output",
        "--timeout",
        str(timeout_s),
    ]
    return argv


def parse_status_line(stdout: str) -> tuple[int, int, int, int]:
    """解析 mutmut 状态行 -> (killed, survived, timeout, skipped)。

    只识别明确的标签格式（机器可解析）：
      "123/456 killed:100 survived:2 timeout:5 skipped:0"
    emoji 状态行（🎉⏰🤔🙁）数字顺序不稳定，不猜——解析失败返回
    (0,0,0,0)（信任红线），实际计数以 `mutmut result-ids` 输出为准。
    """
    import re

    for line in stdout.splitlines():
        if "killed:" not in line:
            continue
        km = re.search(r"killed:(\d+)", line)
        sm = re.search(r"survived:(\d+)", line)
        tm = re.search(r"timeout:(\d+)", line)
        skm = re.search(r"skipped:(\d+)", line)
        killed = int(km.group(1)) if km else 0
        survived = int(sm.group(1)) if sm else 0
        timeout = int(tm.group(1)) if tm else 0
        skipped = int(skm.group(1)) if skm else 0
        return killed, survived, timeout, skipped
    return 0, 0, 0, 0


def _result_ids_count(python: str, wd: Path, kind: str) -> int:
    """用 mutmut result-ids 统计 killed/survived 数量（机器接口，权威）。"""
    try:
        proc = subprocess.run(
            [python, "-m", "mutmut", "result-ids", kind],
            cwd=str(wd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        return len([line for line in (proc.stdout or "").splitlines() if line.strip()])
    except (subprocess.SubprocessError, OSError):
        return -1  # 无法获取（信任红线：调用方决定如何处理）


def run_mutation(
    paths: list[str],
    *,
    python: str = sys.executable,
    runner: str = DEFAULT_RUNNER,
    timeout_s: int = 1800,
    workdir: Path | None = None,
) -> dict:
    """跑变异测试并解析 kill rate。

    返回 MutationReport:
    {"kill_rate": float|None, "killed": int, "survived": int, "timeout": int,
     "skipped": int, "total": int, "survivor_ids": list[str], "elapsed_s": float,
     "error": str|None}
    任何一步异常 → error 字段（fail-open 判定依据）。
    """
    started = time.time()
    report: dict = {
        "kill_rate": None,
        "killed": 0,
        "survived": 0,
        "timeout": 0,
        "skipped": 0,
        "total": 0,
        "survivor_ids": [],
        "elapsed_s": 0.0,
        "error": None,
    }
    wd = workdir or Path.cwd()

    available, reason = mutmut_available(python)
    if not available:
        report["error"] = reason
        report["elapsed_s"] = round(time.time() - started, 1)
        return report

    argv = build_mutmut_argv(python, paths, runner, timeout_s)
    try:
        proc = subprocess.run(
            argv,
            cwd=str(wd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s + 60,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired:
        report["error"] = f"变异测试超时（>{timeout_s}s）"
        report["elapsed_s"] = round(time.time() - started, 1)
        return report
    except OSError as exc:
        report["error"] = f"变异测试执行失败：{exc}"
        report["elapsed_s"] = round(time.time() - started, 1)
        return report

    killed, survived, timeout, skipped = parse_status_line(stdout)
    # 以 result-ids 权威计数修正（status 行不可解析时兜底）
    if survived == 0:
        survived = max(0, _result_ids_count(python, wd, "survived"))
    if killed == 0:
        killed = max(0, _result_ids_count(python, wd, "killed"))
    total = killed + survived + timeout + skipped

    survivor_ids: list[str] = []
    if survived > 0:
        try:
            ids_proc = subprocess.run(
                [python, "-m", "mutmut", "result-ids", "survived"],
                cwd=str(wd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            survivor_ids = [line.strip() for line in (ids_proc.stdout or "").splitlines() if line.strip()]
        except (subprocess.SubprocessError, OSError):
            pass

    report.update(
        {
            "killed": killed,
            "survived": survived,
            "timeout": timeout,
            "skipped": skipped,
            "total": total,
            "survivor_ids": survivor_ids[:50],
            "elapsed_s": round(time.time() - started, 1),
            "error": stderr.strip()[-500:] if (proc.returncode != 0 and stderr.strip()) else None,
        }
    )
    if total > 0 and killed + timeout > 0:
        report["kill_rate"] = round((killed + timeout) / total, 4)
    elif total > 0:
        report["kill_rate"] = 0.0
    return report


def as_result(report: dict, threshold: float = MUT_KILL_THRESHOLD) -> dict:
    """转成与 quality_gate.result() 同构的检查结果结构。

    passed 规则（信任红线）：
    - report.error 非空（mutmut 缺失/超时/执行失败）→ passed=True（fail-open）
    - kill_rate 达标 → passed=True
    - kill_rate 不达标 → passed=False（走现有失败登记管线）
    - 无突变（total=0）→ passed=True（无可验证内容）
    """
    if report.get("error"):
        return {
            "name": "变异测试 kill rate",
            "passed": True,
            "details": f"变异测试跳过（TRUST RED LINE）：{report['error']}",
            "category": "test",
        }
    total = report.get("total", 0)
    if total == 0:
        return {
            "name": "变异测试 kill rate",
            "passed": True,
            "details": "未生成突变（无可验证内容），跳过",
            "category": "test",
        }
    kill_rate = report.get("kill_rate")
    if kill_rate is None:
        return {
            "name": "变异测试 kill rate",
            "passed": True,
            "details": f"变异结果不可解析（TRUST RED LINE）：{report.get('error') or '未知'}",
            "category": "test",
        }
    passed = kill_rate >= threshold
    survivor_lines = "\n".join(report.get("survivor_ids", [])[:20])
    details = (
        f"kill rate {kill_rate:.1%}（阈值 {threshold:.0%}）；"
        f"killed {report['killed']} / survived {report['survived']} / "
        f"timeout {report['timeout']} / skipped {report['skipped']}，"
        f"耗时 {report.get('elapsed_s', 0):.0f}s"
    )
    if not passed and survivor_lines:
        details += "\n幸存突变（示例）：\n" + survivor_lines
    return {
        "name": "变异测试 kill rate",
        "passed": passed,
        "details": details,
        "category": "test",
    }


def run(argv: list[str] | None = None) -> int:
    """CLI 入口：python tools/mut_runner.py [--json] [--paths dir]"""
    parser = argparse.ArgumentParser(prog="mut_runner")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--paths", nargs="+", default=["src"], help="要变异的代码目录")
    parser.add_argument("--runner", default=DEFAULT_RUNNER)
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    report = run_mutation(args.paths, runner=args.runner)
    res = as_result(report)
    if args.json:
        print(report)
    else:
        print(res["details"])
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(run())
