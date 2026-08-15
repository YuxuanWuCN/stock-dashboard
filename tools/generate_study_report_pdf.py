# -*- coding: utf-8 -*-
"""波浪理论量化学习报告 PDF 生成器 —— generate_study_report_pdf.py

功能：
生成排版精美、学术规范、图文并茂的《波浪结构与波动理论量化实证学习报告》PDF。

依赖：
reportlab (已安装在 .venv)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, inch, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIGURES_DIR = REPO_ROOT / "reports" / "figures"
REPORTS_DIR = REPO_ROOT / "reports"


def register_fonts():
    """注册中文字体（优先使用系统微软雅黑，回退到黑体）。"""
    font_candidates = [
        ("C:/Windows/Fonts/msyh.ttc", 0, "YaHei"),
        ("C:/Windows/Fonts/msyhbd.ttc", 0, "YaHei-Bold"),
        ("C:/Windows/Fonts/simhei.ttf", None, "SimHei"),
        ("C:/Windows/Fonts/simsun.ttc", 0, "SimSun"),
    ]
    
    regular_registered = False
    bold_registered = False
    
    # 常规体
    for path, sub_idx, name in font_candidates:
        if os.path.exists(path):
            try:
                if sub_idx is not None:
                    pdfmetrics.registerFont(TTFont("ChineseRegular", path, subfontIndex=sub_idx))
                else:
                    pdfmetrics.registerFont(TTFont("ChineseRegular", path))
                regular_registered = True
                break
            except Exception as e:
                continue
                
    # 粗体
    if os.path.exists("C:/Windows/Fonts/msyhbd.ttc"):
        try:
            pdfmetrics.registerFont(TTFont("ChineseBold", "C:/Windows/Fonts/msyhbd.ttc", subfontIndex=0))
            bold_registered = True
        except Exception:
            pass
    elif os.path.exists("C:/Windows/Fonts/simhei.ttf"):
        try:
            pdfmetrics.registerFont(TTFont("ChineseBold", "C:/Windows/Fonts/simhei.ttf"))
            bold_registered = True
        except Exception:
            pass

    if not bold_registered and regular_registered:
        pdfmetrics.registerFont(TTFont("ChineseBold", "C:/Windows/Fonts/msyh.ttc", subfontIndex=0))


def create_study_report_pdf(out_pdf_path: Path, stock_code: str = "001258", stock_name: str = "立新能源"):
    """生成排版精美的 PDF 学习报告。"""
    register_fonts()

    doc = SimpleDocTemplate(
        str(out_pdf_path),
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )

    styles = getSampleStyleSheet()

    # 自定义样式
    style_title = ParagraphStyle(
        "DocTitle",
        fontName="ChineseBold",
        fontSize=20,
        leading=26,
        textColor=colors.HexColor("#1a365d"),
        alignment=1,  # Center
        spaceAfter=8,
    )

    style_subtitle = ParagraphStyle(
        "DocSubtitle",
        fontName="ChineseRegular",
        fontSize=11,
        leading=16,
        textColor=colors.HexColor("#4a5568"),
        alignment=1,
        spaceAfter=14,
    )

    style_h1 = ParagraphStyle(
        "Heading1_Custom",
        fontName="ChineseBold",
        fontSize=13,
        leading=18,
        textColor=colors.HexColor("#1a365d"),
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True,
    )

    style_h2 = ParagraphStyle(
        "Heading2_Custom",
        fontName="ChineseBold",
        fontSize=10.5,
        leading=15,
        textColor=colors.HexColor("#2b6cb0"),
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True,
    )

    style_body = ParagraphStyle(
        "Body_Custom",
        fontName="ChineseRegular",
        fontSize=9,
        leading=14,
        textColor=colors.HexColor("#2d3748"),
        spaceAfter=5,
    )

    style_callout = ParagraphStyle(
        "Callout_Text",
        fontName="ChineseRegular",
        fontSize=8.5,
        leading=13,
        textColor=colors.HexColor("#1a202c"),
    )

    style_table_cell = ParagraphStyle(
        "TableCell",
        fontName="ChineseRegular",
        fontSize=7.5,
        leading=11,
        textColor=colors.HexColor("#2d3748"),
    )

    style_table_header = ParagraphStyle(
        "TableHeader",
        fontName="ChineseBold",
        fontSize=8,
        leading=11,
        textColor=colors.white,
        alignment=1,
    )

    story = []

    # ============================================================
    # 标题与元数据
    # ============================================================
    story.append(Paragraph(f"{stock_name}（{stock_code}）波浪结构与波动理论量化实证学习报告", style_title))
    meta_text = f"研究标的：{stock_name} ({stock_code})  |  数据来源：268 根真实前复权日 K 线  |  报告日期：{datetime.now().strftime('%Y年%m月%d日')}"
    story.append(Paragraph(meta_text, style_subtitle))
    story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#2b6cb0"), spaceAfter=10))

    # ============================================================
    # 一、 引言与研究背景
    # ============================================================
    story.append(Paragraph("一、 研究背景与学习动机", style_h1))
    intro_p = (
        "在前期针对高波动股票（“妖股”特征）的讨论中，老师指出单纯的技术指标容易在高位钝化，"
        "并提出了<b>“翻倍该减仓”、“回调是早晚的事”</b>等核心判断，同时建议参考<b>波浪理论（Elliott Wave Theory）与波动结构</b>。"
        "为了深入探究老师判断背后的经济学与数学机理，本项目构建了可复现的量化分析程序，"
        "对立新能源（001258）历史 268 根日 K 线进行了严格的波段切分、斐波那契（Fibonacci）回撤度量与动量背离检验。"
    )
    story.append(Paragraph(intro_p, style_body))

    # ============================================================
    # 二、 老师核心论断的量化实证对照
    # ============================================================
    story.append(Paragraph("二、 老师核心论断与量化数据对照表", style_h1))
    
    t1_data = [
        [
            Paragraph("老师核心论断", style_table_header),
            Paragraph("量化测量指标", style_table_header),
            Paragraph("真实历史数据检验", style_table_header),
            Paragraph("量化实证结论", style_table_header),
        ],
        [
            Paragraph("<b>1. 短期翻倍，位置风险较高</b>", style_table_cell),
            Paragraph("滚动低点涨幅 / 真实波动率 ATR%", style_table_cell),
            Paragraph("2026-07-24 收盘达 <b>+100.8%</b> 翻倍点，峰值达 +135.3%；ATR 从 3.2% 飙升至 9.5%", style_table_cell),
            Paragraph("<b>完全证实</b>。翻倍后波动率剧烈放大，进入极端高风险博弈区。", style_table_cell),
        ],
        [
            Paragraph("<b>2. 已获利建议减仓 / 翻倍止盈</b>", style_table_cell),
            Paragraph("翻倍日清仓 vs 持有不动之最大回撤", style_table_cell),
            Paragraph("07-24 减仓完全避开 07-28/07-29 <b>连续两日跌停（-18.98% 回撤）</b>", style_table_cell),
            Paragraph("<b>完全证实</b>。翻倍减仓 100% 规避了断崖式尾部回撤杀跌。", style_table_cell),
        ],
        [
            Paragraph("<b>3. 回调是早晚的事情</b>", style_table_cell),
            Paragraph("主升浪后 20 日内回调 ≥10% 概率", style_table_cell),
            Paragraph("历史 6 次主升推动行情中，<b>5 次在 3~7 天内发生深度回调（83.3% 概率）</b>", style_table_cell),
            Paragraph("<b>完全证实</b>。主升浪后的短期回调在统计上具有极高必然性。", style_table_cell),
        ],
        [
            Paragraph("<b>4. 斐波那契黄金分割节奏</b>", style_table_cell),
            Paragraph("回调浪相对前推动浪的 Fibonacci 比例", style_table_cell),
            Paragraph("7月末暴跌回调 <b>49.3%（0.500 支撑）</b>；8月中旬回踩 <b>62.4%（0.618 支撑）</b>", style_table_cell),
            Paragraph("<b>完全证实</b>。急跌杀跌精准在 0.500 与 0.618 黄金分割带企稳。", style_table_cell),
        ],
        [
            Paragraph("<b>5. 资金动量衰竭与顶背离</b>", style_table_cell),
            Paragraph("浪3 vs 浪5 的成交量与 MACD 柱变化", style_table_cell),
            Paragraph("07-28 见顶 15.73 元当天，<b>成交量萎缩近 20% 且 MACD 柱大幅缩小</b>", style_table_cell),
            Paragraph("<b>完全证实</b>。微观流动性衰竭，知情资金离场引发暴跌。", style_table_cell),
        ],
    ]

    t1 = Table(t1_data, colWidths=[3.2 * cm, 3.5 * cm, 5.8 * cm, 4.5 * cm])
    t1.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a365d")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f7fafc"), colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t1)
    story.append(Spacer(1, 10))

    # ============================================================
    # 三、 多维量化图谱
    # ============================================================
    chart_path = FIGURES_DIR / f"{stock_code}_wave_analysis.png"
    if chart_path.exists():
        story.append(Paragraph("三、 多维量化波浪与斐波那契实证图谱", style_h1))
        # 页面宽度约 18cm
        img = Image(str(chart_path), width=17.5 * cm, height=13.8 * cm)
        story.append(img)
        story.append(Paragraph("<b>图 1：立新能源（001258）2026年7~8月主升推动、翻倍减仓点与斐波那契黄金分割图谱</b>", ParagraphStyle(
            "Caption", fontName="ChineseRegular", fontSize=8, textColor=colors.HexColor("#4a5568"), alignment=1, spaceBefore=4, spaceAfter=8
        )))

    story.append(PageBreak())

    # ============================================================
    # 四、 关键波浪切分与度量表
    # ============================================================
    story.append(Paragraph("四、 ZigZag 波段切分与斐波那契度量明细（核心波段）", style_h1))
    
    t2_data = [
        [
            Paragraph("波浪编号", style_table_header),
            Paragraph("性质", style_table_header),
            Paragraph("起止时间与历时", style_table_header),
            Paragraph("价格区间", style_table_header),
            Paragraph("涨跌幅", style_table_header),
            Paragraph("斐波那契度量", style_table_header),
            Paragraph("结构与微观机理解读", style_table_header),
        ],
        [
            Paragraph("Wave 20", style_table_cell),
            Paragraph("推动浪", style_table_cell),
            Paragraph("07-14 ~ 07-28 (10天)", style_table_cell),
            Paragraph("6.37 → 15.73", style_table_cell),
            Paragraph("<b>+146.94%</b>", style_table_cell),
            Paragraph("扩展 4.83x", style_table_cell),
            Paragraph("超级主升狂热段（07-24 触发 +100.8% 翻倍点）", style_table_cell),
        ],
        [
            Paragraph("Wave 21", style_table_cell),
            Paragraph("调整浪", style_table_cell),
            Paragraph("07-28 ~ 07-31 (3天)", style_table_cell),
            Paragraph("15.73 → 11.12", style_table_cell),
            Paragraph("<b>-29.31%</b>", style_table_cell),
            Paragraph("<b>回撤 49.3% (0.500)</b>", style_table_cell),
            Paragraph("连续跌停杀跌，<b>精准在 0.500 黄金回撤位企稳</b>", style_table_cell),
        ],
        [
            Paragraph("Wave 22", style_table_cell),
            Paragraph("反弹浪", style_table_cell),
            Paragraph("07-31 ~ 08-05 (3天)", style_table_cell),
            Paragraph("11.12 → 13.89", style_table_cell),
            Paragraph("<b>+24.91%</b>", style_table_cell),
            Paragraph("扩展 0.30x", style_table_cell),
            Paragraph("企稳后的次级反弹推动浪", style_table_cell),
        ],
        [
            Paragraph("Wave 24", style_table_cell),
            Paragraph("冲顶浪", style_table_cell),
            Paragraph("08-07 ~ 08-12 (3天)", style_table_cell),
            Paragraph("11.85 → 16.88", style_table_cell),
            Paragraph("<b>+42.45%</b>", style_table_cell),
            Paragraph("扩展 1.82x", style_table_cell),
            Paragraph("Wave 5 新高推动浪（创历史新高 16.88 元）", style_table_cell),
        ],
        [
            Paragraph("Wave 25", style_table_cell),
            Paragraph("回踩浪", style_table_cell),
            Paragraph("08-12 ~ 08-14 (2天)", style_table_cell),
            Paragraph("16.88 → 13.74", style_table_cell),
            Paragraph("<b>-18.60%</b>", style_table_cell),
            Paragraph("<b>回撤 62.4% (0.618)</b>", style_table_cell),
            Paragraph("当前波段回踩 <b>0.618 黄金防线</b> 寻底中", style_table_cell),
        ],
    ]

    t2 = Table(t2_data, colWidths=[1.8 * cm, 1.6 * cm, 3.2 * cm, 2.5 * cm, 2.0 * cm, 2.8 * cm, 3.6 * cm])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b6cb0")),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f7fafc"), colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t2)
    story.append(Spacer(1, 10))

    # ============================================================
    # 五、 学习收获与核心心得体会
    # ============================================================
    story.append(Paragraph("五、 学习收获与核心心得体会（重点提炼）", style_h1))

    gain1 = (
        "<b>1. 从“静态看技术指标”升级为“动态看周期与波段结构”：</b><br/>"
        "以往分析容易陷入单一指标（如 MACD 金叉、均线多头）的局限，在高波动暴涨行情中极易滞后或钝化；"
        "通过波浪理论，建立了<b>【启动 → 蓄势 → 主升加速 → 黄金回踩 → 冲顶衰竭】</b>的完整生命周期视角，"
        "能够清晰判断个股当前所处的真实微观阶段。"
    )
    story.append(Paragraph(gain1, style_body))

    gain2 = (
        "<b>2. 深刻理解了行为金融学中的“心理锚定与大资金共识”：</b><br/>"
        "“翻倍”不仅是一个涨幅数值，更是全市场所有持股者强烈的心理获利兑现关口；"
        "而 <code>0.500 ~ 0.618</code> 黄金分割位之所以屡屡精准支撑，是因为全市场量化模型与抄底资金在此处形成了高度的<b>心理安全边际共识（Self-fulfilling Prophecy）</b>。"
    )
    story.append(Paragraph(gain2, style_body))

    gain3 = (
        "<b>3. 掌握了微观流动性与量价背离的实战预警价值（Kyle 市场微观结构）：</b><br/>"
        "价格的持续推动必须伴随真实成交量的配合；当价格创新高但成交量萎缩、MACD 能量柱减弱时（顶背离），"
        "反映出知情资金已经停止大举吸筹，高位追涨仅靠散户情绪维持，此时必须坚决执行止盈减仓纪律，防范断崖式流动性危机。"
    )
    story.append(Paragraph(gain3, style_body))

    gain4 = (
        "<b>4. 树立了严谨的量化客观性与风险管理纪律：</b><br/>"
        "波浪理论不能停留在主观“数浪”（千人千浪），必须通过 ZigZag 极值算法与量化回测进行客观验证；"
        "任何交易机会都必须与止盈止损策略、资金管理以及公司基本面质量相融合。"
    )
    story.append(Paragraph(gain4, style_body))

    story.append(Spacer(1, 8))

    # ============================================================
    # 六、 向老师请教的进阶问题
    # ============================================================
    story.append(Paragraph("六、 向老师请教的进阶思考", style_h1))
    q_box = [
        [
            Paragraph(
                "<b>请教问题：</b><br/>"
                "在实际市场环境中，当大盘处于强势牛市、弱势震荡市或单边熊市（即不同的宏观市场温度）时，"
                "个股波浪回撤的深度（究竟是止步于 0.382 浅回撤还是深探 0.618 甚至破位）通常会受到宏观 Beta 多大程度的系统性影响？"
                "在进一步构建多因子量化选股与择时系统时，应如何给市场宏观环境赋予动态调节权重？",
                style_callout
            )
        ]
    ]
    t_q = Table(q_box, colWidths=[17.5 * cm])
    t_q.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ebf8ff")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#3182ce")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(t_q)

    # 生成 PDF
    out_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story)
    print(f"[OK] 专业学习报告 PDF 已成功生成: {out_pdf_path}")


if __name__ == "__main__":
    out_path = REPORTS_DIR / "立新能源_波浪理论量化学习报告.pdf"
    create_study_report_pdf(out_path)
