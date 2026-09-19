#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Week 2 Day 4: NALE 方法快速验证

目标: 从已有 Week 1 结果提取验证结论，判断是否值得继续投入
负责人: 算法组
时间: 2-3 小时
"""

import pandas as pd
import numpy as np
import json
import re
from pathlib import Path


def extract_ic_from_report(report_path):
    """从 Markdown 报告中提取 Rank IC

    Args:
        report_path: 报告文件路径

    Returns:
        dict: {version: ic_value}
    """
    ic_results = {}

    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 正则匹配模式（适应不同格式）
        patterns = [
            r'(B0|V1|V2|V3|V4|V5).*?Rank\s*IC[:\s]*(-?\d+\.\d+)',
            r'(B0|V1|V2|V3|V4|V5).*?IC[:\s]*(-?\d+\.\d+)',
            r'版本\s*(B0|V1|V2|V3|V4|V5).*?(-?\d+\.\d+)'
        ]

        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for version, ic_str in matches:
                version = version.upper()
                ic_value = float(ic_str)
                if version not in ic_results:
                    ic_results[version] = ic_value

    except Exception as e:
        print(f"  ✗ 提取失败: {e}")

    return ic_results


def analyze_nale_effectiveness(ic_results):
    """分析 NALE 方法的有效性

    Args:
        ic_results: {version: ic_value}

    Returns:
        dict: 分析结果
    """
    analysis = {
        "has_data": len(ic_results) > 0,
        "versions": list(ic_results.keys()),
        "improvements": {},
        "conclusion": "UNKNOWN",
        "recommendation": "待补充数据"
    }

    if not analysis["has_data"]:
        return analysis

    # 计算逐级增益
    versions_ordered = ['B0', 'V1', 'V2', 'V3', 'V4', 'V5']
    available_versions = [v for v in versions_ordered if v in ic_results]

    for i in range(1, len(available_versions)):
        prev_v = available_versions[i - 1]
        curr_v = available_versions[i]

        prev_ic = ic_results[prev_v]
        curr_ic = ic_results[curr_v]
        improvement = curr_ic - prev_ic

        comparison_name = f"{curr_v} vs {prev_v}"
        analysis["improvements"][comparison_name] = {
            "prev_ic": prev_ic,
            "curr_ic": curr_ic,
            "improvement": improvement,
            "improvement_pct": (improvement / abs(prev_ic) * 100) if prev_ic != 0 else 0
        }

        print(f"\n  {comparison_name}:")
        print(f"    {prev_v} IC: {prev_ic:.4f}")
        print(f"    {curr_v} IC: {curr_ic:.4f}")
        print(f"    提升: {improvement:+.4f} ({improvement / abs(prev_ic) * 100:+.1f}%)")

    # 判断主要对比（V1 vs B0）
    if 'V1' in ic_results and 'B0' in ic_results:
        main_improvement = ic_results['V1'] - ic_results['B0']
        analysis["main_improvement"] = main_improvement

        # 决策逻辑
        if abs(main_improvement) >= 0.02:
            analysis["conclusion"] = "EFFECTIVE"
            analysis["recommendation"] = "✅ 有显著增益，建议 Week 3 推进 R5-R7 全量实验"
        elif abs(main_improvement) >= 0.01:
            analysis["conclusion"] = "MARGINAL"
            analysis["recommendation"] = "⚠️ 有微弱增益，建议调整参数后再评估，或继续用当前结果准备论文"
        else:
            analysis["conclusion"] = "INEFFECTIVE"
            analysis["recommendation"] = "❌ 无明显增益，建议 Pivot 到 12 周计划的其他学术方向"

    return analysis


def main():
    """主函数：NALE 快速验证"""

    print("=" * 60)
    print("Week 2 - NALE 方法快速验证")
    print("=" * 60)

    validation_result = {
        "validation_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "method": "从已有 Week 1 结果提取",
        "source": None,
        "ic_results": {},
        "analysis": {}
    }

    # ============================================================
    # 步骤 1: 查找已有的 Week 1 实验结果
    # ============================================================
    print("\n[1/3] 查找已有实验结果...")

    possible_paths = [
        "reports/tables/nale_alpha_week1/20260910-five-formulas/five_formula_report.md",
        "reports/tables/nale_alpha_week1/mvp/mvp_evolution_report.md",
        "reports/tables/nale_alpha_week1/recovery-audit-20260910/validation_report.md"
    ]

    report_found = None
    for path_str in possible_paths:
        path = Path(path_str)
        if path.exists():
            print(f"  ✓ 发现报告: {path}")
            report_found = path
            validation_result["source"] = str(path)
            break

    if report_found is None:
        print("  ✗ 未发现已有实验报告")
        print("\n建议:")
        print("  1. 确认 Week 1 实验是否已完成")
        print("  2. 检查报告文件路径")
        print("  3. 如需重新运行，参考 specs/contest-2026/week1-recovery-plan.md")

        validation_result["status"] = "NO_DATA"
        validation_result["recommendation"] = "无已有数据，需要重新运行实验或调整计划"

        # 保存结果
        output_path = Path("reports/week2_nale_validation.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(validation_result, f, indent=2, ensure_ascii=False)

        print(f"\n✅ 验证结果已保存: {output_path}")
        return

    # ============================================================
    # 步骤 2: 提取 IC 指标
    # ============================================================
    print("\n[2/3] 提取 Rank IC 指标...")

    ic_results = extract_ic_from_report(report_found)

    if len(ic_results) == 0:
        print("  ✗ 无法从报告中提取 IC 指标")
        print("  提示: 报告格式可能不匹配，需要手动查看")

        validation_result["status"] = "PARSE_ERROR"
        validation_result["recommendation"] = "无法自动提取指标，需要手动查看报告"
    else:
        print(f"  ✓ 成功提取 {len(ic_results)} 个版本的 IC")

        for version, ic in sorted(ic_results.items()):
            print(f"    {version}: {ic:.4f}")

        validation_result["ic_results"] = {k: float(v) for k, v in ic_results.items()}

    # ============================================================
    # 步骤 3: 分析有效性
    # ============================================================
    print("\n[3/3] 分析 NALE 方法有效性...")

    analysis = analyze_nale_effectiveness(ic_results)
    validation_result["analysis"] = analysis

    # 打印结论
    print(f"\n{'=' * 60}")
    print("验证结论")
    print(f"{'=' * 60}")

    if analysis["has_data"]:
        print(f"状态: {analysis['conclusion']}")
        print(f"建议: {analysis['recommendation']}")

        validation_result["status"] = analysis["conclusion"]
        validation_result["recommendation"] = analysis["recommendation"]
    else:
        print("状态: 数据不足")
        validation_result["status"] = "INSUFFICIENT_DATA"

    # ============================================================
    # 保存结果
    # ============================================================
    output_json = Path("reports/week2_nale_validation.json")
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(validation_result, f, indent=2, ensure_ascii=False)

    print(f"\n✅ JSON 结果已保存: {output_json}")

    # 生成 Markdown 摘要
    output_md = Path("reports/week2_nale_validation.md")
    with open(output_md, 'w', encoding='utf-8') as f:
        f.write("# Week 2 NALE 方法快速验证\n\n")
        f.write(f"**验证日期**: {validation_result['validation_date']}\n\n")
        f.write(f"**数据来源**: {validation_result.get('source', 'N/A')}\n\n")

        f.write("## IC 指标汇总\n\n")
        if validation_result["ic_results"]:
            f.write("| 版本 | Rank IC |\n")
            f.write("|------|----------|\n")
            for v, ic in sorted(validation_result["ic_results"].items()):
                f.write(f"| {v} | {ic:.4f} |\n")
        else:
            f.write("*无数据*\n")

        f.write("\n## 逐级增益分析\n\n")
        if analysis.get("improvements"):
            for comp_name, comp_data in analysis["improvements"].items():
                f.write(f"### {comp_name}\n")
                f.write(f"- 提升: {comp_data['improvement']:+.4f}\n")
                f.write(f"- 相对提升: {comp_data['improvement_pct']:+.1f}%\n\n")
        else:
            f.write("*无数据*\n")

        f.write("\n## 结论\n\n")
        f.write(f"**状态**: {validation_result.get('status', 'UNKNOWN')}\n\n")
        f.write(f"**建议**: {validation_result.get('recommendation', 'N/A')}\n\n")

        f.write("\n## Week 3 决策分支\n\n")
        if analysis["conclusion"] == "EFFECTIVE":
            f.write("✅ **路径 A**: 推进 NALE 全量实验（R5-R7）\n")
            f.write("- 完成 V4/V5 扩展\n")
            f.write("- 运行全量数据验证\n")
            f.write("- 撰写学术论文\n")
        elif analysis["conclusion"] == "MARGINAL":
            f.write("⚠️ **路径 B**: 调整参数或准备论文\n")
            f.write("- 尝试调整 lambda/H 超参数\n")
            f.write("- 或用当前结果撰写技术报告\n")
        else:
            f.write("❌ **路径 C**: Pivot 到其他学术方向\n")
            f.write("- 方向 A: 因果推断框架\n")
            f.write("- 方向 B: 强化学习动态调仓\n")
            f.write("- 方向 C: GNN 增强 NALE\n")
            f.write("- 方向 D: 贝叶斯不确定性量化\n")

    print(f"✅ Markdown 摘要已保存: {output_md}")

    print(f"\n{'=' * 60}")
    print("验证任务完成")
    print(f"{'=' * 60}")
    print("\n下一步: 将验证结论提交给文档组，用于撰写技术报告")


if __name__ == "__main__":
    main()
