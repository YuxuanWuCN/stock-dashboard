# -*- coding: utf-8 -*-
"""《读懂“真谛”，方能融会贯通》—— 图文深度增强版 自我推荐式研究报告 PDF 生成器

特色：
1. 包含 4 幅高精量化与架构分析图谱：
   - 图 1: Serenity v2.1 双层协同架构：定性假设生成 + 代码定量硬检验
   - 图 2: AI 光互联/半导体供应链工艺节点本体映射 (Ontology 严禁混淆)
   - 图 3: 动态证据阶段转移与 Alpha 黄金催化窗口
   - 图 4: 立新能源（001258）真实 268 根日K线波浪结构、翻倍减仓点与斐波那契黄金分割实证
2. 严格按“读懂真谛 → 融会贯通 → 批判性反思 → 支撑事实 → 谦逊自荐”主线设计。
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIGURES_DIR = REPO_ROOT / "report_figures"
REPORTS_DIR = REPO_ROOT / "reports"
OLD_FIGURES_DIR = REPO_ROOT / "reports" / "figures"


def register_fonts():
    """注册中文字体（优先微软雅黑，回退黑体/宋体）。"""
    candidates = [
        ("C:/Windows/Fonts/msyh.ttc", 0, "ChineseRegular"),
        ("C:/Windows/Fonts/simhei.ttf", None, "ChineseRegular"),
        ("C:/Windows/Fonts/simsun.ttc", 0, "ChineseRegular"),
    ]
    regular_ok = False
    for path, sub_idx, _name in candidates:
        if os.path.exists(path):
            try:
                if sub_idx is not None:
                    pdfmetrics.registerFont(TTFont("ChineseRegular", path, subfontIndex=sub_idx))
                else:
                    pdfmetrics.registerFont(TTFont("ChineseRegular", path))
                regular_ok = True
                break
            except Exception:
                continue

    bold_ok = False
    for path, sub_idx in [("C:/Windows/Fonts/msyhbd.ttc", 0), ("C:/Windows/Fonts/simhei.ttf", None)]:
        if os.path.exists(path):
            try:
                if sub_idx is not None:
                    pdfmetrics.registerFont(TTFont("ChineseBold", path, subfontIndex=sub_idx))
                else:
                    pdfmetrics.registerFont(TTFont("ChineseBold", path))
                bold_ok = True
                break
            except Exception:
                continue
    if not bold_ok and regular_ok:
        pdfmetrics.registerFont(TTFont("ChineseBold", "C:/Windows/Fonts/msyh.ttc", subfontIndex=0))


def build_enhanced_pdf(out_pdf: Path):
    register_fonts()

    doc = SimpleDocTemplate(
        str(out_pdf), pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.4 * cm, bottomMargin=1.4 * cm,
        title="读懂真谛，方能融会贯通 —— 图文增强版研究与自荐报告",
        author="【姓名】",
    )

    styles = getSampleStyleSheet()
    navy = colors.HexColor("#1a365d")
    blue = colors.HexColor("#2b6cb0")
    gray = colors.HexColor("#4a5568")
    dark = colors.HexColor("#2d3748")

    st_title = ParagraphStyle("T", fontName="ChineseBold", fontSize=18, leading=24, textColor=navy, alignment=1, spaceAfter=4)
    st_sub = ParagraphStyle("S", fontName="ChineseRegular", fontSize=10, leading=15, textColor=gray, alignment=1, spaceAfter=6)
    st_h1 = ParagraphStyle("H1", fontName="ChineseBold", fontSize=12, leading=16, textColor=navy, spaceBefore=8, spaceAfter=4, keepWithNext=True)
    st_h2 = ParagraphStyle("H2", fontName="ChineseBold", fontSize=9.5, leading=13.5, textColor=blue, spaceBefore=5, spaceAfter=2.5, keepWithNext=True)
    st_body = ParagraphStyle("B", fontName="ChineseRegular", fontSize=8.5, leading=13.5, textColor=dark, spaceAfter=3.5)
    st_quote = ParagraphStyle("Q", fontName="ChineseRegular", fontSize=9, leading=14, textColor=navy, alignment=1, spaceAfter=5)
    st_caption = ParagraphStyle("CP", fontName="ChineseRegular", fontSize=7.5, leading=11, textColor=gray, alignment=1, spaceBefore=2, spaceAfter=6)
    
    st_th = ParagraphStyle("TH", fontName="ChineseBold", fontSize=7.5, leading=10.5, textColor=colors.white, alignment=1)
    st_td = ParagraphStyle("TD", fontName="ChineseRegular", fontSize=7.2, leading=10, textColor=dark)
    st_call = ParagraphStyle("C", fontName="ChineseRegular", fontSize=8.5, leading=14, textColor=dark)
    st_sign = ParagraphStyle("SG", fontName="ChineseRegular", fontSize=9.5, leading=16, textColor=dark, alignment=2)

    story = []

    # ============================================================
    # 封面标题与元数据
    # ============================================================
    story.append(Paragraph("读懂“真谛”，方能融会贯通", st_title))
    story.append(Paragraph("—— 研读师弟《Serenity 瓶颈投资框架》的学习体悟与自我推荐报告（图文深度版）", st_sub))
    meta = (
        "研读对象：Serenity Chokepoint Investing Framework (Enhanced v2.1)　|　"
        "汇报人：【姓名】　|　【学校 · 专业 · 年级】　|　日期：%s"
    ) % datetime.now().strftime("%Y年%m月%d日")
    story.append(Paragraph(meta, ParagraphStyle("M", fontName="ChineseRegular", fontSize=7.5, leading=11, textColor=gray, alignment=1, spaceAfter=3)))
    story.append(HRFlowable(width="100%", thickness=1.2, color=blue, spaceAfter=6))

    # ============================================================
    # 一、 缘起：一份让我反复读了三遍的“作业”
    # ============================================================
    story.append(Paragraph("一、缘起：一份让我反复读了三遍的“作业”", st_h1))
    story.append(Paragraph(
        "老师让我认真研读师弟的这个项目。起初我把它当作一份“技术文档”来读，琢磨的是“调了什么接口、跑了什么模型”；"
        "读到第三遍我才真正意识到——它真正的精髓不在代码本身（<b>SKILL.md 里甚至没有一行可执行代码</b>），"
        "而在于一套<b>“如何在极低信噪比市场中不犯认知错误”的研究纪律</b>。这份报告，是我读懂之后向老师汇报体悟、并毛遂自荐的一份图文答卷。",
        st_body,
    ))

    # ============================================================
    # 二、 我读懂的“真谛”：一句话与五层递进
    # ============================================================
    story.append(Paragraph("二、我读懂的“真谛”：一句话与五层递进", st_h1))
    story.append(Paragraph(
        "师弟项目的灵魂，浓缩成一句话——", st_body
    ))
    story.append(Paragraph(
        "「先找瓶颈，再找敞口，然后证据验证，再统计检验，最后按 alpha 显著性定仓位。」", st_quote
    ))
    
    t1 = Table([
        [Paragraph("层级", st_th), Paragraph("要做的事", st_th), Paragraph("我理解到的深层含义与认知防错机制", st_th)],
        [Paragraph("<b>1 找瓶颈</b>", st_td), Paragraph("在供应链里找物理“卡脖子”环节", st_td), Paragraph("不是先问“哪只股会涨”，而是先问“哪个环节在物理上根本无法被绕开”。", st_td)],
        [Paragraph("<b>2 找敞口</b>", st_td), Paragraph("找卡在这个节点的上市公司", st_td), Paragraph("真正有暴利弹性的往往是二、三阶隐形冠军，而非聚光灯下的下游组装厂。", st_td)],
        [Paragraph("<b>3 证据验证</b>", st_td), Paragraph("事实/观点/推断三元三角验证", st_td), Paragraph("对抗 AI 幻觉与检索偏见，要求每句结论可审计、上下游财务共振核验。", st_td)],
        [Paragraph("<b>4 统计检验</b>", st_td), Paragraph("代码跑 Fama-MacBeth + IR 门禁", st_td), Paragraph("Alpha 由严谨数学模型算出，绝不让大模型靠直觉编造概率与打分。", st_td)],
        [Paragraph("<b>5 定仓位</b>", st_td), Paragraph("按赌注类型+证据阶段+拥挤度", st_td), Paragraph("仓位与持有周期必须和“赌的是什么性质的超额”严格绑定，防止长线短做。", st_td)],
    ], colWidths=[1.8 * cm, 4.8 * cm, 11.4 * cm])
    t1.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f7fafc"), colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t1)
    story.append(Spacer(1, 4))

    # ============================================================
    # 三、 架构真谛：双层协同与认知防错图谱
    # ============================================================
    story.append(Paragraph("三、核心架构进化：LLM 定性生成 + 代码定量硬检验（v2.1 突破）", st_h1))
    story.append(Paragraph(
        "师弟在 v2.0 曾尝试用大模型打出 4 个维度概率再做连乘，结果 <code>0.7^4 = 0.24</code>，把好机会判成了“勉强有趣”——"
        "因为<b>大模型天生缺乏概率校准能力</b>。v2.1 架构果断剥离了大模型的数值打分职能，确立了<b>双层协同</b>：",
        st_body
    ))
    
    # 插入图 1
    fig1 = FIGURES_DIR / "arch_framework.png"
    if fig1.exists():
        story.append(Image(str(fig1), width=18.0 * cm, height=9.0 * cm))
        story.append(Paragraph("<b>图 1：Serenity v2.1 双层协同架构（LLM 定性假设生成 + 代码定量硬约束检验）</b>", st_caption))

    story.append(PageBreak())

    # ============================================================
    # 四、 产业深度：工艺节点本体论 vs 证据阶段转移
    # ============================================================
    story.append(Paragraph("四、产业深度：工艺节点本体论与证据阶段跃迁", st_h1))
    
    story.append(Paragraph("1. 工艺节点本体论（Ontology）：反“搜索偏见”与“伪概念”的照妖镜", st_h2))
    story.append(Paragraph(
        "在分析科技股时，若按传统题材将“磷化铟（InP）材料”混为一谈，搜索引擎会优先推送 SEO 优化好的下游外延厂商（如三安），"
        "而真正卡死全球供给、拥有极高定价权的是上游<b>衬底晶圆（如鑫耀半导）</b>。师弟严密划分了 6 大工艺层级：",
        st_body
    ))
    
    # 插入图 2
    fig2 = FIGURES_DIR / "ontology_pipeline.png"
    if fig2.exists():
        story.append(Image(str(fig2), width=18.0 * cm, height=6.8 * cm))
        story.append(Paragraph("<b>图 2：AI 算力与光互联产业链工艺节点本体映射（严格区分上游卡点与下游组装）</b>", st_caption))

    story.append(Paragraph("2. 证据阶段转移图（Stage Map）：捕捉里程碑重估时滞的 Alpha", st_h2))
    story.append(Paragraph(
        "投资研究必须告别静态评级。送样不等于小批量，小批量不等于量产。真正的超额 Alpha 往往孕育在<b>阶段跨越的时滞中</b>：",
        st_body
    ))
    
    # 插入图 3
    fig3 = FIGURES_DIR / "stage_transition.png"
    if fig3.exists():
        story.append(Image(str(fig3), width=18.0 * cm, height=6.4 * cm))
        story.append(Paragraph("<b>图 3：动态证据阶段转移与 Alpha 黄金催化窗口（阶段跃迁驱动估值中枢重塑）</b>", st_caption))

    story.append(PageBreak())

    # ============================================================
    # 五、 批判性反思：我读出的细节不一致与方法论启示
    # ============================================================
    story.append(Paragraph("五、我读出的“别人容易忽略的细节”（批判性阅读与反思）", st_h1))
    story.append(Paragraph(
        "汇报如果只停留在“夸赞”，那是浮于表面。我把逐字精读全部 6 篇 ADR 后发现的三处文档与实现细节记录如下：",
        st_body
    ))

    story.append(Paragraph("1. 迭代留痕：ADR 与 v2.1 正文阈值未完全同步", st_h2))
    story.append(Paragraph(
        "ADR-0001 写“IR&lt;0.5 拒绝”，而 README 与 SKILL.md 正文统一修正为“IR&lt;0.3 拒绝（0.3~0.5 归为弱 alpha 仅小仓位）”；"
        "ADR-0006 仍保留了乘法仓位缩放公式，但 v2.1 正文已全面升级为<b>加权/绝对百分点加减</b>并设置了 <code>max(Base×25%, 0.5%)</code> 硬地板。"
        "这让我深刻体会到：<b>“决策即记录、记录即同步”</b>，读系统必须读版本演化史。",
        st_body
    ))

    story.append(Paragraph("2. “上下游财务交叉验证”是全框架实战穿透力最强的一环", st_h2))
    story.append(Paragraph(
        "单家管理层的口头指引只是观点；<b>标的存货周转加快 + 上游供应商预收账款大增 + 下游巨头资本开支上修</b>形成的全链条同向，才是无可辩驳的事实共振。这一招能击碎绝大多数财务粉饰与伪概念。",
        st_body
    ))

    # ============================================================
    # 六、 融会贯通与实证实战支撑（我的研究底色）
    # ============================================================
    story.append(Paragraph("六、融会贯通：照进我自己的量化系统与实证复盘", st_h1))
    story.append(Paragraph(
        "1. <b>定量底层的英雄所见略同</b>：师弟框架要求用代码跑 Fama-MacBeth 回归与 IR 门控，而我的系统已经独立实现了 <code>fama_macbeth.py</code>（四因子 MKT/SMB/HML/MOM + HAC 稳健标准误、无前视截断）与 <code>alpha_gate.py</code>（p&lt;0.05 且 IR≥0.3 硬门槛）。两套体系在量化硬核性上天然契合！<br/>"
        "2. <b>老师波浪与波动理论的量化实证</b>：此前结合老师关于“翻倍该减仓、回调是早晚的事”的点拨，我对立新能源（001258）268 根日K线进行了严格的 ZigZag 与斐波那契回撤实证，完美印证了老师的判断：",
        st_body
    ))

    # 插入图 4（立新能源真实波浪实证图）
    fig4 = OLD_FIGURES_DIR / "001258_wave_analysis.png"
    if fig4.exists():
        story.append(Image(str(fig4), width=18.0 * cm, height=8.6 * cm))
        story.append(Paragraph("<b>图 4：立新能源（001258）量化实证：翻倍减仓点避开 -19% 跌停杀跌与 0.500/0.618 黄金支撑回踩</b>", st_caption))

    story.append(PageBreak())

    # ============================================================
    # 七、 支撑事实与自我推荐结语
    # ============================================================
    story.append(Paragraph("七、我的研究底色与融合落地规划", st_h1))
    
    t2 = Table([
        [Paragraph("对比维度", st_th), Paragraph("我的量化系统（2.0版）现状", st_th), Paragraph("融合师弟框架后的升级规划（Spec-Kit 模式）", st_th)],
        [Paragraph("<b>覆盖标的</b>", st_td), Paragraph("202 只全球跨市场股票看板（日级自动化抓取）", st_td), Paragraph("以师弟“工艺瓶颈”做漏斗顶端，精选硬科技卡位核心池。", st_td)],
        [Paragraph("<b>定性深度</b>", st_td), Paragraph("宏观行业分类 + LLM 新闻情感与基础研报", st_td), Paragraph("引入 <b>6 级工艺节点本体库</b> + 事实三元标注与交叉验证。", st_td)],
        [Paragraph("<b>定量验证</b>", st_td), Paragraph("Fama-MacBeth 四因子 + HAC 检验 + 门禁熔断", st_td), Paragraph("直接复用原生定量引擎，作为定性假设的终审关卡。", st_td)],
        [Paragraph("<b>仓位管理</b>", st_td), Paragraph("模拟盘稳健 vs 激进对决 + 市场温度调节", st_td), Paragraph("接入 <b>Catalyst Alpha 赌注分类</b> 与证据阶段动态调仓。", st_td)],
    ], colWidths=[2.2 * cm, 7.8 * cm, 8.0 * cm])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f7fafc"), colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t2)
    story.append(Spacer(1, 8))

    story.append(Paragraph("八、结语：毛遂自荐，恳请指教", st_h1))
    call = (
        "老师，精读师弟项目的过程，对我而言是一次极其深刻的“认知照镜子”：它照出了我在产业微观节点上的粗糙，"
        "也极大地坚定了我在工程落地与数学定量硬检验上的探索方向。我最大的蜕变，是真正理解了<b>“用严谨、可证伪的研究纪律，替代盲目的叙事自信”</b>。<br/><br/>"
        "在此向老师毛遂自荐：我目前已做好基于 <b>Spec-Kit</b> 规范的完整工程融合方案，非常渴望在老师的指导下，"
        "将师弟框架中顶级的“工艺节点本体 + 事实三角验证 + 上下游交叉验证”，与我系统完备的“日级自动化流水线 + Fama-MacBeth 门控引擎”深度融合，"
        "打造出一套<b>“既有硬核产业穿透力、又有严密数学硬度”</b>的现代化量化投研系统。<br/><br/>"
        "若有机会，也恳请老师引荐我与师弟当面交流探讨！再次由衷感谢老师的悉心指引与栽培！"
    )
    tq = Table([[Paragraph(call, st_call)]], colWidths=[18.0 * cm])
    tq.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ebf8ff")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#3182ce")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(tq)
    story.append(Spacer(1, 10))
    story.append(Paragraph("汇报人：【姓名】　　【学校 · 专业 · 年级】", st_sign))
    story.append(Paragraph(datetime.now().strftime("%Y年%m月%d日"), st_sign))

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story)
    print("[OK] 图文增强版自荐报告 PDF 已成功生成:", out_pdf)


if __name__ == "__main__":
    out_file = REPO_ROOT / "瓶颈投资框架学习体悟与自我推荐报告_图文增强版.pdf"
    build_enhanced_pdf(out_file)
