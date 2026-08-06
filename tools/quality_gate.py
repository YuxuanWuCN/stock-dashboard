#!/usr/bin/env python3
"""Three-level, reproducible code-quality gates for this project."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / ".quality-gates.json"
STATE_DIR = ROOT / ".quality-state"
REPORT_DIR = STATE_DIR / "reports"
ACTIVE_UNIT_PATH = STATE_DIR / "active-unit.json"
LAST_TESTED_PATH = STATE_DIR / "last-tested.json"
BUG_DIR = ROOT / "bug合集"
BUG_CATALOG_PATH = BUG_DIR / "catalog.json"


def now_iso() -> str:
    """Return a timezone-aware timestamp for receipts and reports."""
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path, default: Any = None) -> Any:
    """Read UTF-8 JSON, returning the supplied default only when absent."""
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    """Atomically write a UTF-8 JSON document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def ensure_layout() -> None:
    """Create state and issue-history directories on first use."""
    for directory in (STATE_DIR, REPORT_DIR, BUG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    if not BUG_CATALOG_PATH.exists():
        write_json(BUG_CATALOG_PATH, {"schema_version": 1, "next_id": 1, "issues": []})


def load_config() -> dict[str, Any]:
    """Load and validate the project quality-gate configuration."""
    config = read_json(CONFIG_PATH)
    if not isinstance(config, dict):
        raise RuntimeError(f"Missing or invalid quality config: {CONFIG_PATH}")

    required_lists = ("source_roots", "source_extensions", "exclude_directories")
    for key in required_lists:
        if not isinstance(config.get(key), list):
            raise RuntimeError(f"Quality config field must be a list: {key}")
    if not isinstance(config.get("commands"), dict):
        raise RuntimeError("Quality config field must be an object: commands")
    return config


def iter_source_files(config: dict[str, Any]) -> list[Path]:
    """Find configured source files without descending into generated directories."""
    excluded = set(config["exclude_directories"])
    extensions = set(config["source_extensions"])
    files: list[Path] = []
    for root_name in config["source_roots"]:
        source_root = ROOT / root_name
        if not source_root.exists():
            continue
        for path in source_root.rglob("*"):
            if not path.is_file() or path.suffix not in extensions:
                continue
            if any(part in excluded for part in path.parts):
                continue
            files.append(path)
    return sorted(files)


def display_path(path: Path) -> str:
    """Return a project-relative path when possible, otherwise an absolute path."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def source_hash(config: dict[str, Any]) -> str:
    """Hash source, configuration, and dependency declarations for a receipt."""
    digest = hashlib.sha256()
    candidates = iter_source_files(config) + [CONFIG_PATH, ROOT / "requirements.txt"]
    for path in sorted({path for path in candidates if path.exists()}):
        digest.update(str(path.relative_to(ROOT)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def check_python_syntax(files: list[Path]) -> dict[str, Any]:
    """Compile all Python source files and report every syntax error."""
    errors: list[str] = []
    python_files = [path for path in files if path.suffix == ".py"]
    for path in python_files:
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except (SyntaxError, UnicodeDecodeError) as exc:
            errors.append(f"{display_path(path)}: {exc}")
    return {
        "name": "python_syntax",
        "passed": not errors,
        "detail": f"Checked {len(python_files)} Python files." if not errors else "\n".join(errors),
    }


def check_javascript_syntax(files: list[Path]) -> dict[str, Any]:
    """Use Node.js to parse every configured JavaScript source file."""
    javascript_files = [path for path in files if path.suffix == ".js"]
    if not javascript_files:
        return {"name": "javascript_syntax", "passed": True, "detail": "No JavaScript files."}

    node = shutil.which("node")
    if node is None:
        return {
            "name": "javascript_syntax",
            "passed": False,
            "detail": "Node.js is required to check configured JavaScript files.",
        }

    errors: list[str] = []
    for path in javascript_files:
        completed = subprocess.run(
            [node, "--check", str(path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            errors.append(f"{display_path(path)}: {(completed.stderr or completed.stdout).strip()}")
    return {
        "name": "javascript_syntax",
        "passed": not errors,
        "detail": f"Checked {len(javascript_files)} JavaScript files." if not errors else "\n".join(errors),
    }


def check_json_config() -> dict[str, Any]:
    """Ensure the gate configuration is valid before subsequent checks use it."""
    try:
        load_config()
    except (OSError, ValueError, RuntimeError) as exc:
        return {"name": "quality_config", "passed": False, "detail": str(exc)}
    return {"name": "quality_config", "passed": True, "detail": "Configuration is valid."}


def run_command(command: str) -> dict[str, Any]:
    """Run one user-owned configured validation command and retain its output."""
    rendered = command.format(python=sys.executable)
    try:
        completed = subprocess.run(
            rendered,
            cwd=ROOT,
            shell=True,
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"name": rendered, "passed": False, "detail": "Timed out after 300 seconds."}

    output = (completed.stdout + completed.stderr).strip()
    return {
        "name": rendered,
        "passed": completed.returncode == 0,
        "detail": output[-8000:] if output else "No output.",
    }


def run_checks(level: str) -> tuple[list[dict[str, Any]], str]:
    """Run the configured checks for a gate level and return source hash evidence."""
    config = load_config()
    files = iter_source_files(config)
    checks = [
        check_json_config(),
        check_python_syntax(files),
        check_javascript_syntax(files),
    ]

    levels = ["small"]
    if level in {"medium", "heavy"}:
        levels.append("medium")
    if level == "heavy":
        levels.append("heavy")

    for current_level in levels:
        commands = config["commands"].get(current_level, [])
        if not isinstance(commands, list) or not commands:
            checks.append({
                "name": f"{current_level}_commands",
                "passed": False,
                "detail": "No configured validation command.",
            })
            continue
        checks.extend(run_command(str(command)) for command in commands)

    if level == "heavy":
        checks.append(run_command('"{python}" -m pip check'))
    return checks, source_hash(config)


def write_report(level: str, report: dict[str, Any]) -> Path:
    """Write a non-overwriting report for every gate invocation."""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = REPORT_DIR / f"{stamp}-{level}-{uuid.uuid4().hex[:8]}.json"
    write_json(path, report)
    return path


def record_failure(level: str, checks: list[dict[str, Any]], report_path: Path) -> None:
    """Keep a permanent issue record for failed quality gates."""
    catalog = read_json(BUG_CATALOG_PATH, {"schema_version": 1, "next_id": 1, "issues": []})
    failed_names = [check["name"] for check in checks if not check["passed"]]
    issue_id = f"BUG-{int(catalog['next_id']):04d}"
    catalog["next_id"] = int(catalog["next_id"]) + 1
    catalog["issues"].append({
        "id": issue_id,
        "status": "open",
        "created_at": now_iso(),
        "stage": level,
        "title": "Quality gate failed",
        "failed_checks": failed_names,
        "report": str(report_path.relative_to(ROOT)).replace("\\", "/"),
    })
    write_json(BUG_CATALOG_PATH, catalog)


def close_active_unit_after_heavy_gate(level: str) -> None:
    """Close the current unit only after the final quality gate succeeds."""
    if level == "heavy":
        ACTIVE_UNIT_PATH.unlink(missing_ok=True)


def command_begin_unit(args: argparse.Namespace) -> int:
    """Create a review receipt before a scoped source change."""
    ensure_layout()
    config = load_config()
    active = {
        "name": args.name,
        "acceptance": args.acceptance,
        "started_at": now_iso(),
        "source_hash_before": source_hash(config),
        "open_issue_count": len(read_json(BUG_CATALOG_PATH)["issues"]),
    }
    write_json(ACTIVE_UNIT_PATH, active)
    print(f"Started quality unit: {args.name}")
    return 0


def command_gate(args: argparse.Namespace) -> int:
    """Run one gate level and save a reproducible receipt."""
    ensure_layout()
    checks, current_hash = run_checks(args.command)
    passed = all(check["passed"] for check in checks)
    report = {
        "schema_version": 1,
        "timestamp": now_iso(),
        "level": args.command,
        "passed": passed,
        "source_hash": current_hash,
        "checks": checks,
    }
    report_path = write_report(args.command, report)
    if passed:
        write_json(LAST_TESTED_PATH, {
            "timestamp": report["timestamp"],
            "level": args.command,
            "source_hash": current_hash,
            "report": str(report_path.relative_to(ROOT)).replace("\\", "/"),
        })
        close_active_unit_after_heavy_gate(args.command)
        print(f"{args.command} gate passed: {report_path.relative_to(ROOT)}")
        return 0

    record_failure(args.command, checks, report_path)
    print(f"{args.command} gate failed: {report_path.relative_to(ROOT)}", file=sys.stderr)
    return 1


def command_bootstrap(_: argparse.Namespace) -> int:
    """Establish a first baseline by running the small gate."""
    return command_gate(argparse.Namespace(command="small"))


def command_status(_: argparse.Namespace) -> int:
    """Display the latest receipt, active unit, and open issue count."""
    ensure_layout()
    catalog = read_json(BUG_CATALOG_PATH)
    status = {
        "active_unit": read_json(ACTIVE_UNIT_PATH),
        "last_tested": read_json(LAST_TESTED_PATH),
        "open_issues": sum(issue.get("status") == "open" for issue in catalog["issues"]),
    }
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    begin = subparsers.add_parser("begin-unit", help="Record the scope and acceptance criteria")
    begin.add_argument("--name", required=True)
    begin.add_argument("--acceptance", required=True)
    begin.set_defaults(handler=command_begin_unit)

    subparsers.add_parser("bootstrap", help="Create a baseline using the small gate").set_defaults(handler=command_bootstrap)
    for level in ("small", "medium", "heavy"):
        subparsers.add_parser(level, help=f"Run the {level} quality gate").set_defaults(handler=command_gate)
    subparsers.add_parser("status", help="Show quality-gate state").set_defaults(handler=command_status)
    return parser


def main() -> int:
    """Run the selected quality-gate command."""
    try:
        args = build_parser().parse_args()
        return args.handler(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Quality gate error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
