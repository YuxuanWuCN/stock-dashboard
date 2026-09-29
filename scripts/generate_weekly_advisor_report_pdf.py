# -*- coding: utf-8 -*-
"""Rainbow-FinGPT 全周期逐周研发与科研进展汇报（导师审阅版）PDF 生成器

文件定位：
- 严格遵循《量化投研与大模型决策系统》学术规范
- 详尽复盘 10 周全周期（2026.07.18 - 2026.09.23）工程研发与学术实证历程
- 客观剖析金融时序极端低信噪比带来的经验瓶颈与特征衰减现实
- 提出三套明确的战略调整与学术收敛方案，供导师审阅定夺

依赖：reportlab, Pillow
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from PIL import Image as PILImage

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm, inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
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

# 路径定义
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIGURES_DIR = PROJECT_ROOT / "本人研究成果" / "figures"
REPORTS_FIG_DIR = PROJECT_ROOT / "reports" / "figures"
OUTPUT_DIR = PROJECT_ROOT / "reports"


def register_fonts():
    """注册中文字体（优先使用系统微软雅黑，回退到黑体/宋体）。"""
    font_candidates = [
        ("C:/Windows/Fonts/msyh.ttc", 0, "YaHei"),
        ("C:/Windows/Fonts/msyhbd.ttc", 0, "YaHei-Bold"),
        ("C:/Windows/Fonts/simhei.ttf", None, "SimHei"),
        ("C:/Windows/Fonts/simsun.ttc", 0, "SimSun"),
    ]

    regular_registered = False
    bold_registered = False

    # 注册常规字体
    for path, sub_idx, name in font_candidates:
        if os.path.exists(path):
            try:
                if sub_idx is not None:
                    pdfmetrics.registerFont(TTFont("ChineseRegular", path, subfontIndex=sub_idx))
                else:
                    pdfmetrics.registerFont(TTFont("ChineseRegular", path))
                regular_registered = True
                break
            except Exception:
                continue

    # 注册粗体字体
    if os.path.exists("C:/Windows/Fonts/msyhbd.ttc"):
        try:
            pdfmetrics.registerFont(TTFont("ChineseBold", "C:/Windows/Fonts/msyhbd.ttc", subfontIndex=0))
            bold_registered = True
        except Exception:
            pass

    if not bold_registered and os.path.exists("C:/Windows/Fonts/simhei.ttf"):
        try:
            pdfmetrics.registerFont(TTFont("ChineseBold", "C:/Windows/Fonts/simhei.ttf"))
            bold_registered = True
        except Exception:
            pass

    if not bold_registered and regular_registered:
        pdfmetrics.registerFont(TTFont("ChineseBold", "C:/Windows/Fonts/msyh.ttc", subfontIndex=0))


class NumberedCanvas(canvas.Canvas):
    """双遍扫描 Canvas，用于精确绘制'第 X 页 / 共 Y 页'页码与专业页眉页脚。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_elements(num_pages)
            super().showPage()
        super().save()

    def draw_page_elements(self, page_count):
        self.saveState()
        page_w, page_h = A4

        # 仅在非首页绘制页眉
        if self._pageNumber > 1:
            self.setFont("ChineseRegular", 7.5)
            self.setFillColor(colors.HexColor("#718096"))
            self.drawString(38, page_h - 32, "华南师范大学阿伯丁数据科学与人工智能学院 · Rainbow-FinGPT 课题研究全周期汇报")
            self.drawRightString(page_w - 38, page_h - 32, "学生：吴宇轩 | 特呈导师审阅")
            self.setStrokeColor(colors.HexColor("#CBD5E0"))
            self.setLineWidth(0.6)
            self.line(38, page_h - 36, page_w - 38, page_h - 36)

        # 全页统一绘制页脚
        self.setFont("ChineseRegular", 7.5)
        self.setFillColor(colors.HexColor("#718096"))
        self.drawString(38, 24, "【机密学术研究报告】涵盖 2026.07.18 - 2026.09.23 累计 10 周工作实录与实证数据")
        page_str = f"第 {self._pageNumber} 页 / 共 {page_count} 页"
        self.drawRightString(page_w - 38, 24, page_str)
        self.setStrokeColor(colors.HexColor("#CBD5E0"))
        self.setLineWidth(0.6)
        self.line(38, 34, page_w - 38, 34)

        self.restoreState()


def get_proportional_image(img_path: Path, max_w: float = 510, max_h: float = 230) -> Image | None:
    """根据实际宽高比计算等比例缩放的 ReportLab Image。"""
    if not img_path.exists():
        return None
    try:
        with PILImage.open(img_path) as im:
            orig_w, orig_h = im.size
        ratio = min(max_w / orig_w, max_h / orig_h)
        return Image(str(img_path), width=orig_w * ratio, height=orig_h * ratio)
    except Exception:
        return None


