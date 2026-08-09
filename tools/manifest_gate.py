"""Manifest 三原语门禁（彩虹找虫 v2）。

借鉴 peaks-cli 的 SOP manifest 门禁：把"流程阶段 + 每阶段可检查条件"
数据化到 .quality-gates.json 的 gates 键，执行层与定义层分离。

三种检查原语（对应 peaks file-exists / grep / command）：
- file-exists: 文件存在性
- grep: 文本模式匹配（absent=True 表示"不应出现"）
- command: 子进程退出码（默认不放行，需 --allow-commands 配置）

三值判决 pass / fail / blocked（blocked=无法评估，不拦截，信任红线）：
- grep 的 path 不存在 → blocked
- command 原语未放行 → blocked
- 路径越界（resolve 后不在项目根内）→ blocked

设计约束：纯标准库；全部 UTF-8；不读 stdin；自身异常 fail-open。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# 允许 grep 扫描的文本文件后缀
_TEXT_SUFFIXES = {".py", ".json", ".md", ".txt", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".ps1", ".js", ".ts"}
# 默认排除目录（评估时跳过）
_EXCLUDED_DIRS = {".git", ".quality-state", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "bug合集", "测试记录", ".mutmut-cache"}

ROOT = Path(__file__).resolve().parents[1]


def load_gates(root: Path | None = None) -> list[dict]:
    """从 .quality-gates.json 读 gates 列表。缺省返回空列表。"""
    project_root = root or ROOT
    try:
        cfg = json.loads((project_root / ".quality-gates.json").read_text(encoding="utf-8"))
        gates = cfg.get("gates") or []
        return gates if isinstance(gates, list) else []
    except Exception:
        return []


def resolve_inside_project(path_str: str, project_root: Path) -> Path | None:
    """钉死项目根：resolve 后必须仍在 project_root 下，否则返回 None（blocked）。"""
    p = Path(path_str)
    if not p.is_absolute():
        p = project_root / p
    try:
        resolved = p.resolve()
        resolved.relative_to(project_root.resolve())
        return resolved
    except (ValueError, OSError):
        return None


def eval_file_exists(check: dict, root: Path) -> dict:
    """file-exists 原语。"""
    path = resolve_inside_project(str(check.get("path", "")), root)
    if path is None:
        return {"name": check.get("name", "file-exists"), "verdict": "blocked", "reason": f"路径越界或非法: {check.get('path')}", "type": "file-exists"}
    exists = path.exists()
    return {
        "name": check.get("name", "file-exists"),
        "verdict": "pass" if exists else "fail",
        "reason": f"{check.get('path')} {'存在' if exists else '不存在'}",
        "type": "file-exists",
    }


def _iter_text_files(root: Path, rel_path: str) -> list[Path]:
    """枚举 path 下的文本文件（文件或目录）。"""
    target = root / rel_path
    if not target.exists():
        return []
    if target.is_file():
        return [target] if target.suffix in _TEXT_SUFFIXES else []
    files: list[Path] = []
    for path in target.rglob("*"):
        if not path.is_file() or path.suffix not in _TEXT_SUFFIXES:
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if any(part in _EXCLUDED_DIRS for part in rel.parts):
            continue
        files.append(path)
    return files


def eval_grep(check: dict, root: Path) -> dict:
    """grep 原语。pattern 匹配 / absent=True 表示不应出现。"""
    pattern = check.get("pattern", "")
    absent = bool(check.get("absent", False))
    rel_path = str(check.get("path", "."))
    target = root / rel_path
    if not target.exists():
        return {"name": check.get("name", "grep"), "verdict": "blocked", "reason": f"路径不存在: {rel_path}（无法评估）", "type": "grep"}
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return {"name": check.get("name", "grep"), "verdict": "blocked", "reason": f"正则非法: {exc}（无法评估）", "type": "grep"}

    hits: list[str] = []
    for path in _iter_text_files(root, rel_path):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                try:
                    rel = path.relative_to(root)
                except ValueError:
                    rel = path
                hits.append(f"{rel}:{line_no}")
                if len(hits) >= 10:
                    break
        if len(hits) >= 10:
            break

    if absent:
        passed = not hits
        reason = f"模式 {pattern!r} {'未出现' if passed else '出现于 ' + '; '.join(hits[:5])}"
    else:
        passed = bool(hits)
        reason = f"模式 {pattern!r} {'命中 ' + '; '.join(hits[:5]) if hits else '未命中'}"
    return {
        "name": check.get("name", "grep"),
        "verdict": "pass" if passed else "fail",
        "reason": reason,
        "type": "grep",
    }


def eval_command(check: dict, root: Path, allow_commands: bool = False) -> dict:
    """command 原语。默认不放行（blocked）；allow_commands 配置后才执行。"""
    run_cmd = check.get("run")
    if not run_cmd or not isinstance(run_cmd, list):
        return {"name": check.get("name", "command"), "verdict": "blocked", "reason": "run 字段缺失或非法（无法评估）", "type": "command"}
    if not allow_commands:
        return {"name": check.get("name", "command"), "verdict": "blocked", "reason": "command 原语未放行（allow_commands=false，信任红线）", "type": "command"}
    argv = [str(a).replace("{python}", sys.executable) for a in run_cmd]
    expect_zero = bool(check.get("expectExitZero", True))
    try:
        proc = subprocess.run(argv, cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        passed = (proc.returncode == 0) == expect_zero
        reason = f"{' '.join(argv)} 退出码 {proc.returncode}（期望 {'0' if expect_zero else '非 0'}）"
        if proc.stdout and proc.stdout.strip():
            reason += "\n" + proc.stdout.strip()[-300:]
        return {"name": check.get("name", "command"), "verdict": "pass" if passed else "fail", "reason": reason, "type": "command"}
    except subprocess.TimeoutExpired:
        return {"name": check.get("name", "command"), "verdict": "blocked", "reason": "command 执行超时（>30s，无法评估）", "type": "command"}
    except OSError as exc:
        return {"name": check.get("name", "command"), "verdict": "blocked", "reason": f"command 执行失败: {exc}（无法评估）", "type": "command"}


def eval_gates(gates: list[dict], root: Path | None = None, allow_commands: bool = False) -> list[dict]:
    """逐条评估全部 gates。"""
    project_root = root or ROOT
    results = []
    for gate in gates:
        gtype = gate.get("type", "file-exists")
        try:
            if gtype == "file-exists":
                results.append(eval_file_exists(gate, project_root))
            elif gtype == "grep":
                results.append(eval_grep(gate, project_root))
            elif gtype == "command":
                results.append(eval_command(gate, project_root, allow_commands))
            else:
                results.append({"name": gate.get("name", "?"), "verdict": "blocked", "reason": f"未知类型 {gtype}（无法评估）", "type": gtype})
        except Exception as exc:  # 自身异常 fail-open
            results.append({"name": gate.get("name", "?"), "verdict": "blocked", "reason": f"评估异常: {exc}（信任红线）", "type": gtype})
    return results


def gates_passed(results: list[dict]) -> bool:
    """任一 fail 即 False；blocked 不算 fail。"""
    return all(r["verdict"] != "fail" for r in results)


def as_result(results: list[dict]) -> dict:
    """转成与 quality_gate.result() 同构的检查结果结构。"""
    fails = [r for r in results if r["verdict"] == "fail"]
    blockeds = [r for r in results if r["verdict"] == "blocked"]
    lines = [f"[{r['verdict']}] {r['name']}: {r['reason']}" for r in results]
    details = "\n".join(lines) if lines else "未配置 Manifest 门禁"
    if blockeds:
        details += f"\n（{len(blockeds)} 条无法评估，未拦截——信任红线）"
    return {
        "name": "Manifest 门禁",
        "passed": gates_passed(results),
        "details": details,
        "category": "security",
    }


def manifest_hook_layer(raw_command: str, root: Path | None = None) -> tuple[bool, str]:
    """供 command_hook_pre_bash 追加调用。

    只评估"命令可判定"的 grep/file-exists 类 gate——把即将执行的 raw_command
    作为被检字符串与 gate 匹配（如 gate grep "git push --force" 命中）。
    command 原语在 hook 中永不执行。门禁自身异常 → (False, "") 绝不 deny。
    命令携带 --bypass-token <id> 时先尝试消费 token，成功则跳过匹配。
    """
    project_root = root or ROOT
    # bypass token 消费（一次性，消费即焚）
    import re as _re

    token_match = _re.search(r"(?:--bypass-token|RAINBOW_BYPASS=)\s*([0-9a-f]{32})", raw_command)
    if token_match:
        try:
            from tools import bypass  # type: ignore

            ok, _sop = bypass.consume_token(token_match.group(1), context="hook-pre-bash")
            if ok:
                return False, ""  # token 有效：本命令放行
        except Exception:
            pass
    try:
        gates = load_gates(project_root)
        for gate in gates:
            if gate.get("type") != "grep":
                continue
            pattern = gate.get("pattern", "")
            if not pattern or gate.get("scope") != "command":
                continue
            try:
                regex = re.compile(pattern)
            except re.error:
                continue
            if regex.search(raw_command):
                return True, f"Manifest 门禁拦截：{gate.get('name', 'grep')} 命中命令模式 {pattern!r}"
    except Exception:
        pass
    return False, ""


def command_manifest(args: argparse.Namespace) -> int:
    """manifest 子命令：手动触发三原语门禁。退出码 fail=1。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    gates = load_gates()
    allow = bool(getattr(args, "allow_commands", False))
    results = eval_gates(gates, allow_commands=allow)
    for r in results:
        print(f"[{r['verdict']}] {r['name']}: {r['reason']}")
    print(f"\n结果: {'通过' if gates_passed(results) else '失败'}（{sum(1 for r in results if r['verdict']=='pass')} 通过 / {sum(1 for r in results if r['verdict']=='fail')} 失败 / {sum(1 for r in results if r['verdict']=='blocked')} 无法评估）")
    return 1 if not gates_passed(results) else 0


def run(argv: list[str] | None = None) -> int:
    """CLI 入口：python tools/manifest_gate.py [--allow-commands]"""
    parser = argparse.ArgumentParser(prog="manifest_gate")
    parser.add_argument("--allow-commands", action="store_true", help="放行 command 原语执行")
    args = parser.parse_args(argv)
    return command_manifest(args)


if __name__ == "__main__":
    raise SystemExit(run())
