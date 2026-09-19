#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Week 2 Day 1: 快速数据质量审计

目标: 2小时内完成 CSMAR 主表和文本因子的质量检查
负责人: 数据组
"""

import pandas as pd
import numpy as np
import json
from pathlib import Path


def main():
    print("=" * 60)
    print("Week 2 快速数据审计")
    print("=" * 60)

    audit_report = {
        "audit_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "critical_issues": []
    }

    # ============================================================
    # 检查项 1: CSMAR 主表基本统计
    # ============================================================
    print("\n[1/4] 检查 CSMAR 主表...")

    csmar_path = "data/task_split/csmar_master/csmar_factor_panel_master.csv"

    try:
        csmar = pd.read_csv(csmar_path)

        n_stocks = csmar['stock_code'].nunique()
        n_dates = csmar['trade_date'].nunique()
        missing_rate = csmar.isnull().mean().mean()

        print(f"  ✓ 股票数: {n_stocks} (预期 299)")
        print(f"  ✓ 交易日数: {n_dates} (预期 644)")
        print(f"  ✓ 总体缺失率: {missing_rate:.2%}")

        # 检查 600317
        has_600317 = '600317' in csmar['stock_code'].values
        print(f"  {'✓' if has_600317 else '✗'} 600317 {'存在' if has_600317 else '缺失'}")

        audit_report["csmar"] = {
            "stocks": int(n_stocks),
            "dates": int(n_dates),
            "missing_rate": float(missing_rate),
            "has_600317": bool(has_600317)
        }

        if not has_600317:
            audit_report["critical_issues"].append("600317 股票代码缺失")

        if missing_rate > 0.1:
            audit_report["critical_issues"].append(f"CSMAR 缺失率过高 ({missing_rate:.2%})")

    except FileNotFoundError:
        print(f"  ✗ 错误: 文件不存在 {csmar_path}")
        audit_report["csmar"] = {"error": "文件不存在"}
        audit_report["critical_issues"].append("CSMAR 主表文件缺失")
    except Exception as e:
        print(f"  ✗ 错误: {e}")
        audit_report["csmar"] = {"error": str(e)}
        audit_report["critical_issues"].append(f"CSMAR 读取失败: {e}")

    # ============================================================
    # 检查项 2: 价格口径一致性（抽样检查）
    # ============================================================
    print("\n[2/4] 检查价格口径一致性...")

    sample_stocks = {
        '000001': 'Group A (Tech)',
        '600000': 'Group B (Energy)',
        '000333': 'Group C (Finance)'
    }

    price_issues = []

    try:
        for code, group in sample_stocks.items():
            stock_data = csmar[csmar['stock_code'] == code]

            if len(stock_data) == 0:
                print(f"  ✗ {code} ({group}): 无数据")
                price_issues.append(f"{code} 无数据")
                continue

            ret_missing = stock_data['ret'].isnull().mean()
            abnormal_ret = (stock_data['ret'].abs() > 0.5).sum()

            print(f"  • {code} ({group}):")
            print(f"    - ret 缺失率: {ret_missing:.2%}")
            print(f"    - 异常收益率 (>50%): {abnormal_ret}")

            if ret_missing > 0.3:
                price_issues.append(f"{code} ret 缺失率过高 ({ret_missing:.2%})")

            if abnormal_ret > 5:
                price_issues.append(f"{code} 存在 {abnormal_ret} 个异常收益率")

        audit_report["price_check"] = {
            "sample_stocks": list(sample_stocks.keys()),
            "issues": price_issues
        }

        if price_issues:
            audit_report["critical_issues"].extend(price_issues)

    except Exception as e:
        print(f"  ✗ 错误: {e}")
        audit_report["price_check"] = {"error": str(e)}

    # ============================================================
    # 检查项 3: 文本因子覆盖
    # ============================================================
    print("\n[3/4] 检查文本因子覆盖...")

    text_factors_path = "data/task_split/factors_768d_all.csv"

    try:
        text_factors = pd.read_csv(text_factors_path)

        n_covered = len(text_factors)
        dim_cols = [c for c in text_factors.columns if c.startswith('dim_')]
        n_dims = len(dim_cols)

        print(f"  ✓ 文本因子覆盖: {n_covered}/300 股")
        print(f"  ✓ 特征维度: {n_dims} (预期 768)")

        # 检查缺失
        if n_dims > 0:
            dim_missing = text_factors[dim_cols].isnull().sum().sum()
            dim_total = len(text_factors) * n_dims
            dim_missing_rate = dim_missing / dim_total if dim_total > 0 else 0

            print(f"  ✓ 特征缺失率: {dim_missing_rate:.2%}")

            audit_report["text_factors"] = {
                "coverage": int(n_covered),
                "dimensions": int(n_dims),
                "missing_rate": float(dim_missing_rate)
            }

            if n_covered < 290:
                audit_report["critical_issues"].append(f"文本因子覆盖不足 ({n_covered}/300)")

            if dim_missing_rate > 0.01:
                audit_report["critical_issues"].append(f"特征缺失率过高 ({dim_missing_rate:.2%})")
        else:
            print(f"  ✗ 错误: 未找到 dim_* 列")
            audit_report["text_factors"] = {"error": "维度列缺失"}
            audit_report["critical_issues"].append("文本因子维度列缺失")

    except FileNotFoundError:
        print(f"  ✗ 错误: 文件不存在 {text_factors_path}")
        audit_report["text_factors"] = {"error": "文件不存在"}
        audit_report["critical_issues"].append("文本因子文件缺失")
    except Exception as e:
        print(f"  ✗ 错误: {e}")
        audit_report["text_factors"] = {"error": str(e)}

    # ============================================================
    # 检查项 4: 汇总与决策
    # ============================================================
    print("\n[4/4] 生成审计报告...")

    # 决策建议
    if len(audit_report["critical_issues"]) == 0:
        audit_report["status"] = "PASS"
        audit_report["recommendation"] = "数据质量可接受，继续执行 Week 2 任务"
    elif len(audit_report["critical_issues"]) <= 2:
        audit_report["status"] = "WARNING"
        audit_report["recommendation"] = "存在已知问题，标记为限制条件，用现有数据继续"
    else:
        audit_report["status"] = "FAIL"
        audit_report["recommendation"] = "数据质量严重不足，需要补充数据或调整计划"

    # 保存报告
    output_dir = Path("reports/tables")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "week2_quick_audit.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(audit_report, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print("审计完成")
    print(f"{'=' * 60}")
    print(f"状态: {audit_report['status']}")
    print(f"关键问题数: {len(audit_report['critical_issues'])}")

    if audit_report["critical_issues"]:
        print("\n关键问题列表:")
        for i, issue in enumerate(audit_report["critical_issues"], 1):
            print(f"  {i}. {issue}")

    print(f"\n建议: {audit_report['recommendation']}")
    print(f"\n✅ 报告已保存: {output_path}")
    print(f"\n下一步: 将此报告提交给测试组和算法组")


if __name__ == "__main__":
    main()
