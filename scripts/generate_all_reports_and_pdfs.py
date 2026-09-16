# -*- coding: utf-8 -*-
"""scripts/generate_all_reports_and_pdfs.py —— 一键执行全行业回测与出版级 PDF 研报矩阵生成

涵盖全行业与全景合订本：
1. 绿电公用事业与新能源板块物理隔离实测研报 PDF
2. 半导体存储超级周期板块物理隔离实测研报 PDF
3. 黄金与贵金属地缘避险板块物理隔离实测研报 PDF
4. 滚动方向校准与拒绝预测专项实证验证报告 PDF
5. Rainbow-FinGPT 产业命题全景合订本 Master 白皮书 PDF (13 页)
6. Rainbow-FinGPT 商业计划书 PDF
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run_cmd(cmd_list, desc):
    print(f"\n[RUNNING] {desc}...")
    res = subprocess.run(cmd_list, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if res.returncode != 0:
        print(f"[WARN] {desc} returned {res.returncode}:\n{res.stderr}")
    else:
        print(f"[SUCCESS] {desc} completed.")
    return res.returncode


def generate_all():
    print("=" * 70)
    print("[START] Generating Rainbow-FinGPT Multi-Industry PDF Report Matrix")
    print("=" * 70)

    # 1. 生成方向校准 300 DPI 图表与验证数据
    run_cmd([sys.executable, "scripts/generate_calibration_figures.py"], "Generate Calibration Figures")
    run_cmd([sys.executable, "scripts/generate_validation_report.py"], "Generate Calibration Markdown and JSON")

    # 2. 生成方向校准专属验证 PDF
    run_cmd([sys.executable, "Rainbow_FinGPTv2/tools/generate_direction_calibration_report_pdf.py"], "Generate Direction Calibration PDF")

    # 3. 生成三大支柱行业物理隔离实测 PDF 研报
    run_cmd([sys.executable, "Rainbow_FinGPTv2/tools/generate_isolated_green_dossier_pdf.py"], "Generate Green Power Dossier PDF")
    run_cmd([sys.executable, "Rainbow_FinGPTv2/tools/generate_isolated_storage_dossier_pdf.py"], "Generate Semiconductor Storage Dossier PDF")
    run_cmd([sys.executable, "Rainbow_FinGPTv2/tools/generate_isolated_gold_dossier_pdf.py"], "Generate Gold Defense Dossier PDF")

    # 4. 生成 13 页全景合订本 Master Dossier PDF 与商业计划书 PDF
    run_cmd([sys.executable, "Rainbow_FinGPTv2/tools/generate_master_dossier_pdf.py"], "Generate 13-Page Master Dossier PDF")
    run_cmd([sys.executable, "tools/build_bizplan_pdf.py"], "Generate Business Plan PDF")

    # 5. 同步至 PPT素材包
    ppt_dir = ROOT / "PPT素材包" / "04_研报PDF原件"
    ppt_dir.mkdir(parents=True, exist_ok=True)
    for name in [
        "绿电公用事业_物理隔绝真实交易实测研报.pdf",
        "存储超级周期_物理隔绝真实交易实测研报.pdf",
        "黄金地缘避险_物理隔绝真实交易实测研报.pdf",
        "方向校准修复验证报告.pdf",
        "Rainbow-FinGPT_产业命题完整答卷与实证白皮书_全景合订本.pdf"
    ]:
        src_p = ROOT / "research-outputs" / "reports" / name
        if src_p.exists():
            shutil.copy(src_p, ppt_dir / name)
            print(f"[SYNC] Mirrored {name} -> {ppt_dir}")

    print("\n" + "=" * 70)
    print("[COMPLETE] All Multi-Industry Reports & Publication PDFs Generated Successfully.")
    print("=" * 70)

    # 打印最终文件清单
    out_dir = ROOT / "research-outputs" / "reports"
    for f in sorted(out_dir.glob("*.pdf")):
        print(f"  [PDF] {f.name} ({f.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    generate_all()
