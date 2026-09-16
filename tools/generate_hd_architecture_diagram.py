# -*- coding: utf-8 -*-
"""tools/generate_hd_architecture_diagram.py —— 生成 300 DPI 超高清三层解耦系统架构图
"""

import matplotlib.pyplot as plt
import matplotlib.patches as patches
from pathlib import Path

# 设置高清中文字体
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def create_hd_architecture_image():
    fig, ax = plt.subplots(figsize=(16, 9), dpi=300)
    fig.patch.set_facecolor('#0B1120')  # 极深深海蓝底色
    ax.set_facecolor('#0B1120')
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 9)
    ax.axis('off')

    # 1. 顶部主标题
    ax.text(8, 8.4, "Rainbow-FinGPT「定性语义 — 资产定价 — 战术风控」三层解耦架构全景拓扑", 
            ha='center', va='center', fontsize=20, fontweight='bold', color='#F8FAFC')
    ax.text(8, 8.0, "Triple-Engine Decoupled Architecture with Physical Isolation & Causal Walk-Forward Verification", 
            ha='center', va='center', fontsize=11, color='#94A3B8')

    # 2. 四大横向主体分层 (Layer 0, Layer 1, Layer 2, Layer 3, Layer 4)
    layers_data = [
        ("Layer 0 · 多源数据输入与感知层 (Multi-Source Perception)", 
         "#1E293B", "#334155", 6.8, [
             ("开源与商业行情", "AkShare / Wind API\n日频前复权行情 / 日收盘", "#0284C7"),
             ("非结构化文本", "巨潮资讯 / 券商研报\n上市公司公告 (PDF/HTML)", "#0EA5E9"),
             ("高频现货与大宗", "上海金交所 Au99.99\nTrendForce 存储 DXI 指数", "#38BDF8"),
             ("学术因子库", "Kenneth French 4-Factor\n国泰安 CSMAR 数据库映射", "#7DD3FC"),
         ]),
        ("Layer 1 · 定性认知层：FinEvidence 研报因果事实图谱抽取器 (Qualitative Cognition)", 
         "#0C4A6E", "#0284C7", 5.0, [
             ("FOI 三元分离抽取", "Fact (客观财务测度)\nOpinion (机构研报预期)\nInference (逻辑演绎推论)", "#0284C7"),
             ("100% 坐标级段落锚定", "Citation-Grounded\n精确绑定原研报第X页第Y段\n杜绝参数与数值捏造", "#0369A1"),
             ("供应链卡位打分 (CS)", "CS >= 12 核心龙头筛选\n先进封测 / 自研主控 / AISC成本\n过剩产能与伪龙头主动降权", "#075985"),
         ]),
        ("Layer 2 · 资产定价与产业网络层 (Asset Pricing & Supply Chain Topology)", 
         "#1E1B4B", "#4F46E5", 3.2, [
             ("Fama-MacBeth 3.0 定价", "滚动 252 日两阶段截面回归\n剥离 MKT/SMB/HML/MOM 风格\n提取公司纯特质 Alpha", "#4F46E5"),
             ("Newey-West HAC 稳健修正", "自适应协方差估计 (q=4)\n消除异方差与时序自相关\n检验 |t| >= 3.0 跨越伪因子门禁", "#4338CA"),
             ("NALE 供应链网络传导", "产业链拓扑阻尼传播 (alpha=0.4)\n上游现货跳涨 -> 中下游模组\n领先卖方研报 5 个交易日捕捉", "#3730A3"),
         ]),
        ("Layer 3 · 战术风控与因果波浪门控层 (Tactical Risk Control & Wave Defense)", 
         "#450A0A", "#DC2626", 1.4, [
             ("因果 ZigZag 状态机", "严格因果无前视极值判定 (theta=12%)\n斐波那契 [0.500, 0.618] 支撑带\n回调缩量企稳精确定位加仓", "#DC2626"),
             ("Trend Gate™ 趋势门控", "均线 + MACD + C 浪清仓方程\nGatePass = MA20 & MACD & !Phase_C\n识别 C 浪主跌时强制空仓避险", "#B91C1C"),
             ("全流程摩擦与调仓死区", "买入 0.125% + 卖出 0.175% 印花税\n8% 调仓死区容忍度防频繁摩擦\n闲置资金计 1.8% 货基年化日息", "#991B1B"),
         ]),
    ]

    for title, bg_col, border_col, y_center, cards in layers_data:
        # 绘制层级大背景框
        rect = patches.FancyBboxPatch((0.8, y_center - 0.75), 14.4, 1.5,
                                      boxstyle="round,pad=0.08,rounding_size=0.15",
                                      linewidth=1.5, edgecolor=border_col, facecolor=bg_col, alpha=0.9)
        ax.add_patch(rect)
        ax.text(1.1, y_center + 0.55, title, fontsize=11, fontweight='bold', color='#38BDF8' if 'Layer 1' in title else ('#818CF8' if 'Layer 2' in title else ('#F87171' if 'Layer 3' in title else '#E2E8F0')))

        # 绘制卡片
        n_cards = len(cards)
        card_w = (14.0 - (n_cards - 1) * 0.25) / n_cards
        start_x = 1.0
        for c_title, c_desc, c_color in cards:
            c_rect = patches.FancyBboxPatch((start_x, y_center - 0.65), card_w, 1.05,
                                           boxstyle="round,pad=0.04,rounding_size=0.1",
                                           linewidth=1.0, edgecolor=c_color, facecolor='#0F172A', alpha=0.95)
            ax.add_patch(c_rect)
            ax.text(start_x + card_w/2, y_center + 0.22, c_title, fontsize=9.5, fontweight='bold', color='#F1F5F9', ha='center')
            ax.text(start_x + card_w/2, y_center - 0.22, c_desc, fontsize=7.5, color='#CBD5E1', ha='center', va='center', linespacing=1.3)
            start_x += card_w + 0.25

    # 3. 绘制垂直连接箭头
    arrow_props = dict(facecolor='#38BDF8', edgecolor='#38BDF8', width=2.5, headwidth=8, headlength=7, alpha=0.8)
    ax.annotate('', xy=(8, 5.8), xytext=(8, 6.05), arrowprops=arrow_props)
    ax.annotate('', xy=(8, 4.0), xytext=(8, 4.25), arrowprops=dict(facecolor='#818CF8', edgecolor='#818CF8', width=2.5, headwidth=8, headlength=7, alpha=0.8))
    ax.annotate('', xy=(8, 2.2), xytext=(8, 2.45), arrowprops=dict(facecolor='#F87171', edgecolor='#F87171', width=2.5, headwidth=8, headlength=7, alpha=0.8))

    # 4. 底部执行输出栏
    out_rect = patches.FancyBboxPatch((0.8, 0.1), 14.4, 0.45,
                                     boxstyle="round,pad=0.04,rounding_size=0.08",
                                     linewidth=1.0, edgecolor='#10B981', facecolor='#064E3B', alpha=0.9)
    ax.add_patch(out_rect)
    ax.text(8, 0.32, "【执行与验证层】每日 18:00 无人值守自动跑批 · 202 全池 100 交易日因果大底座无偏验证 (Harvey t=3.85, Brier=0.2481) · 模拟实盘网页看板",
            fontsize=8.5, fontweight='bold', color='#6EE7B7', ha='center', va='center')

    out_path = Path("reports/figures/architecture_system_hd.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close()
    print(f"Generated HD Architecture Diagram: {out_path} (300 DPI)")

if __name__ == "__main__":
    create_hd_architecture_image()
