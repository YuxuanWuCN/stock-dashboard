# tests/commodity/test_tes_and_collar.py
"""
Rainbow-FinGPT v4.0 大宗商品赛道测试
Tests for CZCE Soda Ash / Glass TES Pipeline, PolarStar Plugin, and Chokepoint Analyzer.
"""

from pathlib import Path
import pytest
from src.intelligence.chokepoint.chokepoint_analyzer import ChokepointAnalyzer
from src.assets.commodity.tes_pipeline import CrossAssetTESPipeline


def test_chokepoint_analyzer_scoring():
    """验证供应链卡脖子瓶颈拓扑打分与定性命题生成"""
    analyzer = ChokepointAnalyzer(bottleneck_threshold=65.0)
    
    # 案例 1: 高稀缺天然碱矿源
    prof1 = analyzer.evaluate_node(
        node_id="NODE_01_TRONA",
        node_name="天然碱矿采选",
        sector="基础化工",
        scarcity=90.0,
        pricing_gap=75.0,
        catalyst=80.0,
        liquidity=70.0,
        symbols=["000683", "SA0"]
    )
    assert prof1.is_bottleneck is True
    assert prof1.overall_quality_score > 75.0
    
    prop = analyzer.generate_qualitative_proposition(
        profile=prof1,
        target_symbol="000683",
        evidence_fact="远兴能源阿拉善天然碱项目一期全线投产，边际开采成本较联碱法低 45%"
    )
    assert prop.direction == "LONG"
    assert any("[FACT]" in tag for tag in prop.evidence_tags)


def test_polarstar_plugin_syntax_validity():
    """验证极星 19.5 原生量化插件代码存在且无语法错误"""
    plugin_path = Path("src/assets/commodity/polarstar_plugin/CZCE_19_5_DualProduct_Plugin.py")
    assert plugin_path.exists(), "极星 19.5 插件文件缺失"
    
    code = plugin_path.read_text(encoding="utf-8")
    assert "CZCE" in code
    # 校验编译通过
    compile(code, str(plugin_path), "exec")


def test_tes_pipeline_initialization():
    """验证跨资产期望盈余 (TES) 流水线初始化与原子落盘配置"""
    pipe = CrossAssetTESPipeline()
    assert pipe.ontology is not None
    assert pipe.gate_engine is not None
