"""
郑商所纯碱/玻璃与A股产业链因果增值节点本体库 (ADR-0002)
Causal Value-Added Process Node Ontology for SA & FG Supply Chain

架构规约遵循:
1. 严禁按化学/材料分类，必须按工艺物理增值层级分类 (4 Tiers / 8 Nodes)
2. 绑定核心大宗商品 (SA/FG 期货主连) 与 12+ 只 A 股核心上市公司
3. 严格化学计量关系 (1 吨玻璃消耗 0.20 吨重碱，燃料成本 ~350 元/吨，窑炉 8-10 年连续刚性)
4. 支持因果拓扑图遍历 (上下游依赖链检索、资产层级校验、成本冲击传导模型)
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


def validate_no_numerical_alpha(text: str) -> None:
    """
    硬约束校验: 严格禁止在文本中伪造或生成数值 Alpha
    """
    patterns = [
        r"ALPHA\s*[:=]",
        r"ALPHA\s*==",
        r"PREDICTED\s*RETURN",
        r"TARGET\s*RETURN",
        r"EXPECTED\s*RETURN",
        r"CONFIDENCE\s*PROBABILITY",
    ]
    text_payload = str(text).upper()
    text_norm = re.sub(r"_", " ", text_payload)
    for pat in patterns:
        if re.search(pat, text_payload) or re.search(pat, text_norm):
            raise ValueError(
                f"Integrity Violation: Strictly prohibited from generating numerical Alpha ({pat})."
            )


class ProcessNodeType(Enum):
    """工艺增值物理层级类型"""
    RAW_MATERIAL = "RAW_MATERIAL"        # Level 1: 原材料与天然碱采矿 (000683, 603299)
    SODA_SYNTHESIS = "SODA_SYNTHESIS"    # Level 2: 中间纯碱合成与制造 (600328, 600409, 000822, 603077, SA)
    GLASS_PROCESS = "GLASS_PROCESS"      # Level 3: 浮法/光伏玻璃加工 (601636, 600586, 601865, 000012, FG)
    TERMINAL_DEMAND = "TERMINAL_DEMAND"  # Level 4: 终端战略需求与制造业 (601012, 600438, 300750)


@dataclass
class ProcessNode:
    """工艺增值拓扑节点实体"""
    node_id: str
    node_name: str
    node_type: ProcessNodeType
    level: int  # 1 到 4
    core_commodities: List[str] = field(default_factory=list)
    core_stocks: List[Dict[str, Any]] = field(default_factory=list)
    stoichiometry: Dict[str, float] = field(default_factory=dict)
    upstream_node_ids: List[str] = field(default_factory=list)
    downstream_node_ids: List[str] = field(default_factory=list)
    description: str = ""

    def contains_symbol(self, symbol: Any) -> bool:
        """检查该节点是否包含指定商品或股票代码"""
        if symbol is None:
            return False
        sym_clean = str(symbol).upper().strip()
        if not sym_clean:
            return False

        # 匹配商品代码 (如 SA, SA0, SA701, FG, FG701, TRONA_ORE)
        # 严格使用精确匹配或前缀+数字格式，杜绝 SAND/SAFE/SALARY 匹配 SA，或 S 匹配 SALT
        for comm in self.core_commodities:
            c_clean = str(comm).upper().strip()
            if sym_clean == c_clean:
                return True
            # 支持期货合约格式，如 SA701, SA0, FG701 (严格由品种代码+数字构成)
            if re.match(rf"^{re.escape(c_clean)}\d+$", sym_clean):
                return True

        # 匹配股票代码 (如 000683, 000683.SZ, 远兴能源)
        for stk in self.core_stocks:
            code = str(stk.get("code", "")).upper().strip()
            name = str(stk.get("name", "")).strip()
            if code and (sym_clean == code or sym_clean in {f"{code}.SZ", f"{code}.SH"}):
                return True
            if name and sym_clean in name:
                return True
        return False


class ValueAddedOntology:
    """
    纯碱-玻璃全产业链工艺增值因果本体中枢 (ADR-0002)
    管理 4 个物理层级、8 个核心工艺增值节点及全部标的映射
    """

    def __init__(self):
        self._nodes: Dict[str, ProcessNode] = {}
        self._symbol_to_node_id: Dict[str, str] = {}
        self._init_default_ontology()

    def _init_default_ontology(self) -> None:
        """初始化郑商所纯碱/玻璃与 A 股核心标的产业链四层拓扑结构"""

        # -------------------------------------------------------------
        # Level 1: 原材料与天然碱采矿 (RAW_MATERIAL)
        # -------------------------------------------------------------
        node_01 = ProcessNode(
            node_id="NODE_01_TRONA",
            node_name="天然碱原料与采矿",
            node_type=ProcessNodeType.RAW_MATERIAL,
            level=1,
            core_commodities=["TRONA_ORE"],
            core_stocks=[
                {
                    "code": "000683",
                    "name": "远兴能源",
                    "role": "国内最大天然碱独占龙头 (阿拉善项目千万吨级规划)",
                    "marginal_cost_rmb": 900.0,
                    "pricing_power": "极高边际成本压制力"
                }
            ],
            stoichiometry={
                "marginal_cost_rmb": 900.0,
                "energy_saving_pct": 0.40,
                "carbon_emission_discount": 0.50
            },
            upstream_node_ids=[],
            downstream_node_ids=["NODE_03_SODA_SYN"],
            description="以倍半碳酸钠固相矿为原料，无需原盐与石灰石，开采与加工成本为全行业最低点 (~900元/吨)"
        )

        node_02 = ProcessNode(
            node_id="NODE_02_SALT",
            node_name="原盐采选与工业盐原料",
            node_type=ProcessNodeType.RAW_MATERIAL,
            level=1,
            core_commodities=["SALT_RAW", "THERMAL_COAL"],
            core_stocks=[
                {
                    "code": "603299",
                    "name": "苏盐井神",
                    "role": "井矿盐龙头 / 华东优质制碱原料基底",
                    "marginal_cost_rmb": 320.0,
                    "pricing_power": "原盐出厂价与盐穴资源壁垒"
                }
            ],
            stoichiometry={
                "salt_consumption_per_ton_soda": 1.55,
                "coal_consumption_per_ton_soda": 0.50
            },
            upstream_node_ids=[],
            downstream_node_ids=["NODE_03_SODA_SYN"],
            description="氨碱法与联碱法制造纯碱的核心原料输入层，原盐消耗比 1.55 吨/吨纯碱"
        )

        # -------------------------------------------------------------
        # Level 2: 中间纯碱合成与制造 (SODA_SYNTHESIS)
        # -------------------------------------------------------------
        node_03 = ProcessNode(
            node_id="NODE_03_SODA_SYN",
            node_name="中间纯碱合成与提纯",
            node_type=ProcessNodeType.SODA_SYNTHESIS,
            level=2,
            core_commodities=["SA", "SA0", "SA701", "SA_DENSE", "SA_LIGHT"],
            core_stocks=[
                {
                    "code": "600328",
                    "name": "中盐化工",
                    "role": "综合制碱龙头 (氨碱+联碱近400万吨)",
                    "marginal_cost_rmb": 1550.0
                },
                {
                    "code": "600409",
                    "name": "三友化工",
                    "role": "华北氨碱龙头 (纯碱340万吨)",
                    "marginal_cost_rmb": 1600.0
                },
                {
                    "code": "000822",
                    "name": "山东海化",
                    "role": "潍坊老牌氨碱龙头 / 重碱基准锚点",
                    "marginal_cost_rmb": 1620.0
                },
                {
                    "code": "603077",
                    "name": "和邦生物",
                    "role": "西南联碱双吨龙头 (纯碱+氯化铵)",
                    "marginal_cost_rmb": 1500.0
                }
            ],
            stoichiometry={
                "dense_to_light_ratio": 0.60,
                "soda_to_glass_factor": 0.20,
                "solvay_marginal_cost_rmb": 1600.0,
                "hou_marginal_cost_rmb": 1500.0
            },
            upstream_node_ids=["NODE_01_TRONA", "NODE_02_SALT"],
            downstream_node_ids=["NODE_04_FLOAT_GLASS", "NODE_05_PV_GLASS"],
            description="郑商所纯碱期货 (SA) 标的层，涵盖氨碱法、联碱法与重质化加工，重碱是玻璃熔炼的核心原料"
        )

        # -------------------------------------------------------------
        # Level 3: 浮法与光伏玻璃冶炼加工 (GLASS_PROCESS)
        # -------------------------------------------------------------
        node_04 = ProcessNode(
            node_id="NODE_04_FLOAT_GLASS",
            node_name="浮法玻璃冶炼与成型",
            node_type=ProcessNodeType.GLASS_PROCESS,
            level=3,
            core_commodities=["FG", "FG0", "FG701", "FG_FLOAT"],
            core_stocks=[
                {
                    "code": "601636",
                    "name": "旗滨集团",
                    "role": "全国浮法玻璃龙头 (在产日熔量超1.7万吨)",
                    "capacity_tpd": 17600
                },
                {
                    "code": "600586",
                    "name": "金晶科技",
                    "role": "超白浮法与纯碱-玻璃一体化",
                    "capacity_tpd": 6000
                },
                {
                    "code": "000012",
                    "name": "南玻A",
                    "role": "节能浮法与高档建筑工程玻璃",
                    "capacity_tpd": 8000
                }
            ],
            stoichiometry={
                "soda_consumption_per_ton_glass": 0.20,  # 严格 1:0.20 耗碱比
                "fuel_cost_rmb": 350.0,                  # 燃料成本约 350 元/吨
                "continuous_kiln_years": 8.5,            # 窑炉连续运转 8-10 年不可轻易停火
                "cold_repair_cost_rmb_million": 40.0     # 冷修重启成本 3000-5000 万元
            },
            upstream_node_ids=["NODE_03_SODA_SYN"],
            downstream_node_ids=["NODE_06_AUTO_GLASS", "NODE_07_END_MODULE"],
            description="郑商所玻璃期货 (FG) 标的层，高温锡槽连续浮法成型，具备极强热态惯性与不可逆点火刚性"
        )

        node_05 = ProcessNode(
            node_id="NODE_05_PV_GLASS",
            node_name="光伏压延玻璃深加工",
            node_type=ProcessNodeType.GLASS_PROCESS,
            level=3,
            core_commodities=["PV_GLASS_ROLLED"],
            core_stocks=[
                {
                    "code": "601865",
                    "name": "福莱特",
                    "role": "全球光伏压延玻璃双寡头 (市占率超30%)",
                    "market_share": 0.32
                },
                {
                    "code": "002623",
                    "name": "亚玛顿",
                    "role": "超薄双玻组件减反镀膜玻璃龙头",
                    "market_share": 0.08
                }
            ],
            stoichiometry={
                "soda_consumption_per_ton_glass": 0.20,
                "low_iron_sand_ratio": 0.72,
                "fuel_cost_rmb": 380.0
            },
            upstream_node_ids=["NODE_03_SODA_SYN"],
            downstream_node_ids=["NODE_07_END_MODULE"],
            description="超白压延光伏玻璃，透光率>=91.5%，双玻组件渗透驱动重质纯碱刚性消耗"
        )

        node_06 = ProcessNode(
            node_id="NODE_06_AUTO_GLASS",
            node_name="汽车安全玻璃精深加工",
            node_type=ProcessNodeType.GLASS_PROCESS,
            level=3,
            core_commodities=["AUTO_GLASS"],
            core_stocks=[
                {
                    "code": "600660",
                    "name": "福耀玻璃",
                    "role": "全球汽车安全玻璃第一龙头 (市占率超34%)",
                    "market_share": 0.34
                }
            ],
            stoichiometry={
                "float_glass_consumption_ratio": 1.05
            },
            upstream_node_ids=["NODE_04_FLOAT_GLASS"],
            downstream_node_ids=["NODE_08_END_STORAGE"],
            description="浮法玻璃原片二次钢化/夹层深加工，高附加值成本转嫁能力强"
        )

        # -------------------------------------------------------------
        # Level 4: 终端战略需求与制造业消纳 (TERMINAL_DEMAND)
        # -------------------------------------------------------------
        node_07 = ProcessNode(
            node_id="NODE_07_END_MODULE",
            node_name="终端光伏组件与建筑工程",
            node_type=ProcessNodeType.TERMINAL_DEMAND,
            level=4,
            core_commodities=["PV_MODULE", "REAL_ESTATE_COMPLETION"],
            core_stocks=[
                {
                    "code": "601012",
                    "name": "隆基绿能",
                    "role": "全球单晶硅片与光伏组件龙头",
                    "industry": "新能源光伏"
                },
                {
                    "code": "600438",
                    "name": "通威股份",
                    "role": "高纯晶硅与光伏电池龙头",
                    "industry": "新能源光伏"
                }
            ],
            stoichiometry={
                "pv_glass_per_gw_sqm": 5000000.0,
                "dual_glass_penetration": 0.75
            },
            upstream_node_ids=["NODE_04_FLOAT_GLASS", "NODE_05_PV_GLASS"],
            downstream_node_ids=[],
            description="终端光伏组件与地产建筑竣工消纳层，装机节奏决定光伏与浮法玻璃的长期拉动力"
        )

        node_08 = ProcessNode(
            node_id="NODE_08_END_STORAGE",
            node_name="终端动力与储能新能源",
            node_type=ProcessNodeType.TERMINAL_DEMAND,
            level=4,
            core_commodities=["BATTERY_CELL", "STORAGE_SYSTEM"],
            core_stocks=[
                {
                    "code": "300750",
                    "name": "宁德时代",
                    "role": "全球动力电池与储能中枢龙头",
                    "industry": "储能动力"
                }
            ],
            stoichiometry={
                "glass_fiber_composite_ratio": 0.08
            },
            upstream_node_ids=["NODE_06_AUTO_GLASS"],
            downstream_node_ids=[],
            description="新能源车与储能电站制造终端，具备全球出海竞争力的独立特质 Alpha 标的"
        )

        # 注册所有节点
        for n in [node_01, node_02, node_03, node_04, node_05, node_06, node_07, node_08]:
            self.register_node(n)

    def register_node(self, node: ProcessNode) -> None:
        """注册工艺增值节点并建立索引"""
        self._nodes[node.node_id] = node
        
        # 索引商品
        for comm in node.core_commodities:
            self._symbol_to_node_id[comm.upper()] = node.node_id
            
        # 索引股票
        for stk in node.core_stocks:
            code = stk.get("code", "")
            if code:
                self._symbol_to_node_id[code] = node.node_id
                self._symbol_to_node_id[f"{code}.SZ"] = node.node_id
                self._symbol_to_node_id[f"{code}.SH"] = node.node_id
            name = stk.get("name", "")
            if name:
                self._symbol_to_node_id[name] = node.node_id

    @property
    def nodes(self) -> Dict[str, ProcessNode]:
        """获取所有已注册工艺增值节点字典"""
        return self._nodes

    def get_node(self, node_id: str) -> Optional[ProcessNode]:
        """根据节点ID获取增值节点"""
        return self._nodes.get(node_id)

    def get_node_by_symbol(self, symbol: Any) -> Optional[ProcessNode]:
        """根据股票代码、商品符号或中文简称智能查找所属增值节点"""
        if symbol is None:
            return None
        sym = str(symbol).strip().upper()
        if not sym:
            return None
        
        # 1. 直接精确索引查找
        if sym in self._symbol_to_node_id:
            return self._nodes[self._symbol_to_node_id[sym]]
            
        # 2. 遍历节点匹配 (支持 SA0, FG0, 严格代码与商品匹配)
        for node in self._nodes.values():
            if node.contains_symbol(sym):
                return node
        return None

    def get_upstream_chain(self, node_id: str) -> List[ProcessNode]:
        """获取指定节点的所有上游追溯依赖链 (按拓扑层级自顶向下排列)"""
        start_node = self.get_node(node_id)
        if not start_node:
            return []

        visited: Set[str] = set()
        queue = list(start_node.upstream_node_ids)
        result: List[ProcessNode] = []

        while queue:
            curr_id = queue.pop(0)
            if curr_id not in visited and curr_id in self._nodes:
                visited.add(curr_id)
                curr_node = self._nodes[curr_id]
                result.append(curr_node)
                queue.extend(curr_node.upstream_node_ids)

        # 按层级升序 (Level 1 -> Level 2 -> ...)
        result.sort(key=lambda n: n.level)
        return result

    def get_downstream_chain(self, node_id: str) -> List[ProcessNode]:
        """获取指定节点的所有下游传导链 (按拓扑层级自底向上排列)"""
        start_node = self.get_node(node_id)
        if not start_node:
            return []

        visited: Set[str] = set()
        queue = list(start_node.downstream_node_ids)
        result: List[ProcessNode] = []

        while queue:
            curr_id = queue.pop(0)
            if curr_id not in visited and curr_id in self._nodes:
                visited.add(curr_id)
                curr_node = self._nodes[curr_id]
                result.append(curr_node)
                queue.extend(curr_node.downstream_node_ids)

        # 按层级升序 (Level 2 -> Level 3 -> Level 4)
        result.sort(key=lambda n: n.level)
        return result

    def validate_asset_mapping(self, symbol: Any, claimed_level: int) -> bool:
        """
        校验标的与声称的工艺增值层级坐标是否一致 (防伪与防偷换概念硬拦截)
        例如: 将下游光伏模组或玩具小盘股包装为'天然碱卡脖子龙头'时坚决返回 False
        """
        if symbol is None:
            return False
        sym_str = str(symbol).strip()
        if not sym_str:
            return False
        node = self.get_node_by_symbol(sym_str)
        if not node:
            return False
        return node.level == claimed_level

    def compute_crush_spread(
        self,
        fg_price: float,
        sa_price: float,
        fuel_cost: float = 350.0,
        soda_consumption: float = 0.20
    ) -> float:
        """
        计算冶金与工业化学裂解加工利润 (Crush Spread):
        CrushSpread = P_FG - (k_soda * P_SA) - FuelCost
        严格遵循 1 吨玻璃消耗 0.20 吨重碱，350 元燃料与辅助成本
        """
        return float(fg_price - (soda_consumption * sa_price) - fuel_cost)

    def propagate_cost_shock(
        self,
        source_node_id: str,
        shock_pct: float,
        damping_factor: float = 0.65
    ) -> Dict[str, float]:
        """
        因果网络成本冲击传导模型 (Cost Shock Propagation):
        计算源头节点的成本冲击向下游各节点的利润/价格弹性冲击
        
        Args:
            source_node_id: 冲击源头节点ID (如 NODE_01_TRONA 天然碱新增投产)
            shock_pct: 冲击幅度 (如 -0.20 表示源头生产成本下挫 20%)
            damping_factor: 逐层传导阻尼系数
            
        Returns:
            Dict[node_id, impact_surplus_pct]: 各节点的预期盈余/成本冲击百分比
        """
        if source_node_id not in self._nodes:
            raise KeyError(f"Node '{source_node_id}' not found in ontology.")

        impacts: Dict[str, float] = {source_node_id: round(float(shock_pct), 4)}
        start_node = self._nodes[source_node_id]

        # 沿下游有向边按层传导
        current_layer = [start_node]

        while current_layer:
            next_layer: List[ProcessNode] = []
            for node in current_layer:
                parent_impact = impacts[node.node_id]
                for ds_id in node.downstream_node_ids:
                    ds_node = self.get_node(ds_id)
                    if ds_node and ds_id not in impacts:
                        # 工业传导机理:
                        # 1. 天然碱 (L1) -> 纯碱合成 (L2): 低成本替代引发价格内卷与毛利压缩 (负向冲击)
                        if ds_node.level == 2 and node.level == 1:
                            impact_val = parent_impact * 0.85
                        # 2. 纯碱 (L2) -> 玻璃加工 (L3): 纯碱成本下挫反哺玻璃加工毛利走阔 (正向反向传导)
                        elif ds_node.level == 3 and node.level == 2:
                            k_soda = ds_node.stoichiometry.get("soda_consumption_per_ton_glass", 0.20)
                            impact_val = - (parent_impact * k_soda * 1.5)
                        # 3. 玻璃 (L3) -> 终端需求/深加工 (L4): 继承玻璃端正向扩张红利并附加阻尼
                        elif ds_node.level >= 3 and node.level >= 3:
                            impact_val = parent_impact * damping_factor
                        else:
                            impact_val = parent_impact * damping_factor

                        impacts[ds_id] = round(impact_val, 4)
                        next_layer.append(ds_node)

            current_layer = next_layer

        return impacts

    def all_nodes(self) -> Dict[str, ProcessNode]:
        """获取所有已注册的工艺增值节点"""
        return dict(self._nodes)

    def all_core_stocks(self) -> List[Dict[str, Any]]:
        """获取全产业链绑定的核心 A 股上市公司清单"""
        stocks = []
        for node in self._nodes.values():
            for stk in node.core_stocks:
                stk_entry = dict(stk)
                stk_entry["node_id"] = node.node_id
                stk_entry["node_name"] = node.node_name
                stk_entry["level"] = node.level
                stocks.append(stk_entry)
        return stocks
