"""Migrate the previous simplified quality history into the v2 schema."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BUG_DIR = ROOT / "bug合集"
CATALOG_PATH = BUG_DIR / "catalog.json"
LEGACY_PATH = BUG_DIR / "迁移" / "legacy-catalog-v1.json"


def _score() -> dict[str, int]:
    """Return a conservative provisional score for a historical test failure."""
    return {"functional": 2, "security": 0, "scope": 1, "probability": 1, "recovery": 1, "hidden": 0}


def _grade(total: int) -> tuple[str, str]:
    if total >= 20:
        return "S", "致命"
    if total >= 17:
        return "A", "高危"
    if total >= 13:
        return "B", "严重"
    if total >= 9:
        return "C", "中等"
    if total >= 5:
        return "D", "轻微"
    return "E", "提示"


def convert_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Convert one legacy issue while retaining its original report reference."""
    issue_id = str(issue.get("id", "BUG-0000"))
    created_at = str(issue.get("created_at", "迁移时未知"))
    failed_checks = issue.get("failed_checks", [])
    details = "旧版质量门禁失败记录，已迁移到 v2 Bug 合集。"
    if failed_checks:
        details += "\n失败检查：\n" + "\n".join(f"- {item}" for item in failed_checks)
    if issue.get("report"):
        details += f"\n旧版报告：{issue['report']}"
    scores = _score()
    total = sum(scores.values())
    grade, severity = _grade(total)
    signature = hashlib.sha256(
        f"legacy-quality-gate|{issue_id}|{issue.get('title', '')}|{details}".encode("utf-8")
    ).hexdigest()[:20]
    return {
        "id": issue_id,
        "signature": signature,
        "status": "resolved" if issue.get("status") == "resolved" else "open",
        "title": str(issue.get("title", "历史质量门禁失败")),
        "category": "test",
        "stage": str(issue.get("stage", "migration")),
        "score": scores,
        "total": total,
        "grade": grade,
        "severity": severity,
        "provisional": True,
        "receipt_binding": False,
        "first_seen": created_at,
        "last_seen": created_at,
        "details": details,
        "cause": "",
        "resolution": "",
        "verification": "历史记录由简化质量门禁产生，迁移本身不宣称原失败已修复。",
        "occurrences": [{"at": created_at, "details": details}],
    }


def migrate() -> bool:
    """Migrate the legacy catalog and render v2 records and index."""
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if "bugs" in catalog:
        return False
    issues = catalog.get("issues")
    if not isinstance(issues, list):
        raise ValueError("未找到可迁移的旧版 issues 目录")
    LEGACY_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEGACY_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools import quality_gate

    migrated = {
        "schema_version": 1,
        "next_id": max((int(str(item.get("id", "BUG-0000")).split("-")[-1]) for item in issues), default=0) + 1,
        "bugs": [convert_issue(item) for item in issues],
    }
    quality_gate.ensure_layout()
    quality_gate.rebuild_bug_files(migrated)
    return True


def main() -> int:
    """Run the one-time migration command."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    print("已迁移旧版质量历史。" if migrate() else "质量历史已经是 v2 格式，无需迁移。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
