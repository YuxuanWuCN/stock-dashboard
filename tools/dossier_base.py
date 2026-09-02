# -*- coding: utf-8 -*-
"""tools/dossier_base.py —— Rainbow-FinGPT 出版级研报通用排版与字体渲染引擎

核心特性与排版修复：
1. 统一注册微软雅黑家族 ("msyh", "" / "msyh", "B")，消除字体跳跃并支持原生 Markdown 加粗
2. 彻底解决 mixed-CJK/ASCII 空格异常拉伸 Bug：显式指定 Align.L (左对齐) 与 WrapMode.CHAR (字符换行)
3. 严格 5 级规范字阶体系 (T1 主标题 ~ T5 表格数据)，建立清晰的视觉节奏
4. 专业数据表格渲染：表头主题底色、交替斑马纹 (#F8FAFC / #FFFFFF)、0.15mm 极细高精边框、舒适内边距
5. 商业级 Accent Callout 叙事框：淡底色 + 左侧 2.2mm 主题色重色指示条
6. 现代化 KPI 磁贴网格：高对比度指标卡片
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fpdf import FPDF
from fpdf.enums import Align, WrapMode, XPos, YPos


class BasePublicationPDF(FPDF):
    """出版级研报通用 PDF 基类。"""

    # 规范字阶体系 (Font Scale)
    FS_DOC_TITLE = 13.5
    FS_SECTION = 9.0
    FS_CARD_VAL = 8.5
    FS_CARD_LBL = 6.2
    FS_BODY = 6.8
    FS_TABLE_HDR = 6.5
    FS_TABLE_CELL = 6.2
    FS_FOOTER = 6.5

    def __init__(self, theme_title: str, theme_color_rgb: Tuple[int, int, int]):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=False)
        self.theme_title = theme_title
        self.theme_color = theme_color_rgb  # (R, G, B)
        self.font_family = "msyh"
        self.font_regular = "msyh"
        self.font_bold = "msyh"
        self._setup_fonts()

    def _setup_fonts(self):
        """统一注册微软雅黑家族，消除字重和字形跳跃。"""
        candidates = [
            ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc"),
            ("C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simhei.ttf"),
            ("C:/Windows/Fonts/simsun.ttc", "C:/Windows/Fonts/simsun.ttc"),
        ]
        reg = "C:/Windows/Fonts/msyh.ttc"
        bold = "C:/Windows/Fonts/msyhbd.ttc"
        for r, b in candidates:
            if os.path.exists(r):
                reg = r
                bold = b if os.path.exists(b) else r
                break
        self.add_font("msyh", "", reg)
        self.add_font("msyh", "B", bold)

    def header(self):
        # 顶栏深色条
        self.set_fill_color(15, 23, 42)  # Slate 900
        self.rect(0, 0, 210, 3.2, "F")
        # 主题色彩色细条
        self.set_fill_color(*self.theme_color)
        self.rect(0, 3.2, 210, 1.2, "F")

        self.set_font("msyh", "", self.FS_FOOTER)
        self.set_text_color(100, 116, 139)
        self.set_xy(15, 5.2)
        self.cell(180, 4.0, f"Rainbow-FinGPT Autonomous Quant Agent | {self.theme_title}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def footer(self):
        self.set_y(-10)
        self.set_draw_color(226, 232, 240)
        self.set_line_width(0.2)
        self.line(15, 287, 195, 287)
        self.set_font("msyh", "", self.FS_FOOTER)
        self.set_text_color(148, 163, 184)
        self.set_xy(15, 288)
        self.cell(140, 4, "Physical Isolation & Causal Walk-Forward Audit | SCNU Aberdeen Institute · DataGrand Track", align="L")
        self.cell(40, 4, f"Page {self.page_no()} of 3", align="R")

    def draw_section_header(self, text: str, y_offset: Optional[float] = None):
        """绘制标准化一级小节标题。"""
        if y_offset is not None:
            self.set_y(y_offset)
        self.set_font("msyh", "B", self.FS_SECTION)
        self.set_text_color(*self.theme_color)
        self.cell(180, 4.8, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def draw_kpi_cards(self, kpis: List[Tuple[str, str, Tuple[int, int, int]]], y_pos: float):
        """绘制现代化高对比度 KPI 磁贴卡片。"""
        n = len(kpis)
        card_w = 34.5
        gap = (180.0 - n * card_w) / (n - 1) if n > 1 else 0.0

        for i, (lbl, val, color) in enumerate(kpis):
            x = 15.0 + i * (card_w + gap)
            # 背景与外边框
            self.set_fill_color(248, 250, 252)
            self.set_draw_color(226, 232, 240)
            self.set_line_width(0.2)
            self.rect(x, y_pos, card_w, 11.5, "DF")

            # 标签
            self.set_xy(x, y_pos + 1.0)
            self.set_font("msyh", "", self.FS_CARD_LBL)
            self.set_text_color(100, 116, 139)
            self.cell(card_w, 3.0, lbl, align="C")

            # 大数值
            self.set_xy(x, y_pos + 4.5)
            self.set_font("msyh", "B", self.FS_CARD_VAL)
            self.set_text_color(*color)
            self.cell(card_w, 5.0, val, align="C")

    def draw_accent_box(self, x: float, y: float, w: float, h: float, text: str, line_h: float = 3.2, markdown: bool = False):
        """绘制带有左侧 Accent Bar 的商业级说明框（严格左对齐与字符换行，彻底消除空格拉伸）。"""
        # 主背景
        self.set_fill_color(248, 250, 252)
        self.set_draw_color(226, 232, 240)
        self.set_line_width(0.2)
        self.rect(x, y, w, h, "DF")

        # 左侧装饰色条
        self.set_fill_color(*self.theme_color)
        self.rect(x, y, 2.2, h, "F")

        # 文字（关键：显式 align=Align.L，wrapmode=WrapMode.CHAR，杜绝空格拉伸）
        self.set_xy(x + 3.8, y + 1.2)
        self.set_font("msyh", "", self.FS_BODY)
        self.set_text_color(30, 41, 59)
        self.multi_cell(w - 5.5, line_h, text, align=Align.L, wrapmode=WrapMode.CHAR, markdown=markdown)

    def draw_styled_table(
        self,
        headers: List[Tuple[str, float, str]],  # (Title, Width, Align)
        rows: List[List[str]],
        y_pos: float,
        highlight_keyword: str = "本系统",
        row_h: float = 3.6
    ):
        """绘制专业数据表格（含表头主题底色、交替斑马纹与高精对齐）。"""
        self.set_y(y_pos)

        # 表头
        self.set_fill_color(226, 232, 240)
        self.set_draw_color(203, 213, 225)
        self.set_line_width(0.2)
        self.set_font("msyh", "B", self.FS_TABLE_HDR)
        self.set_text_color(15, 23, 42)

        cur_x = 15.0
        for title, col_w, align in headers:
            self.set_xy(cur_x, y_pos)
            self.cell(col_w, 4.2, title, border=1, align=align, fill=True)
            cur_x += col_w
        self.set_y(y_pos + 4.2)

        # 数据行
        for idx, row in enumerate(rows):
            row_y = self.get_y()
            is_highlight = highlight_keyword in row[0] if highlight_keyword else False

            # 斑马纹背景
            bg_color = (241, 245, 249) if is_highlight else ((248, 250, 252) if idx % 2 == 1 else (255, 255, 255))
            self.set_fill_color(*bg_color)
            self.set_draw_color(226, 232, 240)
            self.set_line_width(0.15)

            if is_highlight:
                self.set_font("msyh", "B", self.FS_TABLE_CELL)
                self.set_text_color(*self.theme_color)
            else:
                self.set_font("msyh", "", self.FS_TABLE_CELL)
                self.set_text_color(30, 41, 59)

            cur_x = 15.0
            for i, val in enumerate(row):
                col_w = headers[i][1]
                align = headers[i][2]
                self.set_xy(cur_x, row_y)
                self.cell(col_w, row_h, val, border=1, align=align, fill=True)
                cur_x += col_w
            self.set_y(row_y + row_h)
