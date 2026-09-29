#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Week 2 Day 3: 运行完整 PCA 回测

目标: 对全池和 3 个板块分别运行回测，生成对比报告
负责人: 算法组
时间: 3-4 小时
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False


def run_single_backtest(cohort_name, cohort_filter=None):
    """运行单个回测

    Args:
        cohort_name: 回测名称（用于保存文件）
        cohort_filter: 板块过滤（None=全池, "student_A"/"student_B"/"student_C"）

    Returns:
        dict: 回测结果指标
    """
    print(f"\n{'=' * 60}")
    print(f"运行回测: {cohort_name}")
    print(f"{'=' * 60}")

    try:
        from src.pricing.pca_backtest import run_pca_backtest

        result = run_pca_backtest(
            cohort_filter=cohort_filter,
            rebalance_freq=5,  # 每 5 个交易日调仓
            long_pct=0.2,      # 前 20% 做多
            short_pct=0.2      # 后 20% 做空
        )

        # 打印关键指标
        print(f"\n关键指标:")
        print(f"  夏普比率:    {result['sharpe']:.3f}")
        print(f"  年化收益:    {result['annual_return']:.2%}")
        print(f"  年化波动:    {result['annual_vol']:.2%}")
        print(f"  最大回撤:    {result['max_drawdown']:.2%}")
        print(f"  卡玛比率:    {result['calmar']:.3f}")
        print(f"  年化换手:    {result['turnover']:.2f}")

        return result

    except Exception as e:
        print(f"✗ 回测失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def create_summary_table(results):
    """创建回测对比汇总表

    Args:
        results: dict {name: result_dict}

    Returns:
        pd.DataFrame
    """
    summary_data = []

    for name, result in results.items():
        if result is None:
            continue

        summary_data.append({
            "Universe": name,
            "Sharpe Ratio": result['sharpe'],
            "Annual Return": result['annual_return'],
            "Annual Vol": result['annual_vol'],
            "Max Drawdown": result['max_drawdown'],
            "Calmar Ratio": result['calmar'],
            "Turnover": result['turnover']
        })

    return pd.DataFrame(summary_data)


def plot_cumulative_pnl(results, output_path):
    """绘制累计收益曲线（组合图）

    Args:
        results: dict {name: result_dict}
        output_path: 保存路径
    """
    fig, ax = plt.subplots(figsize=(14, 7))

    colors = {
        'Full Universe': '#1f77b4',
        'Tech & Manufacturing': '#ff7f0e',
        'Energy & Cyclicals': '#2ca02c',
        'Finance & Consumer': '#d62728'
    }

    for name, result in results.items():
        if result is None or 'cumulative_returns' not in result:
            continue

        cum_ret = result['cumulative_returns']
        color = colors.get(name, 'gray')

        ax.plot(cum_ret.index, cum_ret.values,
                label=name, linewidth=2, color=color, alpha=0.8)

    ax.axhline(0, color='black', linestyle='--', linewidth=0.5, alpha=0.5)
    ax.set_xlabel('日期', fontsize=12)
    ax.set_ylabel('累计对数收益', fontsize=12)
    ax.set_title('PCA 因子多空组合累计收益对比（修复后）', fontsize=14, fontweight='bold')
    ax.legend(loc='best', fontsize=10)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches='tight')
    print(f"✅ 组合图已保存: {output_path}")
    plt.close()


def plot_individual_pnl(name, result, output_dir):
    """绘制单个回测的详细图（多空分腿 + 净值）

    Args:
        name: 回测名称
        result: 回测结果
        output_dir: 输出目录
    """
    if result is None:
        return

    fig, axes = plt.subplots(2, 1, figsize=(14, 10))

    # 子图 1: 多空分腿
    if 'long_leg_returns' in result and 'short_leg_returns' in result:
        long_cum = result['long_leg_returns'].cumsum()
        short_cum = result['short_leg_returns'].cumsum()
        ls_cum = result['cumulative_returns']

        axes[0].plot(long_cum.index, long_cum.values,
                     label='多头', color='green', linewidth=2, alpha=0.7)
        axes[0].plot(short_cum.index, short_cum.values,
                     label='空头', color='red', linewidth=2, alpha=0.7)
        axes[0].plot(ls_cum.index, ls_cum.values,
                     label='多空净值', color='blue', linewidth=2.5, alpha=0.9)
        axes[0].axhline(0, color='black', linestyle='--', linewidth=0.5)
        axes[0].set_ylabel('累计对数收益', fontsize=11)
        axes[0].set_title(f'{name} - 多空分腿收益', fontsize=13, fontweight='bold')
        axes[0].legend(loc='best')
        axes[0].grid(True, alpha=0.3)

    # 子图 2: 回撤
    if 'drawdown' in result:
        dd = result['drawdown']
        axes[1].fill_between(dd.index, dd.values, 0,
                             color='red', alpha=0.3, label='回撤')
        axes[1].set_ylabel('回撤', fontsize=11)
        axes[1].set_xlabel('日期', fontsize=11)
        axes[1].set_title(f'{name} - 最大回撤分析', fontsize=13, fontweight='bold')
        axes[1].legend(loc='best')
        axes[1].grid(True, alpha=0.3)

    plt.tight_layout()

    safe_name = name.replace(' ', '_').replace('&', 'and')
    output_path = output_dir / f"pnl_{safe_name}.png"
    plt.savefig(output_path, dpi=200, bbox_inches='tight')
    print(f"✅ 详细图已保存: {output_path}")
    plt.close()


