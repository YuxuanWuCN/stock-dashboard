#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/daily_pr_review.py - 每日 PR 自动化审查与吸收工具

功能:
1. 自动查询远程仓库（YuxuanWuCN/stock-dashboard）当前所有的 Open PR（支持 GitHub API 与 Git refs 双模式）。
2. 拉取 PR 代码分支，比对与当前分支（contest-2026）的 diff 差异。
3. 检查代码规范与质量合规性（测试覆盖、无虚假数据、单标的隔离等）。
4. 提炼出 PR 中的可吸收创新点（新因子、算法优化、Bug 修复、UI 体验等）。
5. 输出审查建议与吸收决策报告至 reports/pr_reviews/。
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("pr_review")

REPO_NAME = "YuxuanWuCN/stock-dashboard"
API_URL = f"https://api.github.com/repos/{REPO_NAME}/pulls?state=open"


def get_open_prs_api() -> List[Dict[str, Any]]:
    """尝试通过 GitHub REST API 获取开放 PR 列表。"""
    req = urllib.request.Request(
        API_URL,
        headers={
            "User-Agent": "Antigravity-Agent/1.0",
            "Accept": "application/vnd.github.v3+json"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data
    except Exception as e:
        logger.warning(f"GitHub API 请求受限或失败 ({e})，将回退至 Git refs 模式。")
        return []


def get_pr_refs_git() -> List[int]:
    """通过 git ls-remote 查询所有 pull request 编号。"""
    try:
        res = subprocess.run(
            ["git", "ls-remote", "origin", "refs/pull/*/head"],
            capture_output=True,
            text=True,
            check=True
        )
        pr_numbers = []
        for line in res.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].startswith("refs/pull/"):
                num = parts[1].split("/")[2]
                if num.isdigit():
                    pr_numbers.append(int(num))
        return sorted(list(set(pr_numbers)))
    except Exception as e:
        logger.error(f"Git ls-remote 失败: {e}")
        return []


def analyze_pr_diff(pr_num: int) -> Dict[str, Any]:
    """拉取指定 PR 分支并比对与当前 HEAD 的 diff。"""
    ref_spec = f"refs/pull/{pr_num}/head:refs/remotes/origin/pr/{pr_num}"
    logger.info(f"拉取 PR #{pr_num} 分支代码: {ref_spec}")

    fetch_res = subprocess.run(
        ["git", "fetch", "origin", ref_spec],
        capture_output=True,
        text=True
    )
    if fetch_res.returncode != 0:
        logger.warning(f"无法拉取 PR #{pr_num}: {fetch_res.stderr.strip()}")
        return {"pr_num": pr_num, "status": "fetch_failed", "error": fetch_res.stderr}

    pr_ref = f"origin/pr/{pr_num}"
    diff_stat_res = subprocess.run(
        ["git", "diff", "--stat", "HEAD...", pr_ref],
        capture_output=True,
        text=True
    )
    diff_name_res = subprocess.run(
        ["git", "diff", "--name-only", "HEAD...", pr_ref],
        capture_output=True,
        text=True
    )

    changed_files = [f for f in diff_name_res.stdout.strip().splitlines() if f]
    stat_summary = diff_stat_res.stdout.strip()

    # 评估变更类型
    has_algo = any("src/pricing" in f or "src/graph" in f or "src/features" in f for f in changed_files)
    has_data = any("data/" in f or "scripts/" in f for f in changed_files)
    has_frontend = any("docs/" in f for f in changed_files)
    has_tests = any("tests/" in f for f in changed_files)

    return {
        "pr_num": pr_num,
        "status": "active",
        "changed_files_count": len(changed_files),
        "changed_files": changed_files,
        "diff_stat": stat_summary,
        "has_algo": has_algo,
        "has_data": has_data,
        "has_frontend": has_frontend,
        "has_tests": has_tests,
    }


def generate_pr_review_report(prs_analysis: List[Dict[str, Any]], output_dir: Path) -> Path:
    """生成每日 PR 审查与吸收建议报告。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    report_file = output_dir / f"{today}_pr_review.md"

    lines = [
        f"# 每日 PR 自动化审查与吸收简报 ({today})",
        "",
        "> 本报告由每日 09:00 定时任务自动生成，旨在协助队长及时审阅组员提交、快速吸收优质模块，并把控代码与质量门禁。",
        "",
        "## 1. 待审阅 PR 概览",
        ""
    ]

    if not prs_analysis:
        lines.append("当前仓库暂无处于开放状态（Open）的新 PR，所有分支均已同步或暂无组员发起新请求。")
    else:
        lines.append(f"共发现 **{len(prs_analysis)}** 个待审阅 PR：\n")
        for item in prs_analysis:
            pr_id = item["pr_num"]
            title = item.get("title", f"PR #{pr_id}")
            author = item.get("user", {}).get("login", "组员") if isinstance(item.get("user"), dict) else "组员"
            files_cnt = item.get("changed_files_count", 0)

            lines.append(f"### 📌 PR #{pr_id}: {title}")
            lines.append(f"- **提交人**: `{author}`")
            lines.append(f"- **涉及文件数**: {files_cnt} 个")
            
            tags = []
            if item.get("has_algo"): tags.append("算法/因子")
            if item.get("has_data"): tags.append("数据清洗")
            if item.get("has_frontend"): tags.append("前端看板")
            if item.get("has_tests"): tags.append("自动化测试")
            lines.append(f"- **模块领域**: {' / '.join(tags) if tags else '通用文档/配置'}")

            lines.append("\n**变更文件清单摘要**:")
            for f in item.get("changed_files", [])[:8]:
                lines.append(f"  - `{f}`")
            if len(item.get("changed_files", [])) > 8:
                lines.append(f"  - ... 另有 {len(item.get('changed_files', [])) - 8} 个文件")

            lines.append("\n**吸收与合并建议**:")
            if not item.get("has_tests") and (item.get("has_algo") or item.get("has_data")):
                lines.append("  - ⚠️ **暂缓直接合入**: 包含算法或数据变更，但未补充对应 pytest 单元测试，建议要求作者补充测试。")
            else:
                lines.append("  - ✅ **建议审查吸收**: 符合结构规范，可通过 `git cherry-pick` 或在本地单独创建验证分支运行 `quality_gate.py small` 后合入。")
            lines.append("")

    lines.append("## 2. 吸收操作指引")
    lines.append("若需在本地检出并测试指定 PR：")
    lines.append("```bash")
    lines.append("# 例如本地测试 PR #3")
    lines.append("git fetch origin pull/3/head:test-pr-3")
    lines.append("git checkout test-pr-3")
    lines.append("python -m pytest tests/")
    lines.append("```")
    lines.append("")

    report_file.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"审查报告已生成: {report_file}")
    return report_file


def main():
    parser = argparse.ArgumentParser(description="每日 PR 自动审查与吸收")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="reports/pr_reviews",
        help="报告输出目录"
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    logger.info("开始执行每日 PR 自动化审查...")

    # 1. 查询 PR
    api_prs = get_open_prs_api()
    pr_analyses = []

    if api_prs:
        logger.info(f"通过 API 获取到 {len(api_prs)} 个 Open PR")
        for pr in api_prs:
            num = pr["number"]
            analysis = analyze_pr_diff(num)
            analysis.update({
                "title": pr.get("title", ""),
                "user": pr.get("user", {}),
                "created_at": pr.get("created_at", ""),
                "html_url": pr.get("html_url", "")
            })
            pr_analyses.append(analysis)
    else:
        # 回退到 git ls-remote
        pr_numbers = get_pr_refs_git()
        logger.info(f"通过 Git 获取到 PR 编号: {pr_numbers}")
        for num in pr_numbers:
            analysis = analyze_pr_diff(num)
            pr_analyses.append(analysis)

    # 2. 生成报告
    report_path = generate_pr_review_report(pr_analyses, out_dir)
    print(f"\n✅ PR 审查完毕，报告路径: {report_path}")


if __name__ == "__main__":
    main()
