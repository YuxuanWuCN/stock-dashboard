# -*- coding: utf-8 -*-
"""学生真实手笔：研读师弟《Serenity瓶颈投资》笔记与小结

作者信息：华南师范大学阿伯丁学院 信息管理与信息系统 25级
特点：去AI味、学生第一人称手记口吻、有思考有困惑、图文对照、排版朴素清爽。
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


def build_human_like_pdf(out_pdf: Path):
    register_fonts()

    doc = SimpleDocTemplate(
        str(out_pdf), pagesize=A4,
        leftMargin=1.6 * cm, rightMargin=1.6 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title="读师弟《Serenity瓶颈投资》的学习笔记与自荐小结",
        author="吴宇轩（华南师范大学阿伯丁学院 信管 25级）",
    )

    styles = getSampleStyleSheet()
    
    # 配色：采用清爽朴素的学术报告配色，去掉花哨的修饰
    ink = colors.HexColor("#1a202c")        # 正文字色：深炭黑
    sub_ink = colors.HexColor("#4a5568")    # 副标题/小字：铅灰
    title_blue = colors.HexColor("#1e3a8a") # 大标题：深学术蓝
    h2_blue = colors.HexColor("#2563eb")    # 二级标题：明快蓝
    bg_light = colors.HexColor("#f8fafc")   # 卡片浅灰底
    border_gray = colors.HexColor("#e2e8f0")

    st_title = ParagraphStyle("T", fontName="ChineseBold", fontSize=17, leading=23, textColor=title_blue, alignment=1, spaceAfter=4)
    st_sub = ParagraphStyle("S", fontName="ChineseRegular", fontSize=10, leading=15, textColor=sub_ink, alignment=1, spaceAfter=6)
    
    st_h1 = ParagraphStyle("H1", fontName="ChineseBold", fontSize=12, leading=16, textColor=title_blue, spaceBefore=9, spaceAfter=4, keepWithNext=True)
    st_h2 = ParagraphStyle("H2", fontName="ChineseBold", fontSize=9.5, leading=14, textColor=h2_blue, spaceBefore=6, spaceAfter=2.5, keepWithNext=True)
    st_body = ParagraphStyle("B", fontName="ChineseRegular", fontSize=8.8, leading=14.5, textColor=ink, spaceAfter=4)
    st_body_indent = ParagraphStyle("BI", fontName="ChineseRegular", fontSize=8.8, leading=14.5, textColor=ink, spaceAfter=4, firstLineIndent=16)
    
    st_quote = ParagraphStyle("Q", fontName="ChineseBold", fontSize=9, leading=14, textColor=title_blue, alignment=1, spaceAfter=4)
    st_caption = ParagraphStyle("CP", fontName="ChineseRegular", fontSize=7.5, leading=11, textColor=sub_ink, alignment=1, spaceBefore=2, spaceAfter=5)
    
    st_th = ParagraphStyle("TH", fontName="ChineseBold", fontSize=7.8, leading=11, textColor=colors.white, alignment=1)
    st_td = ParagraphStyle("TD", fontName="ChineseRegular", fontSize=7.5, leading=11, textColor=ink)
    st_call = ParagraphStyle("C", fontName="ChineseRegular", fontSize=8.8, leading=15, textColor=ink)
    st_sign = ParagraphStyle("SG", fontName="ChineseRegular", fontSize=9, leading=15, textColor=ink, alignment=2)

    story = []

    # ============================================================
    # 标题区：真实学生作业/笔记风格
    # ============================================================
    story.append(Paragraph("研读您师弟《Serenity瓶颈投资框架》的学习笔记与自荐小结", st_title))
    meta = "汇报人：吴宇轩（华南师范大学阿伯丁学院 · 信息管理与信息系统 25级）　|　日期：%s" % datetime.now().strftime("%Y年%m月%d日")
    story.append(Paragraph(meta, st_sub))
    story.append(HRFlowable(width="100%", thickness=1.0, color=title_blue, spaceAfter=8))

    # ============================================================
    # 一、 开头直接讲大白话与缘起
    # ============================================================
    story.append(Paragraph("一、 为什么这份“作业”我越看越有意思？", st_h1))
    p1 = (
        "老师您好！前两天您让我把您师弟做的这个开源项目（<code>serenity-chokepoint-investing-enhanced</code>）好好读一读，"
        "我一开始以为是个 Python 算法库或者量化回测框架，刚克隆下来还愣了一下——里面全是 <code>.md</code> 文档，"
        "核心的 <code>SKILL.md</code> 甚至连一行现成的执行代码都没有。"
    )
    story.append(Paragraph(p1, st_body))
    p2 = (
        "但当我静下心把里面的 6 篇 ADR（架构决策记录）逐字看完后，我才明白您为什么让我看这个："
        "师叔（您师弟）在做的根本不是“教大模型怎么炒股”，而是在<b>给大模型立规矩、防犯蠢</b>。"
        "大模型最容易一本正经地胡说八道，在炒股这件事上尤甚。您师弟这套框架最厉害的地方，就是把资深产业研究员查产业链的严谨习惯，"
        "拆成了大模型每一步必须照着执行的<b>“防错流水线”</b>。"
    )
    story.append(Paragraph(p2, st_body))

    # ============================================================
    # 二、 我总结的核心逻辑（真谛）
    # ============================================================
    story.append(Paragraph("二、 我领悟的框架主线：一句话与五个扣子", st_h1))
    story.append(Paragraph("整个项目的核心精髓，您师弟在文档开头写得很精辟：", st_body))
    story.append(Paragraph("“先找瓶颈，再找敞口，然后证据验证，再统计检验，最后按 alpha 显著性定仓位。”", st_quote))
    story.append(Paragraph("这 5 句话就像 5 个环环相扣的扣子，只要前面一个没扣好，后面绝不瞎买：", st_body))

    t1_data = [
        [Paragraph("分析步骤", st_th), Paragraph("您师弟框架的要求", st_th), Paragraph("我的通俗理解与学习体会", st_th)],
        [
            Paragraph("<b>1. 查真瓶颈</b>", st_td),
            Paragraph("按工艺节点 10 问打分，低于 12 分直接淘汰", st_td),
            Paragraph("不听公司吹 AI 故事，先看它在物理上是不是卡脖子、能不能被绕过去。", st_td)
        ],
        [
            Paragraph("<b>2. 找准位置</b>", st_td),
            Paragraph("工艺本体论（原材料→衬底→外延→芯片→模块）", st_td),
            Paragraph("搞清楚它到底在链条哪一段，别把下游赚辛苦钱的组装厂当成高壁垒核心标的。", st_td)
        ],
        [
            Paragraph("<b>3. 证据核验</b>", st_td),
            Paragraph("事实/观点/推断打标签 + 上下游财务交叉比对", st_td),
            Paragraph("管理层说需求好不算数，去查下游客户存货和自身预收款，防被单一财报忽悠。", st_td)
        ],
        [
            Paragraph("<b>4. 代码硬验</b>", st_td),
            Paragraph("Python 跑 Fama-MacBeth 回归，要求 p&lt;0.05 且 IR&ge;0.3", st_td),
            Paragraph("<b>这是最大的亮点</b>：绝不让大模型自己估算概率，交给代码和数学说话！", st_td)
        ],
        [
            Paragraph("<b>5. 纪律定仓</b>", st_td),
            Paragraph("按赌注类型（超级贝塔/催化剂/事件）和证据阶段调仓", st_td),
            Paragraph("短线催化剂就按短线做，别拿长线的仓位去做短线博弈，设好硬底线。", st_td)
        ],
    ]
    t1 = Table(t1_data, colWidths=[2.0 * cm, 5.0 * cm, 11.0 * cm])
    t1.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), title_blue),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, border_gray),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [bg_light, colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t1)
    story.append(Spacer(1, 4))

    # ============================================================
    # 三、 最让我兴奋的架构演进（双层协作）
    # ============================================================
    story.append(Paragraph("三、 为什么说 v2.1 的双层架构是个“真突破”？", st_h1))
    p3 = (
        "我发现您师弟在 v2.0 的时候也踩过坑：他曾让大模型去给 4 个维度打概率并乘起来（P瓶颈 × P错配 × P催化剂 × P流动性）。"
        "结果 4 个维度即使每个都给出 0.7 的不错评分，相乘后 <code>0.7^4 = 0.24</code>，直接把好股票判成了不及格。"
        "这是因为大模型根本没有统计校准能力，乘法只会无限放大主观噪声。"
    )
    story.append(Paragraph(p3, st_body))
    p4 = (
        "所以他在 v2.1 彻底改版成了<b>双层分工</b>：大模型只负责定性提假设（查产业链、看新闻、查节点），"
        "定量的任务全部甩给 Python 代码去跑多因子回归与信息比率（IR）。定性过关 + 统计显著，才算好标的："
    )
    story.append(Paragraph(p4, st_body))

    # 插入图 1
    fig1 = FIGURES_DIR / "arch_framework.png"
    if fig1.exists():
        story.append(Image(str(fig1), width=17.5 * cm, height=8.0 * cm))
        story.append(Paragraph("图 1：您师弟 v2.1 架构核心——大模型负责定性假设，Python 代码负责硬核检验", st_caption))

    # ============================================================
    # 四、 产业认知的两个“顿悟点”
    # ============================================================
    story.append(Paragraph("四、 读完之后让我顿悟的两个产业分析细节", st_h1))

    story.append(Paragraph("1. 工艺节点本体（Ontology）：别把外延当衬底", st_h2))
    p5 = (
        "比如光模块里的磷化铟（InP），如果只当成一个题材去搜，搜索引擎会推很多做外延片的三安光电之类，"
        "但真正卡脖子、全球只有三五家能做的是上游的<b>单晶衬底（如鑫耀半导）</b>。您师弟把产业链按工艺切得很细，"
        "这样选出来的标的才有真正的定价权："
    )
    story.append(Paragraph(p5, st_body))

    # 插入图 2
    fig2 = FIGURES_DIR / "ontology_pipeline.png"
    if fig2.exists():
        story.append(Image(str(fig2), width=17.5 * cm, height=5.8 * cm))
        story.append(Paragraph("图 2：AI 算力与光器件产业链工艺拆解——越靠近晶圆衬底与核心器件，技术壁垒越高", st_caption))

    story.append(Paragraph("2. 证据阶段转移图：超额收益在“阶段之间”", st_h2))
    p6 = (
        "送样 → 小批试产 → 大批量产 → 核心主供，每个阶段的估值和风险完全不同。"
        "股价暴涨往往不是在量产之后，而是在<b>市场刚开始意识到它能突破量产的那个时间差</b>："
    )
    story.append(Paragraph(p6, st_body))

    # 插入图 3
    fig3 = FIGURES_DIR / "stage_transition.png"
    if fig3.exists():
        story.append(Image(str(fig3), width=17.5 * cm, height=5.5 * cm))
        story.append(Paragraph("图 3：证据阶段推进与收益窗口——在客户验证到放量的时滞里赚取 Alpha", st_caption))

    story.append(PageBreak())

    # ============================================================
    # 五、 我发现的几处细节（我的批判性思考）
    # ============================================================
    story.append(Paragraph("五、 我读出来的几处文档小矛盾（向老师汇报）", st_h1))
    p7 = (
        "我在读代码库时发现您师弟在迭代过程中留下的几处小细节，感觉也很有意思："
    )
    story.append(Paragraph(p7, st_body))

    crit_data = [
        [Paragraph("发现的细节", st_th), Paragraph("文档现状与矛盾点", st_th), Paragraph("我的思考与推断", st_th)],
        [
            Paragraph("<b>IR 淘汰阈值</b>", st_td),
            Paragraph("ADR-0001 写的是 <code>IR &lt; 0.5 淘汰</code>，但 README 与 SKILL.md 统一改成了 <code>IR &lt; 0.3 淘汰</code>", st_td),
            Paragraph("实操中 0.3~0.5 确实能涵盖一些弱 Alpha 的小仓位机会，正文更务实，ADR 没来得及同步更新。", st_td)
        ],
        [
            Paragraph("<b>仓位调整公式</b>", st_td),
            Paragraph("ADR-0006 还在写连乘公式，但正文已经改成<b>绝对百分点加减</b>并设置了 0.5% 硬地板", st_td),
            Paragraph("您师弟在实践中发现连乘容易把仓位缩减到 0，改成加减点数更符合基金经理的调仓习惯。", st_td)
        ],
        [
            Paragraph("<b>上下游交叉验证</b>", st_td),
            Paragraph("ADR-0005 提出的“客户资本开支 vs 自身预收款”共振机制", st_td),
            Paragraph("这是我认为最值钱的一个点，它把单家财报的自说自话变成了全链条的互相印证。", st_td)
        ]
    ]
    t_crit = Table(crit_data, colWidths=[2.4 * cm, 6.4 * cm, 9.2 * cm])
    t_crit.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, border_gray),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [bg_light, colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_crit)
    story.append(Spacer(1, 4))

    # ============================================================
    # 六、 照进我自己系统的实证成果
    # ============================================================
    story.append(Paragraph("六、 结合老师指导：我的量化系统现状与实证复盘", st_h1))
    p8 = (
        "读您师弟的项目让我最惊喜的一点是：<b>我们在定量底层的想法完全对上了！</b><br/>"
        "我自己的股票看板系统（2.0版）之前在做自动化日更时，也写了 <code>fama_macbeth.py</code> 和 <code>alpha_gate.py</code>，"
        "同样是用四因子回归检验超额收益与 IR 门槛。看到您师弟也走这条路，我心里更有底了。<br/>"
        "另外，上次您点拨我立新能源“翻倍该减仓、回调是早晚的事”，我用程序回测了真实 268 根 K 线，做出了完整的实证图谱："
    )
    story.append(Paragraph(p8, st_body))

    # 插入图 4（立新能源波浪图）
    fig4 = OLD_FIGURES_DIR / "001258_wave_analysis.png"
    if fig4.exists():
        story.append(Image(str(fig4), width=17.5 * cm, height=7.2 * cm))
        story.append(Paragraph("图 4：我用立新能源 268 根日K线做的回测——翻倍减仓点刚好躲过 -19% 跌停，回调精准踩在 0.500/0.618 黄金位", st_caption))

    story.append(PageBreak())

    # ============================================================
    # 七、 融合规划与自荐结语
    # ============================================================
    story.append(Paragraph("七、 找到短板与下一步融合计划（Spec-Kit 模式）", st_h1))
    p9 = (
        "对照您师弟的框架，我也很诚实地看到了自己目前系统的不足：我的行业标签还是太粗（比如简单分在半导体、新能源），"
        "没有细化到工艺节点；AI 研报偏向摘要，缺少上下游事实的交叉验证。<br/>"
        "所以我规划了一个两全其美的融合方案："
    )
    story.append(Paragraph(p9, st_body))

    t_plan_data = [
        [Paragraph("系统模块", st_th), Paragraph("我目前的看板现状", st_th), Paragraph("融合您师弟框架后的升级设计", st_th)],
        [
            Paragraph("<b>标的池初筛</b>", st_td),
            Paragraph("覆盖 202 只全球股票，全市场粗筛", st_td),
            Paragraph("用您师弟的“工艺瓶颈 10 问”做顶层漏斗，筛选出高硬度核心池。", st_td)
        ],
        [
            Paragraph("<b>产业链定性</b>", st_td),
            Paragraph("传统行业分类 + LLM 研报摘要", st_td),
            Paragraph("接入 <b>6 级工艺节点库</b> + 上下游财报交叉验证 Prompt。", st_td)
        ],
        [
            Paragraph("<b>统计终审</b>", st_td),
            Paragraph("原生 Fama-MacBeth + IR 门控", st_td),
            Paragraph("<b>直接无缝复用现有模块</b>，对定性标的进行严格的无前视检验。", st_td)
        ],
        [
            Paragraph("<b>组合调仓</b>", st_td),
            Paragraph("模拟盘稳健 vs 激进每日对决", st_td),
            Paragraph("引入催化剂赌注分类与证据阶段动态打分。", st_td)
        ],
    ]
    t_plan = Table(t_plan_data, colWidths=[2.2 * cm, 7.8 * cm, 8.0 * cm])
    t_plan.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), title_blue),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, border_gray),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [bg_light, colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_plan)
    story.append(Spacer(1, 8))

    story.append(Paragraph("八、 学生心得与自荐想说的话", st_h1))
    call = (
        "老师，这次认真研读您师弟的项目，对我启发特别大。我最大的收获不仅是搞懂了几个新模型，"
        "而是学到了怎么在充满噪声的市场里建立一套<b>严谨、可被数据证伪的研究纪律</b>。<br/><br/>"
        "作为阿伯丁学院信管专业 25 级的学生，我平时既喜欢钻研信息系统架构和代码工程，也对量化金融充满了兴趣。"
        "目前我已经把整套融合方案的工程接口（Spec-Kit 规范）设计好了，非常希望能在老师您的指导下，"
        "把您师弟的高深度产业定性方法，与我现有的自动化数据流水线真正合在一起，做一个更落地的系统。<br/><br/>"
        "如果后续有课题或者项目机会，学生非常渴望能参与进来多向您和师兄师姐们学习！"
        "如果您觉得合适，也恳请老师能引荐我认识一下您师弟（师叔），向师叔当面请教几个框架落地的细节。非常感谢老师的悉心指引！"
    )
    tq = Table([[Paragraph(call, st_call)]], colWidths=[18.0 * cm])
    tq.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdf4")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#16a34a")),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(tq)
    story.append(Spacer(1, 10))
    
    sign_text = "华南师范大学阿伯丁学院 · 信息管理与信息系统 25级学生：吴宇轩<br/>%s" % datetime.now().strftime("%Y年%m月%d日")
    story.append(Paragraph(sign_text, st_sign))

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story)
    print("[OK] 去AI味、真实学生手笔 PDF 已生成:", out_pdf)


if __name__ == "__main__":
    out_file = REPO_ROOT / "研读师弟瓶颈投资框架学习笔记与自荐小结.pdf"
    build_human_like_pdf(out_file)