def main():
    """主函数：运行完整回测流程"""

    print("=" * 60)
    print("Week 2 - 768D PCA 回测系统验证")
    print("=" * 60)

    # 创建输出目录
    output_table_dir = Path("reports/tables/ashare_pca_backtest/week2")
    output_figure_dir = Path("reports/figures/ashare_pca_backtest/week2")
    output_table_dir.mkdir(parents=True, exist_ok=True)
    output_figure_dir.mkdir(parents=True, exist_ok=True)

    # 定义回测宇宙
    universes = {
        'Full Universe': None,
        'Tech & Manufacturing': 'student_A',
        'Energy & Cyclicals': 'student_B',
        'Finance & Consumer': 'student_C'
    }

    # 运行所有回测
    results = {}
    for name, cohort_filter in universes.items():
        result = run_single_backtest(name, cohort_filter)
        results[name] = result

        # 绘制个体详细图
        if result is not None:
            plot_individual_pnl(name, result, output_figure_dir)

    # 生成汇总表
    print(f"\n{'=' * 60}")
    print("生成汇总对比表")
    print(f"{'=' * 60}")

    summary_df = create_summary_table(results)

    if len(summary_df) > 0:
        print("\n汇总表:")
        print(summary_df.to_string(index=False))

        # 保存汇总表
        summary_path = output_table_dir / "backtest_summary.csv"
        summary_df.to_csv(summary_path, index=False, encoding='utf-8-sig')
        print(f"\n✅ 汇总表已保存: {summary_path}")

        # 绘制组合对比图
        combined_path = output_figure_dir / "cumulative_pnl_combined.png"
        plot_cumulative_pnl(results, combined_path)
    else:
        print("\n✗ 错误: 所有回测均失败，无法生成汇总表")

    # 验收检查
    print(f"\n{'=' * 60}")
    print("验收检查")
    print(f"{'=' * 60}")

    success_count = sum(1 for r in results.values() if r is not None)
    print(f"成功回测数: {success_count}/4")

    if success_count == 4:
        print("✅ 所有回测成功")

        # 检查指标合理性
        issues = []
        for name, result in results.items():
            if result['sharpe'] < -2 or result['sharpe'] > 5:
                issues.append(f"{name}: 夏普比率异常 ({result['sharpe']:.2f})")
            if abs(result['max_drawdown']) > 0.8:
                issues.append(f"{name}: 最大回撤过大 ({result['max_drawdown']:.2%})")
            if result['turnover'] > 10:
                issues.append(f"{name}: 换手率过高 ({result['turnover']:.2f})")

        if issues:
            print("\n⚠️ 指标异常:")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("✅ 所有指标在合理范围内")
    else:
        print(f"⚠️ 部分回测失败 ({4 - success_count} 个)")

    # 生成交付清单
    print(f"\n{'=' * 60}")
    print("交付物清单")
    print(f"{'=' * 60}")

    deliverables = [
        output_table_dir / "backtest_summary.csv",
        output_figure_dir / "cumulative_pnl_combined.png"
    ]

    for name in universes.keys():
        safe_name = name.replace(' ', '_').replace('&', 'and')
        deliverables.append(output_figure_dir / f"pnl_{safe_name}.png")

    for path in deliverables:
        if path.exists():
            print(f"  ✅ {path}")
        else:
            print(f"  ✗ {path} (缺失)")

    print(f"\n{'=' * 60}")
    print("回测任务完成")
    print(f"{'=' * 60}")
    print("\n下一步: 将汇总表和图表提交给文档组")


if __name__ == "__main__":
    main()
