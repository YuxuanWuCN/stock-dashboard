# tests/integration/test_competition_isolation.py
"""
Rainbow-FinGPT v4.0 赛事资产物理隔离契约测试
Tests verifying strict competition material isolation between DaChuang (大创赛) and CZCE (郑商所杯).
"""

from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
COMPETITIONS_DIR = REPO_ROOT / "competitions"
DACHUANG_DIR = COMPETITIONS_DIR / "dachuang_2026"
CZCE_DIR = COMPETITIONS_DIR / "czce_futures"


def test_competition_directories_exist():
    """验证两大专属赛事目录结构存在"""
    assert COMPETITIONS_DIR.exists(), f"Missing {COMPETITIONS_DIR}"
    assert DACHUANG_DIR.exists(), f"Missing {DACHUANG_DIR}"
    assert CZCE_DIR.exists(), f"Missing {CZCE_DIR}"


def test_dachuang_material_presence():
    """验证大创赛 (中国国际大学生创新大赛) 核心材料完整就绪"""
    required_keywords = ["申报", "路演", "攻防"]
    files = list(DACHUANG_DIR.rglob("*.*"))
    file_names = " ".join([f.name for f in files])
    
    for kw in required_keywords:
        assert kw in file_names, f"大创赛材料目录缺少包含 '{kw}' 的核心文档"


def test_czce_futures_material_presence():
    """验证郑商所衍生品大赛核心材料完整就绪"""
    subdirs = [p.name for p in CZCE_DIR.iterdir() if p.is_dir()]
    assert any("研究计划" in s or "论文" in s for s in subdirs), "缺少郑商所 01_研究计划与论文 目录"
    assert any("极星" in s or "实盘" in s for s in subdirs), "缺少郑商所 02_极星量化与实盘 目录"


def test_cross_competition_isolation_integrity():
    """验证赛道物理隔离完整性，杜绝赛道内容混淆与串味"""
    # 1. 大创赛目录严禁混入极星实盘策略与纯碱玻璃套保代码
    dc_files = [f.name for f in DACHUANG_DIR.rglob("*.*")]
    for f in dc_files:
        assert "CZCE_19_5_DualProduct_Plugin" not in f, f"大创赛目录意外混入期货插件: {f}"
        assert "EPOLESTAR_LIVE_MANUAL" not in f, f"大创赛目录意外混入极星手册: {f}"
        
    # 2. 郑商所目录严禁混入大创赛申报书与校赛PPT
    czce_files = [f.name for f in CZCE_DIR.rglob("*.*")]
    for f in czce_files:
        assert "中国国际大学生创新大赛" not in f, f"郑商所目录意外混入大创赛材料: {f}"
        assert "达观数据产业命题" not in f, f"郑商所目录意外混入达观命题材料: {f}"
