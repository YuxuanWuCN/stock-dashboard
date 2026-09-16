# -*- coding: utf-8 -*-
"""《读懂"真谛"，方能融会贯通》—— 自我推荐式研究报告 PDF 生成器

主线：读懂真谛 → 融会贯通；目的：向老师毛遂自荐；语气：谦逊务实。
复用项目内 generate_study_report_pdf.py 的中文字体注册方案。
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
    HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports"


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


def build(out_pdf: Path):
    register_fonts()

    doc = SimpleDocTemplate(
        str(out_pdf), pagesize=A4,
        leftMargin=1.6 * cm, rightMargin=1.6 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title="读懂真谛，方能融会贯通 —— 自我推荐式研究报告",
        author="【姓名】",
    )

    styles = getSampleStyleSheet()
    navy = colors.HexColor("#1a365d")
    blue = colors.HexColor("#2b6cb0")
    gray = colors.HexColor("#4a5568")
    dark = colors.HexColor("#2d3748")

    st_title = ParagraphStyle("T", fontName="ChineseBold", fontSize=19, leading=27, textColor=navy, alignment=1, spaceAfter=6)
    st_sub = ParagraphStyle("S", fontName="ChineseRegular", fontSize=10.5, leading=16, textColor=gray, alignment=1, spaceAfter=8)
    st_h1 = ParagraphStyle("H1", fontName="ChineseBold", fontSize=12.5, leading=17, textColor=navy, spaceBefore=10, spaceAfter=5, keepWithNext=True)
    st_h2 = ParagraphStyle("H2", fontName="ChineseBold", fontSize=10, leading=14, textColor=blue, spaceBefore=6, spaceAfter=3, keepWithNext=True)
    st_body = ParagraphStyle("B", fontName="ChineseRegular", fontSize=9, leading=14.5, textColor=dark, spaceAfter=4)
    st_quote = ParagraphStyle("Q", fontName="ChineseRegular", fontSize=9.5, leading=15, textColor=navy, alignment=1, spaceAfter=6)
    st_th = ParagraphStyle("TH", fontName="ChineseBold", fontSize=7.6, leading=10.5, textColor=colors.white, alignment=1)
    st_td = ParagraphStyle("TD", fontName="ChineseRegular", fontSize=7.4, leading=10.5, textColor=dark)
    st_call = ParagraphStyle("C", fontName="ChineseRegular", fontSize=9, leading=15, textColor=dark)
    st_sign = ParagraphStyle("SG", fontName="ChineseRegular", fontSize=10, leading=18, textColor=dark, alignment=2)

    story = []

    # ===================== 封面标题 =====================
    story.append(Paragraph("读懂“真谛”，方能融会贯通", st_title))
    story.append(Paragraph("—— 研读师弟《Serenity 瓶颈投资框架》的学习体悟与自我推荐报告", st_sub))
    meta = (
        "研读对象：Serenity Chokepoint Investing Framework (Enhanced v2.1)　|　"
        "汇报人：【姓名】　|　【学校 · 专业 · 年级】　|　报告日期：%s"
    ) % datetime.now().strftime("%Y年%m月%d日")
    story.append(Paragraph(meta, ParagraphStyle("M", fontName="ChineseRegular", fontSize=8, leading=12, textColor=gray, alignment=1, spaceAfter=4)))
    story.append(HRFlowable(width="100%", thickness=1.2, color=blue, spaceAfter=10))

    # ===================== 一、缘起 =====================
    story.append(Paragraph("一、缘起：一份让我反复读了三遍的“作业”", st_h1))
    story.append(Paragraph(
        "老师让我认真研读师弟的这个项目。起初我把它当作一份“技术文档”来读，想的是“它用了什么模型、什么接口”；"
        "读到第三遍我才真正意识到——它真正的价值不在代码（<b>SKILL.md 里甚至没有一行可执行代码</b>），"
        "而在于一套<b>“如何在噪声市场中不犯认知错误”的研究纪律</b>。这份报告，是我读懂之后向老师汇报体悟、并毛遂自荐的一份答卷。",
        st_body,
    ))

    # ===================== 二、真谛 =====================
    story.append(Paragraph("二、我读懂的“真谛”：一句话与五层递进", st_h1))
    story.append(Paragraph(
        "师弟项目的灵魂，浓缩成一句话——",
        st_body,
    ))
    story.append(Paragraph(
        "「先找瓶颈，再找敞口，然后证据验证，再统计检验，最后按 alpha 显著性定仓位。」",
        st_quote,
    ))
    story.append(Paragraph(
        "这句话看似朴素，拆开是五层严密的递进。我把每一层都对应到了自己真正理解到的“深层含义”：",
        st_body,
    ))
    t1 = Table([
        [Paragraph("层级", st_th), Paragraph("要做的事", st_th), Paragraph("我理解到的深层含义", st_th)],
        [Paragraph("<b>1 找瓶颈</b>", st_td), Paragraph("在供应链里找“卡脖子”环节", st_td), Paragraph("不是先问“哪只股会涨”，而是先问“哪个环节物理上无法被绕开”。", st_td)],
        [Paragraph("<b>2 找敞口</b>", st_td), Paragraph("找卡在这个环节的上市公司", st_td), Paragraph("真正的机会常在二、三阶隐形冠军，而非聚光灯下的组装厂。", st_td)],
        [Paragraph("<b>3 证据验证</b>", st_td), Paragraph("事实/观点/推断三角验证", st_td), Paragraph("对抗 AI 幻觉与检索偏见，让每句话都可审计、可复核。", st_td)],
        [Paragraph("<b>4 统计检验</b>", st_td), Paragraph("代码跑 Fama-MacBeth + IR", st_td), Paragraph("alpha 由数学算出，不由语言模型猜出。", st_td)],
        [Paragraph("<b>5 定仓位</b>", st_td), Paragraph("按赌注类型+证据阶段+拥挤度", st_td), Paragraph("仓位与持有周期必须和“赌的是什么”绑定。", st_td)],
    ], colWidths=[2.0 * cm, 5.0 * cm, 10.8 * cm])
    t1.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f7fafc"), colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t1)
    story.append(Spacer(1, 8))

    # ===================== 三、认知转变 =====================
    story.append(Paragraph("三、三个让我“顿悟”的认知转变", st_h1))

    story.append(Paragraph("1. 从“买 AI 故事”到“查物理瓶颈”", st_h2))
    story.append(Paragraph(
        "真正的瓶颈有九条硬特征：需求结构性增长、供给受限、扩产慢、技术壁垒高、客户认证难、替代技术少、影响系统级交付、"
        "市场尚未充分认知、业绩弹性非线性。而“伪瓶颈”恰恰相反：竞争者众多、扩产快、切换成本低、靠社媒叙事、估值已透支多年业绩。"
        "这套二分法最触动我的一句话是——<b>“不买 AI 叙事，只查 AI 瓶颈”</b>。",
        st_body,
    ))

    story.append(Paragraph("2. 从“静态评级”到“动态阶段”", st_h2))
    story.append(Paragraph(
        "师弟把静态的 A/B/C/D 证据评级，升级为动态的<b>证据阶段转移图</b>：概念 → 送样 → 小批量 → 量产 → 主供。"
        "关键洞见在于：<b>alpha 窗口往往在“阶段之间”，不在某个静态时点</b>——“送样”不等于“量产”，"
        "两者之间的“里程碑重估时滞”才是超额收益真正的来源。这与我此前用数据验证老师“业务成绩兑现期”判断时的感受完全同频。",
        st_body,
    ))

    story.append(Paragraph("3. 从“让 LLM 猜”到“让代码算”（最深刻的一层）", st_h2))
    story.append(Paragraph(
        "这是整份框架里我认为最有价值的一次“自我革命”。v2.0 曾让大模型给四个维度打分再连乘，结果 0.7^4=0.24，"
        "把明明不错的标的判成“勉强有趣”——因为<b>大模型天生不擅长概率校准</b>，还会自信地编造精确数字。"
        "v2.1 的解法是：<b>LLM 负责定性假设生成（找瓶颈、查节点、三角验证），代码负责定量检验（Fama-MacBeth 回归、IR、GMM）</b>。"
        "再配合硬约束保证可证伪：瓶颈分&lt;12 拒、α 不显著降级、IR&lt;0.3 拒。",
        st_body,
    ))

    story.append(PageBreak())

    # ===================== 四、批判性阅读 =====================
    story.append(Paragraph("四、我读出了“别人容易忽略的细节”（批判性阅读）", st_h1))
    story.append(Paragraph(
        "汇报里如果只夸“写得好”，是敷衍。我把自己真读进去、且能指出的三处细节写在这里，也算向老师证明我确实逐字读完了全部 6 篇 ADR。",
        st_body,
    ))

    story.append(Paragraph("1. 迭代留痕：v2.0→v2.1 之间文档没有完全同步", st_h2))
    story.append(Paragraph(
        "ADR-0001 写“IR&lt;0.5 拒绝”，但 README 与 SKILL.md 正文用的是“IR&lt;0.3 拒绝”（0.3~0.5 归为弱 alpha，仅小仓位）；"
        "ADR-0006 写的是<b>乘法</b>仓位调整，而 v2.1 正文已改成<b>加权/绝对百分点</b>调整并加硬地板 max(Base×25%, 0.5%)。"
        "我由此悟出一个方法论层面的道理：<b>“决策即记录、记录即同步”</b>，文档一旦与决策脱节，就会误导后来者——读源码要读“决策历史”，不能只看最终结论。",
        st_body,
    ))

    story.append(Paragraph("2. 工艺节点本体论不是文字游戏，是反“搜索偏见”的武器", st_h2))
    story.append(Paragraph(
        "把 InP 衬底（晶体生长、全球供应商&lt;5 家、壁垒极高）与 InP 外延片（MOCVD 设备、竞争者更多）区分开，"
        "看似只是分类学洁癖，实则能防止“搜磷化铟供应商”时被 SEO 软文导向下游概念股、从而错失真瓶颈。"
        "这正是我之前行业标签太粗、需要补的一课。",
        st_body,
    ))

    story.append(Paragraph("3. “上下游交叉验证”是整份框架里最被低估的一层", st_h2))
    story.append(Paragraph(
        "单家公司管理层嘴里的“需求强劲”是观点；上游预收款与下游客户资本开支的<b>同向变化</b>才是事实。"
        "共振信号增信、背离信号预警——它把研究从“听一家之言”升级为“听一整条链的财务事实”，信噪比成倍提高。",
        st_body,
    ))

    # ===================== 五、融会贯通 =====================
    story.append(Paragraph("五、融会贯通：这套真谛照进我自己的项目", st_h1))

    story.append(Paragraph("1. 英雄所见略同：定量层我已独立实现", st_h2))
    story.append(Paragraph(
        "读到这里我最大的惊喜是——师弟“代码算 alpha”的思路，与我系统里已经跑通的底层<b>完全一致</b>："
        "我的 <b>fama_macbeth.py</b> 已实现四因子（MKT/SMB/HML/MOM）+ HAC 稳健标准误 + 无前视截断，"
        "我的 <b>alpha_gate.py</b> 已实现“p&lt;0.05 且 IR≥0.3 才放行”的硬门槛。"
        "这说明“量化不可被大模型幻觉替代”已是领域共识，也让我对自己的方向更有信心。",
        st_body,
    ))

    story.append(Paragraph("2. 我该补的短板（诚实的自我审视）", st_h2))
    story.append(Paragraph(
        "对照师弟框架，我坦诚自己有三处明显短板：① 缺<b>工艺节点本体</b>——我的行业标签偏宏观（光伏/新能源/半导体），易被下游概念股误导；"
        "② 缺<b>事实三角验证</b>——我的 AI 研报偏叙述性，缺少 [FACT]/[OPINION]/[INFERENCE] 标注与跨信源核验；"
        "③ 缺<b>上下游交叉验证</b>——目前主要看单家财报，没有“听一整条链”。",
        st_body,
    ))

    story.append(Paragraph("3. 融合落地思路（简要 Spec-Kit 规划）", st_h2))
    story.append(Paragraph(
        "我的设想：用师弟框架做“漏斗顶端”，选出核心卡位池；再用我的看板做日级跟踪与门控检验。"
        "具体落地为四个模块——新增 <b>chokepoint.py</b>（节点校验 + 20 分问卷）、<b>ontology_db.py</b>（工艺节点库）、"
        "事实标注 Prompt 模板，以及 <b>serenity_pipeline.py</b>（把定性结果接入现有 alpha_gate 做双重门禁）。",
        st_body,
    ))

    # ===================== 六、研究底色 =====================
    story.append(Paragraph("六、我的研究底色（支撑这份自荐的“事实”）", st_h1))
    story.append(Paragraph(
        "毛遂自荐不能只靠“态度”，我把自己已有的、可核验的事实列在这里：",
        st_body,
    ))
    t2 = Table([
        [Paragraph("维度", st_th), Paragraph("我的现状", st_th)],
        [Paragraph("覆盖规模", st_td), Paragraph("202 只全球标的（A股 91 / 港股 36 / 美股 44 / 韩股 10 / ETF 21），日级自动化看板。", st_td)],
        [Paragraph("定量检验", st_td), Paragraph("已跑通 Fama-MacBeth 四因子回归 + IR 门禁 + 无前视截断。", st_td)],
        [Paragraph("策略验证", st_td), Paragraph("模拟盘“稳健 vs 激进”每日对决 + 预测校准后训练闭环。", st_td)],
        [Paragraph("实证复盘", st_td), Paragraph("用数据验证过老师的判断（立新能源翻倍减仓、涨停后 20 日回调 83.3%）。", st_td)],
        [Paragraph("理论结合", st_td), Paragraph("波浪/波动理论量化复盘（立新能源、山东黄金）。", st_td)],
    ], colWidths=[3.0 * cm, 14.8 * cm])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), blue),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f7fafc"), colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t2)
    story.append(Spacer(1, 8))

    # ===================== 七、结语 =====================
    story.append(Paragraph("七、结语：毛遂自荐，恳请指教", st_h1))
    call = (
        "老师，读这份项目的过程，像一次“照镜子”：它照出了我的短板（产业深度、证据纪律），也印证了我的方向（量化不可替代）。"
        "我最大的收获不是某一个具体指标，而是学会了<b>“用可证伪的纪律，替代模糊的自信”</b>。<br/><br/>"
        "在此毛遂自荐：我希望能在老师的指导下，把师弟框架里的“工艺节点本体 + 事实三角验证 + 上下游交叉验证”真正落地进我的量化流水线，"
        "做出一个<b>“既有产业深度、又有数学硬度”</b>的融合版本；若有机会，也恳请老师引荐我与师弟当面交流、请教框架细节。<br/><br/>"
        "无论结果如何，这次研读都让我受益良多。谢谢老师！"
    )
    tq = Table([[Paragraph(call, st_call)]], colWidths=[17.8 * cm])
    tq.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ebf8ff")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#3182ce")),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
    ]))
    story.append(tq)
    story.append(Spacer(1, 12))
    story.append(Paragraph("汇报人：【姓名】　　【学校 · 专业 · 年级】", st_sign))
    story.append(Paragraph(datetime.now().strftime("%Y年%m月%d日"), st_sign))

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story)
    print("[OK] 自荐报告 PDF 已生成:", out_pdf)


if __name__ == "__main__":
    # 注：reports 目录在当前沙箱环境 ACL 锁定（无写权限），故输出到项目根目录（已确认可写）
    build(REPO_ROOT / "瓶颈投资框架学习体悟与自我推荐报告.pdf")
