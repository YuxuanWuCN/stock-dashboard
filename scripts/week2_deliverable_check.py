#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Week 2 交付物完整性检查

在 Week 2 结束前运行此脚本，确保所有必须交付的文件都已生成
"""

from pathlib import Path
import json


def check_file_exists(filepath, category):
    """检查文件是否存在"""
    path = Path(filepath)
    exists = path.exists()

    status = "✅" if exists else "❌"
    print(f"  {status} {filepath}")

    return {
        "file": filepath,
        "exists": exists,
        "category": category
    }


def main():
    """主函数：检查所有交付物"""

    print("=" * 70)
    print("Week 2 交付物完整性检查")
    print("=" * 70)

    all_checks = []

    # ========================================
    # 1. 核心交付物（必须）
    # ========================================
    print("\n[1/5] 核心交付物（必须完成）")

    core_deliverables = [
        "reports/week2_data_audit_report.md",
        "reports/week2_test_summary.txt",
        "reports/tables/ashare_pca_backtest/week2/backtest_summary.csv",
        "reports/week2_nale_validation.json",
        "reports/week2_technical_summary.md",
        "PPT素材/Week2_答辩素材.pptx"
    ]

    for filepath in core_deliverables:
        result = check_file_exists(filepath, "core")
        all_checks.append(result)

    # ========================================
    # 2. 数据审计相关
    # ========================================
    print("\n[2/5] 数据审计相关")

    audit_files = [
        "reports/tables/week2_quick_audit.json",
        "scripts/week2_quick_data_audit.py"
    ]

    for filepath in audit_files:
        result = check_file_exists(filepath, "audit")
        all_checks.append(result)

    # ========================================
    # 3. 回测系统相关
    # ========================================
    print("\n[3/5] 回测系统相关")

    backtest_files = [
        "scripts/week2_run_pca_backtest.py",
        "reports/figures/ashare_pca_backtest/week2/cumulative_pnl_combined.png",
        "reports/figures/ashare_pca_backtest/week2/pnl_Full_Universe.png",
        "reports/figures/ashare_pca_backtest/week2/pnl_Tech_and_Manufacturing.png",
        "reports/figures/ashare_pca_backtest/week2/pnl_Energy_and_Cyclicals.png",
        "reports/figures/ashare_pca_backtest/week2/pnl_Finance_and_Consumer.png"
    ]

    for filepath in backtest_files:
        result = check_file_exists(filepath, "backtest")
        all_checks.append(result)

    # ========================================
    # 4. NALE 验证相关
    # ========================================
    print("\n[4/5] NALE 验证相关")

    nale_files = [
        "scripts/week2_nale_quick_validation.py",
        "reports/week2_nale_validation.md"
    ]

    for filepath in nale_files:
        result = check_file_exists(filepath, "nale")
        all_checks.append(result)

    # ========================================
    # 5. 测试验证相关
    # ========================================
    print("\n[5/5] 测试验证相关")

    test_files = [
        "reports/quality_gate_small.txt",
        "reports/quality_gate_medium.txt",
        "reports/test_results_pca.txt",
        "reports/test_results_graph.txt"
    ]

    for filepath in test_files:
        result = check_file_exists(filepath, "test")
        all_checks.append(result)

    # ========================================
    # 汇总统计
    # ========================================
    print("\n" + "=" * 70)
    print("汇总统计")
    print("=" * 70)

    total = len(all_checks)
    exists = sum(1 for c in all_checks if c["exists"])
    missing = total - exists

    print(f"\n总计: {total} 个文件")
    print(f"  ✅ 已生成: {exists}")
    print(f"  ❌ 缺失: {missing}")
    print(f"  完成率: {exists / total * 100:.1f}%")

    # 按类别统计
    print("\n按类别统计:")
    categories = {}
    for check in all_checks:
        cat = check["category"]
        if cat not in categories:
            categories[cat] = {"total": 0, "exists": 0}
        categories[cat]["total"] += 1
        if check["exists"]:
            categories[cat]["exists"] += 1

    for cat, stats in categories.items():
        rate = stats["exists"] / stats["total"] * 100
        print(f"  {cat:10s}: {stats['exists']}/{stats['total']} ({rate:.0f}%)")

    # 缺失文件清单
    missing_files = [c["file"] for c in all_checks if not c["exists"]]

    if missing_files:
        print("\n缺失文件清单:")
        for i, filepath in enumerate(missing_files, 1):
            print(f"  {i}. {filepath}")

    # 决策建议
    print("\n" + "=" * 70)
    print("决策建议")
    print("=" * 70)

    core_missing = [c for c in all_checks if c["category"] == "core" and not c["exists"]]

    if len(core_missing) == 0:
        print("\n✅ 核心交付物全部完成！")
        print("   可以进行 Week 2 验收和 Week 3 规划。")
    elif len(core_missing) <= 2:
        print("\n⚠️ 核心交付物基本完成，但还有少量缺失。")
        print("   建议补齐后再进行正式验收。")
        print(f"\n   缺失的核心文件:")
        for c in core_missing:
            print(f"     - {c['file']}")
    else:
        print("\n❌ 核心交付物缺失较多，Week 2 尚未完成。")
        print("   建议继续执行任务，达到最小验收标准。")

    # 保存检查结果
    result_path = Path("reports/week2_deliverable_check.json")
    result_data = {
        "check_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "total": total,
            "exists": exists,
            "missing": missing,
            "completion_rate": exists / total
        },
        "by_category": categories,
        "missing_files": missing_files,
        "all_checks": all_checks
    }

    result_path.parent.mkdir(parents=True, exist_ok=True)
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)

    print(f"\n✅ 检查结果已保存: {result_path}")

    # 返回状态码
    if len(core_missing) == 0:
        return 0  # 成功
    elif len(core_missing) <= 2:
        return 1  # 警告
    else:
        return 2  # 失败


if __name__ == "__main__":
    import sys
    import pandas as pd

    exit_code = main()
    sys.exit(exit_code)
