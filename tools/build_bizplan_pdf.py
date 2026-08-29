# -*- coding: utf-8 -*-
"""tools/build_bizplan_pdf.py —— 国创赛产业赛道「商业计划书」PDF 构建脚本

用途：
    产出校内申报系统第三上传位所需的《项目简称+商业计划书.pdf》。
    内容按附件5「产业赛道项目评审要点（企业命题组）」5 大评审维度组织。

设计：
    - 内容与排版彻底分离：所有事实/数字/口径在 tools/bizplan_content.py，
      本文件只负责渲染，不含任何业务内容。
    - 复用 Rainbow_FinGPTv2/tools/dossier_base.py 的 BasePublicationPDF 视觉规范
      （字阶、配色、表格样式、Accent Box），但改造为支持多页自动分页。

用法：
    python tools/build_bizplan_pdf.py [--out DIR]

对应规范：specs/016-contest-business-plan-pdf/spec.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(REPO_ROOT / "Rainbow_FinGPTv2" / "tools"))

from fpdf.enums import Align, WrapMode, XPos, YPos  # noqa: E402

import bizplan_content as C  # noqa: E402
from dossier_base import BasePublicationPDF  # noqa: E402

# 主题色：Slate 900 深蓝体系，与既有三份研报保持一致
THEME_COLOR: Tuple[int, int, int] = (30, 58, 138)

# 各评审维度的章节配色（用于章节标题与索引表）
DIM_COLORS = {
    "个人成长": (190, 24, 93),    # 玫红 —— 最高权重，视觉上最先被注意
    "项目创新": (30, 58, 138),    # 深蓝
    "团队协作": (13, 148, 136),   # 青绿
    "实现成效": (180, 83, 9),     # 琥珀
    "项目分析": (109, 40, 217),   # 紫
}

PAGE_W = 210.0
MARGIN = 15.0
CONTENT_W = PAGE_W - 2 * MARGIN  # 180mm
BOTTOM_LIMIT = 278.0             # 触发分页的 y 阈值


class BizPlanPDF(BasePublicationPDF):
    """商业计划书 PDF：在研报基类之上增加多页流式排版能力。

    基类为 3 页定长研报设计（auto_page_break=False，页脚硬编码 "of 3"），
    本类改为按需分页，并将页脚改为章节名 + 真实总页数占位。
    """

    def __init__(self) -> None:
        super().__init__(theme_title="商业计划书", theme_color_rgb=THEME_COLOR)
        self.set_auto_page_break(auto=False)
        self.current_chapter: str = ""
        self.toc_entries: List[Tuple[str, int, int]] = []  # (维度名, 分值, 页码)
        self._cover_mode = False

    # ---------------- 页眉页脚 ----------------

    def header(self) -> None:
        if self._cover_mode:
            return
        self.set_fill_color(15, 23, 42)
        self.rect(0, 0, PAGE_W, 3.2, "F")
        self.set_fill_color(*self.theme_color)
        self.rect(0, 3.2, PAGE_W, 1.2, "F")
        self.set_font("msyh", "", self.FS_FOOTER)
        self.set_text_color(100, 116, 139)
        self.set_xy(MARGIN, 5.2)
        left = f"{C.PROJECT_SHORT_NAME} · 商业计划书"
        self.cell(120, 4.0, left, align="L")
        self.cell(60, 4.0, self.current_chapter, align="R")

    def footer(self) -> None:
        if self._cover_mode:
            return
        self.set_y(-10)
        self.set_draw_color(226, 232, 240)
        self.set_line_width(0.2)
        self.line(MARGIN, 287, PAGE_W - MARGIN, 287)
        self.set_font("msyh", "", self.FS_FOOTER)
        self.set_text_color(148, 163, 184)
        self.set_xy(MARGIN, 288)
        self.cell(140, 4, "2026 中国国际大学生创新大赛 · 产业赛道企业命题组 · 达观数据", align="L")
        self.cell(40, 4, f"第 {self.page_no()} 页", align="R")

    # ---------------- 流式排版辅助 ----------------

    def ensure_space(self, needed: float) -> None:
        """若当前页剩余高度不足 needed，则换页。"""
        if self.get_y() + needed > BOTTOM_LIMIT:
            self.add_page()
            self.set_y(12.0)

    def body_text(self, text: str, line_h: float = 4.4, size: Optional[float] = None) -> None:
        """输出正文段落，自动左对齐 + 字符换行（规避 mixed-CJK 空格拉伸）。"""
        self.set_font("msyh", "", size or 8.2)
        self.set_text_color(30, 41, 59)
        self.set_x(MARGIN)
        self.multi_cell(CONTENT_W, line_h, text, align=Align.L, wrapmode=WrapMode.CHAR)
        self.ln(1.2)

    def chapter_title(self, index: str, name: str, score: int) -> None:
        """开启一个评审维度章节：新页 + 大标题 + 分值徽标，并登记目录。"""
        self.add_page()
        self.current_chapter = f"{index} {name}"
        color = DIM_COLORS.get(name, THEME_COLOR)
        self.toc_entries.append((name, score, self.page_no()))

        self.set_y(16.0)
        # 左侧色条
        self.set_fill_color(*color)
        self.rect(MARGIN, 16.0, 3.0, 13.0, "F")
        # 标题
        self.set_xy(MARGIN + 6.0, 16.5)
        self.set_font("msyh", "B", 15.0)
        self.set_text_color(15, 23, 42)
        self.cell(120, 7.0, f"{index}  {name}")
        # 分值徽标
        self.set_xy(PAGE_W - MARGIN - 34.0, 17.5)
        self.set_fill_color(*color)
        self.rect(PAGE_W - MARGIN - 34.0, 17.5, 34.0, 8.0, "F")
        self.set_font("msyh", "B", 9.0)
        self.set_text_color(255, 255, 255)
        self.cell(34.0, 8.0, f"评审分值 {score} 分", align="C")

        self.set_y(31.5)

    def sub_header(self, text: str, color: Optional[Tuple[int, int, int]] = None) -> None:
        """二级小节标题。"""
        self.ensure_space(12.0)
        self.ln(1.5)
        self.set_font("msyh", "B", 9.5)
        self.set_text_color(*(color or self.theme_color))
        self.set_x(MARGIN)
        self.cell(CONTENT_W, 5.4, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(226, 232, 240)
        self.set_line_width(0.3)
        self.line(MARGIN, self.get_y() + 0.3, MARGIN + 40, self.get_y() + 0.3)
        self.ln(2.2)

    def flow_table(
        self,
        headers: List[Tuple[str, float, str]],
        rows: List[List[str]],
        row_h: float = 4.6,
    ) -> None:
        """可跨页的数据表格（基类 draw_styled_table 为定长单页版本）。"""
        def _draw_head() -> None:
            self.set_fill_color(226, 232, 240)
            self.set_draw_color(203, 213, 225)
            self.set_line_width(0.2)
            self.set_font("msyh", "B", self.FS_TABLE_HDR)
            self.set_text_color(15, 23, 42)
            y = self.get_y()
            x = MARGIN
            for title, w, align in headers:
                self.set_xy(x, y)
                self.cell(w, 4.6, title, border=1, align=align, fill=True)
                x += w
            self.set_y(y + 4.6)

        self.ensure_space(4.6 + row_h * 2)
        _draw_head()

        for idx, row in enumerate(rows):
            # 估算本行需要的高度（按最长单元格的换行数）
            needed = row_h
            for i, val in enumerate(row):
                w = headers[i][1]
                n_lines = max(1, self.multi_cell(
                    w, row_h, val, align=Align.L, wrapmode=WrapMode.CHAR,
                    dry_run=True, output="LINES",
                ).__len__())
                needed = max(needed, n_lines * row_h)

            if self.get_y() + needed > BOTTOM_LIMIT:
                self.add_page()
                self.set_y(12.0)
                _draw_head()

            y = self.get_y()
            x = MARGIN
            self.set_fill_color(*((248, 250, 252) if idx % 2 == 1 else (255, 255, 255)))
            self.set_draw_color(226, 232, 240)
            self.set_line_width(0.15)
            self.set_font("msyh", "", self.FS_TABLE_CELL)
            self.set_text_color(30, 41, 59)

            for i, val in enumerate(row):
                w = headers[i][1]
                align = headers[i][2]
                self.set_xy(x, y)
                self.rect(x, y, w, needed, "DF")
                self.set_xy(x + 1.0, y + 0.6)
                self.multi_cell(
                    w - 2.0, row_h, val,
                    align=Align.C if align == "C" else Align.L,
                    wrapmode=WrapMode.CHAR,
                )
                x += w
            self.set_y(y + needed)
        self.ln(2.0)

    def callout(self, text: str, color: Optional[Tuple[int, int, int]] = None,
                label: str = "") -> None:
        """带左侧色条的强调框，高度按内容自动计算。"""
        self.set_font("msyh", "", self.FS_BODY + 0.6)
        lines = self.multi_cell(
            CONTENT_W - 6.0, 4.0, text, align=Align.L,
            wrapmode=WrapMode.CHAR, dry_run=True, output="LINES",
        )
        h = len(lines) * 4.0 + 3.0 + (5.0 if label else 0.0)
        self.ensure_space(h + 3.0)

        y = self.get_y()
        c = color or self.theme_color
        self.set_fill_color(248, 250, 252)
        self.set_draw_color(226, 232, 240)
        self.set_line_width(0.2)
        self.rect(MARGIN, y, CONTENT_W, h, "DF")
        self.set_fill_color(*c)
        self.rect(MARGIN, y, 2.2, h, "F")

        inner_y = y + 1.5
        if label:
            self.set_xy(MARGIN + 4.0, inner_y)
            self.set_font("msyh", "B", self.FS_BODY + 0.4)
            self.set_text_color(*c)
            self.cell(CONTENT_W - 6.0, 4.2, label)
            inner_y += 5.0

        self.set_xy(MARGIN + 4.0, inner_y)
        self.set_font("msyh", "", self.FS_BODY + 0.6)
        self.set_text_color(30, 41, 59)
        self.multi_cell(CONTENT_W - 6.0, 4.0, text, align=Align.L, wrapmode=WrapMode.CHAR)
        self.set_y(y + h + 2.5)


# ============================================================================
# 封面
# ============================================================================

def render_cover(pdf: BizPlanPDF) -> None:
    """P1 封面：身份信息必须与《附件3 申报表》逐字一致（spec FR-017）。"""
    pdf._cover_mode = True
    pdf.add_page()

    # 顶部深色区块
    pdf.set_fill_color(15, 23, 42)
    pdf.rect(0, 0, PAGE_W, 92.0, "F")
    pdf.set_fill_color(*THEME_COLOR)
    pdf.rect(0, 92.0, PAGE_W, 2.4, "F")

    pdf.set_xy(MARGIN, 22.0)
    pdf.set_font("msyh", "", 9.5)
    pdf.set_text_color(148, 163, 184)
    pdf.cell(CONTENT_W, 5.0, "2026 中国国际大学生创新大赛 · 产业赛道（企业命题组）")

    pdf.set_xy(MARGIN, 36.0)
    pdf.set_font("msyh", "B", 25.0)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(CONTENT_W, 12.0, "商业计划书")

    pdf.set_xy(MARGIN, 54.0)
    pdf.set_font("msyh", "B", 12.5)
    pdf.set_text_color(226, 232, 240)
    pdf.multi_cell(CONTENT_W, 6.4, C.IDENTITY["项目名称"],
                   align=Align.L, wrapmode=WrapMode.CHAR)

    pdf.set_xy(MARGIN, 78.0)
    pdf.set_font("msyh", "", 8.6)
    pdf.set_text_color(148, 163, 184)
    pdf.cell(CONTENT_W, 4.6, f"命题企业：{C.IDENTITY['命题企业']}")

    # 身份信息表
    y = 106.0
    rows = [
        ("命题名称", C.IDENTITY["命题名称"]),
        ("参赛组别", C.IDENTITY["参赛组别"]),
        ("申报单位", C.IDENTITY["申报单位"]),
        ("项目负责人", C.IDENTITY["项目负责人"]),
        ("团队规模", f"{len(C.TEAM)} 人（华南师范大学 + 中山大学跨校组建）"),
        ("在线演示", C.IDENTITY["在线演示"]),
    ]
    for i, (k, v) in enumerate(rows):
        pdf.set_fill_color(*((248, 250, 252) if i % 2 == 0 else (255, 255, 255)))
        pdf.set_draw_color(226, 232, 240)
        pdf.set_line_width(0.2)
        pdf.rect(MARGIN, y, CONTENT_W, 9.0, "DF")
        pdf.set_xy(MARGIN + 3.0, y + 2.2)
        pdf.set_font("msyh", "B", 8.0)
        pdf.set_text_color(71, 85, 105)
        pdf.cell(32.0, 4.6, k)
        pdf.set_font("msyh", "", 8.0)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(CONTENT_W - 38.0, 4.6, v)
        y += 9.0

    # 诚信声明
    pdf.set_y(y + 8.0)
    pdf.callout(
        "本文件所载全部量化结果均为历史数据回测与模拟盘测试，非真实资金实盘业绩。"
        "所有绩效指标均标注样本期、标的范围与适用边界；未达标指标如实列示，"
        "并单设章节披露局限性与失败案例。文中每一项量化结论均可追溯至项目仓库内的证据文件。",
        color=(180, 83, 9), label="数据口径与诚信声明",
    )

    pdf.set_y(268.0)
    pdf.set_font("msyh", "", 7.6)
    pdf.set_text_color(148, 163, 184)
    pdf.set_x(MARGIN)
    pdf.cell(CONTENT_W, 4.0, f"提交截止：{C.DEADLINE}", align="C")

    pdf._cover_mode = False


# ============================================================================
# 评审索引页
# ============================================================================

def render_rubric_index(pdf: BizPlanPDF, page_map: dict) -> None:
    """P2 评审要点—章节—页码对照索引（spec FR-003）。

    Args:
        page_map: 维度名 -> (起始页, 结束页)，由两遍渲染的第一遍产生。
    """
    pdf.current_chapter = "评审索引"
    pdf.add_page()
    pdf.set_y(16.0)

    pdf.set_font("msyh", "B", 15.0)
    pdf.set_text_color(15, 23, 42)
    pdf.set_x(MARGIN)
    pdf.cell(CONTENT_W, 8.0, "评审要点 · 章节 · 佐证对照索引", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1.0)

    pdf.body_text(
        "本索引依据《附件5 中国国际大学生创新大赛（2026）评审规则》第 15–16 页"
        "「八、产业赛道项目评审要点（企业命题组）」编制，五个评审要点与本文件章节一一对应，"
        f"共覆盖 {C.TOTAL_SUB_POINTS} 个官方子评审点。",
        size=8.0,
    )
    pdf.ln(1.0)

    headers = [("评审要点", 26.0, "C"), ("分值", 13.0, "C"), ("对应章节", 30.0, "C"),
               ("页码", 14.0, "C"), ("官方子评审点与核心佐证", 97.0, "L")]
    chapter_names = ["第一章", "第二章", "第三章", "第四章", "第五章"]
    rows = []
    for i, d in enumerate(C.DIMENSIONS):
        pages = page_map.get(d.name)
        page_str = f"P{pages[0]}–{pages[1]}" if pages and pages[0] != pages[1] else (
            f"P{pages[0]}" if pages else "—")
        rows.append([
            d.name, f"{d.score} 分", f"{chapter_names[i]} {d.name}",
            page_str, " · ".join(d.sub_points),
        ])
    pdf.flow_table(headers, rows, row_h=4.4)

    pdf.callout(
        "评分权重提示：技术与实证内容对应「项目创新」20 分与「实现成效」20 分，合计 40 分；"
        "而「个人成长」30 分、「团队协作」20 分、「项目分析」10 分合计 60 分，"
        "考察的是研究过程、团队组织与产业调研。本文件据此配置篇幅，"
        "而非将全部篇幅投入技术描述。",
        color=(109, 40, 217), label="本文件的篇幅配置依据",
    )

    pdf.sub_header("附加章节")
    pdf.flow_table(
        [("章节", 40.0, "L"), ("内容", 140.0, "L")],
        [["局限性与失败案例", "含样本期偏差、跑输基准、预测能力边界、Alpha 门控代价、"
                             "回测与实盘差异、大模型实现边界共 6 项主动披露"],
         ["附录 · 证据索引", "全部量化结论到仓库内证据文件的映射，含样本期与口径"]],
        row_h=4.4,
    )


# ============================================================================
# 第一章 个人成长（30 分）
# ============================================================================

def render_ch1_growth(pdf: BizPlanPDF) -> None:
    """个人成长：立德树人 / 调研深入 / 逻辑正确 / 知识掌握与应用 / 人才培养成效。"""
    color = DIM_COLORS["个人成长"]
    pdf.chapter_title("第一章", "个人成长", 30)

    pdf.callout(
        "本章回应附件5「个人成长」项下五个子评审点。核心线索是一次真实的认知转向："
        "从「我找到了一个因子」转为「我凭什么相信我找到的是因子」。"
        "这一转向由一次向产业界研究者的请教触发，并直接改变了本项目的技术架构。",
        color=color, label="本章主线",
    )

    # ---- 1.1 立德树人 ----
    pdf.sub_header("1.1 立德树人：选择做一个可被审计的系统，而不是一个收益更高的黑箱", color)
    pdf.body_text(
        "在量化投研领域，追求更高的回测收益是最容易获得关注的路径。本项目选择了另一条："
        "把工程重心放在证据可追溯、数值不可幻觉、风险可截断上。这一取向体现在三处具体决策："
    )
    pdf.body_text(
        "第一，强制证据锚定。系统生成的每一项财务数据与业务结论都必须绑定原始文档的段落级坐标，"
        "无法溯源的内容不予输出，而不是让模型「补全」一个看起来合理的数字。\n"
        "第二，主动自我审计。项目组撰写了《学术纠错报告》，对自身对外材料中存在的"
        "结果选择性报告、样本期选择偏差、模拟盘与实盘混淆等问题进行独立审核并逐条纠正。"
        "本文件即为该审计结论的落地版本。\n"
        "第三，如实列示未达标项。本文件第四章的指标对照表中，"
        "胜率、盈亏比与方向预测命中率均标注为未达标，未作任何修饰。"
    )
    pdf.callout(
        "恪守伦理规范在本项目中不是一句表态，而是一个可验证的行为记录："
        "我们主动写下了一份指出自己问题的报告，并据此修改了申报材料的数据口径。",
        color=color,
    )

    # ---- 1.2 调研深入 ----
    pdf.sub_header("1.2 调研深入：向产业界研究者请教，并留下完整往来记录", color)
    mentor = C.MENTOR_ANONYMOUS_LABEL if not C.MENTOR_CITATION_AUTHORIZED else "指导者"
    pdf.body_text(
        f"项目选题阶段，本人就「衡量股价最本质的东西是什么」向一位{mentor}请教，"
        "得到的回答是「因子」。在继续追问「因子究竟是什么」之后，"
        "收到一封三页的书面回复，内容涵盖财报时滞与领先指标、因子的正确用法、"
        "验证成本与免费数据路径、新兴技术在公开信源稀缺时的处理方式、"
        "以及实盘预期管理五个方面。"
    )
    pdf.body_text(
        "这次往来不是一次性的问答，而是形成了「提问 → 书面回复 → 代码实现 → 复盘验证」的闭环。"
        "本章 1.4 节列出了该回复中每一条具体建议在项目代码中的落点。"
    )
    for act in C.GROWTH_ACTS:
        if act.act_no == "第三幕":
            pdf.callout(act.body, color=(180, 83, 9), label="待补充：自主因子探索的具体记录")
            break

    # ---- 1.3 逻辑正确 ----
    pdf.sub_header("1.3 逻辑正确：一次可复述的认知转向（六幕）", color)
    pdf.body_text(
        "本项目的技术路线不是先有架构再找问题，而是由一连串真实的困惑推动形成。"
        "下表按时间顺序复述这一过程，并标注每一幕对应的附件5 子评审点。"
    )
    rows = [[a.act_no, a.title, a.body, a.sub_point] for a in C.GROWTH_ACTS]
    pdf.flow_table(
        [("阶段", 14.0, "C"), ("标题", 36.0, "L"), ("内容", 106.0, "L"), ("对应评审点", 24.0, "C")],
        rows, row_h=4.2,
    )
    pdf.callout(
        "第四幕是全过程的支点。在此之前，工作目标是「挖出有效因子」；"
        "在此之后，工作目标变成「建立一套能够拒绝无效因子的机制」。"
        "本文件第二章的 Alpha 门控与第四章披露的立新能源拒绝案例，"
        "都是这一转向的直接产物。",
        color=color, label="转向发生在哪里",
    )

    # ---- 1.4 知识掌握与应用能力 ----
    pdf.sub_header("1.4 知识掌握与应用能力：书面指导到代码产物的逐条落点", color)
    pdf.body_text(
        "下表将收到的书面指导逐条对应到项目仓库中的实际代码产物。"
        "该对应关系可在仓库内直接核验，构成「用学到的知识解决实际问题」的可查证据。"
    )
    pdf.flow_table(
        [("收到的指导内容", 80.0, "L"), ("项目中的代码产物", 100.0, "L")],
        [[m["指导内容"], m["代码产物"]] for m in C.MENTOR_CLOSURE],
        row_h=4.2,
    )
    pdf.callout(
        "其中最直接的一条：回复中提到做套利时会盯「因子拥挤（factor crowding）」与"
        "「因子半衰期（factor half-life）」两个指标，并建议以此为关键词检索文献。"
        "项目随后实现了 src/analysis/factor_quality.py，"
        "其模块说明写明「要度量预测力衰减速度（半衰期）与市场拥挤度来防因子动物园」。"
        "从一句口头建议到一个可运行模块，这条链路是完整且可验证的。",
        color=color, label="一个可核验的闭环",
    )
    pdf.body_text(
        "在计量方法层面，项目实现并验证了以下内容：Carhart 四因子模型的 Fama-MacBeth "
        "两阶段截面回归；Newey-West HAC 异方差自相关稳健修正（滞后期按 "
        "q = floor(4·(T/100)^(2/9)) 自适应）；采用 Harvey-Liu-Zhu (2016) 提出的 "
        "|t| ≥ 3.0 显著性标准而非常规 t ≥ 2.0；以及 611 项 pytest 单元与集成测试。"
    )

    # ---- 1.5 人才培养成效 ----
    pdf.sub_header("1.5 人才培养成效：专创融合与跨校协作", color)
    pdf.body_text(C.CROSS_SCHOOL_NOTE)
    pdf.flow_table(
        [("融合方式", 30.0, "L"), ("在本项目中的具体体现", 150.0, "L")],
        [
            ["专创融合", "信息管理与信息系统专业的数据建模与系统分析训练，"
                        "直接转化为多因子定价引擎与自动化投研流水线的工程实现"],
            ["产教融合", f"针对达观数据真实产业命题立项；与企业建立对接往来"
                        f"（详见第五章 5.2）；{C.MENTOR_ANONYMOUS_LABEL}的书面方法论指导"],
            ["科教融汇", "以 Fama-MacBeth、Carhart、Newey-West、Harvey-Liu-Zhu、"
                        "NALE 等公开学术成果为方法论基础，并在 A 股场景完成迁移与实证"],
            ["跨校协作", "华南师范大学与中山大学学生联合组队，学科视角与院校资源互补"],
            ["课程与科研训练关联", C.PH],
        ],
        row_h=4.2,
    )


# ============================================================================
# 第二章 项目创新（20 分）
# ============================================================================

def render_ch2_innovation(pdf: BizPlanPDF) -> None:
    """项目创新：创新理念 / 创新成效。四段式呈现每个创新点。"""
    color = DIM_COLORS["项目创新"]
    pdf.chapter_title("第二章", "项目创新", 20)

    pdf.callout(
        "本章不以收益率作为创新性的论据。每一个创新点都按「产业痛点 → 我们的选择 → "
        "为此付出的代价 → 可核验的证据」四段呈现。明确写出代价，是因为"
        "任何真实的工程取舍都有代价，只讲收益的方案在专家质询下无法自证。",
        color=color, label="本章的论证方式",
    )

    pdf.sub_header("2.1 创新理念：四项核心技术选择", color)
    for i, inv in enumerate(C.INNOVATIONS, 1):
        pdf.ensure_space(46.0)
        pdf.ln(1.0)
        pdf.set_font("msyh", "B", 9.0)
        pdf.set_text_color(*color)
        pdf.set_x(MARGIN)
        pdf.multi_cell(CONTENT_W, 5.0, f"创新点 {i} · {inv.title}",
                       align=Align.L, wrapmode=WrapMode.CHAR)
        pdf.ln(0.8)
        pdf.flow_table(
            [("维度", 22.0, "C"), ("内容", 158.0, "L")],
            [
                ["产业痛点", inv.pain],
                ["我们的选择", inv.choice],
                ["为此付出的代价", inv.cost],
                ["可核验的证据", inv.evidence],
            ],
            row_h=4.2,
        )

    pdf.sub_header("2.2 创新成效：对达观数据命题的针对性回应", color)
    pdf.body_text(
        "达观数据命题的核心诉求是构建面向金融量化投研全流程的智能体系统，"
        "并明确要求解决研报自动提取、因子沉淀与定价、多组合回测与自我进化闭环。"
        "本项目的四项创新分别对应企业侧的具体痛点："
    )
    pdf.flow_table(
        [("企业侧痛点", 46.0, "L"), ("本项目的回应", 74.0, "L"), ("提高创新效率的具体方式", 60.0, "L")],
        [
            ["大模型生成金融数值时出现幻觉，无法通过合规审计",
             "语义层与计算层解耦，LLM 不参与任何数值计算",
             "输出结论 100% 绑定原文坐标锚点，审计环节无需人工回查原始文档"],
            ["研报复现单篇耗时 4–20 小时，占用核心投研精力",
             "自动化 ETL 与结构化因子卡片流水线",
             "端到端耗时缩短 85% 以上（4–20h 降至约 15min）"],
            ["因子知识散落于个人经验，缺乏数字化沉淀载体",
             "统一结构因子卡片 + 因子质量度量模块",
             "因子的经济含义、计算逻辑、适用边界与半衰期可入库检索"],
            ["回测结果无法在实盘复现，根因是前视偏差",
             "物理隔绝数据集 + T+1 封箱协议 + 纯因果状态机",
             "回测结论具备可复现性，降低策略上线后的失效风险"],
        ],
        row_h=4.2,
    )
    pdf.callout(
        "需要说明的边界：本项目未进行 LoRA/QLoRA 参数微调，未加载 FinGPT 的 LoRA 权重"
        "（见 src/llm/fingpt_deepseek_adapter.py 源码声明）。"
        "创新位于工作流层——DAG 状态机编排、外部材料提示注入防御、"
        "后端与模型强制锁定、调用预算控制与显式降级路径，而非模型参数层。"
        "本项目是 FinGPT 方法论在中国 A 股场景的独立实现与适配，不等同于 FinGPT 论文本身。",
        color=(180, 83, 9), label="技术边界的如实说明",
    )


# ============================================================================
# 第三章 团队协作（20 分）
# ============================================================================

def render_ch3_team(pdf: BizPlanPDF) -> None:
    """团队协作：团队结构 / 团队效能 / 团队资源 / 团队贡献。"""
    color = DIM_COLORS["团队协作"]
    pdf.chapter_title("第三章", "团队协作", 20)

    pdf.sub_header("3.1 团队结构", color)
    pdf.body_text(C.CROSS_SCHOOL_NOTE)
    pdf.flow_table(
        [("姓名", 18.0, "C"), ("学校", 24.0, "C"), ("院系及专业", 62.0, "L"),
         ("年级学历", 22.0, "C"), ("团队分工与角色", 54.0, "L")],
        [[m.name, m.school, m.college_major, m.grade, m.role] for m in C.TEAM],
        row_h=4.2,
    )
    pdf.body_text(
        f"团队现有成员 {len(C.TEAM)} 人，符合大赛通知关于「每队成员为 3–15 人（含负责人）"
        "且须为项目实际核心成员」的要求。"
    )

    pdf.sub_header("3.2 团队效能：与项目关系的真实性", color)
    pdf.body_text(
        "附件5「团队效能」子项考察团队与项目关系的真实性与紧密性。本项目提供两类可核验证据："
    )
    pdf.flow_table(
        [("证据类型", 34.0, "L"), ("说明", 146.0, "L")],
        [
            ["版本控制提交记录",
             "项目全部代码与文档变更均在 git 仓库中留有带时间戳的提交记录，"
             "可逐条核验各成员的实际参与内容与时间分布，非事后补写"],
            ["自动化测试与质量门禁",
             "611 项 pytest 测试与分层质量门禁（small / medium / heavy）持续运行，"
             "任何成员的代码变更均须通过门禁，协作过程有客观留痕"],
            ["长期运行记录",
             "系统按交易日自动执行数据清洗、评分、调仓与发布，"
             "形成连续的每日产出记录与策略进化轨迹"],
        ],
        row_h=4.2,
    )

    pdf.sub_header("3.3 团队资源", color)
    pdf.flow_table(
        [("资源类型", 34.0, "L"), ("与项目的关系", 146.0, "L")],
        [
            ["院校资源", "华南师范大学阿伯丁数据科学与人工智能学院的专业课程与实验环境"],
            ["跨校资源", "中山大学成员带来的学科视角与院校资源互补"],
            ["产业界指导", f"{C.MENTOR_ANONYMOUS_LABEL}提供的书面方法论指导，"
                          f"内容已逐条落实为代码产物（见第一章 1.4）"],
            ["企业对接", f"与达观数据的对接往来（详见第五章 5.2）"],
            ["开源与公开数据", "akshare 行情接口、Kenneth French 公开因子库、"
                             "巨潮资讯公告信源、交易所公开披露数据"],
        ],
        row_h=4.2,
    )

    pdf.sub_header("3.4 团队贡献", color)
    pdf.flow_table(
        [("姓名", 18.0, "C"), ("在项目中的实质性贡献", 162.0, "L")],
        [[m.name, m.contribution] for m in C.TEAM],
        row_h=4.2,
    )

    pdf.body_text("指导教师及其实质性贡献：")
    pdf.flow_table(
        [("姓名", 22.0, "C"), ("单位", 46.0, "L"), ("职称/研究方向", 46.0, "L"),
         ("实质性贡献", 66.0, "L")],
        [[a["姓名"], a["单位"], a["职称/研究方向"], a["实质性贡献"]] for a in C.ADVISORS],
        row_h=4.2,
    )
    pdf.callout(
        "按大赛通知要求，项目指导教师须为高校教师。本栏信息在确认前保持待补充状态，"
        "不以任何非真实姓名或机构填充。",
        color=(180, 83, 9), label="填报说明",
    )


# ============================================================================
# 第四章 实现成效（20 分）
# ============================================================================

def render_ch4_effect(pdf: BizPlanPDF) -> None:
    """实现成效：实施方案 / 需求匹配 / 社会效益，并单设局限性披露。"""
    color = DIM_COLORS["实现成效"]
    pdf.chapter_title("第四章", "实现成效", 20)

    pdf.sub_header("4.1 实施方案", color)
    pdf.flow_table(
        [("阶段", 26.0, "L"), ("工作目标", 62.0, "L"), ("难点", 50.0, "L"), ("状态", 42.0, "L")],
        [
            ["一 · 数据与因子基座", "多源数据接入、因子库构建、无风险利率与四因子对齐",
             "A 股因子日历与行情日历不一致导致样本损失", "已完成"],
            ["二 · 定价引擎", "Fama-MacBeth 两阶段回归 + Newey-West HAC + Alpha 门控",
             "小样本下 HAC 滞后期选择与统计功效不足", "已完成"],
            ["三 · 战术风控", "纯因果 ZigZag 状态机、斐波那契买点、C 浪强制清仓",
             "杜绝未来函数的同时保持信号及时性", "已完成"],
            ["四 · 三大板块实证", "存储、黄金、绿电三板块物理隔绝回测与出版级研报",
             "样本期均为板块上行周期，缺乏熊市验证", "已完成"],
            ["五 · 全池广度验证", "202 支股票、100 交易日全截面因果回测",
             "全池平均胜率与盈亏比未达标", "已完成"],
            ["六 · 实盘验证", "小资金实盘测试（≤10 万元）与规模化跟踪",
             "涨跌停流动性、冲击成本与系统故障等实盘约束", "计划中（3–12 个月）"],
        ],
        row_h=4.2,
    )

    pdf.sub_header("4.2 需求匹配：达观命题考核指标诚实对照", color)
    pdf.body_text(
        "下表逐项对照达观数据命题的考核指标。达标项与未达标项一并列示，"
        "未达标项不作修饰。每项均标注实测口径与证据来源。"
    )
    pdf.flow_table(
        [("考核指标", 34.0, "L"), ("门槛", 20.0, "C"), ("实测结果", 44.0, "L"),
         ("结论", 18.0, "C"), ("口径与局限说明", 64.0, "L")],
        [[m.requirement, m.threshold, m.measured, m.status, m.note] for m in C.DAGUAN_METRICS],
        row_h=4.2,
    )

    n_pass = sum(1 for m in C.DAGUAN_METRICS if m.status == "达标")
    n_part = sum(1 for m in C.DAGUAN_METRICS if m.status == "部分达标")
    n_fail = sum(1 for m in C.DAGUAN_METRICS if m.status == "未达标")
    pdf.callout(
        f"共 {len(C.DAGUAN_METRICS)} 项指标：达标 {n_pass} 项，部分达标 {n_part} 项，"
        f"未达标 {n_fail} 项。未达标项为价格方向预测命中率与胜率/盈亏比，"
        "二者共同指向同一结论：本系统的价值在于风险控制而非精准预测。"
        "这一自我认知直接决定了架构重心的取舍。",
        color=color, label="对照结论",
    )

    pdf.sub_header("4.3 三大板块实证结果", color)
    pdf.body_text(
        "三个板块均使用物理隔绝数据集，严禁读取样本期之后的任何数据。"
        "全部结果为历史回测，非真实资金实盘。"
    )
    pdf.flow_table(
        [("实证项目", 44.0, "L"), ("结果", 42.0, "L"), ("样本期", 24.0, "C"),
         ("适用边界与局限", 70.0, "L")],
        [[r.label, r.value, r.sample_period, r.caveat] for r in C.BACKTEST_RESULTS],
        row_h=4.2,
    )

    pdf.sub_header("4.4 局限性与失败案例披露", color)
    pdf.body_text(
        "本节主动披露项目已识别的六项局限。披露的目的不是自我否定，"
        "而是明确每一项结论的适用范围——一个说不清自己边界的系统，其结论无法被信任。"
    )
    for i, lim in enumerate(C.LIMITATIONS, 1):
        pdf.ensure_space(34.0)
        pdf.ln(0.8)
        pdf.set_font("msyh", "B", 8.6)
        pdf.set_text_color(180, 83, 9)
        pdf.set_x(MARGIN)
        pdf.multi_cell(CONTENT_W, 4.8, f"局限 {i} · {lim.title}",
                       align=Align.L, wrapmode=WrapMode.CHAR)
        pdf.ln(0.6)
        pdf.flow_table(
            [("项", 20.0, "C"), ("内容", 160.0, "L")],
            [["事实", lim.fact], ["成因与影响", lim.analysis], ["证据出处", lim.source]],
            row_h=4.2,
        )

    pdf.sub_header("4.5 社会效益", color)
    pdf.flow_table(
        [("受益方", 30.0, "L"), ("效益说明", 150.0, "L")],
        [
            ["命题企业", "为达观数据在金融垂直场景的文本智能能力提供可审计的量化落地路径，"
                        "降低其金融行业客户的合规审计成本"],
            ["中小投研机构", "全流程基于公开与免费数据源实现，"
                            "降低缺乏商业数据库授权的机构开展量化投研的门槛"],
            ["金融学科教育", "方法论与代码开源，可作为资产定价、计量经济学与"
                            "金融工程课程的实践教学案例；主动披露失败案例的做法"
                            "对学术诚信教育具有示范意义"],
            ["个人投资者保护", "系统以风险控制而非收益承诺为核心定位，"
                              "明确披露预测能力边界，不助长过度自信的交易行为"],
        ],
        row_h=4.2,
    )


# ============================================================================
# 第五章 项目分析（10 分）
# ============================================================================

def render_ch5_analysis(pdf: BizPlanPDF) -> None:
    """项目分析：需求调研 / 资源对接 / 解决方案。"""
    color = DIM_COLORS["项目分析"]
    pdf.chapter_title("第五章", "项目分析", 10)

    pdf.sub_header("5.1 需求调研", color)
    pdf.body_text(
        "附件5「需求调研」子项要求全方位开展与所选命题相关产业的调研，"
        "涵盖产业规模、增长速度、竞争格局、产业趋势、产业政策以及市场定位、特征与需求，"
        "并形成一手资料。本节内容如下："
    )
    pdf.flow_table(
        [("调研维度", 34.0, "L"), ("调研结论", 146.0, "L")],
        [[k, v] for k, v in C.INDUSTRY_RESEARCH.items()],
        row_h=4.2,
    )
    pdf.callout(
        "已完成的一手调研工作包括：文献与研报研读记录（波浪理论文献综述、"
        "多支个股的深度复盘报告）、以及向产业界研究者的书面请教往来。"
        "上表中标注待补充的部分为尚未整理归档的调研记录，"
        "不以推测内容填充。",
        color=(180, 83, 9), label="调研佐证状态",
    )

    pdf.sub_header("5.2 资源对接：与达观数据的往来", color)
    pdf.body_text(
        "大赛通知要求企业命题组团队须登录大赛官网查看命题并对接联系出题企业。"
        "本项目与达观数据的对接情况如下："
    )
    pdf.flow_table(
        [("对接事项", 34.0, "L"), ("情况说明", 146.0, "L")],
        [[k, v] for k, v in C.DAGUAN_ENGAGEMENT.items()],
        row_h=4.2,
    )

    pdf.sub_header("5.3 解决方案：可行性与匹配度分析", color)
    pdf.flow_table(
        [("分析维度", 28.0, "L"), ("本团队条件", 74.0, "L"), ("与命题的匹配度", 78.0, "L")],
        [
            ["技术可行性", "已完成三大板块实证与 202 股全池验证，"
                          "611 项测试通过，系统可无人值守连续运行",
             "命题要求的研报提取、因子沉淀定价、多组合回测与自我进化闭环均已落地"],
            ["数据可行性", "全流程基于 akshare、Kenneth French 公开因子库、"
                          "巨潮资讯与交易所公开数据，无需商业数据库授权",
             "方案不依赖付费数据源，企业侧复制部署成本低"],
            ["团队匹配度", f"{len(C.TEAM)} 人跨校团队，"
                          "涵盖系统架构、算法与数据工程、展示材料制作",
             "具备命题所需的数据建模、计量方法与工程实现能力"],
            ["风险与不足", "缺乏熊市与震荡市验证；未进行实盘；"
                          "方向预测能力有限；大模型部分未做参数微调",
             "已在第四章 4.4 逐项披露，并给出分阶段实盘验证计划"],
        ],
        row_h=4.2,
    )


# ============================================================================
# 附录 · 证据索引
# ============================================================================

def render_appendix(pdf: BizPlanPDF) -> None:
    """附录：全部量化结论到仓库证据文件的映射（spec FR-010 / SC-003）。"""
    pdf.current_chapter = "附录 · 证据索引"
    pdf.add_page()
    pdf.set_y(16.0)
    pdf.set_font("msyh", "B", 15.0)
    pdf.set_text_color(15, 23, 42)
    pdf.set_x(MARGIN)
    pdf.cell(CONTENT_W, 8.0, "附录 · 证据索引", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1.0)
    pdf.body_text(
        "本附录列出文中全部量化结论对应的仓库内证据文件路径、样本期与性质，供评审抽查核验。",
        size=8.0,
    )

    pdf.sub_header("A.1 板块实证结果")
    pdf.flow_table(
        [("结论", 40.0, "L"), ("样本期", 22.0, "C"), ("性质", 30.0, "L"),
         ("标的范围", 34.0, "L"), ("证据路径", 54.0, "L")],
        [[r.label, r.sample_period, r.nature, r.universe, r.source]
         for r in C.BACKTEST_RESULTS],
        row_h=4.2,
    )

    pdf.sub_header("A.2 考核指标")
    pdf.flow_table(
        [("指标", 40.0, "L"), ("实测值", 46.0, "L"), ("结论", 18.0, "C"),
         ("证据来源", 76.0, "L")],
        [[m.requirement, m.measured, m.status, m.source] for m in C.DAGUAN_METRICS],
        row_h=4.2,
    )

    pdf.sub_header("A.3 局限性条目")
    pdf.flow_table(
        [("局限", 62.0, "L"), ("证据出处", 118.0, "L")],
        [[l.title, l.source] for l in C.LIMITATIONS],
        row_h=4.2,
    )

    pdf.sub_header("A.4 方法论文献")
    pdf.flow_table(
        [("方法", 40.0, "L"), ("文献", 140.0, "L")],
        [
            ["四因子模型", "Carhart, M. M. (1997). On Persistence in Mutual Fund Performance. "
                          "Journal of Finance."],
            ["动量因子", "Jegadeesh, N., & Titman, S. (1993). Returns to Buying Winners and "
                        "Selling Losers. Journal of Finance."],
            ["因子动物园批判", "Harvey, C. R., Liu, Y., & Zhu, H. (2016). ...and the "
                              "Cross-Section of Expected Returns. Review of Financial Studies."],
            ["HAC 稳健标准误", "Newey, W. K., & West, K. D. (1987). A Simple, Positive "
                              "Semi-Definite, Heteroskedasticity and Autocorrelation "
                              "Consistent Covariance Matrix. Econometrica."],
            ["截面回归框架", "Fama, E. F., & MacBeth, J. D. (1973). Risk, Return, and "
                            "Equilibrium: Empirical Tests. Journal of Political Economy."],
            ["供应链网络传导（NALE）",
             "Yılkı, A. (2026). Supply Chain Propagation of Textual Signals: LLM Embeddings "
             "and Cross-Sectional Return Predictability. arXiv:2606.29290v1. "
             "（原文为美股 S&P 500 / 10-K MD&A 场景，FinBERT 768 维嵌入经 PCA 降维；"
             "本项目为其在 A 股供应链场景的迁移与适配，未复现原论文实证结果）"],
            ["FinGPT 方法论",
             "Yang, H., Liu, X.-Y., & Wang, C. D. (2023). FinGPT: Open-Source Financial "
             "Large Language Models. arXiv:2306.06031. "
             "（本项目参考其方法论并在 A 股场景独立实现，未加载其 LoRA 权重、"
             "未复现其训练规模与性能指标）"],
        ],
        row_h=4.2,
    )


# ============================================================================
# 构建入口
# ============================================================================

CHAPTER_RENDERERS = [
    ("个人成长", render_ch1_growth),
    ("项目创新", render_ch2_innovation),
    ("团队协作", render_ch3_team),
    ("实现成效", render_ch4_effect),
    ("项目分析", render_ch5_analysis),
]


def _render_all(pdf: BizPlanPDF, page_map: dict) -> dict:
    """渲染完整文档，返回各章实际起止页码。"""
    render_cover(pdf)
    render_rubric_index(pdf, page_map)

    actual: dict = {}
    for name, fn in CHAPTER_RENDERERS:
        start = pdf.page_no() + 1  # chapter_title 内部会 add_page
        fn(pdf)
        actual[name] = (start, pdf.page_no())
    render_appendix(pdf)
    return actual


def build(out_dir: Path) -> Path:
    """两遍渲染：首遍取得真实页码，次遍据此填充索引页。"""
    # 第一遍：页码未知，索引页显示占位
    first = BizPlanPDF()
    page_map = _render_all(first, {})

    # 第二遍：用第一遍得到的页码渲染索引页
    final = BizPlanPDF()
    _render_all(final, page_map)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{C.PROJECT_SHORT_NAME}+商业计划书.pdf"
    final.output(str(out_path))
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="构建国创赛商业计划书 PDF")
    parser.add_argument("--out", default=str(REPO_ROOT / "research-outputs" / "reports"),
                        help="输出目录")
    args = parser.parse_args()

    out_path = build(Path(args.out))
    size_mb = out_path.stat().st_size / 1024 / 1024

    print("=" * 68)
    print(" 国创赛产业赛道「商业计划书」PDF 构建完成")
    print("=" * 68)
    print(f" 输出路径 : {out_path}")
    print(f" 文件体积 : {size_mb:.2f} MB  (上限 50MB — {'通过' if size_mb < 50 else '超限'})")

    # 占位符扫描（spec FR-022）：不阻断构建，但显著告警
    counts = C.count_placeholders()
    total = sum(counts.values())
    print("-" * 68)
    if total == 0:
        print(" 占位符检查 : 通过，无待补充字段")
    else:
        print(f" [警告] 尚有 {total} 处「{C.PH}」待补充，当前为草稿版，不可直接提交：")
        for section, n in counts.items():
            if n:
                print(f"        - {section}: {n} 处")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
