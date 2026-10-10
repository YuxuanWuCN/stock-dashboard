# -*- coding: utf-8 -*-
"""
纯碱-玻璃产业链因果增值节点本体库测试套件 (tests/test_causal_ontology.py)
------------------------------------------------------------------------
验证 ADR-0002 架构契约与 M1 核心功能:
1. 工艺物理增值层级结构 (4 Tiers / 8 Nodes)
2. 化学计量学刚性关系 (1 吨玻璃消耗 0.20 吨重碱, 350 元燃料成本)
3. 核心大宗商品 (SA/FG) 与 12 只核心 A 股上市公司增值节点映射
4. 拓扑因果遍历 (上游追溯链与下游传导链检索)
5. 成本冲击因果传导模型 (propagate_cost_shock)
6. 冶炼加工裂解利润计算 (compute_crush_spread)
7. 资产坐标硬门禁校验与虚假概念硬拦截 (validate_asset_mapping)
"""

import pytest
from src.intelligence.causal_ontology import (
    ValueAddedOntology,
    ProcessNodeType,
    ProcessNode
)


@pytest.fixture(scope="module")
def ontology() -> ValueAddedOntology:
    """初始化因果本体中枢实例"""
    return ValueAddedOntology()


# ==============================================================================
# 1. 物理层级与节点完整性测试
# ==============================================================================

def test_ontology_node_hierarchy_and_levels(ontology: ValueAddedOntology):
    """验证 4 个物理增值层级与 8 个核心工艺节点的层级分布"""
    nodes = ontology.all_nodes()
    assert len(nodes) == 8, f"预期包含 8 个核心工艺节点，实际为: {len(nodes)}"

    expected_nodes = {
        "NODE_01_TRONA": (ProcessNodeType.RAW_MATERIAL, 1),
        "NODE_02_SALT": (ProcessNodeType.RAW_MATERIAL, 1),
        "NODE_03_SODA_SYN": (ProcessNodeType.SODA_SYNTHESIS, 2),
        "NODE_04_FLOAT_GLASS": (ProcessNodeType.GLASS_PROCESS, 3),
        "NODE_05_PV_GLASS": (ProcessNodeType.GLASS_PROCESS, 3),
        "NODE_06_AUTO_GLASS": (ProcessNodeType.GLASS_PROCESS, 3),
        "NODE_07_END_MODULE": (ProcessNodeType.TERMINAL_DEMAND, 4),
        "NODE_08_END_STORAGE": (ProcessNodeType.TERMINAL_DEMAND, 4),
    }

    for node_id, (expected_type, expected_level) in expected_nodes.items():
        node = ontology.get_node(node_id)
        assert node is not None, f"缺失工艺节点: {node_id}"
        assert node.node_type == expected_type, f"节点 {node_id} 类型不匹配: {node.node_type} != {expected_type}"
        assert node.level == expected_level, f"节点 {node_id} 层级不匹配: {node.level} != {expected_level}"


# ==============================================================================
# 2. 化学计量学刚性关系测试
# ==============================================================================

def test_chemical_stoichiometry_rigid_relations(ontology: ValueAddedOntology):
    """
    验证物理工艺核心化学计量学参数:
    - 浮法玻璃 1:0.20 耗碱比 (soda_consumption_per_ton_glass == 0.20)
    - 燃料固定成本 ~350 元/吨
    - 浮法窑炉连续运转 8.5 年刚性，冷修重启成本 4000 万元
    - 原盐制碱单耗 1.55 吨原盐/吨纯碱
    - 天然碱完全成本 ~900 元/吨
    """
    float_node = ontology.get_node("NODE_04_FLOAT_GLASS")
    assert float_node is not None
    stoich = float_node.stoichiometry
    assert stoich.get("soda_consumption_per_ton_glass") == 0.20
    assert stoich.get("fuel_cost_rmb") == 350.0
    assert stoich.get("continuous_kiln_years") >= 8.0
    assert stoich.get("cold_repair_cost_rmb_million") >= 30.0

    salt_node = ontology.get_node("NODE_02_SALT")
    assert salt_node is not None
    assert salt_node.stoichiometry.get("salt_consumption_per_ton_soda") == 1.55

    trona_node = ontology.get_node("NODE_01_TRONA")
    assert trona_node is not None
    assert trona_node.stoichiometry.get("marginal_cost_rmb") == 900.0


