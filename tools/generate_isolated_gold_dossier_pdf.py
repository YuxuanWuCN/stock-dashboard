# -*- coding: utf-8 -*-
"""tools/generate_isolated_gold_dossier_pdf.py —— 生成黄金板块物理隔绝实测专属研报 PDF

数据来源：
- src/analysis/gold_backtest_runner.py 样本外日频拟真回测
- reports/figures/backtest_gold_2025q3_2026q8/ 下的两幅实证图表
- 严格基于 data/raw/backtest_gold_2025q3_2026q8/ 原始数据
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fpdf import FPDF

ROOT = Path(r"D:\股票分析项目\Rainbow_FinGPTv2")
JSON_PATH = ROOT / "docs" / "data" / "paper" / "backtest_gold_2025q3_2026q8.json"
FIG_DIR = ROOT / "reports" / "figures" / "backtest_gold_2025q3_2026q8"
OUTPUT_PDF = Path(r"D:\股票分析项目\research-outputs\reports\黄金地缘避险_物理隔绝真实交易实测研报.pdf")


class IsolatedGoldDossierPDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=16)
        self.font_regular = "ChineseRegular"
        self.font_bold = "ChineseBold"
        self._setup_fonts()

    def _setup_fonts(self):
        candidates = [
            ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc"),
            ("C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simhei.ttf"),
        ]
        reg = "C:/Windows/Fonts/msyh.ttc"
        bold = "C:/Windows/Fonts/msyhbd.ttc"
        for r, b in candidates:
            if os.path.exists(r):
                reg = r
                bold = b if os.path.exists(b) else r
                break
        self.add_font(self.font_regular, "", reg)
        self.add_font(self.font_bold, "", bold)

    def header(self):
        self.set_fill_color(15, 23, 42)
        self.rect(0, 0, 210, 3, "F")
        self.set_fill_color(217, 119, 6)
        self.rect(0, 3, 210, 1.2, "F")
        self.set_font(self.font_regular, "", 8)
        self.set_text_color(100, 116, 139)
        self.set_xy(15, 6)
        self.cell(180, 5, "Rainbow-FinGPT Autonomous Quant Agent | Gold Geopolitical Physical Isolation Dossier", align="L")

    def footer(self):
        self.set_y(-12)
        self.set_draw_color(226, 232, 240)
        self.set_line_width(0.3)
        self.line(15, 285, 195, 285)
        self.set_font(self.font_regular, "", 7.5)
        self.set_text_color(148, 163, 184)
        self.set_xy(15, 286)
        self.cell(140, 4, "Physical Isolation & Causal Walk-Forward Audit | SCNU Aberdeen Institute", align="L")
        self.cell(40, 4, f"Page {self.page_no()}", align="R")


def main() -> int:
    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)

    metrics = data["metrics"]
    strat = metrics["strategy_stats"]
    ew = metrics["benchmark_gold_ew_stats"]
    etf = metrics["benchmark_gold_etf_stats"]
    csi = metrics["benchmark_csi300_stats"]

    pdf = IsolatedGoldDossierPDF()
    pdf.add_page()

    # 标题
    pdf.set_xy(15, 13)
    pdf.set_font(pdf.font_bold, "", 15)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(180, 7, "A股黄金与地缘避险板块物理隔绝真实交易实测报告")
    pdf.ln(7)

    pdf.set_font(pdf.font_regular, "", 8.5)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(180, 4.5, "样本外逐日推进 (2025Q3-2026Q8) · 机构摩擦成本 · 三级基准对照 · 地缘风险动态调仓")
    pdf.ln(6)

    # KPI 网格
    kpis = [
        ("实测样本区间", "2025Q3~2026Q8", (15, 23, 42)),
        ("策略累积收益", f"+{strat['total_return']*100:.2f}%", (22, 163, 74)),
        ("年化夏普比率", f"{strat['sharpe_ratio']:.2f}", (2, 132, 199)),
        ("最大动态回撤", f"{strat['max_drawdown']*100:.2f}%", (220, 38, 38)),
        ("Harvey t-stat", f"{strat['harvey_alpha_t_stat']:.2f}", (124, 58, 237)),
    ]

    y_start = pdf.get_y()
    w = 36.0
    for i, (title, val, color) in enumerate(kpis):
        x = 15 + i * w
        pdf.set_fill_color(248, 250, 252)
        pdf.set_draw_color(226, 232, 240)
        pdf.rect(x, y_start, w, 13.5, "DF")
        pdf.set_xy(x, y_start + 1.5)
        pdf.set_font(pdf.font_regular, "", 6.8)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(w, 3.5, title, align="C")
        pdf.set_xy(x, y_start + 5.8)
        pdf.set_font(pdf.font_bold, "", 9.2)
        pdf.set_text_color(*color)
        pdf.cell(w, 5.5, val, align="C")

    pdf.set_y(y_start + 16)

    # 1. 实验设计与隔离规范
    pdf.set_font(pdf.font_bold, "", 10.5)
    pdf.set_text_color(30, 58, 138)
    pdf.cell(180, 5.5, "1. 物理隔离与真实交易人设计 (Strict Isolation Protocol)")
    pdf.ln(6)

    pdf.set_fill_color(241, 245, 249)
    pdf.set_draw_color(203, 213, 225)
    box_y = pdf.get_y()
    pdf.rect(15, box_y, 180, 19, "DF")
    pdf.set_xy(17, box_y + 2)
    pdf.set_font(pdf.font_regular, "", 7.8)
    pdf.set_text_color(30, 41, 59)
    desc = (
        "【无未来函数与样本外推进】数据物理隔离于 data/raw/backtest_gold_2025q3_2026q8/ 目录，"
        "仅使用 <= t 日历史切片数据进行决策。买入费率 0.125%，卖出费率 0.175%，闲置资金计入 1.8% 年化收益。"
        "标的池涵盖 600547(山东黄金)、600489(中金黄金)、601899(紫金矿业)、002155(湖南黄金)、000975(山金国际)、"
        "600988(赤峰黄金)、601069(西部黄金) 七大核心资产，并同台对比黄金股等权、黄金 ETF (518880) 与沪深 300。"
    )
    pdf.multi_cell(176, 3.8, desc)
    pdf.set_y(box_y + 21)

    # 2. 绩效对比表
    pdf.set_font(pdf.font_bold, "", 10.5)
    pdf.set_text_color(30, 58, 138)
    pdf.cell(180, 5.5, "2. 策略与三级对照基准全周期实测表现")
    pdf.ln(6)

    rows = [
        ("三层解耦拟真策略 (本系统)", f"+{strat['total_return']*100:.2f}%", f"+{strat['annualized_return']*100:.2f}%", f"{strat['sharpe_ratio']:.2f}", f"{strat['max_drawdown']*100:.2f}%", f"{strat['calmar_ratio']:.2f}"),
        ("黄金股7巨头等权买入持有", f"+{ew['total_return']*100:.2f}%", f"+{ew['annualized_return']*100:.2f}%", f"{ew['sharpe_ratio']:.2f}", f"{ew['max_drawdown']*100:.2f}%", f"{ew['calmar_ratio']:.2f}"),
        ("黄金ETF (518880.SH)", f"+{etf['total_return']*100:.2f}%", f"+{etf['annualized_return']*100:.2f}%", f"{etf['sharpe_ratio']:.2f}", f"{etf['max_drawdown']*100:.2f}%", f"{etf['calmar_ratio']:.2f}"),
        ("沪深300 (000300.SH)", f"+{csi['total_return']*100:.2f}%", f"+{csi['annualized_return']*100:.2f}%", f"{csi['sharpe_ratio']:.2f}", f"{csi['max_drawdown']*100:.2f}%", f"{csi['calmar_ratio']:.2f}"),
    ]

    t_y = pdf.get_y()
    headers = [("组合 / 基准", 55, "L"), ("累计收益", 25, "R"), ("年化收益", 25, "R"), ("夏普", 25, "R"), ("最大回撤", 25, "R"), ("卡玛", 25, "R")]
    pdf.set_fill_color(226, 232, 240)
    pdf.set_font(pdf.font_bold, "", 7.5)
    pdf.set_text_color(15, 23, 42)
    cur_x = 15
    for h, hw, align in headers:
        pdf.set_xy(cur_x, t_y)
        pdf.cell(hw, 5, h, border=1, align=align, fill=True)
        cur_x += hw
    pdf.ln(5)

    pdf.set_font(pdf.font_regular, "", 7.5)
    for r in rows:
        row_y = pdf.get_y()
        cur_x = 15
        is_strat = "本系统" in r[0]
        pdf.set_text_color(217, 119, 6) if is_strat else pdf.set_text_color(30, 41, 59)
        pdf.set_font(pdf.font_bold if is_strat else pdf.font_regular, "", 7.5)
        for i, val in enumerate(r):
            hw = headers[i][1]
            align = headers[i][2]
            pdf.set_xy(cur_x, row_y)
            pdf.cell(hw, 4.8, val, border=1, align=align)
            cur_x += hw
        pdf.ln(4.8)

    pdf.ln(2)

    # 3. 双图并排
    pdf.set_font(pdf.font_bold, "", 10.5)
    pdf.set_text_color(30, 58, 138)
    pdf.cell(180, 5.5, "3. 累积净值走势与水下回撤控制实证")
    pdf.ln(6)

    img1 = FIG_DIR / "nav_comparison.png"
    img2 = FIG_DIR / "underwater_drawdown.png"
    img_y = pdf.get_y()
    if img1.exists():
        pdf.image(str(img1), x=15, y=img_y, w=88)
    if img2.exists():
        pdf.image(str(img2), x=107, y=img_y, w=88)

    OUTPUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUTPUT_PDF))
    print(f"Generated: {OUTPUT_PDF}")
    return 0


if __name__ == "__main__":
    main()
