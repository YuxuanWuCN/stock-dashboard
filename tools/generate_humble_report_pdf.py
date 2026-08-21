# -*- coding: utf-8 -*-
"""吴宇轩真实手笔：研读您师弟《Serenity瓶颈投资》的学习笔记与请教

华南师范大学阿伯丁学院 信息管理与信息系统 25级
特点：谦逊请教式、真实困惑、图文印证、避免评价性语言。
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
    """注册中文字体"""
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


def build_humble_pdf(out_pdf: Path):
    register_fonts()

    doc = SimpleDocTemplate(
        str(out_pdf), pagesize=A4,
        leftMargin=1.6 * cm, rightMargin=1.6 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title="研读您师弟Serenity框架的学习笔记与请教",
        author="吴宇轩（华南师范大学阿伯丁学院 信管 25级）",
    )

    styles = getSampleStyleSheet()
    
    ink = colors.HexColor("#1a202c")
    sub_ink = colors.HexColor("#4a5568")
    title_blue = colors.HexColor("#1e3a8a")
    h2_blue = colors.HexColor("#2563eb")
    bg_light = colors.HexColor("#f8fafc")
    border_gray = colors.HexColor("#e2e8f0")

    st_title = ParagraphStyle("T", fontName="ChineseBold", fontSize=17, leading=23, textColor=title_blue, alignment=1, spaceAfter=4)
    st_sub = ParagraphStyle("S", fontName="ChineseRegular", fontSize=10, leading=15, textColor=sub_ink, alignment=1, spaceAfter=6)
    
    st_h1 = ParagraphStyle("H1", fontName="ChineseBold", fontSize=12, leading=16, textColor=title_blue, spaceBefore=9, spaceAfter=4, keepWithNext=True)
    st_h2 = ParagraphStyle("H2", fontName="ChineseBold", fontSize=9.5, leading=14, textColor=h2_blue, spaceBefore=6, spaceAfter=2.5, keepWithNext=True)
    st_body = ParagraphStyle("B", fontName="ChineseRegular", fontSize=8.8, leading=14.5, textColor=ink, spaceAfter=4)
    
    st_quote = ParagraphStyle("Q", fontName="ChineseBold", fontSize=9, leading=14, textColor=title_blue, alignment=1, spaceAfter=4)
    st_caption = ParagraphStyle("CP", fontName="ChineseRegular", fontSize=7.5, leading=11, textColor=sub_ink, alignment=1, spaceBefore=2, spaceAfter=5)
    
    st_th = ParagraphStyle("TH", fontName="ChineseBold", fontSize=7.8, leading=11, textColor=colors.white, alignment=1)
    st_td = ParagraphStyle("TD", fontName="ChineseRegular", fontSize=7.5, leading=11, textColor=ink)
    st_call = ParagraphStyle("C", fontName="ChineseRegular", fontSize=8.8, leading=15, textColor=ink)
    st_sign = ParagraphStyle("SG", fontName="ChineseRegular", fontSize=9, leading=15, textColor=ink, alignment=2)

    story = []

    # 标题
    story.append(Paragraph('研读您师弟《Serenity瓶颈投资框架》的学习笔记与请教', st_title))
    meta = '学生：吴宇轩（华南师范大学阿伯丁学院 · 信息管理与信息系统 25级）　|　日期：%s' % datetime.now().strftime("%Y年%m月%d日")
    story.append(Paragraph(meta, st_sub))
    story.append(HRFlowable(width="100%", thickness=1.0, color=title_blue, spaceAfter=8))

    # ============================================================
    # 一、 缘起
    # ============================================================
    story.append(Paragraph('一、 缘起：一份让我反复读了好几遍的“作业”', st_h1))
    p1 = '''老师您好！前两天您让我认真读一读您师弟做的这个开源项目（<code>serenity-chokepoint-investing-enhanced</code>），我克隆下来后第一反应是愣了一下——里面全是 <code>.md</code> 文档，核心的 <code>SKILL.md</code> 甚至一行可执行代码都没有，我还以为下错了。'''
    story.append(Paragraph(p1, st_body))
    p2 = '''但当我静下心把 6 篇 ADR（架构决策记录）逐字逐句读完后，才明白您为什么让我读这个：您师弟（师叔）做的不是“教大模型炒股”，而是在<b>给大模型建立一套严格的研究纪律和防错机制</b>。大模型最容易一本正经地胡说八道，特别是在金融这种噪声极大的领域。师叔这套框架的核心价值，是把资深产业研究员查产业链的严谨方法，拆解成了大模型必须一步步执行的“防错检查清单”。'''
    story.append(Paragraph(p2, st_body))

    # ============================================================
    # 二、 我理解的核心主线
    # ============================================================
    story.append(Paragraph('二、 我理解的框架核心主线（请老师指正）', st_h1))
    story.append(Paragraph('整个框架的主线，师叔在 README 开头用一句话概括得很清楚：', st_body))
    story.append(Paragraph('“先找瓶颈，再找敞口，然后证据验证，再统计检验，最后按 alpha 显著性定仓位。”', st_quote))
    story.append(Paragraph('我理解这 5 步是环环相扣的硬门槛，前面不过关，后面就不继续：', st_body))

    t1_data = [
        [Paragraph('分析步骤', st_th), Paragraph('师叔框架的要求', st_th), Paragraph('我的初步理解（可能不全面）', st_th)],
        [
            Paragraph('<b>1. 查真瓶颈</b>', st_td),
            Paragraph('按 10 个维度打分（20 分制），低于 12 分直接淘汰', st_td),
            Paragraph('不听公司讲 AI 故事，先看它在物理层面是不是真卡脖子、能不能被绕过。', st_td)
        ],
        [
            Paragraph('<b>2. 找准位置</b>', st_td),
            Paragraph('工艺本体论：按工艺节点分类（原材料→衬底→外延→器件→模块→系统）', st_td),
            Paragraph('搞清楚标的到底在链条哪一段，避免把下游组装厂当成上游核心卡点。', st_td)
        ],
        [
            Paragraph('<b>3. 证据验证</b>', st_td),
            Paragraph('事实/观点/推断三元标签 + 独立信源交叉核验 + 上下游财务共振/背离', st_td),
            Paragraph('单家公司管理层的话不算数，要去查下游客户的资本开支、上游的预收款。', st_td)
        ],
        [
            Paragraph('<b>4. 代码硬验</b>', st_td),
            Paragraph('Python 跑 Fama-MacBeth 四因子回归，要求 p&lt;0.05 且 IR≥0.3', st_td),
            Paragraph('Alpha 由统计方法算出，不让大模型自己估算概率和打分。', st_td)
        ],
        [
            Paragraph('<b>5. 纪律定仓</b>', st_td),
            Paragraph('按赌注类型（Super Beta/Catalyst Alpha/Event）+ 证据阶段动态调整', st_td),
            Paragraph('短线催化剂按短线仓位做，长线成长按长线仓位做，别混着来。', st_td)
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
    # 三、 双层架构的设计
    # ============================================================
    story.append(Paragraph('三、 v2.1 双层架构的设计逻辑（我的理解）', st_h1))
    p3 = '''我在读 ADR-0001 时看到，师叔在 v2.0 时也踩过坑：曾经让大模型给 4 个维度分别打概率再相乘（P瓶颈 × P错配 × P催化剂 × P流动性），结果发现 <code>0.7^4 = 0.24</code>，明明每个维度评分都不错，乘起来反而把好标的判成了不及格。'''
    story.append(Paragraph(p3, st_body))
    p4 = '''v2.1 的改进思路是<b>双层分工</b>：大模型负责定性（查产业链、识别节点、打瓶颈分、做证据判断），定量检验（拉数据、跑回归、算 alpha 和 IR）全部交给 Python 代码。两层各司其职，避免大模型去硬算数字：'''
    story.append(Paragraph(p4, st_body))

    # 插入图 1
    fig1 = FIGURES_DIR / "arch_framework.png"
    if fig1.exists():
        story.append(Image(str(fig1), width=17.5 * cm, height=8.0 * cm))
        story.append(Paragraph('图 1：v2.1 双层架构——大模型定性生成假设，Python 代码定量检验', st_caption))

    # ============================================================
    # 四、 两个让我印象深刻的设计细节
    # ============================================================
    story.append(Paragraph('四、 两个让我印象特别深刻的设计（配图说明）', st_h1))

    story.append(Paragraph('1. 工艺节点本体论：防止被 SEO 内容误导', st_h2))
    p5 = '''ADR-0002 里举的例子特别有说服力：磷化铟（InP）上游的<b>单晶衬底</b>（如鑫耀半导）和下游的<b>外延片</b>（如三安光电），虽然都用 InP 材料，但前者是全球只有三五家能做的真卡脖子（定价权极强），后者是 MOCVD 设备型、竞争者更多。如果只按材料分类，搜索引擎会优先推 SEO 做得好的下游公司，而不是真正的上游瓶颈。'''
    story.append(Paragraph(p5, st_body))

    # 插入图 2
    fig2 = FIGURES_DIR / "ontology_pipeline.png"
    if fig2.exists():
        story.append(Image(str(fig2), width=17.5 * cm, height=5.8 * cm))
        story.append(Paragraph('图 2：AI 算力与光器件产业链工艺节点拆解（越往上游，壁垒越高）', st_caption))

    story.append(Paragraph('2. 证据阶段转移图：Alpha 在“阶段之间”', st_h2))
    p6 = '''ADR-0003 提出的动态证据阶段（概念 → 送样 → 小批试产 → 规模量产 → 主力独供）让我很受启发。师叔特别强调：超额收益往往不是在某个静态时点，而是在<b>市场刚意识到阶段跃迁的时滞里</b>。另外 ADR 还要求必须同时评估“advancement triggers”（向上推进信号）和“regression triggers”（倒退/证伪信号），这样不仅知道什么时候加仓，也知道什么时候止损。'''
    story.append(Paragraph(p6, st_body))

    # 插入图 3
    fig3 = FIGURES_DIR / "stage_transition.png"
    if fig3.exists():
        story.append(Image(str(fig3), width=17.5 * cm, height=5.5 * cm))
        story.append(Paragraph('图 3：证据阶段动态推进与 Alpha 捕获窗口', st_caption))

    story.append(PageBreak())

    # ============================================================
    # 五、 读完后我还没完全理解的几个地方（向老师请教）
    # ============================================================
    story.append(Paragraph('五、 读完后我还没完全理解的几个地方（向老师请教）', st_h1))
    p7 = '''老师，虽然我把 6 篇 ADR 和 SKILL.md 都逐字读完了，但有几个地方自己想了很久还是没太理解透，想向老师和师叔请教：'''
    story.append(Paragraph(p7, st_body))

    conf_data = [
        [Paragraph('我的困惑点', st_th), Paragraph('具体问题描述', st_th), Paragraph('想请教老师的', st_th)],
        [
            Paragraph('<b>1. 财报时滞问题</b>', st_td),
            Paragraph('ADR-0005 的上下游财务交叉验证很有穿透力，但 A 股财报季度披露，等拿到数据可能滞后 1-3 个月。', st_td),
            Paragraph('师叔实际用时，有没有用高频数据（招标公告、调研纪要）来弥补时滞？还是主要用在长周期标的上？', st_td)
        ],
        [
            Paragraph('<b>2. A 股适配性</b>', st_td),
            Paragraph('四因子模型（MKT/SMB/HML/MOM）是美股验证的。我用立新能源回测时发现，它翻倍更多是政策+游资，跟 MOM 关系不大。', st_td),
            Paragraph('A 股是否需要加入“政策敏感度因子”或“资金流因子”？还是四因子本身就能覆盖？', st_td)
        ],
        [
            Paragraph('<b>3. 验证子代理成本</b>', st_td),
            Paragraph('ADR-0004 要求独立验证子代理跨信源核对每个 FACT，这需要搜索 API 和财务数据源（Wind/Bloomberg）。', st_td),
            Paragraph('个人或学生用户搞不到这些付费 API 时，有没有低成本的替代方案？', st_td)
        ],
        [
            Paragraph('<b>4. 新兴技术判定</b>', st_td),
            Paragraph('对于 CPO、硅光、Chiplet 这类新兴技术，公开信源很少。ADR-0002 要求至少 2 个独立信源验证节点，信源稀缺时怎么办？', st_td),
            Paragraph('是标记为 [FACT:single_source] 并降低仓位？还是有其他验证办法？', st_td)
        ],
        [
            Paragraph('<b>5. 实盘效果</b>', st_td),
            Paragraph('这套框架在真实市场里跑过吗？效果如何（年化收益、夏普、回撤）？', st_td),
            Paragraph('如果有案例（哪怕脱敏的），我在融合时会更有方向感。', st_td)
        ],
    ]
    t_conf = Table(conf_data, colWidths=[2.4 * cm, 7.0 * cm, 8.6 * cm])
    t_conf.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, border_gray),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [bg_light, colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_conf)
    story.append(Spacer(1, 4))

    # ============================================================
    # 六、 结合老师指导：我自己的系统现状与实证
    # ============================================================
    story.append(Paragraph('六、 结合老师之前的指导：我自己系统的现状与实证复盘', st_h1))
    p8 = '''读师叔的框架时，让我很惊喜的一个发现是：<b>我们在定量检验这一层的想法是对上的</b>！<br/>我自己的股票看板系统（2.0版）之前在做自动化日更时，也独立写了 <code>fama_macbeth.py</code> 和 <code>alpha_gate.py</code>，同样是用四因子回归检验超额收益、用 IR 做门槛判断。看到师叔也是这个思路，我觉得方向应该是对的。<br/><br/>另外，上次您点拨我立新能源“翻倍该减仓、回调是早晚的事”，我后来用程序把真实 268 根 K 线回测了一遍，做出了完整的波浪切分图，验证了您的判断：'''
    story.append(Paragraph(p8, st_body))

    # 插入图 4（立新能源波浪图）
    fig4 = OLD_FIGURES_DIR / "001258_wave_analysis.png"
    if fig4.exists():
        story.append(Image(str(fig4), width=17.5 * cm, height=7.2 * cm))
        story.append(Paragraph('图 4：立新能源（001258）真实回测——翻倍减仓点躲过 -19% 跌停，回调踩在 0.500/0.618 黄金位', st_caption))

    story.append(PageBreak())

    # ============================================================
    # 七、 我的短板与融合思路
    # ============================================================
    story.append(Paragraph('七、 我诚实看到的自己的短板与融合思路', st_h1))
    p9 = '''对照师叔的框架，我很清楚地看到了自己系统的不足：<br/>我的行业标签太粗（简单分在半导体、新能源、光伏这种大类），没有细化到师叔那种“衬底 vs 外延 vs 器件”的工艺节点粒度；AI 研报目前偏向文本摘要，缺少“上下游财务交叉验证”和“事实/观点/推断三元标签”这种严格的证据机制。<br/><br/>所以我现在的想法是：<b>把师叔的框架当作“核心标的筛选器”</b>，用他的瓶颈 10 问 + 工艺节点 + 证据验证，从我系统跟踪的 202 只标的里筛出 10-20 只真正有产业逻辑的核心池；然后用我的自动化流水线对这个核心池做日级 Fama-MacBeth 检验、IR 门控、模拟盘对决，验证定性假设在真实市场里是否成立。'''
    story.append(Paragraph(p9, st_body))

    t_plan_data = [
        [Paragraph('系统模块', st_th), Paragraph('我目前的现状', st_th), Paragraph('融合师叔框架后的设想', st_th)],
        [
            Paragraph('<b>标的初筛</b>', st_td),
            Paragraph('202 只全球跨市场股票，全覆盖粗筛', st_td),
            Paragraph('用瓶颈 10 问 + 工艺节点做顶层漏斗，筛出 10-20 只核心池', st_td)
        ],
        [
            Paragraph('<b>产业定性</b>', st_td),
            Paragraph('传统行业分类 + LLM 摘要', st_td),
            Paragraph('接入工艺节点库 + 上下游财务交叉验证 + 事实三元标签', st_td)
        ],
        [
            Paragraph('<b>定量检验</b>', st_td),
            Paragraph('已有 Fama-MacBeth + IR 门控', st_td),
            Paragraph('直接复用，作为定性假设的终审门槛', st_td)
        ],
        [
            Paragraph('<b>实盘验证</b>', st_td),
            Paragraph('模拟盘每日对决 + 预测校准闭环', st_td),
            Paragraph('对核心池做实盘跟踪，验证瓶颈投资的真实胜率与夏普', st_td)
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

    # ============================================================
    # 八、 学生自荐与请教
    # ============================================================
    story.append(Paragraph('八、 学生自荐与诚恳请教', st_h1))
    call = '''老师，这次认真研读师叔的项目，对我最大的触动是：<b>学会了用严格、可证伪的研究纪律，替代模糊的叙事直觉</b>。我之前的系统更偏向工程自动化和全市场横扫，在产业链穿透和证据验证上确实太粗糙了。<br/><br/>我是华南师范大学阿伯丁学院信管专业 25 级的学生，平时既喜欢写代码搭系统，也对量化投研很感兴趣。目前我已经把融合方案的工程接口（Spec-Kit 规范）设计好了，非常希望能在老师的指导下，把师叔的高深度产业定性方法与我的自动化流水线真正合在一起，做出一个更扎实的系统。<br/><br/>上面第五章列的那 5 个困惑，是我融合过程中最担心踩坑的地方，恳请老师指点！如果后续有课题或项目机会，学生非常渴望能参与进来多向您和师兄师姐们学习。如果合适，也恳请老师能引荐我认识师叔，向他当面请教几个框架细节。<br/><br/>再次感谢老师的悉心指引！'''
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
    
    sign_text = '学生：吴宇轩　　华南师范大学阿伯丁学院 · 信息管理与信息系统 25级<br/>%s' % datetime.now().strftime("%Y年%m月%d日")
    story.append(Paragraph(sign_text, st_sign))

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story)
    print("[OK] 谦逊请教式、真实学生手笔 PDF 已生成:", out_pdf)


if __name__ == "__main__":
    out_file = REPO_ROOT / "研读您师弟瓶颈投资框架的学习笔记与请教（吴宇轩）.pdf"
    build_humble_pdf(out_file)