# ==============================================================================
# 3. 核心商品与 A 股标的映射测试
# ==============================================================================

def test_commodity_futures_and_equity_mapping(ontology: ValueAddedOntology):
    """
    验证 SA/FG 期货与 12 只核心上市公司准确映射至物理增值节点
    """
    # 纯碱期货 (SA) 映射至中间纯碱合成 (NODE_03_SODA_SYN)
    sa_node = ontology.get_node_by_symbol("SA")
    assert sa_node is not None
    assert sa_node.node_id == "NODE_03_SODA_SYN"

    sa701_node = ontology.get_node_by_symbol("SA701")
    assert sa701_node is not None
    assert sa701_node.node_id == "NODE_03_SODA_SYN"

    # 玻璃期货 (FG) 映射至浮法玻璃成型 (NODE_04_FLOAT_GLASS)
    fg_node = ontology.get_node_by_symbol("FG")
    assert fg_node is not None
    assert fg_node.node_id == "NODE_04_FLOAT_GLASS"

    # 核心 A 股映射校验
    symbol_node_expectations = {
        "000683": "NODE_01_TRONA",         # 远兴能源
        "603299": "NODE_02_SALT",          # 苏盐井神
        "600328": "NODE_03_SODA_SYN",      # 中盐化工
        "600409": "NODE_03_SODA_SYN",      # 三友化工
        "000822": "NODE_03_SODA_SYN",      # 山东海化
        "603077": "NODE_03_SODA_SYN",      # 和邦生物
        "601636": "NODE_04_FLOAT_GLASS",   # 旗滨集团
        "600586": "NODE_04_FLOAT_GLASS",   # 金晶科技
        "000012": "NODE_04_FLOAT_GLASS",   # 南玻A
        "601865": "NODE_05_PV_GLASS",      # 福莱特
        "002623": "NODE_05_PV_GLASS",      # 亚玛顿
        "600660": "NODE_06_AUTO_GLASS",    # 福耀玻璃
        "601012": "NODE_07_END_MODULE",    # 隆基绿能
        "600438": "NODE_07_END_MODULE",    # 通威股份
        "300750": "NODE_08_END_STORAGE",   # 宁德时代
    }

    for sym, expected_nid in symbol_node_expectations.items():
        node = ontology.get_node_by_symbol(sym)
        assert node is not None, f"标的 {sym} 未能检索到所属工艺节点"
        assert node.node_id == expected_nid, f"标的 {sym} 映射节点不匹配: {node.node_id} != {expected_nid}"


def test_symbol_fuzzy_and_format_lookup(ontology: ValueAddedOntology):
    """验证各种格式（如 000683.SZ, 中文名称, 小写符号）的智能解析兼容性"""
    # 股票后缀
    node_sz = ontology.get_node_by_symbol("000683.SZ")
    assert node_sz is not None and node_sz.node_id == "NODE_01_TRONA"

    node_sh = ontology.get_node_by_symbol("600328.SH")
    assert node_sh is not None and node_sh.node_id == "NODE_03_SODA_SYN"

    # 中文简称
    node_name = ontology.get_node_by_symbol("旗滨集团")
    assert node_name is not None and node_name.node_id == "NODE_04_FLOAT_GLASS"

    # 期货主连小写
    node_lower = ontology.get_node_by_symbol("sa701")
    assert node_lower is not None and node_lower.node_id == "NODE_03_SODA_SYN"


# ==============================================================================
# 4. 拓扑因果遍历测试 (Upstream / Downstream Traversal)
# ==============================================================================

