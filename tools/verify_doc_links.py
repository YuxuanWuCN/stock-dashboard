# -*- coding: utf-8 -*-
"""tools/verify_doc_links.py —— Adversarial Markdown Link & Image Resolution Verification.
Scans README.md and README_CN.md for all relative links, markdown images, and HTML tags,
confirming every referenced file exists on disk and has non-zero byte size.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent


def check_markdown_links(md_path: Path) -> list[dict]:
    text = md_path.read_text(encoding="utf-8")
    print(f"\n========================================================")
    print(f"Scanning Markdown File: {md_path.name}")
    print(f"========================================================")

    # 1. Standard markdown links [text](url) and images ![alt](url)
    md_matches = re.findall(r"!?\[([^\]]*)\]\(([^)]+)\)", text)
    # 2. HTML tags <img src="..."> and <a href="...">
    html_src = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', text, re.IGNORECASE)
    html_href = re.findall(r'<a[^>]+href=["\']([^"\']+)["\']', text, re.IGNORECASE)

    all_links = [m[1] for m in md_matches] + html_src + html_href

    results = []
    broken_count = 0
    checked_count = 0

    for raw_link in all_links:
        link = raw_link.strip()
        # Remove anchor and query parameters
        clean_target = link.split("#")[0].split("?")[0].strip()

        if not clean_target:
            continue

        # Skip web URLs and mailto
        if clean_target.startswith(("http://", "https://", "mailto:")):
            continue

        checked_count += 1
        decoded = unquote(clean_target)

        # Resolve relative to markdown directory first, then fallback to project root
        target = (md_path.parent / decoded).resolve()
        if not target.exists():
            alt = (ROOT / decoded).resolve()
            if alt.exists():
                target = alt

        is_valid = target.exists() and (target.is_dir() or target.stat().st_size > 0)
        size_bytes = target.stat().st_size if (target.exists() and target.is_file()) else 0

        info = {
            "link": link,
            "resolved_path": str(target),
            "exists": target.exists(),
            "size_bytes": size_bytes,
            "is_valid": is_valid,
        }
        results.append(info)

        if is_valid:
            print(f"  [OK]  {link} -> {target.relative_to(ROOT)} ({size_bytes} bytes)")
        else:
            broken_count += 1
            reason = "NOT FOUND (404)" if not target.exists() else "EMPTY (0 bytes)"
            print(f"  [FAIL 404] {link} -> {reason} ({target})")

    print(f"Total Local References Checked: {checked_count}")
    print(f"Broken References: {broken_count}")
    return results


def main() -> int:
    readme_en = ROOT / "README.md"
    readme_cn = ROOT / "README_CN.md"

    res_en = check_markdown_links(readme_en)
    res_cn = check_markdown_links(readme_cn)

    all_results = res_en + res_cn
    failures = [r for r in all_results if not r["is_valid"]]

    print(f"\n========================================================")
    print(f"SUMMARY: {len(all_results)} local links verified across README.md and README_CN.md")
    print(f"Failures: {len(failures)}")
    print(f"========================================================")

    if failures:
        print("\nBroken links found:")
        for f in failures:
            print(f"  - {f['link']} -> {f['resolved_path']}")
        return 1

    print("\nSUCCESS: All links and images resolve to valid, non-empty files (Zero 404s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
