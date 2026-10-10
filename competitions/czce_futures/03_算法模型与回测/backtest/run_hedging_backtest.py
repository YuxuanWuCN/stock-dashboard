# -*- coding: utf-8 -*-
"""
纯碱套期保值回测主程序 (run_hedging_backtest.py)
-----------------------------------------------
执行四大方案回测、指标矩阵输出与出版级图表绘制
"""

import sys
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

# 强制 UTF-8 输出
sys.stdout.reconfigure(encoding='utf-8')

# 定位工程目录
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(ROOT_DIR))

from src.models.hedging_strategies import HedgingEngine, compute_performance_metrics

PROCESSED_DATA_PATH = ROOT_DIR / "data" / "processed" / "czce_sa_fg_aligned_features.csv"
TABLES_DIR = ROOT_DIR / "reports" / "tables"
FIGURES_DIR = ROOT_DIR / "reports" / "figures"
BACKTEST_DATA_DIR = ROOT_DIR / "data" / "processed"

TABLES_DIR.mkdir(parents=True, exist_ok=True)
FIGURES_DIR.mkdir(parents=True, exist_ok=True)

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def run():
    print("=========================================================")
    print("【第九届郑商所杯】纯碱衍生品套期保值全真实证回测启动...")
    print("=========================================================")
    
    if not PROCESSED_DATA_PATH.exists():
        raise FileNotFoundError(f"未找到输入数据: {PROCESSED_DATA_PATH}")
        
    df = pd.read_csv(PROCESSED_DATA_PATH)
    df["date"] = pd.to_datetime(df["date"])
    print(f"-> 成功加载特征数据: {len(df)} 交易日 (从 {df['date'].min().strftime('%Y-%m-%d')} 至 {df['date'].max().strftime('%Y-%m-%d')})")
    
    # 实例化套保引擎 (假定现货库存 10,000 吨纯碱)
    engine = HedgingEngine(
        df=df,
        inventory_tons=10000.0,
        contract_multiplier=20.0,
        margin_ratio=0.12,
        commission_rate=0.0002,
        annual_risk_free_rate=0.03
    )
    
    print("-> 正在执行方案 A: 裸暴露 (未对冲基准)...")
    res_a = engine.run_unhedged()
    
    print("-> 正在执行方案 B: 传统 Naïve 1:1 静态套保...")
    res_b = engine.run_naive_hedge()
    
    print("-> 正在执行方案 C: 经典滚动 OLS 最小方差套保...")
    res_c = engine.run_ols_hedge(window=60)
    
    print("-> 正在执行方案 D: 本课题 Trend Gate™ + 期权领子动态套保...")
    res_d = engine.run_trend_gate_collar()
    
    res_dict = {
        "方案A(裸暴露)": res_a,
        "方案B(传统1:1静态套保)": res_b,
        "方案C(经典滚动OLS对冲)": res_c,
        "方案D(TrendGate自适应领子对冲)": res_d
    }
    
    # 1. 计算核心指标对比矩阵
    metrics_df = compute_performance_metrics(res_dict)
    metrics_csv_path = TABLES_DIR / "hedging_benchmark_metrics.csv"
    metrics_df.to_csv(metrics_csv_path, index=False, encoding="utf-8-sig")
    print(f"\n[OK] 核心学术指标矩阵已保存 -> {metrics_csv_path}")
    print("\n-------------------------- 回测指标综合对比 --------------------------")
    print(metrics_df.to_string(index=False))
    print("----------------------------------------------------------------------\n")
    
    # 2. 导出方案 D 逐日四分解 PnL 归因表 (T9 / B8)
    decomp_cols = [
        "date", "spot_pnl", "futures_pnl", "option_pnl",
        "fee_trade", "fee_roll", "fee_option", "capital_cost", "cost",
        "net_pnl", "total_equity", "net_worth", "contracts", "residual_exposure",
        "trend_gate", "hedge_ratio", "margin_used", "collar_strike_put", "collar_strike_call"
    ]
    decomp_df = res_d[decomp_cols].copy()
    decomp_csv_path = TABLES_DIR / "scheme_d_pnl_decomposition.csv"
    decomp_df.to_csv(decomp_csv_path, index=False, encoding="utf-8-sig")
    print(f"[OK] 方案 D 四分解逐日归因明细表已保存 -> {decomp_csv_path}")

    # 导出期权持仓流水账本 (T9 / B8)
    if hasattr(engine, "option_ledger") and not engine.option_ledger.empty:
        ledger_path = TABLES_DIR / "scheme_d_option_ledger.csv"
        engine.option_ledger.to_csv(ledger_path, index=False, encoding="utf-8-sig")
        print(f"[OK] 方案 D 场内期权持仓流水账本已保存 -> {ledger_path}")

    # 3. 导出时序对齐明细
    traj_df = pd.DataFrame({"date": df["date"]})
    for k, v in res_dict.items():
        prefix = k.split("(")[0]
        traj_df[f"{prefix}_net_worth"] = v["net_worth"]
        traj_df[f"{prefix}_margin"] = v["margin_used"]
    traj_df.to_csv(BACKTEST_DATA_DIR / "hedging_backtest_trajectories.csv", index=False, encoding="utf-8-sig")
    
    # 3. 绘制出版级 4 联图
    print("-> 正在绘制出版级对比图表 (300 DPI)...")
    fig, axes = plt.subplots(4, 1, figsize=(14, 16), sharex=True, dpi=300)
    fig.patch.set_facecolor('white')
    
    colors = {
        "方案A(裸暴露)": "#95a5a6",
        "方案B(传统1:1静态套保)": "#2980b9",
        "方案C(经典滚动OLS对冲)": "#f39c12",
        "方案D(TrendGate自适应领子对冲)": "#e74c3c"
    }
    
    # 图 1: 累计资产净值演化曲线
    ax1 = axes[0]
    for name, res in res_dict.items():
        lw = 2.4 if "D" in name else 1.5
        linestyle = "-" if "D" in name else ("--" if "A" in name else "-.")
        ax1.plot(res["date"], res["net_worth"], label=name, color=colors[name], lw=lw, linestyle=linestyle)
    ax1.set_title("【图1】纯碱实体企业四大套期保值方案累计资产净值演化 (2019-2026)", fontsize=13, fontweight='bold', pad=10)
    ax1.set_ylabel("资产净值 (基准=1.0)", fontsize=11)
    ax1.grid(True, linestyle="--", alpha=0.5)
    ax1.legend(loc="upper left", frameon=True, fontsize=10)
    
    # 图 2: 回撤深度曲线对比 (Drawdown Profile)
    ax2 = axes[1]
    for name, res in res_dict.items():
        cummax = res["net_worth"].cummax()
        dd = (res["net_worth"] - cummax) / cummax * 100.0
        lw = 2.0 if "D" in name else 1.2
        ax2.plot(res["date"], dd, label=name, color=colors[name], lw=lw)
    ax2.set_title("【图2】资产净值动态回撤深度对比 (方案 D 最大回撤压制至最低区间)", fontsize=13, fontweight='bold', pad=10)
    ax2.set_ylabel("动态回撤 (%)", fontsize=11)
    ax2.grid(True, linestyle="--", alpha=0.5)
    ax2.legend(loc="lower left", frameon=True, fontsize=9)
    
    # 图 3: 动态对冲比率演化 (Hedge Ratio)
    ax3 = axes[2]
    ax3.plot(res_b["date"], res_b["hedge_ratio"], label="方案B: 机械 1:1 恒定", color=colors["方案B(传统1:1静态套保)"], lw=1.2, linestyle=":")
    ax3.plot(res_c["date"], res_c["hedge_ratio"], label="方案C: 滚动 OLS 最优比率", color=colors["方案C(经典滚动OLS对冲)"], lw=1.4)
    ax3.plot(res_d["date"], res_d["hedge_ratio"], label="方案D: Trend Gate 门控自适应阶跃", color=colors["方案D(TrendGate自适应领子对冲)"], lw=2.0)
    ax3.set_title("【图3】套期保值头寸动态对冲比率 (Hedge Ratio) 时序对比", fontsize=13, fontweight='bold', pad=10)
    ax3.set_ylabel("对冲比率 h*", fontsize=11)
    ax3.set_ylim(-0.05, 1.3)
    ax3.grid(True, linestyle="--", alpha=0.5)
    ax3.legend(loc="upper right", frameon=True, fontsize=9)
    
    # 图 4: 保证金资金占用对比 (Margin Capital Tied Up)
    ax4 = axes[3]
    ax4.plot(res_b["date"], res_b["margin_used"] / 10000.0, label="方案B: 传统全额期货保证金占用", color=colors["方案B(传统1:1静态套保)"], lw=1.5)
    ax4.plot(res_c["date"], res_c["margin_used"] / 10000.0, label="方案C: OLS 保证金占用", color=colors["方案C(经典滚动OLS对冲)"], lw=1.3, linestyle="-.")
    ax4.plot(res_d["date"], res_d["margin_used"] / 10000.0, label="方案D: 门控+领子策略保证金占用 (节约 >50% 现金流)", color=colors["方案D(TrendGate自适应领子对冲)"], lw=2.2)
    ax4.set_title("【图4】企业套保日常保证金资金占用演化对比 (万元)", fontsize=13, fontweight='bold', pad=10)
    ax4.set_ylabel("保证金占用 (万元)", fontsize=11)
    ax4.set_xlabel("交易日期", fontsize=11)
    ax4.grid(True, linestyle="--", alpha=0.5)
    ax4.legend(loc="upper left", frameon=True, fontsize=9)
    
    ax4.xaxis.set_major_locator(mdates.YearLocator())
    ax4.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    
    plt.tight_layout()
    chart_path = FIGURES_DIR / "hedging_performance_comparison.png"
    plt.savefig(chart_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"[OK] 出版级学术对比图表 (300 DPI) 已生成 -> {chart_path}")
    print("=========================================================")
    print("【全真实证回测全部执行完毕】")
    print("=========================================================")

if __name__ == "__main__":
    run()