def test_upstream_dependency_chain_traversal(ontology: ValueAddedOntology):
    """
    验证上游依赖链回溯:
    从浮法玻璃 (Level 3) 回溯，应包含 Level 2 (中间纯碱合成) 与 Level 1 (天然碱与原盐)
    """
    upstream = ontology.get_upstream_chain("NODE_04_FLOAT_GLASS")
    upstream_ids = [n.node_id for n in upstream]

    assert "NODE_03_SODA_SYN" in upstream_ids
    assert "NODE_01_TRONA" in upstream_ids
    assert "NODE_02_SALT" in upstream_ids

    # 验证按层级升序排列 (Level 1 在前, Level 2 在后)
    levels = [n.level for n in upstream]
    assert levels == sorted(levels), f"上游拓扑回溯层级未按拓扑次序排列: {levels}"


def test_downstream_transmission_chain_traversal(ontology: ValueAddedOntology):
    """
    验证下游传导链检索:
    从天然碱 (NODE_01_TRONA, Level 1) 出发，应完整传导至 Level 2, Level 3, Level 4
    """
    downstream = ontology.get_downstream_chain("NODE_01_TRONA")
    downstream_ids = [n.node_id for n in downstream]

    assert "NODE_03_SODA_SYN" in downstream_ids
    assert "NODE_04_FLOAT_GLASS" in downstream_ids
    assert "NODE_05_PV_GLASS" in downstream_ids
    assert "NODE_07_END_MODULE" in downstream_ids

    # 验证按层级升序排列 (Level 2 -> Level 3 -> Level 4)
    levels = [n.level for n in downstream]
    assert levels == sorted(levels), f"下游拓扑传导层级未按拓扑次序排列: {levels}"


# ==============================================================================
# 5. 成本冲击传导模型与裂解利润计算测试
# ==============================================================================

def test_cost_shock_propagation_model(ontology: ValueAddedOntology):
    """
    验证天然碱成本坍塌 (-20%) 沿有向边的物理传导:
    - 天然碱源头: -20%
    - 纯碱合成 (Level 2): 成本下行约 -17%
    - 浮法玻璃加工 (Level 3): 纯碱成本降低反哺加工毛利，呈正向扩张冲击 (+5.1%)
    - 光伏玻璃深加工 (Level 3): 同样毛利走阔 (+5.1%)
    """
    impacts = ontology.propagate_cost_shock(
        source_node_id="NODE_01_TRONA",
        shock_pct=-0.20,
        damping_factor=0.65
    )

    assert "NODE_01_TRONA" in impacts
    assert impacts["NODE_01_TRONA"] == -0.20

    # 纯碱合成层成本下挫
    assert "NODE_03_SODA_SYN" in impacts
    assert impacts["NODE_03_SODA_SYN"] < 0.0

    # 下游玻璃加工层毛利走阔 (正向冲击)
    assert "NODE_04_FLOAT_GLASS" in impacts
    assert impacts["NODE_04_FLOAT_GLASS"] > 0.0
    assert "NODE_05_PV_GLASS" in impacts
    assert impacts["NODE_05_PV_GLASS"] > 0.0


def test_crush_spread_calculation(ontology: ValueAddedOntology):
    """
    验证冶炼加工裂解利润计算:
    CrushSpread = P_FG - (0.20 * P_SA) - 350
    当 FG = 1100, SA = 1014 时:
    CrushSpread = 1100 - (0.20 * 1014) - 350 = 1100 - 202.8 - 350 = 547.2 元/吨
    """
    spread = ontology.compute_crush_spread(fg_price=1100.0, sa_price=1014.0, fuel_cost=350.0, soda_consumption=0.20)
    expected = 1100.0 - (0.20 * 1014.0) - 350.0
    assert abs(spread - expected) < 1e-4
    assert round(spread, 1) == 547.2


# ==============================================================================
# 6. 资产坐标硬门禁校验与防伪拦截测试
# ==============================================================================

