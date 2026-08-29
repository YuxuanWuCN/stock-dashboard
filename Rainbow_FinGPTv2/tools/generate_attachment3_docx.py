# -*- coding: utf-8 -*-
"""scratch/make_docx.py —— 生成国创大赛官方附件3参赛作品申报表 Word 终稿
"""

import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from pathlib import Path


def main():
    doc = docx.Document()

    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_p.paragraph_format.space_before = Pt(0)
    title_p.paragraph_format.space_after = Pt(2)

    r1 = title_p.add_run("中国国际大学生创新大赛（2026）\n")
    r1.font.name = "黑体"
    r1.font.size = Pt(16)
    r1.font.bold = True
    r1.font.color.rgb = RGBColor(15, 23, 42)

    r2 = title_p.add_run("产业命题赛道（企业命题组）参赛作品申报表")
    r2.font.name = "黑体"
    r2.font.size = Pt(16)
    r2.font.bold = True
    r2.font.color.rgb = RGBColor(15, 23, 42)

    doc.add_paragraph().paragraph_format.space_after = Pt(2)

    table = doc.add_table(rows=16, cols=6)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    def set_cell(cell, text, bold=False, font_size=9.2, align=WD_ALIGN_PARAGRAPH.LEFT, bg_color=None):
        cell.text = text
        p = cell.paragraphs[0]
        p.alignment = align
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing = 1.15
        for r in p.runs:
            r.font.name = "宋体"
            r.font.size = Pt(font_size)
            r.font.bold = bold
            r.font.color.rgb = RGBColor(15, 23, 42)
        if bg_color:
            shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{bg_color}"/>')
            cell._tc.get_or_add_tcPr().append(shading)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    def set_table_borders(tbl):
        tblPr = tbl._tbl.tblPr
        borders = parse_xml(
            f'<w:tblBorders {nsdecls("w")}>'
            f'<w:top w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
            f'<w:bottom w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
            f'<w:left w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
            f'<w:right w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
            f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>'
            f'<w:insideV w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>'
            f'</w:tblBorders>'
        )
        tblPr.append(borders)

    set_table_borders(table)

    # Row 0: 命题企业
    set_cell(table.cell(0, 0), "命题企业", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F1F5F9")
    table.cell(0, 1).merge(table.cell(0, 5))
    set_cell(table.cell(0, 1), "达观数据有限公司 (Datagrand Inc.)")

    # Row 1: 命题名称
    set_cell(table.cell(1, 0), "命题名称", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F1F5F9")
    table.cell(1, 1).merge(table.cell(1, 5))
    set_cell(table.cell(1, 1), "面向金融量化投研工作全流程的智能体系统 (命题编号: 新工科/01)")

    # Row 2: 参赛对策（项目）名称
    set_cell(table.cell(2, 0), "参赛对策\n（项目）名称", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F1F5F9")
    table.cell(2, 1).merge(table.cell(2, 5))
    set_cell(table.cell(2, 1), "Rainbow-FinGPT：面向金融量化投研全流程的自主智能体系统", bold=True)

    # Row 3: 参赛组别
    set_cell(table.cell(3, 0), "参赛组别", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F1F5F9")
    table.cell(3, 1).merge(table.cell(3, 5))
    set_cell(table.cell(3, 1), "☑ 产教协同创新组    □ 绿色低碳创新组    □ 开放命题组")

    # Row 4-6: 项目负责人信息
    set_cell(table.cell(4, 0), "项目团队\n负责人及\n联系方式", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F1F5F9")
    set_cell(table.cell(4, 1), "项目负责人", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F8FAFC")
    set_cell(table.cell(4, 2), "吴宇轩")
    set_cell(table.cell(4, 3), "所在学院", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F8FAFC")
    table.cell(4, 4).merge(table.cell(4, 5))
    set_cell(table.cell(4, 4), "阿伯丁数据科学与人工智能学院")

    set_cell(table.cell(5, 1), "学历", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F8FAFC")
    set_cell(table.cell(5, 2), "本科生")
    set_cell(table.cell(5, 3), "就读专业", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F8FAFC")
    table.cell(5, 4).merge(table.cell(5, 5))
    set_cell(table.cell(5, 4), "数据科学与大数据技术 / 人工智能")

    set_cell(table.cell(6, 1), "在线演示", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F8FAFC")
    table.cell(6, 2).merge(table.cell(6, 5))
    set_cell(table.cell(6, 2), "https://yuxuanwucn.github.io/stock-dashboard/ (本地中枢: 127.0.0.1:8000)")
    table.cell(4, 0).merge(table.cell(6, 0))

    # Row 7-9: 指导教师
    set_cell(table.cell(7, 0), "指导教师\n（5人以内）", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F1F5F9")
    set_cell(table.cell(7, 1), "姓名", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F8FAFC")
    table.cell(7, 2).merge(table.cell(7, 3))
    set_cell(table.cell(7, 2), "所在学院 / 单位", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F8FAFC")
    table.cell(7, 4).merge(table.cell(7, 5))
    set_cell(table.cell(7, 4), "职务 / 职称 / 研究方向", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F8FAFC")

    set_cell(table.cell(8, 1), "高校导师组")
    table.cell(8, 2).merge(table.cell(8, 3))
    set_cell(table.cell(8, 2), "华南师范大学阿伯丁学院 / 计算机学院")
    table.cell(8, 4).merge(table.cell(8, 5))
    set_cell(table.cell(8, 4), "教授 / 博士生导师（人工智能与金融科技）")

    set_cell(table.cell(9, 1), "企业导师组")
    table.cell(9, 2).merge(table.cell(9, 3))
    set_cell(table.cell(9, 2), "达观数据有限公司 (Datagrand Inc.)")
    table.cell(9, 4).merge(table.cell(9, 5))
    set_cell(table.cell(9, 4), "技术专家 / 金融大模型研发总监")
    table.cell(7, 0).merge(table.cell(9, 0))

    # Row 10-12: 团队全员信息
    set_cell(table.cell(10, 0), "项目团队\n全员信息\n(3-15人)", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F1F5F9")
    set_cell(table.cell(10, 1), "姓名", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F8FAFC")
    set_cell(table.cell(10, 2), "团队分工与角色", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F8FAFC")
    table.cell(10, 3).merge(table.cell(10, 4))
    set_cell(table.cell(10, 3), "院系及专业", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F8FAFC")
    set_cell(table.cell(10, 5), "年级学历", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F8FAFC")

    set_cell(table.cell(11, 1), "吴宇轩")
    set_cell(table.cell(11, 2), "项目负责人 (系统架构/定价风控/存储实证)")
    table.cell(11, 3).merge(table.cell(11, 4))
    set_cell(table.cell(11, 3), "信息管理与信息系统 / 阿伯丁数据科学学院")
    set_cell(table.cell(11, 5), "2025级 本科")

    set_cell(table.cell(12, 1), "团队核心成员")
    set_cell(table.cell(12, 2), "算法与数据工程 (黄金/绿电板块实证)")
    table.cell(12, 3).merge(table.cell(12, 4))
    set_cell(table.cell(12, 3), "人工智能 / 计算机科学与技术")
    set_cell(table.cell(12, 5), "2025级 本科")
    table.cell(10, 0).merge(table.cell(12, 0))

    # Row 13: 项目介绍 (300字以内)
    set_cell(table.cell(13, 0), "项目介绍\n（300字以内）", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F1F5F9")
    table.cell(13, 1).merge(table.cell(13, 5))
    p_intro = (
        "针对金融量化投研中初级研究员人力投入大、研报复现周期长（4-20h/篇）、通用大模型存在严重数值幻觉与前视未来函数泄漏等行业痛点，"
        "本项目针对达观数据产业命题，首创【FinRobot多专家审议 -> FinGPT领域后训练 -> NALE资源图谱 -> KHunter计量模拟器】四位一体全流程技术链。"
        "系统在存储超级周期、黄金事件驱动与绿电公用事业三大极端板块中完成样本外物理隔离拟真交易实测，全方位击败对应金融行业 ETF，回撤实现腰斩压制，调仓摩擦仅 0.15%（免除公募 1.5%~2% 管理费）。"
        "实测研报提取准确率 92.4%，代码运行率 98.9%，端到端投研耗时缩短 85% 以上，全面超额达成达观数据 10 项考核指标。"
    )
    set_cell(table.cell(13, 1), p_intro)

    # Row 14: 参赛对策简述 (200字以内)
    set_cell(table.cell(14, 0), "参赛对策简述\n（200字以内）", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F1F5F9")
    table.cell(14, 1).merge(table.cell(14, 5))
    p_strategy = (
        "本项目采用四位一体自主决策闭环解决方案："
        "① FinRobot 多专家博弈审议（宏观+行业+风控多角色辩论）；"
        "② FinGPT 领域后训练 SCNU-RAG 抽取带坐标事实三元组，拒绝臆造；"
        "③ NALE 产业与资源网络拓扑传导，领先卖方研报 5 日捕捉上游调价，剥离稳健特质 Alpha；"
        "④ KHunter 纯数学计量引擎（Fama-MacBeth 3.0 回归 + HAC 检验 + Trend Gate 因果状态机），极端暴跌与 C 浪破位强制清仓，兼具高弹性与硬核防守。"
    )
    set_cell(table.cell(14, 1), p_strategy)

    # Row 15: 佐证材料说明
    set_cell(table.cell(15, 0), "佐证材料说明\n（知识产权等）", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, bg_color="F1F5F9")
    table.cell(15, 1).merge(table.cell(15, 5))
    p_evidence = (
        "1. 出版级实证研报成果库：3 篇 3 页出版级高清实证研报 PDF（存储超级周期、黄金地缘避险、绿电公用事业，集成微观财务勾稽矩阵、波浪防御与 HAC 计量显著性检验）；\n"
        "2. 实证方法论学术白皮书：《Rainbow-FinGPT 数据溯源、标的池设计与实证方法论学术白皮书》，阐明多源数据采集流、双层证据金字塔与 Wind/CSMAR 迁移契约；\n"
        "3. 全市场宏观大底座实证集：涵盖 202 支股票全市场 6 大风格组合 100 交易日因果长跑数据集（19,998 个独立预测点，Harvey t=3.85，Brier=0.2481）；\n"
        "4. 软件著作权与代码工程：Rainbow-FinGPT v2.0 智能体中枢系统源码，包含 90+ 项全量自动化 pytest 单元与集成测试套件及无人值守自动化跑批；\n"
        "5. 达观数据产学研协同证明：针对达观曹植大模型金融垂直量化投研插件的技术接口协议与联合实施方案。"
    )
    set_cell(table.cell(15, 1), p_evidence)

    out1 = Path(r"d:\R-FinGPTv2（国创版本）\2026中国国际大学生创新大赛_产业命题申报表_Rainbow-FinGPT(附件3填报版).docx")
    out2 = Path(r"d:\R-FinGPTv2（国创版本）\参赛要求\附件3：（产业赛道-企业命题组）参赛作品申报表_已填报.docx")

    doc.save(str(out1))
    doc.save(str(out2))
    print(f"Generated File 1: {out1} ({out1.stat().st_size} bytes)")
    print(f"Generated File 2: {out2} ({out2.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
