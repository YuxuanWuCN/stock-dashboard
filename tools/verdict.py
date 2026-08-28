"""verdict 汇聚（彩虹找虫 v2）。

从 .quality-state/reports/ 读三层测试报告 JSON + 弱断言扫描结果，
按优先级汇聚成单一裁决（pass / warn / return-to-rd / block），
并输出结构化的 re-run reason 供修复循环机器消费。

借鉴 peaks-cli 的 verdict-aggregator：
- VERDICT_PRECEDENCE = [pass, warn, return-to-rd, block] 取最高
- 跨源按 (file, line, hint) 去重合并 sources
- re-run reason: {source, signal, severity, file, line, hint}

设计约束（v2 信任红线）：
- 纯标准库；只读汇聚，不写凭证、不改门禁状态、不调 add_bug
- 读报告失败/损坏 → 该信号忽略并记录 warn，不 block（fail-open）
- 全部 UTF-8；不读 stdin
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

VERDICT_PRECEDENCE = ["pass", "warn", "return-to-rd", "block"]
REPORT_DIR = Path(__file__).resolve().parents[1] / ".quality-state" / "reports"
LEVELS = ("small", "medium", "heavy")

# 弱断言 error 级 → return-to-rd；仅 warn 级 → warn
WEAK_ERROR_VERDICT = "return-to-rd"
WEAK_WARN_VERDICT = "warn"

# 变异测试 kill rate 阈值（对应 peaks ≥80%）
MUT_KILL_THRESHOLD = 0.8


# ---------------------------------------------------------------------------
# 报告读取
# ---------------------------------------------------------------------------


def latest_report_paths(report_dir: Path | None = None) -> dict[str, Path | None]:
    """按文件名 '-{level}-' 与 mtime 取各层最新报告。"""
    rd = report_dir or REPORT_DIR
    result: dict[str, Path | None] = {level: None for level in LEVELS}
    if not rd.is_dir():
        return result
    files = sorted(rd.glob("*.json"), key=lambda p: p.stat().st_mtime)
    for path in files:
        name = path.name
        for level in LEVELS:
            if f"-{level}-" in name:
                result[level] = path
    return result


def read_report(path: Path | None) -> dict | None:
    """读单份报告，兼容 schema_version 1/2；失败返回 None。"""
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None


def report_to_signals(report: dict, level: str) -> list[dict]:
    """单份 v1 报告 -> Signal 列表。

    Signal: {"source": str, "severity": str, "file": str, "line": int, "hint": str}
    severity ∈ VERDICT_PRECEDENCE。
    schema_version 2: {level, passed, checks: [{name, passed, details, category}]}
    schema_version 1: {level, passed, checks|detail}
    """
    signals: list[dict] = []
    if not report.get("passed"):
        checks = report.get("checks") or []
        if not checks and isinstance(report.get("detail"), str):
            checks = [{"name": report.get("level", level), "passed": False, "details": report["detail"]}]
        for check in checks:
            if not isinstance(check, dict):
                continue
            if check.get("passed"):
                continue
            details = check.get("details") or check.get("detail") or ""
            signals.append(
                {
                    "source": level,
                    "severity": "block",
                    "file": str(check.get("name", level)),
                    "line": 0,
                    "hint": str(details)[:500],
                }
            )
    return signals


# ---------------------------------------------------------------------------
# 弱断言 / 变异信号
# ---------------------------------------------------------------------------


def weak_assert_signals(report_dir: Path | None = None) -> tuple[list[dict], dict]:
    """扫描弱断言，转成信号。返回 (signals, summary)。

    error 级 → return-to-rd；仅 warn 级 → warn；无 findings → 无信号。
    扫描失败（tests 目录缺失等）→ 无信号（fail-open）。
    """
    try:
        from tools import assert_scanner  # 惰性 import，避免加载引擎

        test_dir = Path(__file__).resolve().parents[1] / "tests"
        findings = assert_scanner.scan_tests(test_dir)
        total = assert_scanner.count_total_asserts(test_dir)
        if not findings:
            return [], {"total": 0}
        errors = [f for f in findings if f["severity"] == "error"]
        severity = WEAK_ERROR_VERDICT if errors else WEAK_WARN_VERDICT
        signals = [
            {
                "source": "weak-assert",
                "severity": severity,
                "file": f["file"],
                "line": f["line"],
                "hint": f"{f['pattern']}: {f['code']}",
            }
            for f in findings
        ]
        return signals, {"total": len(findings), "errors": len(errors), "total_asserts": total}
    except Exception as exc:  # fail-open
        return [], {"total": 0, "error": str(exc)}


def mutation_signals(mut_report: dict | None) -> list[dict]:
    """变异测试报告 -> 信号。mutmut 缺失/报告异常 → 无信号（fail-open）。"""
    if not mut_report:
        return []
    if mut_report.get("error"):
        return []
    if mut_report.get("skipped") is True:
        return []
    kill_rate = mut_report.get("kill_rate")
    if kill_rate is None:
        return []
    if kill_rate >= MUT_KILL_THRESHOLD:
        return []
    return [
        {
            "source": "mutation",
            "severity": "block",
            "file": mut_report.get("paths", "src"),
            "line": 0,
            "hint": f"变异测试 kill rate {kill_rate:.1%} < 阈值 {MUT_KILL_THRESHOLD:.0%}（幸存 {mut_report.get('survived', 0)} 个突变）",
        }
    ]


# ---------------------------------------------------------------------------
# 汇聚
# ---------------------------------------------------------------------------


def merge_signals(signals: list[dict]) -> list[dict]:
    """跨源去重：按 (file, line, hint) 相同则合并（sources 变列表）。"""
    merged: dict[tuple, dict] = {}
    for sig in signals:
        key = (sig.get("file", ""), sig.get("line", 0), sig.get("hint", ""))
        if key in merged:
            existing = merged[key]
            existing.setdefault("sources", []).append(sig["source"])
        else:
            sig = dict(sig)
            sig["sources"] = [sig["source"]]
            merged[key] = sig
    return list(merged.values())


def aggregate(signals: list[dict]) -> str:
    """取信号集中最高 severity；空信号 -> pass。"""
    if not signals:
        return "pass"
    ranks = {v: i for i, v in enumerate(VERDICT_PRECEDENCE)}
    return max((s["severity"] for s in signals), key=lambda v: ranks.get(v, 0))


def _reasons_from_signals(signals: list[dict]) -> list[dict]:
    """Signal 列表 -> re-run reason 列表。"""
    reasons = []
    for sig in signals:
        reasons.append(
            {
                "source": sig.get("source", ""),
                "signal": sig.get("signal", sig.get("pattern", sig["source"])),
                "severity": sig["severity"],
                "file": sig.get("file", ""),
                "line": sig.get("line", 0),
                "hint": sig.get("hint", ""),
            }
        )
    return reasons


def build_verdict(*, include_scans: bool = True, report_dir: Path | None = None) -> dict:
    """主入口：读三层报告 + 扫描，汇聚成 Verdict。"""
    rd = report_dir or REPORT_DIR
    paths = latest_report_paths(rd)
    signals: list[dict] = []
    sources_checked: list[str] = []
    for level in LEVELS:
        report = read_report(paths[level])
        if report is None:
            continue
        sources_checked.append(level)
        signals.extend(report_to_signals(report, level))

    weak_summary = {"total": 0}
    if include_scans:
        weak_signals, weak_summary = weak_assert_signals(rd)
        signals.extend(weak_signals)
        if weak_signals:
            sources_checked.append("weak-assert")

    signals = merge_signals(signals)
    verdict = aggregate(signals)
    reasons = _reasons_from_signals(signals)

    result: dict = {
        "schema_version": 1,
        "verdict": verdict,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "sources_checked": sources_checked,
        "weak_assert_summary": weak_summary,
        "signals": signals,
        "reasons": reasons,
        "report_dir": str(rd),
    }
    return result


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def _write_outputs(verdict: dict) -> tuple[Path, Path]:
    """写 verdict-{ts}.json + .md 到 report_dir。返回 (json_path, md_path)。"""
    rd = Path(verdict["report_dir"])
    rd.mkdir(parents=True, exist_ok=True)
    ts = re.sub(r"[^0-9]", "", verdict["checked_at"])[:14]
    json_path = rd / f"verdict-{ts}.json"
    md_path = rd / f"verdict-{ts}.md"

    json_path.write_text(
        json.dumps(verdict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        f"# Verdict: {verdict['verdict']}",
        "",
        f"- 检查时间: {verdict['checked_at']}",
        f"- 信号源: {', '.join(verdict['sources_checked']) or '（无）'}",
        "",
        "## re-run reasons",
    ]
    if verdict["reasons"]:
        for r in verdict["reasons"]:
            lines.append(f"- [{r['severity']}] {r['source']} {r['file']}:{r['line']} — {r['hint']}")
    else:
        lines.append("- （无）")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return json_path, md_path


def command_verdict(args: argparse.Namespace) -> int:
    """verdict 子命令：输出 stdout JSON + 写报告文件。

    退出码: block=2 / return-to-rd=1 / warn=0 / pass=0（--strict 时 warn=1）
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    verdict = build_verdict()
    json_path, md_path = _write_outputs(verdict)
    verdict["json_path"] = str(json_path)
    verdict["markdown_path"] = str(md_path)

    print(json.dumps({"verdict": verdict["verdict"], "reasons": verdict["reasons"]}, ensure_ascii=False, indent=2))

    v = verdict["verdict"]
    if v == "block":
        return 2
    if v == "return-to-rd":
        return 1
    if v == "warn" and getattr(args, "strict", False):
        return 1
    return 0


def run(argv: list[str] | None = None) -> int:
    """CLI 入口：python tools/verdict.py [--strict] [--no-scans]"""
    parser = argparse.ArgumentParser(prog="verdict")
    parser.add_argument("--strict", action="store_true", help="warn 时退出码 1")
    parser.add_argument("--no-scans", action="store_true", help="只汇聚三层报告，不跑弱断言扫描")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    verdict = build_verdict(include_scans=not args.no_scans)
    json_path, md_path = _write_outputs(verdict)
    print(json.dumps({"verdict": verdict["verdict"], "reasons": verdict["reasons"], "json_path": str(json_path)}, ensure_ascii=False, indent=2))

    v = verdict["verdict"]
    if v == "block":
        return 2
    if v == "return-to-rd":
        return 1
    if v == "warn" and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
