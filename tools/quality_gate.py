#!/usr/bin/env python3
"""Agent-neutral quality gates and permanent bug history for this project."""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / ".quality-gates.json"
BUG_DIR = ROOT / "bug合集"
CATALOG_PATH = BUG_DIR / "catalog.json"
BUG_INDEX_PATH = BUG_DIR / "INDEX.md"
OPEN_BUG_DIR = BUG_DIR / "未解决"
RESOLVED_BUG_DIR = BUG_DIR / "已解决"
STATE_DIR = ROOT / ".quality-state"
REPORT_DIR = STATE_DIR / "reports"
UNIT_DIR = STATE_DIR / "units"
ACTIVE_UNIT_PATH = STATE_DIR / "active-unit.json"
LAST_TESTED_PATH = STATE_DIR / "last-tested.json"
VERSION_REPORT_DIR = ROOT / "测试记录" / "版本"


# These credential files are intentionally local-only and are excluded by
# .gitignore. Scan every other eligible file so a secret in source, tests,
# generated reports, or documentation still fails the gate.
LOCAL_SECRET_FILE_NAMES = frozenset({"api-key.txt", "api_key.txt"})
SCORE_LIMITS = {
    "functional": 6,
    "security": 5,
    "scope": 4,
    "probability": 3,
    "recovery": 2,
    "hidden": 2,
}