def generate_weekly_report_pdf(out_pdf_path: Path):
    """主构建函数：生成专业出版级逐周汇报 PDF。"""
    register_fonts()
    out_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    # 边距设置：A4 (595.27 x 841.89 pt)，边距 38 pt (~1.34 cm)，可用宽 519.27 pt
    doc = SimpleDocTemplate(
        str(out_pdf_path),
        pagesize=A4,
        leftMargin=38,
        rightMargin=38,
        topMargin=46,
        bottomMargin=46,
    )

    # 色彩体系
    NAVY = colors.HexColor("#1A365D")       # 主标题/学术深蓝
    SLATE = colors.HexColor("#2B6CB0")      # 二级标题/深天蓝
    ACCENT = colors.HexColor("#C53030")     # 警示/关键瓶颈深红
    DARK = colors.HexColor("#2D3748")       # 主正文黑灰
    MUTED = colors.HexColor("#718096")      # 次级说明灰
    BORDER = colors.HexColor("#E2E8F0")     # 细边框灰
    BG_LIGHT = colors.HexColor("#F7FAFC")   # 背景底色灰
    BG_WARN = colors.HexColor("#FFF5F5")    # 警示背景浅红
    BG_CALLOUT = colors.HexColor("#EBF8FF") # 呼应背景浅蓝

    # 样式定义
    styles = getSampleStyleSheet()

    st_inst = ParagraphStyle(
        "InstHeader",
        fontName="ChineseBold",
        fontSize=10.5,
        leading=15,
        textColor=SLATE,
        alignment=0,
        spaceAfter=3,
    )

    st_title = ParagraphStyle(
        "DocTitle",
        fontName="ChineseBold",
        fontSize=17,
        leading=23,
        textColor=NAVY,
        alignment=0,
        spaceAfter=5,
    )

    st_subtitle = ParagraphStyle(
        "DocSubtitle",
        fontName="ChineseRegular",
        fontSize=9.5,
        leading=14,
        textColor=MUTED,
        alignment=0,
        spaceAfter=10,
    )

    st_h1 = ParagraphStyle(
        "Heading1_Custom",
        fontName="ChineseBold",
        fontSize=12,
        leading=17,
        textColor=NAVY,
        spaceBefore=11,
        spaceAfter=5,
        keepWithNext=True,
    )

    st_h2 = ParagraphStyle(
        "Heading2_Custom",
        fontName="ChineseBold",
        fontSize=9.5,
        leading=14,
        textColor=SLATE,
        spaceBefore=7,
        spaceAfter=3,
        keepWithNext=True,
    )

    st_body = ParagraphStyle(
        "Body_Custom",
        fontName="ChineseRegular",
        fontSize=8.5,
        leading=13.5,
        textColor=DARK,
        spaceAfter=5,
    )

    st_body_bold = ParagraphStyle(
        "Body_Bold_Custom",
        fontName="ChineseBold",
        fontSize=8.5,
        leading=13.5,
        textColor=DARK,
        spaceAfter=5,
    )

    st_callout = ParagraphStyle(
        "Callout_Text",
        fontName="ChineseRegular",
        fontSize=8,
        leading=12.5,
        textColor=DARK,
    )

    st_callout_bold = ParagraphStyle(
        "Callout_Bold",
        fontName="ChineseBold",
        fontSize=8.5,
        leading=13,
        textColor=NAVY,
        spaceAfter=3,
    )

    st_th = ParagraphStyle(
        "TableHeader",
        fontName="ChineseBold",
        fontSize=7.5,
        leading=10.5,
        textColor=colors.white,
        alignment=1,
    )

    st_td = ParagraphStyle(
        "TableCell",
        fontName="ChineseRegular",
        fontSize=7.2,
        leading=10,
        textColor=DARK,
    )

    st_td_bold = ParagraphStyle(
        "TableCellBold",
        fontName="ChineseBold",
        fontSize=7.2,
        leading=10,
        textColor=NAVY,
    )

    st_td_center = ParagraphStyle(
        "TableCellCenter",
        fontName="ChineseRegular",
        fontSize=7.2,
        leading=10,
        textColor=DARK,
        alignment=1,
    )

    st_fig_cap = ParagraphStyle(
        "FigureCaption",
        fontName="ChineseRegular",
        fontSize=7.5,
        leading=11,
        textColor=MUTED,
        alignment=1,
        spaceBefore=3,
        spaceAfter=8,
    )

    story = []

    # ============================================================
    # 顶部机构标识与标题
    # ============================================================
    story.append(Paragraph("华南师范大学阿伯丁数据科学与人工智能学院 · 本科毕业设计与课题研究", st_inst))
    story.append(Paragraph("Rainbow-FinGPT 量化投研与大模型决策系统 · 全周期逐周研发与科研进展汇报", st_title))
    story.append(Paragraph("<b>执行周期</b>：2026.07.18 - 2026.09.23（累计 10 周） | <b>学生</b>：吴宇轩 | <b>指导教师</b>：特呈导师审阅", st_subtitle))
    story.append(HRFlowable(width="100%", thickness=1.5, color=NAVY, spaceAfter=8))

    # 关键指标快照卡片（Hero Metrics）
    meta_box_data = [
        [
            Paragraph("<b>累计工作周期</b><br/><font size=11 color='#1A365D'><b>10 周 (68 天)</b></font><br/><font color='#718096' size=6.5>全量实战代码闭环</font>", st_callout),
            Paragraph("<b>代码仓库演进</b><br/><font size=11 color='#1A365D'><b>289 次 Commits</b></font><br/><font color='#718096' size=6.5>Git 完整可溯源生命周期</font>", st_callout),
            Paragraph("<b>自动化质量门禁</b><br/><font size=11 color='#2B6CB0'><b>92 项测试 100% 通过</b></font><br/><font color='#718096' size=6.5>pytest+覆盖率+弱断言校验</font>", st_callout),
            Paragraph("<b>覆盖重点资产池</b><br/><font size=11 color='#1A365D'><b>159 支真实标的</b></font><br/><font color='#718096' size=6.5>存储/绿电/黄金/CSMAR</font>", st_callout),
            Paragraph("<b>当前研究状态</b><br/><font size=11 color='#C53030'><b>面临经验低信噪比瓶颈</b></font><br/><font color='#718096' size=6.5>亟待导师点拨选题优化</font>", st_callout),
        ]
    ]
    meta_box = Table(meta_box_data, colWidths=[103, 104, 104, 104, 104])
    meta_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.8, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(meta_box)
    story.append(Spacer(1, 8))

    # ============================================================
    # 一、 致导师信：阶段性复盘与面临的研究瓶颈
    # ============================================================
    story.append(Paragraph("一、 致导师信：阶段性复盘与面临的研究瓶颈", st_h1))

    letter_text_1 = (
        "尊敬的老师：<br/>"
        "您好！从 2026 年 7 月中旬项目立项启动至今，我围绕金融多因子资产定价、大模型定性归纳与因果量化交易系统（Rainbow-FinGPT）"
        "已连续高强度进行了为期 <b>10 周</b> 的系统开发与实证研究。在这两个半月的时间里，我严格遵循可复现的学术标准与工业级质量门禁，"
        "完成了涵盖数据流水线、Fama-MacBeth 资产定价引擎、导师波浪与波动理论实证、解耦三引擎架构以及多端交互终端的完整工程底座，"
        "并通过了全部 92 项单元与集成测试。"
    )
    story.append(Paragraph(letter_text_1, st_body))

    letter_text_2 = (
        "在前期工程搭建与典型案例验证中，进展非常顺利（如验证您关于<b>立新能源 001258‘翻倍该减仓、回调是早晚的事’</b>的判断，"
        "量化实证证实翻倍减仓成功规避了两日连续跌停 -18.98% 的断崖回撤；在半导体存储板块中，Trend Gate 状态机成功将佰维存储最大回撤由基准的 45%+ 压制至 11.75%）。"
        "然而，随着项目从<b>‘工程实现与局部攻防’</b>步入<b>‘全市场特征挖掘与收益率连续预测’</b>的科研深水区，"
        "近两周我的研究遭遇了非常显著的<b>经验性瓶颈与正反馈衰减</b>，特借此周报向您坦诚汇报：<br/>"
        "<b>1. 金融时序的极端低信噪比与特征边际递减</b>：在对 768 维深度文本表征与多因子矩阵进行 PCA 降维与时效衰减拟合时，"
        "我发现无论如何精细化调整 PC5 的半衰期参数，其样本外的信息系数（IC）提升均极易钝化甚至衰减至统计不显著。继续在微观特征上死磕，边际回报极低。<br/>"
        "<b>2. 单兵全栈的心智负荷透支</b>：两个半月来，我一人兼顾从底层开源数据清洗勾稽、大模型提示词工程、计量经济学自适应回归，到图神经网络算法与前端可视化看板，"
        "持续在‘工程苦力’与‘无确定性探索’两线作战，目前心智带宽消耗极大，亟需明确收敛边界。<br/>"
        "这份报告系统汇总了 10 周来我完成的每一项具体任务与实证数据，并客观梳理了当前的理论瓶颈，恳请老师审阅指正，并在后续研究重心上给予点拨！"
    )

    letter_box = Table([[Paragraph(letter_text_2, st_callout)]], colWidths=[519])
    letter_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.8, SLATE),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(letter_box)
    story.append(Spacer(1, 10))

    # ============================================================
    # 二、 10 周任务执行全景清单（全量复盘矩阵）
    # ============================================================
    story.append(Paragraph("二、 10 周任务执行与核心产出全景清单（Week 1 - Week 10）", st_h1))
    story.append(Paragraph("下表系统展示了过去 10 周每周攻关的核心任务、技术落地点、定量验证指标以及产出交付物：", st_body))

    weekly_table_data = [
        [
            Paragraph("周次 / 区间", st_th),
            Paragraph("核心战略攻坚主题", st_th),
            Paragraph("关键技术任务与工程落地", st_th),
            Paragraph("定量验证结果 / 核心指标", st_th),
            Paragraph("主要交付物 / 状态", st_th),
        ],
        [
            Paragraph("<b>Week 1</b><br/>07.18-07.24", st_td_bold),
            Paragraph("<b>系统初始化与工程底座搭建</b>", st_td),
            Paragraph("• 搭建 Stock Dashboard 1.0 框架<br/>• 接入 AkShare 前复权 K 线与基础行情<br/>• 搭建 Flask API 后端与 GitHub Actions 自动更新", st_td),
            Paragraph("• 跑通 150+ 核心自选股日 K 线抓取<br/>• 自动化定时任务稳定率 100%<br/>• 建立基础技术指标池（MA/MACD/RSI）", st_td),
            Paragraph("项目骨架、API 接口、K 线看板<br/><font color='#2B6CB0'><b>【已交付】</b></font>", st_td),
        ],
        [
            Paragraph("<b>Week 2</b><br/>07.25-07.31", st_td_bold),
            Paragraph("<b>理论初验：导师论断量化实证</b>", st_td),
            Paragraph("• 量化实证导师“翻倍该减仓、回调是早晚的事”<br/>• 编写 ZigZag 波段划分与斐波那契回撤程序<br/>• 以立新能源（001258）268 根日 K 为样本对照", st_td),
            Paragraph("• 07-24 触发翻倍点，减仓完全规避 07-28/29 两连跌停（<b>-18.98%</b>）<br/>• 涨停后 20 日回调概率达 <b>83.3%</b>", st_td),
            Paragraph("《立新能源教师框架验证报告》<br/><font color='#2B6CB0'><b>【已验证】</b></font>", st_td),
        ],
        [
            Paragraph("<b>Week 3</b><br/>08.01-08.07", st_td_bold),
            Paragraph("<b>资产定价：Carhart 四因子回归</b>", st_td),
            Paragraph("• 引入经典金融计量经济学定价范式<br/>• 实现 252 日滚动 Carhart 四因子回归模型<br/>• 引入 Newey-West HAC 异方差自适应修正（q=4）", st_td),
            Paragraph("• 提出特质 Alpha 与 IR 门控机制（p<0.05, IR≥0.30）<br/>• 完成开源与 CSMAR 商业数据库映射矩阵", st_td),
            Paragraph("Fama-MacBeth 因子定价模块、回测接口<br/><font color='#2B6CB0'><b>【已交付】</b></font>", st_td),
        ],
        [
            Paragraph("<b>Week 4</b><br/>08.08-08.14", st_td_bold),
            Paragraph("<b>风险度量：高波动妖股预警</b>", st_td),
            Paragraph("• 针对高位钝化问题构建四因子风险评分矩阵<br/>• 融合资金放大倍数、情绪波动率与乖离率<br/>• 建立涨停簇聚类与动量衰竭识别机制", st_td),
            Paragraph("• 立新能源跌停前 5 日风险均分 <b>69.7 分</b>，显著高于全样本均值（24.8 分）<br/>• 成功实现高位流动性坍塌预警", st_td),
            Paragraph("四因子风险预警雷达、复盘分析报告<br/><font color='#2B6CB0'><b>【已交付】</b></font>", st_td),
        ],
        [
            Paragraph("<b>Week 5</b><br/>08.15-08.21", st_td_bold),
            Paragraph("<b>架构创新：解耦三引擎设计</b>", st_td),
            Paragraph("• 融合 FinGPT 与 FinRobot 前沿技术路线<br/>• 攻克大模型生成式“数值幻觉”难题<br/>• 提出 Causal-RAG 事实-观点-推论（FOI）三元体系", st_td),
            Paragraph("• 架构解耦为定性过滤+资产定价+战术执行<br/>• 建立供应链卡位硬门控（CS≥12）与 768D 向量抽取", st_td),
            Paragraph("三引擎系统架构蓝图、FOI 抽取流水线<br/><font color='#2B6CB0'><b>【已交付】</b></font>", st_td),
        ],
        [
            Paragraph("<b>Week 6</b><br/>08.22-08.28", st_td_bold),
            Paragraph("<b>超级周期攻防：存储与绿电实证</b>", st_td),
            Paragraph("• 深入 2025-2026 半导体存储超级周期闭环实证<br/>• 落地 Trend Gate™ 纯因果无未来函数状态机<br/>• 美光科技（MU）与佰维存储（688525）攻防对决", st_td),
            Paragraph("• 美光科技捕获主升浪，达成 <b>Sharpe = 1.72</b><br/>• 佰维存储拦截 C 浪杀跌，MaxDD 压制至 <b>11.75%</b>（基准 45%+）<br/>• KNN 校准 Brier Score = 0.185", st_td),
            Paragraph("存储超级周期学术论文初稿、实证图表集<br/><font color='#2B6CB0'><b>【已实证】</b></font>", st_td),
        ],
        [
            Paragraph("<b>Week 7</b><br/>08.29-09.04", st_td_bold),
            Paragraph("<b>竞赛冲刺与学术出版化</b>", st_td),
            Paragraph("• 对标 2026 中国国际大学生创新大赛达观产业命题<br/>• 制作 18 页麦肯锡/高盛白底深蓝高奢路演 PPT<br/>• 编制 13 页 Master 全景合订本与 300 DPI 规范图表", st_td),
            Paragraph("• 输出 15,000+ 字严谨产业命题申报书<br/>• 全面执行学术诚信纠错标准，剔除夸大宣传<br/>• 确立“下行腰斩防守”真实核心价值", st_td),
            Paragraph("国创赛金牌申报书、高规格路演 PPT、出版基类<br/><font color='#2B6CB0'><b>【已交付】</b></font>", st_td),
        ],
        [
            Paragraph("<b>Week 8</b><br/>09.05-09.11", st_td_bold),
            Paragraph("<b>复杂网络与稳健性检验</b>", st_td),
            Paragraph("• 接入演进版 Temporal-NALE 时空连续图引擎<br/>• 探索双波峰时空时滞共振扩散模型 α(t,τ,σ)<br/>• 实施 AAA 方案：贝叶斯不确定性惩罚与波动率反平价", st_td),
            Paragraph("• 运行全样本安慰剂置换检验（Placebo Test）<br/>• 消除回测中的前视偏差，校准经验 p-value", st_td),
            Paragraph("时空图计算模块、安慰剂检验报告<br/><font color='#2B6CB0'><b>【已交付】</b></font>", st_td),
        ],
        [
            Paragraph("<b>Week 9</b><br/>09.12-09.18", st_td_bold),
            Paragraph("<b>规范化工程门禁与团队协作拆解</b>", st_td),
            Paragraph("• 全面落地 `AGENTS.md` 质量门禁（彩虹捕虫体系）<br/>• 建立自动化测试套件（覆盖率扫描与弱断言排查）<br/>• 编制数据/算法/测试/文档四角色任务分工卡", st_td),
            Paragraph("• 达成 <b>92 项单元与集成测试 100% 通过</b><br/>• 推进 768D 文本因子 PCA 降维与 PC5 时效衰减调优", st_td),
            Paragraph("质量门禁脚本、组员任务分工包、测试档案<br/><font color='#2B6CB0'><b>【已交付】</b></font>", st_td),
        ],
        [
            Paragraph("<b>Week 10</b><br/>09.19-09.23", st_td_bold),
            Paragraph("<b>学术终端升级与研究瓶颈暴露</b>", st_td),
            Paragraph("• 升级 Publication-grade 学术研究终端<br/>• 实现离线兜底架构、API 可视化配置与每日盘后调度<br/>• 进行全样本跨周期统计检验与特征衰减分析", st_td),
            Paragraph("• 系统工程全链路无死角闭环（Web/移动端）<br/>• <b>暴露瓶颈</b>：PC5 因子时效加权在样本外边际递减<br/>• 预测信噪比极低，进入科研瓶颈与灵感枯竭期", st_td),
            Paragraph("学术研究终端 v3.0、瓶颈复盘与转向提议<br/><font color='#C53030'><b>【本期汇报】</b></font>", st_td),
        ],
    ]

    weekly_table = Table(weekly_table_data, colWidths=[55, 95, 175, 120, 74])
    weekly_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
    ]))
    story.append(weekly_table)
    story.append(Spacer(1, 10))

    # ============================================================
    # 三、 核心学术成果与量化实证精选（图文互证）
    # ============================================================
    story.append(PageBreak())
    story.append(Paragraph("三、 核心学术成果与量化实证精选（图文互证）", st_h1))
    story.append(Paragraph("以下是前 10 周沉淀的代表性学术与工程成果，均具备完全可复现的数据与代码支持：", st_body))

    # 1. 解耦三引擎
    story.append(Paragraph("1. 解耦三引擎系统架构（Triple-Engine Decoupled Architecture）", st_h2))
    p_arch = (
        "为彻底规避大语言模型（LLM）直接生成数字或给出交易建议时的“数值幻觉”与不可复现性，"
        "本项目提出了<b>解耦三引擎架构</b>：将‘定性研判’与‘定量定价’彻底物理隔离。"
        "Layer 1 Causal-RAG 仅负责事实归纳与供应链硬门控；Layer 2 Fama-MacBeth 严格依托连续日频数据与 Carhart 四因子回归；"
        "Layer 3 Trend Gate 状态机负责纯因果战术执行。该架构有效解决了大模型直接用于量化投资的核心痛点。"
    )
    story.append(Paragraph(p_arch, st_body))

    img_arch = get_proportional_image(FIGURES_DIR / "fig0_triple_engine_framework.jpg", max_w=490, max_h=175)
    if img_arch:
        story.append(KeepTogether([
            img_arch,
            Paragraph("图 1：Rainbow-FinGPT 解耦三引擎架构图（Layer 1 定性门控 → Layer 2 定量定价 → Layer 3 因果执行）", st_fig_cap)
        ]))

    # 2. 导师波浪与波动理论的立新能源实证 & 存储超级周期防守
    story.append(Spacer(1, 3))
    story.append(Paragraph("2. 导师理论实证与半导体存储超级周期极端行情防御", st_h2))
    p_defense = (
        "<b>（1）立新能源（001258）实证</b>：严格检验老师提出的‘翻倍该减仓、回调是早晚的事’论断。"
        "数据检验表明：2026-07-24 触发 +100.8% 翻倍止盈后，次日执行减仓，完美回避了随后 07-28 与 07-29 的<b>连续两日跌停（-18.98% 断崖杀跌）</b>；"
        "全样本统计 6 组涨停簇，20 日内发生回撤比例高达 <b>83.3%</b>（中位数回撤 12.05%），在统计学层面完全印证了老师的预判。<br/>"
        "<b>（2）佰维存储（688525）防御</b>：在 2026 年存储现货价格雪崩期间，Trend Gate 状态机精准识别顶点衰竭并强制清仓进入防御，"
        "将基准 45%+ 的深幅腰斩回撤严格压制在 <b>11.75%</b> 以内，凸显了非对称下行风控的巨大实战价值。"
    )
    story.append(Paragraph(p_defense, st_body))

    img_defense = get_proportional_image(FIGURES_DIR / "fig3_zigzag_trend_gate_biwin_defense.png", max_w=490, max_h=150)
    if not img_defense:
        img_defense = get_proportional_image(REPORTS_FIG_DIR / "001258_wave_analysis.png", max_w=490, max_h=160)
    if img_defense:
        story.append(KeepTogether([
            img_defense,
            Paragraph("图 2：极端行情下因果状态机拦截断崖杀跌实证图（左侧逃顶与右侧现金避险对比）", st_fig_cap)
        ]))

    # 3. 学术研究终端（移至 Page 4 开头，使 Page 3 与 Page 4 均保持紧凑充实）
    story.append(PageBreak())
    story.append(Paragraph("3. 工业级质量门禁与学术研究终端（Academic Research Terminal）", st_h2))
    p_terminal = (
        "为保障学术研究资产的可维护性与工程可靠性，团队建立了规范的 `AGENTS.md` 质量门禁体系："
        "包含 <b>92 项自动化单元与集成测试</b>、覆盖率校验、弱断言扫描以及数据指纹溯源。"
        "系统已封装为集多因子评分、回测对比、实时行情、风险雷达于一体的现代化交互终端，支持移动端与桌面端无缝响应。"
    )
    story.append(Paragraph(p_terminal, st_body))

    img_term = get_proportional_image(REPORTS_FIG_DIR / "wealth_terminal_preview.png", max_w=490, max_h=150)
    if img_term:
        story.append(KeepTogether([
            img_term,
            Paragraph("图 3：全栈学术研究终端交互界面（多因子打分、滚动净值与风险雷达看板）", st_fig_cap)
        ]))
    story.append(Spacer(1, 8))

    # ============================================================
    # 四、 深入剖析：为什么当前会出现“无正反馈与灵感枯竭”？
    # ============================================================
    story.append(Paragraph("四、 深入剖析：为什么当前会出现“无正反馈感与灵感枯竭”？", st_h1))

    intro_burnout = (
        "作为一名求知欲强烈的学生，我一直在反思：为什么在完成了如此多坚实的工程工作后，最近反而陷入了巨大的疲惫与空虚？"
        "经过冷思考，我认识到这绝不是简单的‘身体累’，而是**量化与金融数据科学本身特有的规律，在特定研发节点上对研究者造成的认知撞墙**："
    )
    story.append(Paragraph(intro_burnout, st_body))

    reasons_data = [
        [
            Paragraph("<b>客观困局维度</b>", st_th),
            Paragraph("<b>技术机理与实证表现</b>", st_th),
            Paragraph("<b>对心态与灵感的真实消耗</b>", st_th),
        ],
        [
            Paragraph("<b>1. 工程确定性 vs 金融低信噪比的断崖</b>", st_td_bold),
            Paragraph(
                "前 8 周是在解决<b>确定性的计算机工程问题</b>：数据接口报错修好就能跑，UI 样式调好就能看，测试写好就能绿，这种即时正反馈极强。"
                "但进入第 9-10 周的核心特征挖掘时，面对的是信噪比不足 5% 的金融随机游走市场。"
                "你写了上千行数学公式，跑出来的收益曲线可能依然与大盘同频。", st_td
            ),
            Paragraph(
                "心理预期从‘付出就有确定产出’骤降为‘高投入低产出’，巨大的落差让人怀疑代码的意义，产生严重的无意义感与挫败感。", st_td
            ),
        ],
        [
            Paragraph("<b>2. 微观调参与特征挖掘的边际效应趋零</b>", st_td_bold),
            Paragraph(
                "在 768D 降维到 PC5 的尝试中，我们试图通过时效指数衰减（半衰期 λ）来增强因子的时间敏感性。"
                "但在真实 A 股数据中，这种微调带来的 IC 提升极其微弱（在 0.01 左右微震），且样本外衰减极快。"
                "这在金融计量学上被称为<b>‘因子动物园过拟合困局’（Factor Zoo Overfitting）</b>。", st_td
            ),
            Paragraph(
                "感觉继续加参数、换模型只是在‘自欺欺人’地拟合历史噪声，脑子彻底空了，找不到新的真实 Alpha 逻辑支撑。", st_td
            ),
        ],
        [
            Paragraph("<b>3. Alpha 收益追求与防守价值的认知错位</b>", st_td_bold),
            Paragraph(
                "我潜意识里一直把‘系统能否精准预测涨跌、能否做出暴赚的超额 Alpha’当成了唯一的及格线。"
                "但事实上，在弱有效市场中，单纯依靠公开技术数据持续获得超额 Alpha 极其困难；"
                "相反，系统在<b>极端行情的风险拦截（如立新能源减仓、佰维防守）上已经极其优秀</b>，但我却因‘未能持续进攻’而否定整体成果。", st_td
            ),
            Paragraph(
                "把不可能达成的目标当及格线，导致大脑长期处于‘任务失败’的负反馈状态，彻底扼杀了探索新思路的兴趣与灵感。", st_td
            ),
        ],
        [
            Paragraph("<b>4. 单兵扛全栈的心智带宽极限</b>", st_td_bold),
            Paragraph(
                "一人同时包揽了数据清洗、计量金融、大模型 RAG、算法回测、自动化测试、前端交互全栈工作。"
                "当心智带宽长期处于 100% 满载甚至超载时，大脑根本没有闲暇空间进行高维度的学术思考，只能陷入低效的疲劳应对。", st_td
            ),
            Paragraph(
                "陷入‘为了调参而调参’的机械内卷，完全丧失了从更高产业或学术视角审视课题的从容感。", st_td
            ),
        ],
    ]

    reasons_table = Table(reasons_data, colWidths=[110, 245, 164])
    reasons_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_WARN]),
    ]))
    story.append(reasons_table)

    # ============================================================
    # 五、 恳请导师指引的战略调整方案（三大备选出路）
    # ============================================================
    story.append(PageBreak())
    story.append(Paragraph("五、 恳请导师指引的战略调整方案（三大备选出路）", st_h1))
    story.append(Paragraph("为了打破低效内卷、将已有的高质量工程转化为扎实的学术或竞赛成果，我整理了三套调整方向，恳请老师定夺：", st_body))

    opts_data = [
        [
            Paragraph("<b>备选调整方案</b>", st_th),
            Paragraph("<b>核心研究逻辑与实施路径</b>", st_th),
            Paragraph("<b>学术价值与预期产出</b>", st_th),
            Paragraph("<b>对学生的现实意义</b>", st_th),
        ],
        [
            Paragraph("<b>方案 A（推荐）<br/>全面转向非对称下行风控与宏观门禁</b>", st_td_bold),
            Paragraph(
                "• 放弃在全市场盲目追求‘超额收益预测’；<br/>"
                "• 聚焦系统已被实证充分验证的强项：<b>‘识别泡沫破裂、规避极端尾部杀跌’</b>；<br/>"
                "• 强化极值理论（EVT）、条件在险价值（CVaR）与导师波浪结构的高位减仓机制；<br/>"
                "• 将系统定位为<b>‘大模型辅助的非对称下行风险控制决策系统’</b>。", st_td
            ),
            Paragraph(
                "• 学术界极度看重下行风控与稳健性（审稿人更容易认可真实可信的防守成果，而非神话般的暴利）；<br/>"
                "• 形成立新能源、佰维存储两篇高质量的风险控制典型案例与实证论文。", st_td
            ),
            Paragraph(
                "<b>立竿见影卸下心智包袱</b>：不需要再去死磕虚无缥缈的 Alpha，基于现有代码即可完美闭环，正反馈极强。", st_td
            ),
        ],
        [
            Paragraph("<b>方案 B<br/>冻结基线，转向跨周期大样本稳健性与消融分析</b>", st_td_bold),
            Paragraph(
                "• 立即停止增量功能开发与无意义的参数调优；<br/>"
                "• 将当前通过 92 项测试的系统完整固化为 <b>v3.0 Baseline</b>；<br/>"
                "• 集中精力补齐 2024-2026 全市场 300 标的的<b>消融实验（Ablation Study）</b>：测试‘有无大模型门控’、‘有无波浪回撤减仓’、‘有无 HAC 校准’的横向差异。", st_td
            ),
            Paragraph(
                "• 极度符合顶级实证计量与数据科学论文范式；<br/>"
                "• 实验完全标准化、可批量跑批，结论客观中立（即便是负结果也能写出高水平讨论）。", st_td
            ),
            Paragraph(
                "<b>研发节奏高度可控</b>：将不确定性的‘找灵感’变为确定性的‘跑实验与写章节’，适合毕业设计与结项报告收尾。", st_td
            ),
        ],
        [
            Paragraph("<b>方案 C<br/>跳出技术面内卷，引入产业链事件传导时滞</b>", st_td_bold),
            Paragraph(
                "• 放弃日频高频技术面与波动率预测；<br/>"
                "• 将 Causal-RAG 升级为低频产业链图谱：重点研究<b>‘上游原厂价格涨跌对下游封测与模组厂的滞后传导周期’</b>（离散事件驱动）；<br/>"
                "• 结合半导体与新能源行业的真实财务勾稽关系，做低频、高确信度的中长期基本面配置。", st_td
            ),
            Paragraph(
                "• 具备极强的产业实操价值与大创产业赛道说服力；<br/>"
                "• 避开公开市场高频博弈的噪声，从经济学逻辑源头解释超额收益。", st_td
            ),
            Paragraph(
                "需要补充产业链数据，但研究视野开阔，能真正将产业知识与大模型结合，避免技术枯燥感。", st_td
            ),
        ],
    ]

    opts_table = Table(opts_data, colWidths=[90, 165, 145, 119])
    opts_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
    ]))
    story.append(opts_table)
    story.append(Spacer(1, 8))

    # ============================================================
    # 六、 面谈请教提纲与下一步工作
    # ============================================================
    story.append(Paragraph("六、 约请面谈提纲与下一步工作计划", st_h1))

    closing_text = (
        "老师，回顾这 10 周，虽然过程伴随着探索的艰难与疲惫，但我深切体会到：<b>一段真实扎实的科研历程，必然会经历‘工程顺利的兴奋期’到‘直面真实世界噪声的瓶颈期’</b>。"
        "正是您此前的精准点拨（如立新能源的翻倍减仓），让我避免了在单纯技术指标中迷失，并拿到了关键的实证验证成果。<br/><br/>"
        "目前代码库处于随时可复现的最佳健康状态（92 项测试全绿，文档完备）。为了不耽误后续毕业论文开题与竞赛推进，"
        "我非常希望能约老师一次 <b>15 分钟左右的面谈或线上沟通</b>，当面向您请教以下三个关键决策点：<br/>"
        "<b>1. 选题定位决断</b>：在【方案 A（主攻下行极端风控）】与【方案 B（冻结基线做大样本消融沉淀论文）】之间，您更倾向于我以哪个作为毕业设计/成果的核心主线？<br/>"
        "<b>2. 负结果的学术处理</b>：对于 768D 文本因子降维预测收益率在统计上显著性较弱这一客观现象，我们是将其作为‘低信噪比实证发现’写入论文，还是彻底剔除？<br/>"
        "<b>3. 团队分工收敛</b>：组内数据与测试同学的任务是否需要同步向‘消融验证与数据审计’收敛，以减轻整体的心智损耗？<br/><br/>"
        "无论老师建议如何调整，我都已做好充分准备。再次由衷感谢老师一直以来的悉心教导与方向引领！"
    )

    closing_box = Table([[Paragraph(closing_text, st_callout)]], colWidths=[519])
    closing_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_CALLOUT),
        ("BOX", (0, 0), (-1, -1), 0.8, SLATE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(closing_box)
    story.append(Spacer(1, 6))

    # 署名区
    sign_text = (
        f"<b>汇报学生</b>：华南师范大学阿伯丁数据科学与人工智能学院 · 吴宇轩<br/>"
        f"<b>报告生成时间</b>：{datetime.now().strftime('%Y年%m月%d日')} | <b>文档校验哈希</b>：Rainbow-FinGPT-v3.0-Rev289"
    )
    story.append(Paragraph(sign_text, st_subtitle))

    # 构建文档
    doc.build(story, canvasmaker=NumberedCanvas)
    sys.stdout.buffer.write(f"PDF success: {out_pdf_path} ({out_pdf_path.stat().st_size / 1024:.1f} KB)\n".encode("utf-8"))


if __name__ == "__main__":
    out_file = OUTPUT_DIR / "吴宇轩_量化投研与大模型系统每周进展汇报_导师审阅版.pdf"
    generate_weekly_report_pdf(out_file)