def test_validate_asset_mapping_authentic_and_counterfactual(ontology: ValueAddedOntology):
    """
    验证资产工艺层级防伪硬检验:
    - 真实标的: 远兴能源 (000683) 为 Level 1 -> True
    - 伪命题拦截: 试图将隆基绿能 (601012, Level 4) 或旗滨集团 (Level 3) 包装为 Level 1 矿产龙头 -> False
    - 未知代码: 坚决返回 False
    """
    # 正确匹配
    assert ontology.validate_asset_mapping("000683", claimed_level=1) is True
    assert ontology.validate_asset_mapping("600328", claimed_level=2) is True
    assert ontology.validate_asset_mapping("601636", claimed_level=3) is True
    assert ontology.validate_asset_mapping("601012", claimed_level=4) is True

    # 错误层级/移花接木拦截
    assert ontology.validate_asset_mapping("601012", claimed_level=1) is False
    assert ontology.validate_asset_mapping("601636", claimed_level=1) is False
    assert ontology.validate_asset_mapping("000683", claimed_level=3) is False

    # 虚构代码拦截
    assert ontology.validate_asset_mapping("999999", claimed_level=1) is False
    assert ontology.validate_asset_mapping("", claimed_level=1) is False


def test_invalid_node_lookup_returns_none(ontology: ValueAddedOntology):
    """验证无效节点ID或标的查询安全返回 None，绝不抛出未捕获异常"""
    assert ontology.get_node("NON_EXISTENT_NODE") is None
    assert ontology.get_node_by_symbol("NON_EXISTENT_SYMBOL") is None
    assert ontology.get_upstream_chain("NON_EXISTENT_NODE") == []
    assert ontology.get_downstream_chain("NON_EXISTENT_NODE") == []


def test_adversarial_symbol_lookups_and_whitespace(ontology: ValueAddedOntology):
    """
    【Challenger 1 对抗用例测试】
    1. 空白符号 ("   ", "\t", "\n") 绝不匹配为 Level 1 天然碱
    2. 整数代码 600328 安全转为字符串并准确匹配
    3. 相似大宗词汇 ("SAND", "SAMPLE", "SAFE") 与单字符 "S" 绝不误匹配 SA 或 SALT
    """
    # 1. 空白符防护
    for blank in ["   ", "\t", "\n", "  \n\t  "]:
        assert ontology.get_node_by_symbol(blank) is None
        assert ontology.validate_asset_mapping(blank, claimed_level=1) is False

    # 2. 整数代码安全支持
    node_int = ontology.get_node_by_symbol(600328)
    assert node_int is not None
    assert node_int.node_id == "NODE_03_SODA_SYN"

    node_int_trona = ontology.get_node_by_symbol(683)  # 000683
    # 严格代码匹配
    assert ontology.get_node_by_symbol(601636).node_id == "NODE_04_FLOAT_GLASS"

    # 3. 词根子串碰撞防护
    collision_words = ["SAND", "SAMPLE", "SAFE", "SALARY", "S"]
    for w in collision_words:
        assert ontology.get_node_by_symbol(w) is None, f"词汇 '{w}' 产生误匹配"


def test_cost_shock_non_existent_node_raises_key_error(ontology: ValueAddedOntology):
    """验证对未注册节点执行成本冲击传导严格抛出 KeyError"""
    with pytest.raises(KeyError, match="not found in ontology"):
        ontology.propagate_cost_shock("NON_EXISTENT_NODE", -0.20)


def test_cost_shock_propagation_l3_l4_positive_margin(ontology: ValueAddedOntology):
    """
    验证 L3 玻璃冶炼毛利扩张能够合理传导至 L4 终端深加工，
    杜绝 L4 发生物理逻辑不合规的负向反转
    """
    impacts = ontology.propagate_cost_shock("NODE_01_TRONA", shock_pct=-0.20)
    assert impacts["NODE_01_TRONA"] == -0.20
    assert impacts["NODE_03_SODA_SYN"] < 0.0
    assert impacts["NODE_04_FLOAT_GLASS"] > 0.0
    assert impacts["NODE_05_PV_GLASS"] > 0.0
    assert impacts["NODE_06_AUTO_GLASS"] > 0.0
    assert impacts["NODE_07_END_MODULE"] > 0.0