SCORE_LABELS = {
    "functional": "功能或结论影响",
    "security": "数据、安全或隐私影响",
    "scope": "影响范围",
    "probability": "发生概率",
    "recovery": "修复与恢复成本",
    "hidden": "隐蔽性和回归风险",
}


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_layout() -> None:
    for directory in (
        BUG_DIR,
        OPEN_BUG_DIR,
        RESOLVED_BUG_DIR,
        STATE_DIR,
        REPORT_DIR,
        UNIT_DIR,
        VERSION_REPORT_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def project_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


# ---------------------------------------------------------------------------
# Config memo – eliminates repeated .quality-gates.json parsing (D6)
# ---------------------------------------------------------------------------
_config_cache: dict[str, Any] | None = None


def load_config() -> dict[str, Any]:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    config = read_json(CONFIG_PATH)
    if not isinstance(config, dict):
        raise RuntimeError(f"无法读取配置：{CONFIG_PATH}")
    _config_cache = config
    return config


def reset_config_cache() -> None:
    """Clear the config memo (for tests that modify CONFIG_PATH)."""
    global _config_cache
    _config_cache = None


# ---------------------------------------------------------------------------
# Control files
# ---------------------------------------------------------------------------

def _hardcoded_control_file_paths() -> list[Path]:
    """Hard-coded floor that config may only add to, never shrink."""
    return [
        ROOT / "AGENTS.md",
        ROOT / "CLAUDE.md",
        ROOT / "GEMINI.md",
        ROOT / "CODEX.md",
        ROOT / "WORKFLOW.md",
        ROOT / ".gitignore",
        ROOT / ".quality-gates.json",
        ROOT / ".claude" / "settings.json",
        ROOT / "tools" / "run_quality.ps1",
        ROOT / "tools" / "install_hooks.ps1",
        ROOT / ".githooks" / "pre-commit",
        ROOT / ".githooks" / "commit-msg",
        ROOT / ".githooks" / "pre-push",
    ]


def control_file_candidates() -> list[Path]:
    """Return hard-coded floor plus any additional entries from config."""
    floor = _hardcoded_control_file_paths()
    config = load_config()
    extras = config.get("additional_control_files", [])
    if not isinstance(extras, list):
        extras = []
    extra_paths = [
        (ROOT / str(e) if not Path(e).is_absolute() else Path(e))
        for e in extras
    ]
    return sorted(set(floor + extra_paths), key=lambda p: project_relative(p).casefold())


def control_files() -> list[Path]:
    """Files that define the gates must invalidate old test receipts when changed."""
    return sorted(
        {path for path in control_file_candidates() if path.exists() and path.is_file()},
        key=lambda item: project_relative(item).casefold(),
    )


# ---------------------------------------------------------------------------
# Source discovery
# ---------------------------------------------------------------------------

def source_extensions() -> set[str]:
    return set(load_config().get("source_extensions", []))


def excluded_directories() -> set[str]:
    return set(load_config().get("exclude_directories", []))


def is_source_file(path: Path) -> bool:
    candidate = path if path.is_absolute() else ROOT / path
    try:
        relative = candidate.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return False
    if any(part in excluded_directories() for part in relative.parts):
        return False
    protected = {project_relative(item) for item in control_file_candidates()}
    return candidate.suffix in source_extensions() or relative.as_posix() in protected


def iter_source_files() -> list[Path]:
    """Walk source roots, pruning excluded directory subtrees (D6)."""
    config = load_config()
    extensions = source_extensions()
    excluded = excluded_directories()
    files: list[Path] = []
    roots = config.get("source_roots") or ["."]

    for root_name in roots:
        source_root = ROOT / str(root_name)
        if not source_root.exists():
            continue
        if source_root.is_file():
            candidates = [source_root]
        else:
            candidates = []
            for dirpath_str, dirnames, filenames in os.walk(str(source_root)):
                dirpath = Path(dirpath_str)
                # Prune excluded directories in-place
                dirnames[:] = [
                    d for d in dirnames
                    if d not in excluded and d not in (".git",)
                ]
                for fname in filenames:
                    candidates.append(dirpath / fname)
        for path in candidates:
            if not path.is_file() or path.suffix not in extensions:
                continue
            try:
                relative = path.resolve().relative_to(ROOT.resolve())
            except ValueError:
                continue
            if any(part in excluded for part in relative.parts):
                continue
            files.append(path)

    return sorted(set(files), key=lambda item: project_relative(item).casefold())


# ---------------------------------------------------------------------------
# Protected state paths – writing these directly is always denied (D1)
# ---------------------------------------------------------------------------

def protected_state_paths() -> list[Path]:
    """Paths that may NEVER be written directly via Edit / Write / NotebookEdit / Bash.

    Use the CLI (log-error, resolve, begin-unit, small, …) to modify them.
    """
    return [
        STATE_DIR,
        CATALOG_PATH,
        BUG_INDEX_PATH,
        OPEN_BUG_DIR,
        RESOLVED_BUG_DIR,
        VERSION_REPORT_DIR,
    ]


def _is_under_protection(target: Path) -> bool:
    """True when *target* is inside or equal to any protected path."""
    resolved = target.resolve()
    for protected in protected_state_paths():
        if protected.is_dir():
            try:
                resolved.relative_to(protected.resolve())
                return True
            except ValueError:
                continue
        else:
            if resolved == protected.resolve():
                return True
    return False


# ---------------------------------------------------------------------------
# Hook path extraction (D2 – also handle notebook_path)
# ---------------------------------------------------------------------------

def hook_target_path(tool_input: dict[str, Any]) -> str | None:
    """Extract the target file path from a tool_input dict.

    Handles file_path (Edit/Write), notebook_path (NotebookEdit),
    and a bare ``path`` key as fallback.
    """
    for key in ("file_path", "notebook_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def hash_paths(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: project_relative(item).casefold()):
        digest.update(project_relative(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def source_hash() -> str:
    return hash_paths([*iter_source_files(), *control_files()])


# ---------------------------------------------------------------------------
# Bug hash – split into receipt-binding hash and archive hash (D5)
# ---------------------------------------------------------------------------

def _is_receipt_binding(record: dict[str, Any]) -> bool:
    """Does this bug record bind to test receipts?

    backward-compat: if ``receipt_binding`` key is absent, old records where
    stage != 'agent-tool-call' are binding.
    """
    if "receipt_binding" in record:
        return bool(record["receipt_binding"])
    return record.get("stage") != "agent-tool-call"


def bug_hash() -> str:
    """SHA-256 of only receipt-binding bug records (projections + .md files).

    Non-binding records (e.g. auto-logged agent-tool-call failures) are
    permanently stored but do NOT invalidate test receipts.
    """
    catalog = load_catalog()
    records = catalog.get("bugs", [])
    digest = hashlib.sha256()
    for rec in records:
        if not _is_receipt_binding(rec):
            continue
        projection = json.dumps(
            {
                "id": rec.get("id"),
                "status": rec.get("status"),
                "total": rec.get("total"),
                "grade": rec.get("grade"),
                "title": rec.get("title"),
                "details": rec.get("details"),
                "cause": rec.get("cause"),
                "resolution": rec.get("resolution"),
                "verification": rec.get("verification"),
                "occurrences": rec.get("occurrences", []),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        digest.update(projection.encode("utf-8"))
        digest.update(b"\0")

    # Also hash the on-disk .md files of binding records
    for rec in sorted(records, key=lambda r: r.get("id", "")):
        if not _is_receipt_binding(rec):
            continue
        md_path = bug_record_path(rec)
        if md_path.exists():
            digest.update(project_relative(md_path).encode("utf-8"))
            digest.update(b"\0")
            digest.update(md_path.read_bytes())
            digest.update(b"\0")

    return digest.hexdigest()


def bug_archive_hash() -> str:
    """SHA-256 of ALL bug files (complete historical trace, non-binding)."""
    return hash_paths(bug_files())


# ---------------------------------------------------------------------------
# Bug files / bundle (still full-file for begin-unit output)
# ---------------------------------------------------------------------------

def bug_files() -> list[Path]:
    if not BUG_DIR.exists():
        return []
    return sorted(
        (path for path in BUG_DIR.rglob("*") if path.is_file()),
        key=lambda item: project_relative(item).casefold(),
    )


def bug_bundle() -> str:
    paths = bug_files()
    lines = [
        "# bug合集全量阅读包",
        f"生成时间：{now_iso()}",
        f"文件数量：{len(paths)}",
        f"合集 SHA-256（凭证绑定部分）：{bug_hash()}",
        f"合集 SHA-256（全量归档）：{bug_archive_hash()}",
        "",
    ]
    for path in paths:
        relative = project_relative(path)
        lines.extend((f"===== BEGIN {relative} =====",))
        try:
            lines.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            lines.append(f"[读取失败：{exc}]")
        lines.extend((f"===== END {relative} =====", ""))
    return "\n".join(lines)


def redact_secrets(value: str) -> str:
    patterns = (
        (re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s]+"), r"\1[REDACTED]"),
        (
            re.compile(
                r"(?i)((?:api[_-]?key|token|password|secret)\s*[:=]\s*)['\"]?[^\s'\"]+"
            ),
            r"\1[REDACTED]",
        ),
        (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_TOKEN]"),
    )
    result = value
    for par, replacement in patterns:
        result = par.sub(replacement, result)
    return result


def normalize_signature_text(value: str) -> str:
    value = re.sub(r"[A-Fa-f0-9]{12,}", "<hex>", value)
    value = re.sub(r"\d{4}-\d{2}-\d{2}[T ][^\s]+", "<time>", value)
    value = re.sub(r"\s+", " ", value).strip().casefold()
    return value[:1000]


def grade_for(score: int) -> tuple[str, str]:
    if score >= 20:
        return "S", "致命"
    if score >= 17:
        return "A", "高危"
    if score >= 13:
        return "B", "严重"
    if score >= 9:
        return "C", "中等"
    if score >= 5:
        return "D", "轻微"
    return "E", "提示"


def validate_scores(scores: dict[str, int]) -> tuple[dict[str, int], int]:
    validated: dict[str, int] = {}
    for key, limit in SCORE_LIMITS.items():
        value = int(scores.get(key, 0))
        if value < 0 or value > limit:
            raise ValueError(f"{key} 必须在 0-{limit} 之间")
        validated[key] = value
    total = sum(validated.values())
    if total == 0:
        validated["functional"] = 1
        total = 1
    return validated, total


def load_catalog() -> dict[str, Any]:
    catalog = read_json(
        CATALOG_PATH, {"schema_version": 1, "next_id": 1, "bugs": []}
    )
    if not isinstance(catalog, dict) or not isinstance(catalog.get("bugs"), list):
        raise RuntimeError("bug合集/catalog.json 格式无效")
    catalog.setdefault("schema_version", 1)
    catalog.setdefault("next_id", 1)
    return catalog


def bug_record_path(record: dict[str, Any]) -> Path:
    directory = RESOLVED_BUG_DIR if record["status"] == "resolved" else OPEN_BUG_DIR
    return directory / f"{record['id']}.md"


def render_bug_record(record: dict[str, Any]) -> str:
    score = record["score"]
    status_text = "已解决" if record["status"] == "resolved" else "未解决"
    resolved_at = record.get("resolved_at", "")
    lines = [
        f"# {record['id']}：{record['title']}",
        "",
        f"- 状态：{status_text}",
        f"- 字母等级：{record['grade']}",
        f"- 中文级别：{record['severity']}",
        f"- 评分：{record['total']}/22",
        f"- 类型：{record['category']}",
        f"- 阶段：{record['stage']}",
        f"- 首次发现：{record['first_seen']}",
        f"- 最近发生：{record['last_seen']}",
        f"- 发生次数：{len(record['occurrences'])}",
        f"- 是否待人工复核：{'是' if record.get('provisional', True) else '否'}",
        f"- 影响凭证绑定：{'是' if _is_receipt_binding(record) else '否'}",
    ]
    if resolved_at:
        lines.append(f"- 解决时间：{resolved_at}")
    lines.extend(("", "## 分项评分", ""))
    for key, limit in SCORE_LIMITS.items():
        lines.append(f"- {SCORE_LABELS[key]}：{score[key]}/{limit}")
    lines.extend(
        (
            "",
            "## 现象与复现",
            "",
            record.get("details", "尚无详细信息。"),
            "",
            "## 原因",
            "",
            record.get("cause") or "尚待分析。",
            "",
            "## 修复",
            "",
            record.get("resolution") or "尚未修复。",
            "",
            "## 验证证据",
            "",
            record.get("verification") or "尚无。",
            "",
            "## 发生记录",
            "",
        )
    )
    for occurrence in record["occurrences"]:
        summary = occurrence.get("details", "")[:1200].replace("\n", " ")
        lines.append(f"- {occurrence['at']}：{summary}")
    return "\n".join(lines).rstrip() + "\n"


def rebuild_bug_files(catalog: dict[str, Any]) -> None:
    for record in catalog["bugs"]:
        path = bug_record_path(record)
        write_text(path, render_bug_record(record))
        other_dir = OPEN_BUG_DIR if path.parent == RESOLVED_BUG_DIR else RESOLVED_BUG_DIR
        stale = other_dir / path.name
        if stale.exists():
            stale.unlink()

    rows = [
        "# Bug 总索引",
        "",
        f"更新时间：{now_iso()}",
        "",
        "| ID | 状态 | 等级 | 分数 | 类型 | 阶段 | 标题 | 发生次数 | 绑定凭证 | 记录 |",
        "|---|---|---:|---:|---|---|---:|---|---|",
    ]
    for record in sorted(catalog["bugs"], key=lambda item: item["id"]):
        status_text = "已解决" if record["status"] == "resolved" else "未解决"
        path = bug_record_path(record).relative_to(BUG_DIR).as_posix()
        title = record["title"].replace("|", "\\|")
        binding = "是" if _is_receipt_binding(record) else "否"
        rows.append(
            f"| {record['id']} | {status_text} | {record['grade']} | "
            f"{record['total']}/22 | {record['category']} | {record['stage']} | "
            f"{title} | {len(record['occurrences'])} | {binding} | [{path}]({path}) |"
        )
    if not catalog["bugs"]:
        rows.append("| - | - | - | - | - | - | 当前尚无记录 | 0 | - | - |")
    write_text(BUG_INDEX_PATH, "\n".join(rows) + "\n")
    write_json(CATALOG_PATH, catalog)


def add_bug(
    *,
    category: str,
    stage: str,
    title: str,
    details: str,
    scores: dict[str, int],
    provisional: bool = True,
    receipt_binding: bool | None = None,
) -> tuple[str, bool]:
    ensure_layout()
    details = redact_secrets(details.strip() or "未提供详细信息。")
    scores, total = validate_scores(scores)
    grade, severity = grade_for(total)
    signature_source = "|".join(
        (category, stage, normalize_signature_text(title), normalize_signature_text(details))
    )
    signature = hashlib.sha256(signature_source.encode("utf-8")).hexdigest()[:20]
    timestamp = now_iso()
    catalog = load_catalog()

    for record in catalog["bugs"]:
        if record.get("signature") == signature:
            record["last_seen"] = timestamp
            was_resolved = record["status"] == "resolved"
            if was_resolved:
                record["status"] = "open"
                record["provisional"] = True
            occurrence_details = (
                "复发：" + details if was_resolved else details
            )
            record["occurrences"].append({"at": timestamp, "details": occurrence_details})
            rebuild_bug_files(catalog)
            return record["id"], True

    if receipt_binding is None:
        receipt_binding = stage != "agent-tool-call"

    number = int(catalog["next_id"])
    bug_id = f"BUG-{number:04d}"
    catalog["next_id"] = number + 1
    catalog["bugs"].append(
        {
            "id": bug_id,
            "signature": signature,
            "status": "open",
            "title": title.strip() or "未命名错误",
            "category": category,
            "stage": stage,
            "score": scores,
            "total": total,
            "grade": grade,
            "severity": severity,
            "provisional": provisional,
            "receipt_binding": receipt_binding,
            "first_seen": timestamp,
            "last_seen": timestamp,
            "details": details,
            "cause": "",
            "resolution": "",
            "verification": "",
            "occurrences": [{"at": timestamp, "details": details}],
        }
    )
    rebuild_bug_files(catalog)
    return bug_id, False


def resolve_bug(bug_id: str, reason: str, verification: str) -> None:
    catalog = load_catalog()
    for record in catalog["bugs"]:
        if record["id"].casefold() == bug_id.casefold():
            record["status"] = "resolved"
            record["resolution"] = reason.strip()
            record["verification"] = verification.strip()
            record["provisional"] = False
            record["resolved_at"] = now_iso()
            record["last_seen"] = now_iso()
            rebuild_bug_files(catalog)
            print(f"已归档 {record['id']}，历史记录仍完整保留。")
            return
    raise RuntimeError(f"找不到 Bug：{bug_id}")


def result(name: str, passed: bool, details: str, category: str = "test") -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "details": details.strip(),
        "category": category,
    }


def selected_files(target: str | None = None) -> list[Path]:
    files = iter_source_files()
    if not target:
        return files

    path = Path(target) if Path(target).is_absolute() else ROOT / target
    if not path.exists() or not is_source_file(path):
        raise ValueError(f"--file 必须指向项目内已有的源码文件：{target}")

    # A receipt covers the entire source hash, so every source file must be checked.
    return files


def check_python_syntax(files: list[Path]) -> dict[str, Any]:
    python_files = [path for path in files if path.suffix == ".py"]
    errors: list[str] = []
    for path in python_files:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeError, OSError) as exc:
            errors.append(f"{project_relative(path)}: {exc}")
    if errors:
        return result("Python 语法", False, "\n".join(errors), "code")
    return result("Python 语法", True, f"检查 {len(python_files)} 个 Python 文件。")


def notebook_code(source: Any) -> str:
    text = "".join(source) if isinstance(source, list) else str(source or "")
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("%", "!", "?")):
            indentation = line[: len(line) - len(stripped)]
            kept.append(indentation + "pass")
        else:
            kept.append(line)
    return "\n".join(kept)


def check_notebooks(files: list[Path]) -> dict[str, Any]:
    notebooks = [path for path in files if path.suffix == ".ipynb"]
    errors: list[str] = []
    for path in notebooks:
        try:
            notebook = read_json(path)
            if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
                raise ValueError("缺少 cells 数组")
            for index, cell in enumerate(notebook["cells"]):
                if cell.get("cell_type") == "code":
                    ast.parse(notebook_code(cell.get("source")), filename=f"{path}#cell-{index}")
        except (ValueError, SyntaxError, UnicodeError, OSError, json.JSONDecodeError) as exc:
            errors.append(f"{project_relative(path)}: {exc}")
    if errors:
        return result("Notebook 结构与语法", False, "\n".join(errors), "code")
    return result("Notebook 结构与语法", True, f"检查 {len(notebooks)} 个 Notebook。")


def check_project_json() -> dict[str, Any]:
    candidates = [CONFIG_PATH, ROOT / ".claude" / "settings.json"]
    errors: list[str] = []
    checked = 0
    for path in candidates:
        if not path.exists():
            continue
        checked += 1
        try:
            read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{project_relative(path)}: {exc}")
    if errors:
        return result("项目 JSON 配置", False, "\n".join(errors), "code")
    return result("项目 JSON 配置", True, f"检查 {checked} 个配置文件。")


def run_command(argv: list[str], timeout: int = 300) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            argv,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    return completed.returncode == 0, output or f"退出码 {completed.returncode}"


def has_custom_commands(level: str) -> bool:
    commands = load_config().get("custom_commands", {}).get(level, [])
    return isinstance(commands, list) and bool(commands)


def check_language_runtimes(files: list[Path]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    matlab_files = [path for path in files if path.suffix in {".m", ".mlx"}]
    if matlab_files:
        executable = shutil.which("matlab")
        if not executable:
            results.append(
                result(
                    "MATLAB 运行时",
                    False,
                    f"发现 {len(matlab_files)} 个 MATLAB 文件，但找不到 matlab 命令。",
                    "environment",
                )
            )
        else:
            results.append(result("MATLAB 运行时", True, executable))

    r_files = [path for path in files if path.suffix in {".r", ".R"}]
    if r_files:
        executable = shutil.which("Rscript")
        if not executable:
            results.append(
                result(
                    "R 运行时",
                    False,
                    f"发现 {len(r_files)} 个 R 文件，但找不到 Rscript 命令。",
                    "environment",
                )
            )
        else:
            errors: list[str] = []
            for path in r_files:
                passed, output = run_command(
                    [executable, "-e", f"parse(file={json.dumps(str(path))})"], timeout=60
                )
                if not passed:
                    errors.append(f"{project_relative(path)}: {output}")
            results.append(result("R 语法", not errors, "\n".join(errors) or f"检查 {len(r_files)} 个文件。", "code"))

    unsupported = sorted(
        {
            path.suffix
            for path in files
            if path.suffix
            not in {".py", ".ipynb", ".m", ".mlx", ".r", ".R", ".json"}
        }
    )
    if unsupported:
        covered = has_custom_commands("small")
        details = "以下扩展名需要项目专用小测：" + ", ".join(unsupported)
        if covered:
            details += "；已配置自定义小测命令。"
        results.append(
            result("其他语言专用检查", covered, details, "environment")
        )
    return results


def run_unittest_suite() -> dict[str, Any]:
    tests_dir = ROOT / "tests"
    if not tests_dir.exists():
        return result("Python 自动化测试", True, "tests 目录尚不存在，无测试可运行。")
    passed, output = run_command(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        timeout=300,
    )
    return result("Python 自动化测试", passed, output, "test")


def project_code_files(files: list[Path]) -> list[Path]:
    roots = [ROOT / str(value) for value in load_config().get("project_code_roots", [])]
    selected: list[Path] = []
    for path in files:
        resolved = path.resolve()
        for code_root in roots:
            try:
                resolved.relative_to(code_root.resolve())
            except ValueError:
                continue
            selected.append(path)
            break
    return selected


def test_files(pattern: str) -> list[Path]:
    tests_dir = ROOT / "tests"
    if not tests_dir.exists():
        return []
    return sorted(
        (path for path in tests_dir.rglob(pattern) if path.is_file()),
        key=lambda item: project_relative(item).casefold(),
    )


def count_unittest_cases(paths: list[Path]) -> tuple[int, list[str]]:
    """Load candidate modules and count tests recognized by unittest."""
    total = 0
    errors: list[str] = []
    original_sys_path = list(sys.path)
    for value in (str(ROOT), str(ROOT / "tests")):
        if value not in sys.path:
            sys.path.insert(0, value)

    try:
        for path in paths:
            if not path.exists():
                errors.append(f"{project_relative(path)} 不存在。")
                continue
            module_digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
            module_name = f"_quality_gate_test_{module_digest}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            if not spec or not spec.loader:
                errors.append(f"无法加载 {project_relative(path)}。")
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
                loader = unittest.TestLoader()
                suite = loader.loadTestsFromModule(module)
                total += suite.countTestCases()
                errors.extend(loader.errors)
            except (Exception, SystemExit) as exc:
                errors.append(f"{project_relative(path)} 加载失败：{exc}")
            finally:
                sys.modules.pop(module_name, None)
    finally:
        sys.path[:] = original_sys_path
    return total, errors


def _quality_system_test_names() -> set[str]:
    """Test file names that count as quality-system tests (not business coverage)."""
    config = load_config()
    policy = config.get("test_policy", {})
    names = policy.get("quality_system_test_files", ["test_quality_system.py"])
    return {n.casefold() for n in names}


def project_test_coverage(level: str, files: list[Path]) -> dict[str, Any]:
    code_files = project_code_files(files)
    if not code_files:
        return result(
            f"{level} 项目测试覆盖入口",
            True,
            "代码与算法目录尚无业务代码；当前只验证质量系统本身。",
        )

    policy = load_config().get("test_policy", {})
    quality_names = _quality_system_test_names()
    if level == "small":
        required = bool(policy.get("require_unit_tests_when_code_exists", True))
        candidates = [
            path
            for path in test_files("test_*.py")
            if path.name.casefold() not in quality_names
            and not path.name.startswith(("test_integration", "test_reproducibility"))
        ]
        expected = "tests/test_*.py 中的业务单元测试，或 custom_commands.small"
    elif level == "medium":
        required = bool(policy.get("require_integration_tests_when_code_exists", True))
        candidates = test_files("test_integration*.py")
        expected = "tests/test_integration*.py，或 custom_commands.medium"
    else:
        required = bool(policy.get("require_reproducibility_tests_when_code_exists", True))
        candidates = test_files("test_reproducibility*.py")
        expected = "tests/test_reproducibility*.py，或 custom_commands.heavy"

    discovered_tests, discovery_errors = count_unittest_cases(candidates)
    custom_coverage = has_custom_commands(level)
    covered = discovered_tests > 0 or custom_coverage
    if not required:
        covered = True
    details = (
        f"发现 {len(code_files)} 个业务代码文件；"
        f"发现 {len(candidates)} 个 {level} 级测试文件、"
        f"{discovered_tests} 个 unittest 可执行测试。要求：{expected}。"
    )
    if discovery_errors:
        details += "\n测试发现错误：\n" + "\n".join(discovery_errors)
    return result(f"{level} 项目测试覆盖入口", covered, details, "test")


def secret_scan() -> dict[str, Any]:
    private_key_marker = "-----BEGIN " + "PRIVATE KEY-----"
    patterns = [
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        re.compile(re.escape(private_key_marker)),
    ]
    allowed_suffixes = {".py", ".json", ".md", ".txt", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env"}
    excluded = excluded_directories() | {"bug合集"}
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in allowed_suffixes:
            continue
        relative = path.relative_to(ROOT)
        if (
            any(part in excluded for part in relative.parts)
            or (
                len(relative.parts) == 1
                and relative.name.casefold() in LOCAL_SECRET_FILE_NAMES
            )
            or path.stat().st_size > 2_000_000
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in patterns:
            if pattern.search(text):
                findings.append(f"{project_relative(path)} 命中 {pattern.pattern}")
    return result(
        "秘密扫描",
        not findings,
        "\n".join(findings) if findings else "未发现高置信度硬编码秘密。",
        "security",
    )


def dependency_check() -> dict[str, Any]:
    manifests = list(ROOT.glob("requirements*.txt")) + [ROOT / "pyproject.toml"]
    manifests = [path for path in manifests if path.exists()]
    if not manifests:
        return result("Python 依赖一致性", True, "尚无 Python 依赖清单。")
    passed, output = run_command([sys.executable, "-m", "pip", "check"], timeout=120)
    return result("Python 依赖一致性", passed, output, "dependency")


def custom_checks(levels: list[str]) -> list[dict[str, Any]]:
    config = load_config()
    checks: list[dict[str, Any]] = []
    commands = config.get("custom_commands", {})
    for level in levels:
        for entry in commands.get(level, []):
            if not isinstance(entry, dict) or not isinstance(entry.get("argv"), list):
                checks.append(result(f"自定义检查 {level}", False, "配置项必须包含 argv 数组。", "test"))
                continue
            argv = [str(value).replace("{python}", sys.executable) for value in entry["argv"]]
            passed, output = run_command(argv, timeout=int(entry.get("timeout", 300)))
            checks.append(result(str(entry.get("name", "自定义检查")), passed, output, str(entry.get("category", "test"))))
    return checks


def run_checks(level: str, target: str | None = None) -> list[dict[str, Any]]:
    files = selected_files(target)
    checks = [
        check_python_syntax(files),
        check_notebooks(files),
        check_project_json(),
        run_unittest_suite(),
        project_test_coverage("small", files),
    ]
    checks.extend(check_language_runtimes(files))
    levels = ["small"]
    if level in {"medium", "heavy"}:
        checks.append(project_test_coverage("medium", files))
        levels.append("medium")
    if level == "heavy":
        checks.extend(
            (
                project_test_coverage("heavy", files),
                secret_scan(),
                dependency_check(),
            )
        )
        levels.append("heavy")
    checks.extend(custom_checks(levels))
    return checks


def report_paths(level: str, timestamp: str) -> tuple[Path, Path]:
    safe_time = re.sub(r"[^0-9]", "", timestamp)[:14]
    unique = uuid.uuid4().hex[:6]
    base = REPORT_DIR / f"{safe_time}-{level}-{unique}"
    return base.with_suffix(".json"), base.with_suffix(".md")


def write_report(
    level: str,
    checks: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    timestamp = now_iso()
    passed = all(check["passed"] for check in checks)
    report = {
        "schema_version": 2,
        "level": level,
        "passed": passed,
        "created_at": timestamp,
        "source_hash": source_hash(),
        "bug_hash_before_logging": bug_hash(),
        "bug_archive_hash": bug_archive_hash(),
        "metadata": metadata,
        "checks": checks,
    }
    json_path, markdown_path = report_paths(level, timestamp)
    write_json(json_path, report)
    lines = [
        f"# {level} 测试报告",
        "",
        f"- 时间：{timestamp}",
        f"- 结果：{'通过' if passed else '失败'}",
        f"- 源码哈希：`{report['source_hash']}`",
        "",
    ]
    for check in checks:
        lines.extend(
            (
                f"## {'PASS' if check['passed'] else 'FAIL'} - {check['name']}",
                "",
                check["details"] or "无输出。",
                "",
            )
        )
    write_text(markdown_path, "\n".join(lines))
    report["json_path"] = project_relative(json_path)
    report["markdown_path"] = project_relative(markdown_path)
    return report


def failure_scores(level: str, category: str) -> dict[str, int]:
    functional = {"small": 2, "medium": 4, "heavy": 6}[level]
    security = 3 if category == "security" else 0
    scope = {"small": 1, "medium": 2, "heavy": 4}[level]
    return {
        "functional": functional,
        "security": security,
        "scope": scope,
        "probability": 3,
        "recovery": 1,
        "hidden": 0,
    }


def log_failed_checks(level: str, report: dict[str, Any]) -> list[str]:
    bug_ids: list[str] = []
    for check in report["checks"]:
        if check["passed"]:
            continue
        bug_id, repeated = add_bug(
            category=check["category"],
            stage=level,
            title=f"{level} 测试失败：{check['name']}",
            details=check["details"],
            scores=failure_scores(level, check["category"]),
            provisional=True,
        )
        bug_ids.append(f"{bug_id}{'（复发）' if repeated else ''}")
    return bug_ids


def read_state(path: Path) -> dict[str, Any] | None:
    value = read_json(path)
    return value if isinstance(value, dict) else None


def close_active_unit(status: str, report: dict[str, Any] | None = None, reason: str = "") -> None:
    active = read_state(ACTIVE_UNIT_PATH)
    if not active:
        return
    active["status"] = status
    active["closed_at"] = now_iso()
    active["closing_source_hash"] = source_hash()
    active["reason"] = reason
    if report:
        active["report"] = report["json_path"]
        active["passed"] = report["passed"]
    write_json(UNIT_DIR / f"{active['id']}.json", active)
    ACTIVE_UNIT_PATH.unlink(missing_ok=True)


def command_begin_unit(args: argparse.Namespace) -> int:
    ensure_layout()
    current_source_hash = source_hash()
    active = read_state(ACTIVE_UNIT_PATH)
    if active:
        if current_source_hash != active.get("baseline_source_hash"):
            print("拒绝开始新单元：现有活动单元已经修改源码但尚未运行小度测试。", file=sys.stderr)
            return 2
        close_active_unit("aborted", reason="开始新单元前关闭未产生源码改动的旧单元")

    last_tested = read_state(LAST_TESTED_PATH)
    if last_tested and current_source_hash != last_tested.get("source_hash"):
        print(
            "拒绝开始：源码已在没有活动单元的情况下变化。先恢复到最后测试状态，或由人工审查后执行 bootstrap。",
            file=sys.stderr,
        )
        return 2

    bundle = bug_bundle()
    unit_id = f"UNIT-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    state = {
        "schema_version": 1,
        "id": unit_id,
        "status": "active",
        "name": args.name,
        "acceptance": args.acceptance,
        "started_at": now_iso(),
        "baseline_source_hash": current_source_hash,
        "reviewed_bug_hash": bug_hash(),
        "reviewed_bug_archive_hash": bug_archive_hash(),
        "reviewed_bug_files": [project_relative(path) for path in bug_files()],
    }
    write_json(ACTIVE_UNIT_PATH, state)
    print(bundle)
    print(f"\n活动单元：{unit_id}")
    print(f"名称：{args.name}")
    print(f"验收条件：{args.acceptance}")
    print("现在可以编写这个最小可运行单元；完成后必须运行 small。")
    return 0


def command_bootstrap(args: argparse.Namespace) -> int:
    """Establish a reviewed baseline after installation, clone, or manual recovery."""
    ensure_layout()
    active = read_state(ACTIVE_UNIT_PATH)
    if active:
        print("拒绝建立基线：存在活动单元。", file=sys.stderr)
        return 2
    bundle = bug_bundle()
    unit_id = f"BOOTSTRAP-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    state = {
        "schema_version": 1,
        "id": unit_id,
        "status": "active",
        "name": "质量门禁基线",
        "acceptance": args.acceptance,
        "started_at": now_iso(),
        "baseline_source_hash": source_hash(),
        "reviewed_bug_hash": bug_hash(),
        "reviewed_bug_archive_hash": bug_archive_hash(),
        "reviewed_bug_files": [project_relative(path) for path in bug_files()],
        "bootstrap_reason": args.reason,
    }
    write_json(ACTIVE_UNIT_PATH, state)
    print(bundle)
    print(f"\n基线事务：{unit_id}")
    print(f"原因：{args.reason}")
    print("开始执行完整小度测试；只有通过后才能建立新基线。")
    gate_args = argparse.Namespace(
        command="small", file=None, feature=None, version=None
    )
    return command_gate(gate_args)


def command_abort_unit(args: argparse.Namespace) -> int:
    active = read_state(ACTIVE_UNIT_PATH)
    if not active:
        print("当前没有活动单元。")
        return 0
    if source_hash() != active.get("baseline_source_hash"):
        print("不能中止：活动单元已经修改源码，必须运行 small。", file=sys.stderr)
        return 2
    close_active_unit("aborted", reason=args.reason)
    print("活动单元已中止；没有源码改动。")
    return 0


def prerequisite_receipt(level: str) -> tuple[bool, str]:
    prerequisite = "small" if level == "medium" else "medium"
    receipt = read_state(STATE_DIR / f"{prerequisite}.json")
    if not receipt or not receipt.get("passed"):
        return False, f"缺少通过的 {prerequisite} 测试凭证。"
    if receipt.get("source_hash") != source_hash():
        return False, f"源码已在 {prerequisite} 测试后变化。"
    if receipt.get("bug_hash") != bug_hash():
        return False, f"Bug 合集已在 {prerequisite} 测试后变化，必须重新阅读并测试。"
    return True, ""


def command_gate(args: argparse.Namespace) -> int:
    level = args.command
    ensure_layout()
    active = read_state(ACTIVE_UNIT_PATH)
    if level == "small" and not active:
        print("拒绝测试：没有活动单元。先运行 begin-unit。", file=sys.stderr)
        return 2
    if level in {"medium", "heavy"}:
        if active:
            print("拒绝测试：还有未关闭的最小代码单元。", file=sys.stderr)
            return 2
        ready, reason = prerequisite_receipt(level)
        if not ready:
            print(f"拒绝测试：{reason}", file=sys.stderr)
            return 2

    metadata: dict[str, Any] = {}
    if level == "small" and active:
        metadata["unit_id"] = active["id"]
        metadata["unit_name"] = active["name"]
        metadata["acceptance"] = active["acceptance"]
        metadata["reviewed_bug_hash"] = active["reviewed_bug_hash"]
    if getattr(args, "feature", None):
        metadata["feature"] = args.feature
    if getattr(args, "version", None):
        if not re.fullmatch(r"v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", args.version):
            print("版本号必须采用 vX.Y.Z 格式。", file=sys.stderr)
            return 2
        metadata["version"] = args.version

    checks = run_checks(level, getattr(args, "file", None))
    report = write_report(level, checks, metadata)
    bug_ids: list[str] = []
    if not report["passed"]:
        bug_ids = log_failed_checks(level, report)
    report["bug_hash_after_logging"] = bug_hash()
    report["bug_archive_hash"] = bug_archive_hash()
    report["bug_ids"] = bug_ids
    write_json(ROOT / report["json_path"], report)

    receipt = {
        "schema_version": 2,
        "level": level,
        "passed": report["passed"],
        "tested_at": report["created_at"],
        "source_hash": report["source_hash"],
        "bug_hash": report["bug_hash_after_logging"],
        "bug_archive_hash": report["bug_archive_hash"],
        "report": report["json_path"],
        "metadata": metadata,
    }
    write_json(STATE_DIR / f"{level}.json", receipt)
    write_json(LAST_TESTED_PATH, receipt)

    if level == "small":
        close_active_unit("passed" if report["passed"] else "failed", report=report)

    if level == "heavy" and getattr(args, "version", None):
        evidence_json = VERSION_REPORT_DIR / f"{args.version}.json"
        evidence_md = VERSION_REPORT_DIR / f"{args.version}.md"
        write_json(evidence_json, report)
        local_markdown = ROOT / report["markdown_path"]
        write_text(evidence_md, local_markdown.read_text(encoding="utf-8"))

    for check in checks:
        print(f"[{'PASS' if check['passed'] else 'FAIL'}] {check['name']}")
        if not check["passed"]:
            print(check["details"])
    print(f"报告：{report['markdown_path']}")
    if bug_ids:
        print("登记 Bug：" + ", ".join(bug_ids))
    print(f"{level} 测试{'通过' if report['passed'] else '失败'}。")
    return 0 if report["passed"] else 1


def current_receipt(level: str) -> tuple[bool, str]:
    receipt = read_state(STATE_DIR / f"{level}.json")
    if not receipt or not receipt.get("passed"):
        return False, f"缺少通过的 {level} 测试凭证。"
    if receipt.get("source_hash") != source_hash():
        return False, f"源码与最近一次 {level} 测试不一致。"
    if receipt.get("bug_hash") != bug_hash():
        return False, f"Bug 合集与最近一次 {level} 测试不一致。"
    return True, ""


def _is_dirty_staging() -> tuple[bool, str]:
    """Check for source/control files whose worktree != index (D4).

    Returns (dirty, reason).
    """
    try:
        porcelain = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain", "-u"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return True, f"无法执行 git status：{exc}"

    if porcelain.returncode != 0:
        return True, f"git status 失败：{porcelain.stderr.strip() or porcelain.stdout.strip()}"

    for line in porcelain.stdout.splitlines():
        if not line.strip():
            continue
        # XYZ flags: X = staged change, Y = worktree change
        index_flag = line[0] if len(line) > 1 else " "
        worktree_flag = line[1] if len(line) > 1 else " "
        file_path = line[3:].strip()

        # Unresolved merge conflict in staging
        if index_flag in ("U", "A", "D") and worktree_flag in ("U", "A", "D"):
            return True, f"暂存区存在合并冲突：{file_path}"

        candidate = ROOT / file_path
        if not is_source_file(candidate) and file_path not in {
            project_relative(p) for p in control_files()
        }:
            # Also check partial paths for new untracked files
            if not is_source_file(candidate):
                continue

        # Untracked file that hasn't been staged
        if index_flag == "?":
            return True, f"源码文件未跟踪且未暂存：{file_path}"

        # Staging has a different version than worktree (partial staging)
        if index_flag != " " and worktree_flag != " ":
            return True, f"源码文件工作区与暂存区不一致：{file_path}"

    return False, ""


def command_verify_commit(_: argparse.Namespace) -> int:
    if read_state(ACTIVE_UNIT_PATH):
        print("提交被拒绝：存在尚未关闭的代码单元。", file=sys.stderr)
        return 2
    passed, reason = current_receipt("small")
    if not passed:
        print(f"提交被拒绝：{reason}", file=sys.stderr)
        return 2
    dirty, detail = _is_dirty_staging()
    if dirty:
        print(f"提交被拒绝：{detail}。提交前必须将源码全部暂存并与工作区一致。", file=sys.stderr)
        return 2
    print("提交门禁通过：当前源码已有对应的小度测试和 Bug 阅读凭证。")
    return 0


def command_commit_msg(args: argparse.Namespace) -> int:
    message = Path(args.message_file).read_text(encoding="utf-8", errors="replace").strip()
    first_line = message.splitlines()[0] if message else ""
    feature_commit = bool(re.match(r"^(?:feat(?:\([^)]*\))?!?:|功能[:：])", first_line, re.IGNORECASE))
    if not feature_commit:
        return 0
    passed, reason = current_receipt("medium")
    if not passed:
        print(f"功能提交被拒绝：{reason}", file=sys.stderr)
        return 2
    print("功能提交门禁通过：当前源码已有中度测试凭证。")
    return 0


def git_output(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def command_release(args: argparse.Namespace) -> int:
    version = args.version
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
        print("版本号必须采用 vX.Y.Z 格式。", file=sys.stderr)
        return 2
    passed, reason = current_receipt("heavy")
    if not passed:
        print(f"不能发布：{reason}", file=sys.stderr)
        return 2
    receipt = read_state(STATE_DIR / "heavy.json") or {}
    if receipt.get("metadata", {}).get("version") != version:
        print("不能发布：重度测试凭证对应的版本号不同。", file=sys.stderr)
        return 2
    for suffix in (".json", ".md"):
        evidence = VERSION_REPORT_DIR / f"{version}{suffix}"
        if not evidence.exists():
            print(f"不能发布：缺少版本测试证据 {project_relative(evidence)}。", file=sys.stderr)
            return 2
    if git_output("status", "--porcelain"):
        print("不能发布：Git 工作区不干净，请先提交重度测试证据和版本代码。", file=sys.stderr)
        return 2
    try:
        git_output("rev-parse", "--verify", "HEAD")
        git_output("tag", "-a", version, "-m", f"Release {version}: heavy gate passed")
        commit = git_output("rev-parse", "HEAD")
    except RuntimeError as exc:
        print(f"创建版本标签失败：{exc}", file=sys.stderr)
        return 2
    release_state = {
        "version": version,
        "commit": commit,
        "source_hash": source_hash(),
        "bug_hash": bug_hash(),
        "created_at": now_iso(),
        "heavy_report": receipt.get("report"),
    }
    write_json(STATE_DIR / "releases" / f"{version}.json", release_state)
    print(f"已创建经过重度测试的 Git 标签 {version}，提交 {commit[:12]}。")
    return 0


def command_verify_push(_: argparse.Namespace) -> int:
    lines = sys.stdin.read().splitlines()
    for line in lines:
        fields = line.split()
        if len(fields) < 4:
            continue
        local_ref, local_sha, remote_ref, _remote_sha = fields[:4]
        if not local_ref.startswith("refs/tags/") or set(local_sha) == {"0"}:
            continue
        version = local_ref.removeprefix("refs/tags/")
        evidence = read_json(VERSION_REPORT_DIR / f"{version}.json")
        if not isinstance(evidence, dict):
            print(f"推送被拒绝：缺少标签 {version} 的可提交重度测试证据。", file=sys.stderr)
            return 2
        try:
            tag_commit = git_output("rev-list", "-n", "1", local_ref)
            head_commit = git_output("rev-parse", "HEAD")
        except RuntimeError as exc:
            print(f"推送被拒绝：{exc}", file=sys.stderr)
            return 2
        if tag_commit != head_commit:
            print(f"推送被拒绝：标签 {version} 不指向当前经过验证的提交。", file=sys.stderr)
            return 2
        if evidence.get("source_hash") != source_hash() or evidence.get("bug_hash_after_logging") != bug_hash():
            print(f"推送被拒绝：标签 {version} 的测试证据与当前源码或 Bug 合集不一致。", file=sys.stderr)
            return 2
        print(f"版本标签 {version} 的重度测试凭证有效。")
    return 0


# ---------------------------------------------------------------------------
# Hook helpers
# ---------------------------------------------------------------------------

def parse_hook_input() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def hook_json(event: str, *, context: str = "", deny: str = "", block: str = "") -> None:
    payload: dict[str, Any] = {}
    if event == "PreToolUse":
        output: dict[str, Any] = {"hookEventName": event}
        if deny:
            output["permissionDecision"] = "deny"
            output["permissionDecisionReason"] = deny
        elif context:
            output["additionalContext"] = context
        payload["hookSpecificOutput"] = output
    else:
        if block:
            payload["decision"] = "block"
            payload["reason"] = block
        if context:
            payload["hookSpecificOutput"] = {
                "hookEventName": event,
                "additionalContext": context,
            }
    print(json.dumps(payload, ensure_ascii=False))


def _fail_fallback_details(data: dict[str, Any]) -> str:
    """Build fallback error text when tool_name/error fields are empty."""
    compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    compact = redact_secrets(compact)[:2000]
    if compact.strip():
        return compact
    # absolute last resort: list top-level keys so schema drift is diagnosable
    return f"payload top-level keys: {', '.join(sorted(data.keys()))}" if data else "empty payload"


# ---------------------------------------------------------------------------
# hook-pre  (Edit / Write / NotebookEdit / MultiEdit)
# ---------------------------------------------------------------------------

def command_hook_pre(_: argparse.Namespace) -> int:
    data = parse_hook_input()
    tool_input = data.get("tool_input", {})
    target_str = hook_target_path(tool_input)
    if not target_str:
        print("{}")
        return 0

    target = Path(target_str)

    # --- D1: never allow direct writes to protected state dirs ---
    if _is_under_protection(target):
        hook_json(
            "PreToolUse",
            deny=(
                "禁止直接编辑质量门禁状态或 Bug 合集文件。"
                "如需登记错误请使用 tools/run_quality.ps1 log-error；"
                "如需归档请使用 resolve 命令。"
            ),
        )
        return 0

    if not is_source_file(target):
        print("{}")
        return 0

    active = read_state(ACTIVE_UNIT_PATH)
    if not active:
        hook_json(
            "PreToolUse",
            deny="源码写入被质量门禁拒绝：先运行 tools/run_quality.ps1 begin-unit，完整阅读 bug合集并声明验收条件。",
        )
        return 0
    if active.get("reviewed_bug_hash") != bug_hash():
        hook_json(
            "PreToolUse",
            deny="源码写入被拒绝：bug合集在本单元开始后发生变化。先完成或中止当前单元，再重新 begin-unit 阅读全部记录。",
        )
        return 0
    hook_json(
        "PreToolUse",
        context=f"当前活动单元为 {active['id']}（{active['name']}），Bug 全量阅读哈希已验证。完成该最小可运行单元后必须运行 small。",
    )
    return 0


# ---------------------------------------------------------------------------
# hook-pre-bash  (Bash tool Hard Deny – round-1 issues 1&2)
# ---------------------------------------------------------------------------

def _segment_and_tokens(raw: str) -> list[list[str]]:
    """Split a bash line by ; && || | into segments, then tokenize each.

    Redirect operators (> >> < <<) and path separators (/) are preserved as
    part of neighbouring tokens so deny rules can inspect them.
    """
    segments = re.split(r"\s*(?:;|&&|\|\||\|)(?![|=])\s*", raw)
    result: list[list[str]] = []
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        # Tokenize: keep > >> < << as separate tokens, allow / in file paths
        toks = re.findall(
            r"""(?:>>?|<<?)|(?:[^\s"'<>]+|"[^"]*"|'[^']*')+""",
            seg,
        )
        result.append(toks)
    return result


# Read-only git subcommands that are always allowed
_READONLY_GIT_SUBCOMMANDS = {
    "log", "status", "diff", "show", "rev-parse", "rev-list",
    "branch", "tag", "remote", "ls-files", "ls-tree", "cat-file",
    "for-each-ref", "describe", "stash list", "worktree list",
    # "config" is handled separately below — reads are allowed, writes are caught
}


def _check_bash_segment(tokens: list[str], active: dict[str, Any] | None) -> tuple[bool, str]:
    """Return (deny, reason). Empty reason means allow."""
    if not tokens:
        return False, ""

    first = tokens[0].casefold()

    # Always allow quality gate scripts
    if first in ("powershell", "pwsh", "powershell.exe", "pwsh.exe"):
        cmd_line = " ".join(tokens).casefold()
        if "run_quality.ps1" in cmd_line or "quality_gate.py" in cmd_line:
            return False, ""
    if "run_quality.ps1" in first or "quality_gate.py" in first:
        return False, ""

    # Allow read-only git
    if first == "git":
        if len(tokens) >= 2:
            subcmd = tokens[1].casefold()
            # Multi-word subcommands
            if subcmd == "stash" and len(tokens) >= 3 and tokens[2].casefold() == "list":
                return False, ""
            if subcmd == "worktree" and len(tokens) >= 3 and tokens[2].casefold() == "list":
                return False, ""
            if subcmd in _READONLY_GIT_SUBCOMMANDS:
                # special case: config read is ok, config set is caught below
                if subcmd == "config":
                    # if --unset / assignment / set → deny
                    for t in tokens[2:]:
                        if "=" in t or t in ("--unset", "--replace-all", "--add"):
                            break
                    else:
                        # looks like a pure read → allow
                        if not any("=" in t for t in tokens):
                            return False, ""
                else:
                    return False, ""
    # Allow plain dir listing and simple FS reads (no redirects)
    if first in ("ls", "dir", "pwd", "echo", "cat", "head", "tail", "wc"):
        if ">" not in tokens and ">>" not in tokens:
            return False, ""
    # Allow cd / pushd / popd
    if first in ("cd", "pushd", "popd"):
        return False, ""

    # ------------------------------------------------------------------
    # Deny 1: git commit / push with --no-verify
    # ------------------------------------------------------------------
    if first == "git" and len(tokens) >= 2:
        subcmd = tokens[1].casefold()
        if subcmd in ("commit", "push"):
            for t in tokens:
                t_clean = t.lower().lstrip("-")
                if t_clean in ("no-verify", "n"):
                    # git push -n is --dry-run; allow that
                    if subcmd == "push" and t_clean == "n":
                        continue
                    return True, (
                        f"禁止 git {subcmd} 带 --no-verify 参数。"
                        "没有通过质量门禁的提交将被拒绝。"
                    )

    # ------------------------------------------------------------------
    # Deny 2: git config touching core.hooksPath
    # ------------------------------------------------------------------
    if first == "git" and len(tokens) >= 2 and tokens[1].casefold() == "config":
        # build a set of normalized key references
        cmd_text = " ".join(tokens).casefold()
        if "core.hookspath" in cmd_text.replace("-", "").replace("_", ""):
            return True, "禁止通过 git config 修改 core.hooksPath。"

    # ------------------------------------------------------------------
    # Deny 3: remove / rename of gate infrastructure
    # ------------------------------------------------------------------
    if first in ("rm", "del", "remove-item", "mv", "move-item", "rename-item"):
        protected_files = {
            ".githooks", "tools/quality_gate.py", "tools/run_quality.ps1",
            ".claude/settings.json", ".quality-gates.json",
        }
        arg_text = " ".join(tokens[1:]).casefold()
        for pf in protected_files:
            if normalize_sig(pf) in normalize_sig(arg_text):
                return True, f"禁止删除或移动质量门禁基础设施：{pf}"

    # ------------------------------------------------------------------
    # Deny 4: redirect / write targeting protected state paths
    # ------------------------------------------------------------------
    lower_tokens = [t.casefold() for t in tokens]
    has_redirect = (">" in tokens or ">>" in tokens)
    has_file_writer = any(
        w in lower_tokens
        for w in ("tee", "set-content", "add-content", "out-file")
    )
    if has_redirect or has_file_writer:
        # Find the target path: token after > or >> for redirects,
        # or the last path-like argument for tee/Set-Content/Out-File
        target_paths: list[str] = []
        for idx, t in enumerate(tokens):
            if t in (">", ">>") and idx + 1 < len(tokens):
                target_paths.append(tokens[idx + 1])
            elif t.casefold() == "tee" and idx + 1 < len(tokens):
                target_paths.append(tokens[idx + 1])
        # For Set-Content / Add-Content / Out-File, the last non-flag arg is the target
        if has_file_writer:
            for t in reversed(tokens[2:]):
                if not t.startswith("-"):
                    target_paths.append(t)
                    break

        for t in target_paths:
            candidate = Path(t)
            if not candidate.is_absolute():
                candidate = ROOT / t
            try:
                if _is_under_protection(candidate):
                    return True, f"禁止通过 Bash 直接写入质量门禁数据：{t}"

                if is_source_file(candidate):
                    if not active:
                        return True, (
                            f"禁止写入源码 {t}：没有活动单元。"
                            "先运行 tools/run_quality.ps1 begin-unit。"
                        )
                    if active.get("reviewed_bug_hash") != bug_hash():
                        return True, (
                            "源码写入被拒绝：bug合集在本单元开始后发生变化。"
                            "先完成或中止当前单元，再重新 begin-unit。"
                        )
            except (ValueError, OSError):
                pass

    # ------------------------------------------------------------------
    # Deny 5: cp / mv / sed -i to protected or source files
    # ------------------------------------------------------------------
    if first in ("cp", "copy-item", "mv", "move-item", "sed"):
        for t in tokens[1:]:
            if t.startswith("-"):
                continue
            candidate = Path(t)
            if not candidate.is_absolute():
                candidate = ROOT / t
            try:
                if _is_under_protection(candidate):
                    return True, f"禁止通过 Bash 覆盖质量门禁数据：{t}"
            except (ValueError, OSError):
                pass
            try:
                if is_source_file(candidate):
                    if not active:
                        return True, (
                            f"禁止写入源码 {t}：没有活动单元。"
                            "先运行 tools/run_quality.ps1 begin-unit。"
                        )
                    if active.get("reviewed_bug_hash") != bug_hash():
                        return True, (
                            "源码写入被拒绝：bug合集在本单元开始后发生变化。"
                            "先完成或中止当前单元，再重新 begin-unit。"
                        )
            except (ValueError, OSError):
                pass

    # ------------------------------------------------------------------
    # Deny 6: git destructive without active unit
    # ------------------------------------------------------------------
    if first == "git" and len(tokens) >= 2:
        subcmd = tokens[1].casefold()
        if subcmd in ("checkout", "restore", "reset", "clean", "stash"):
            if not active:
                return True, (
                    f"禁止 git {tokens[1]}：没有活动单元。"
                    "先运行 tools/run_quality.ps1 begin-unit。"
                )

    return False, ""


def normalize_sig(s: str) -> str:
    """Reduce to a comparable slug for path matching (lower, no sep, no ext)."""
    return re.sub(r"[\\/_.\-\s]", "", s).casefold()


def command_hook_pre_bash(_: argparse.Namespace) -> int:
    data = parse_hook_input()
    tool_input = data.get("tool_input", {})
    raw = tool_input.get("command", "")
    if not raw:
        print("{}")
        return 0

    active = read_state(ACTIVE_UNIT_PATH)

    for tokens in _segment_and_tokens(raw):
        deny, reason = _check_bash_segment(tokens, active)
        if deny:
            hook_json("PreToolUse", deny=reason)
            return 0

    # If we get here and there's an active unit, inject context
    if active:
        hook_json(
            "PreToolUse",
            context=f"当前活动单元为 {active['id']}（{active['name']}），Bug 全量阅读哈希已验证。",
        )
        return 0

    print("{}")
    return 0


# ---------------------------------------------------------------------------
# hook-failure  (D3 – robust field extraction)
# ---------------------------------------------------------------------------

def command_hook_failure(_: argparse.Namespace) -> int:
    data = parse_hook_input()
    if data.get("is_interrupt"):
        print("{}")
        return 0

    # Try every plausible field name for the tool name
    tool_name = "unknown-tool"
    for key in ("tool_name", "toolName", "tool"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            tool_name = val.strip()
            break

    # Try every plausible field for the error body
    error = ""
    for key in ("error", "error_message", "message", "result"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            error = val.strip()
            break

    # If still empty, try nested paths: tool_response.error / tool_response.stderr
    if not error:
        tr = data.get("tool_response")
        if isinstance(tr, dict):
            for sub in ("error", "stderr", "stdout"):
                val = tr.get(sub)
                if isinstance(val, str) and val.strip():
                    error = val.strip()
                    break
            # last resort: dump the whole tool_response as compact JSON
            if not error:
                error = json.dumps(tr, ensure_ascii=False, separators=(",", ":"))[:2000]

    # Fallback: full payload dump so signature is unique
    if not error or error.strip() == "未提供错误信息":
        error = _fail_fallback_details(data)

    if not error.strip():
        error = "工具调用失败，未返回错误详情。"

    lowered = tool_name.casefold()
    if "search" in lowered or "knowledge" in lowered or "memory" in lowered:
        category = "knowledge"
    elif tool_name.startswith("mcp__"):
        category = "tool"
    else:
        category = "agent"

    bug_id, repeated = add_bug(
        category=category,
        stage="agent-tool-call",
        title=f"Agent 工具调用失败：{tool_name}",
        details=error,
        scores={
            "functional": 1,
            "security": 0,
            "scope": 1,
            "probability": 1,
            "recovery": 1,
            "hidden": 0,
        },
        provisional=True,
        receipt_binding=False,
    )
    hook_json(
        "PostToolUseFailure",
        context=(
            f"该失败已永久登记为 {bug_id}{'（复发）' if repeated else ''}。"
            "此记录不影响测试凭证；继续修改源码前必须重新执行 begin-unit 阅读完整 bug合集。"
        ),
    )
    return 0


# ---------------------------------------------------------------------------
# hook-stop
# ---------------------------------------------------------------------------

def command_hook_stop(_: argparse.Namespace) -> int:
    data = parse_hook_input()
    if data.get("stop_hook_active"):
        print("{}")
        return 0
    active = read_state(ACTIVE_UNIT_PATH)
    if active:
        hook_json(
            "Stop",
            block=f"活动单元 {active['id']} 尚未关闭。完成代码后运行 small；若没有源码改动则运行 abort-unit。",
        )
        return 0
    latest = read_state(STATE_DIR / "small.json")
    if iter_source_files() and (
        not latest
        or not latest.get("passed")
        or latest.get("source_hash") != source_hash()
        or latest.get("bug_hash") != bug_hash()
    ):
        hook_json("Stop", block="当前源码或 bug合集没有对应的小度测试凭证，不能结束编码任务。")
        return 0
    print("{}")
    return 0


# ---------------------------------------------------------------------------
# log-error
# ---------------------------------------------------------------------------

def command_log_error(args: argparse.Namespace) -> int:
    scores = {key: getattr(args, key) for key in SCORE_LIMITS}
    bug_id, repeated = add_bug(
        category=args.category,
        stage=args.stage,
        title=args.title,
        details=args.details,
        scores=scores,
        provisional=not args.reviewed,
    )
    print(f"已登记 {bug_id}{'（复发）' if repeated else ''}，评分记录永久保留。")
    return 0


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def command_status(_: argparse.Namespace) -> int:
    active = read_state(ACTIVE_UNIT_PATH)
    print(f"源码哈希：{source_hash()}")
    print(f"Bug 哈希（凭证绑定）：{bug_hash()}")
    print(f"Bug 哈希（全量归档）：{bug_archive_hash()}")
    print(f"活动单元：{active['id'] if active else '无'}")
    for level in ("small", "medium", "heavy"):
        passed, reason = current_receipt(level)
        print(f"{level}: {'有效' if passed else '无效'}{'' if passed else ' - ' + reason}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    begin = subparsers.add_parser("begin-unit", help="全量阅读 Bug 并开始最小代码单元")
    begin.add_argument("--name", required=True)
    begin.add_argument("--acceptance", required=True)
    begin.set_defaults(handler=command_begin_unit)

    bootstrap = subparsers.add_parser("bootstrap", help="克隆或恢复后建立可信基线")
    bootstrap.add_argument("--reason", required=True)
    bootstrap.add_argument("--acceptance", required=True)
    bootstrap.set_defaults(handler=command_bootstrap)

    abort = subparsers.add_parser("abort-unit", help="中止没有源码改动的活动单元")
    abort.add_argument("--reason", required=True)
    abort.set_defaults(handler=command_abort_unit)

    small = subparsers.add_parser("small", help="运行小度测试")
    small.add_argument("--file")
    small.set_defaults(handler=command_gate)

    medium = subparsers.add_parser("medium", help="运行中度测试")
    medium.add_argument("--feature", required=True)
    medium.set_defaults(handler=command_gate)

    heavy = subparsers.add_parser("heavy", help="运行重度测试")
    heavy.add_argument("--version", required=True)
    heavy.set_defaults(handler=command_gate)

    log_error = subparsers.add_parser("log-error", help="永久登记错误")
    log_error.add_argument("--category", required=True)
    log_error.add_argument("--stage", required=True)
    log_error.add_argument("--title", required=True)
    log_error.add_argument("--details", required=True)
    for key, limit in SCORE_LIMITS.items():
        log_error.add_argument(f"--{key}", type=int, choices=range(limit + 1), required=True)
    log_error.add_argument("--reviewed", action="store_true", help="评分已经人工复核")
    log_error.set_defaults(handler=command_log_error)

    resolve = subparsers.add_parser("resolve", help="归档已解决 Bug")
    resolve.add_argument("bug_id")
    resolve.add_argument("--reason", required=True)
    resolve.add_argument("--verification", required=True)
    resolve.set_defaults(
        handler=lambda args: (resolve_bug(args.bug_id, args.reason, args.verification) or 0)
    )

    subparsers.add_parser("verify-commit").set_defaults(handler=command_verify_commit)
    commit_msg = subparsers.add_parser("verify-commit-message")
    commit_msg.add_argument("message_file")
    commit_msg.set_defaults(handler=command_commit_msg)
    subparsers.add_parser("verify-push").set_defaults(handler=command_verify_push)

    release = subparsers.add_parser("release", help="创建通过重度测试的 Git 标签")
    release.add_argument("version")
    release.set_defaults(handler=command_release)

    subparsers.add_parser("hook-pre").set_defaults(handler=command_hook_pre)
    subparsers.add_parser("hook-pre-bash").set_defaults(handler=command_hook_pre_bash)
    subparsers.add_parser("hook-failure").set_defaults(handler=command_hook_failure)
    subparsers.add_parser("hook-stop").set_defaults(handler=command_hook_stop)
    subparsers.add_parser("status").set_defaults(handler=command_status)
    return parser


def main() -> int:
    ensure_layout()
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"质量门禁错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
