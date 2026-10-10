# -*- coding: utf-8 -*-
"""
可视化图表绘制: 绘制郑商所纯碱 (SA) 与玻璃 (FG) 历史走势、价差演化、已实现波动率与动态相关性
保存路径: reports/figures/czce_market_dynamics.png (300 DPI 出版级)
"""

import sys
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
PROCESSED_FILE = ROOT_DIR / "data" / "processed" / "czce_sa_fg_aligned_features.csv"
FIGURES_DIR = ROOT_DIR / "reports" / "figures"
FIGURES_DIR.mkdir(parents=True, exist_ok=True)

# 配置中文字体与负号正常显示
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def plot_dynamics() -> Path:
    if not PROCESSED_FILE.exists():
        raise FileNotFoundError(f"未找到清洗后的特征数据集: {PROCESSED_FILE}")
        
    df = pd.read_csv(PROCESSED_FILE)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    
    fig, axes = plt.subplots(4, 1, figsize=(13, 14), sharex=True, dpi=300)
    fig.patch.set_facecolor('white')
    
    # 1. 价格走势对比
    ax1 = axes[0]
    ax1.plot(df["date"], df["close_sa"], label="纯碱主力连续 (SA)", color="#c0392b", lw=1.6)
    ax1.plot(df["date"], df["close_fg"], label="玻璃主力连续 (FG)", color="#2980b9", lw=1.6)
    ax1.set_title("【图1】郑商所纯碱 (SA) 与玻璃 (FG) 主力合约历史收盘价走势 (2019-2026)", fontsize=13, fontweight='bold', pad=10)
    ax1.set_ylabel("收盘价 (元/吨)", fontsize=11)
    ax1.grid(True, linestyle="--", alpha=0.5)
    ax1.legend(loc="upper right", frameon=True)
    
    # 2. 跨品种价差与比价
    ax2 = axes[1]
    ax2.plot(df["date"], df["spread_fg_sa"], label="价差 (FG - SA)", color="#8e44ad", lw=1.4)
    ax2_twin = ax2.twinx()
    ax2_twin.plot(df["date"], df["ratio_fg_sa"], label="比价 (FG / SA)", color="#f39c12", lw=1.4, linestyle=":")
    ax2.axhline(0, color="gray", linestyle="--", alpha=0.7)
    ax2.set_title("【图2】纯碱-玻璃产业链跨品种价差与比价演化", fontsize=13, fontweight='bold', pad=10)
    ax2.set_ylabel("绝对价差 (元/吨)", fontsize=11)
    ax2_twin.set_ylabel("价格比值 (FG/SA)", fontsize=11)
    ax2.grid(True, linestyle="--", alpha=0.5)
    
    lines_1, labels_1 = ax2.get_legend_handles_labels()
    lines_2, labels_2 = ax2_twin.get_legend_handles_labels()
    ax2.legend(lines_1 + lines_2, labels_1 + labels_2, loc="upper right", frameon=True)
    
    # 3. 20日滚动年化波动率
    ax3 = axes[2]
    ax3.plot(df["date"], df["vol_20d_sa"] * 100, label="纯碱 20日波动率 (SA)", color="#e74c3c", lw=1.3)
    ax3.plot(df["date"], df["vol_20d_fg"] * 100, label="玻璃 20日波动率 (FG)", color="#3498db", lw=1.3)
    ax3.set_title("【图3】纯碱与玻璃 20日年化已实现波动率 (Realized Volatility)", fontsize=13, fontweight='bold', pad=10)
    ax3.set_ylabel("年化波动率 (%)", fontsize=11)
    ax3.grid(True, linestyle="--", alpha=0.5)
    ax3.legend(loc="upper right", frameon=True)
    
    # 4. 动态联动相关系数
    ax4 = axes[3]
    ax4.plot(df["date"], df["rolling_corr_20d"], label="20日滚动收益率相关系数", color="#27ae60", lw=1.5)
    ax4.axhline(0, color="black", linestyle="-", alpha=0.4, lw=0.8)
    ax4.axhline(0.6, color="red", linestyle="--", alpha=0.6, label="强相关基准线 (0.6)")
    ax4.set_title("【图4】产业链日收益率时变相关性演化 (揭示非线性传导与基差背离风险)", fontsize=13, fontweight='bold', pad=10)
    ax4.set_ylabel("相关系数", fontsize=11)
    ax4.set_xlabel("交易日期", fontsize=11)
    ax4.set_ylim(-0.8, 1.05)
    ax4.grid(True, linestyle="--", alpha=0.5)
    ax4.legend(loc="lower right", frameon=True)
    
    # 优化日期轴刻度
    ax4.xaxis.set_major_locator(mdates.YearLocator())
    ax4.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    
    plt.tight_layout()
    output_path = FIGURES_DIR / "czce_market_dynamics.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"成功保存高清学术图表 (300 DPI) -> {output_path}")
    return output_path

if __name__ == "__main__":
    plot_dynamics()
