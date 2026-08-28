# -*- coding: utf-8 -*-
"""src/llm/scnu_rag_filter.py —— SCNU-RAG 定性过滤引擎 (Engine 1)

依据《Backtesting Specification: The 2025-2026 Semiconductor Storage Supercycle》第 3 节实现：
1. 事实-观点-推论 (FOI) 解析：
   - [FACT:source]: 可验证、量化事件（如预付款、海关价格、产能采购）
   - [OPINION:holder]: 主观预测/评论（如券商研报、分析师预期）
   - [INFERENCE:chain]: 逻辑推导链条
2. 供应链卡位评分矩阵 (Chokepoint Score, CS ∈ [0, 20]):
   - 覆盖 5 大工艺环节（衬底 Substrate → 外延 Epitaxy → 器件 Device → 模组 Module → 系统集成 Integration）
   - 共 10 道结构化供应链评估问题，每题评分 {0, 1, 2}
   - 硬门控准入条件：CS_i >= 12（未达到则从候选池剪枝，不进入阶段二回归计算）
3. 对抗性降级与证据降权规则 (Adversarial Qualitative Scaling Rules, 表 1)：
   - 单一来源陈述 (High Uncertainty) → 标记 [FACT:single_source]，仓位上限限制为 50%
   - 样品/送样测试阶段 (Early Stage) → 标记 [FACT:low_confidence]，基础权重减半 (x0.5)
   - 资本承诺与财务不匹配 (Supply Strain) → 触发下游应收账款 (AR) 交叉验证
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class FOIEvidence:
    """FOI 证据项数据结构。"""
    sentence: str
    category: str  # "FACT", "OPINION", "INFERENCE"
    tag: str       # e.g., "source", "holder", "chain", "single_source", "low_confidence"
    raw_text: str


@dataclass
class AdversarialModifier:
    """对抗性缩放修饰符。"""
    position_cap: float = 1.0          # 仓位上限比例（默认 100%）
    weight_multiplier: float = 1.0     # 基础权重乘数（默认 1.0）
    ar_check_required: bool = False    # 是否触发应收账款与现金流交叉验证
    tags: List[str] = field(default_factory=list)


# 10 道标准工艺节点供应链卡位评估题（覆盖 5 大工艺节点，每题满分 2 分，总分 20 分）
CHOKEPOINT_QUESTIONS = [
    {
        "id": "Q1_SUBSTRATE_CAPACITY",
        "node": "Substrate",
        "question": "是否具备高纯硅片/先进晶圆衬底的长期排他性供货协议或自主衬底制备能力？",
        "weight": 2,
    },
    {
        "id": "Q2_SUBSTRATE_PURITY",
        "node": "Substrate",
        "question": "核心原材料纯度与缺陷密度是否已达到先进制程 DRAM/3D NAND 规格门槛？",
        "weight": 2,
    },
    {
        "id": "Q3_EPITAXY_UNIFORMITY",
        "node": "Epitaxy",
        "question": "外延层厚度均匀性与掺杂浓度控制是否满足多层堆叠存储单元要求？",
        "weight": 2,
    },
    {
        "id": "Q4_EPITAXY_THROUGHPUT",
        "node": "Epitaxy",
        "question": "外延设备与量产良率是否支持规模化产能扩张（Throughput 达标）？",
        "weight": 2,
    },
    {
        "id": "Q5_DEVICE_NODE",
        "node": "Device",
        "question": "DRAM/NAND 工艺制程节点（如 1beta/1gamma DRAM 或 200+ 层 3D NAND）是否处于行业前沿？",
        "weight": 2,
    },
    {
        "id": "Q6_DEVICE_PATENT",
        "node": "Device",
        "question": "是否拥有核心存储单元架构专利或原厂直接技术授权与晶圆代工产能保障？",
        "weight": 2,
    },
    {
        "id": "Q7_MODULE_CONTROLLER",
        "node": "Module",
        "question": "主控芯片（Controller IC）与固件算法是否具备自主可控能力及高效纠错 (LDPC) 支持？",
        "weight": 2,
    },
    {
        "id": "Q8_MODULE_PACKAGING",
        "node": "Module",
        "question": "先进封装技术（如 SiP, 晶圆级封装, 倒装焊, 高层数超薄叠 Die）是否具备量产交付能力？",
        "weight": 2,
    },
    {
        "id": "Q9_INTEGRATION_TIER1",
        "node": "Integration",
        "question": "产品是否已批量导入 Tier-1 服务器、PC、智能终端或车规级核心客户供应链？",
        "weight": 2,
    },
    {
        "id": "Q10_INTEGRATION_LOCKIN",
        "node": "Integration",
        "question": "在下游客户产品周期中是否具备高替换壁垒与战略备货优先锁定协议？",
        "weight": 2,
    },
]

CS_HARD_GATE_THRESHOLD = 12  # Specification 3.2: Filter CS_i >= 12


class SCNURAGFilter:
    """SCNU-RAG 定性文本过滤与卡位评分引擎。"""

    def __init__(self, cs_threshold: int = CS_HARD_GATE_THRESHOLD):
        self.cs_threshold = cs_threshold

    def parse_foi(self, text_feed: str) -> List[FOIEvidence]:
        """解析非结构化文本，进行 FOI 实体与逻辑归类。

        Sentence s in {[FACT:source], [OPINION:holder], [INFERENCE:chain]}
        """
        evidence_list: List[FOIEvidence] = []
        if not text_feed or not text_feed.strip():
            return evidence_list

        sentences = [s.strip() for s in re.split(r"[\n\r；;。]+", text_feed) if s.strip()]

        for s in sentences:
            # 显式标签匹配
            tag_match = re.match(r"^\[(FACT|OPINION|INFERENCE):([^\]]+)\]\s*(.*)$", s, re.IGNORECASE)
            if tag_match:
                cat = tag_match.group(1).upper()
                tag = tag_match.group(2).strip()
                content = tag_match.group(3).strip()
                evidence_list.append(FOIEvidence(sentence=content or s, category=cat, tag=tag, raw_text=s))
                continue

            # 启发式规则解析
            is_fact = any(k in s for k in [
                "海关", "进出口", "预付款", "现货价", "元/片", "美元", "同比增长", "环比增长",
                "扩产", "锁单", "产能", "报表", "财报", "DDR5", "NAND", "采购", "库存"
            ])
            is_opinion = any(k in s for k in [
                "预计", "预测", "分析师", "看好", "观点", "目标价", "研报", "猜测", "评级", "预期"
            ])
            is_inference = any(k in s for k in [
                "因此", "由此推导", "意味着", "导致", "推论", "从而", "将引发"
            ])

            if is_opinion:
                evidence_list.append(FOIEvidence(sentence=s, category="OPINION", tag="analyst_view", raw_text=s))
            elif is_inference:
                evidence_list.append(FOIEvidence(sentence=s, category="INFERENCE", tag="logic_chain", raw_text=s))
            elif is_fact:
                evidence_list.append(FOIEvidence(sentence=s, category="FACT", tag="market_feed", raw_text=s))
            else:
                evidence_list.append(FOIEvidence(sentence=s, category="OPINION", tag="general", raw_text=s))

        return evidence_list

    def apply_adversarial_rules(self, evidence_list: List[FOIEvidence], text_feed: str) -> AdversarialModifier:
        """执行表 1 的对抗性定性缩放规则。

        1. Single-source qualitative claim -> Mark [FACT:single_source]; Cap position at 50%
        2. "Sample-stage / Sending test"   -> Mark [FACT:low_confidence]; Halve base weight (0.5x)
        3. Mismatched capital commitments  -> Trigger downstream AR cross-validation check
        """
        modifier = AdversarialModifier()
        text_lower = text_feed.lower()

        # 规则 1: 单一来源 / 未经多方交叉验证的陈述
        has_single_source = (
            "[fact:single_source]" in text_lower or
            "[fact:single source]" in text_lower or
            "单一来源" in text_feed or
            "独家传闻" in text_feed or
            "未经证实" in text_feed
        )
        if has_single_source:
            modifier.position_cap = min(modifier.position_cap, 0.50)
            modifier.tags.append("[FACT:single_source]")

        # 规则 2: 送样/样品验证阶段
        has_sample_stage = (
            "[fact:low_confidence]" in text_lower or
            "[fact:low confidence]" in text_lower or
            "送样" in text_feed or
            "验证阶段" in text_feed or
            "小批量试产" in text_feed or
            "sample-stage" in text_lower or
            "sending test" in text_lower
        )
        if has_sample_stage:
            modifier.weight_multiplier *= 0.50
            modifier.tags.append("[FACT:low_confidence]")

        # 规则 3: 资本承诺与账面资金/应收不匹配
        has_mismatch = (
            "资本开支不匹配" in text_feed or
            "预付款剧增" in text_feed or
            "应收账款高企" in text_feed or
            "资金链承压" in text_feed or
            "mismatched capital" in text_lower or
            "supply strain" in text_lower
        )
        if has_mismatch:
            modifier.ar_check_required = True
            modifier.tags.append("[RISK:ar_cross_validation_check]")

        return modifier

    def evaluate_chokepoint_score(
        self,
        stock_code: str,
        stock_name: str,
        qualitative_text: str,
        custom_scores: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """计算供应链卡位评分 (CS ∈ [0, 20]) 并实施硬门控过滤。"""
        evidence_list = self.parse_foi(qualitative_text)
        adversarial = self.apply_adversarial_rules(evidence_list, qualitative_text)

        scores_by_question: Dict[str, int] = {}
        node_scores: Dict[str, int] = {"Substrate": 0, "Epitaxy": 0, "Device": 0, "Module": 0, "Integration": 0}

        kb_profiles = {
            "688525": {  # 佰维存储 BIWIN: 模组+先进封测+Tier1客户强卡位
                "Q1_SUBSTRATE_CAPACITY": 1, "Q2_SUBSTRATE_PURITY": 1,
                "Q3_EPITAXY_UNIFORMITY": 1, "Q4_EPITAXY_THROUGHPUT": 1,
                "Q5_DEVICE_NODE": 1, "Q6_DEVICE_PATENT": 1,
                "Q7_MODULE_CONTROLLER": 2, "Q8_MODULE_PACKAGING": 2,
                "Q9_INTEGRATION_TIER1": 2, "Q10_INTEGRATION_LOCKIN": 2,  # Total = 14 >= 12
            },
            "MU": {  # 美光科技 Micron: 原厂 IDM 全链条卡位
                "Q1_SUBSTRATE_CAPACITY": 2, "Q2_SUBSTRATE_PURITY": 2,
                "Q3_EPITAXY_UNIFORMITY": 2, "Q4_EPITAXY_THROUGHPUT": 2,
                "Q5_DEVICE_NODE": 2, "Q6_DEVICE_PATENT": 2,
                "Q7_MODULE_CONTROLLER": 2, "Q8_MODULE_PACKAGING": 2,
                "Q9_INTEGRATION_TIER1": 2, "Q10_INTEGRATION_LOCKIN": 2,  # Total = 20 >= 12
            },
            "005930": {  # 三星电子 Samsung: IDM 龙头
                "Q1_SUBSTRATE_CAPACITY": 2, "Q2_SUBSTRATE_PURITY": 2,
                "Q3_EPITAXY_UNIFORMITY": 2, "Q4_EPITAXY_THROUGHPUT": 2,
                "Q5_DEVICE_NODE": 2, "Q6_DEVICE_PATENT": 2,
                "Q7_MODULE_CONTROLLER": 2, "Q8_MODULE_PACKAGING": 2,
                "Q9_INTEGRATION_TIER1": 2, "Q10_INTEGRATION_LOCKIN": 2,
            },
            "000660": {  # SK 海力士 SK Hynix: HBM 龙头
                "Q1_SUBSTRATE_CAPACITY": 2, "Q2_SUBSTRATE_PURITY": 2,
                "Q3_EPITAXY_UNIFORMITY": 2, "Q4_EPITAXY_THROUGHPUT": 2,
                "Q5_DEVICE_NODE": 2, "Q6_DEVICE_PATENT": 2,
                "Q7_MODULE_CONTROLLER": 2, "Q8_MODULE_PACKAGING": 2,
                "Q9_INTEGRATION_TIER1": 2, "Q10_INTEGRATION_LOCKIN": 2,
            },
            "WDC": {  # 西部数据 Western Digital
                "Q1_SUBSTRATE_CAPACITY": 1, "Q2_SUBSTRATE_PURITY": 1,
                "Q3_EPITAXY_UNIFORMITY": 2, "Q4_EPITAXY_THROUGHPUT": 2,
                "Q5_DEVICE_NODE": 2, "Q6_DEVICE_PATENT": 2,
                "Q7_MODULE_CONTROLLER": 2, "Q8_MODULE_PACKAGING": 2,
                "Q9_INTEGRATION_TIER1": 2, "Q10_INTEGRATION_LOCKIN": 2,  # Total = 18 >= 12
            },
        }

        base_profile = kb_profiles.get(stock_code, {})
        for q in CHOKEPOINT_QUESTIONS:
            qid = q["id"]
            node = q["node"]
            if custom_scores and qid in custom_scores:
                score = int(custom_scores[qid])
            elif qid in base_profile:
                score = int(base_profile[qid])
            else:
                keywords = [node.lower(), "dram", "nand", "hbm", "产能", "先进制程", "主控", "客户"]
                hits = sum(1 for kw in keywords if kw in qualitative_text.lower())
                score = 2 if hits >= 4 else (1 if hits >= 1 else 0)

            score = max(0, min(2, score))
            scores_by_question[qid] = score
            node_scores[node] += score

        total_cs = sum(scores_by_question.values())
        passed_gate = total_cs >= self.cs_threshold

        return {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "chokepoint_score": total_cs,
            "cs_threshold": self.cs_threshold,
            "passed_gate": passed_gate,
            "node_scores": node_scores,
            "question_scores": scores_by_question,
            "adversarial_modifier": {
                "position_cap": adversarial.position_cap,
                "weight_multiplier": adversarial.weight_multiplier,
                "ar_check_required": adversarial.ar_check_required,
                "tags": adversarial.tags,
            },
            "evidence_count": len(evidence_list),
            "evidence_summary": [
                {"category": e.category, "tag": e.tag, "sentence": e.sentence}
                for e in evidence_list[:5]
            ],
        }

    def filter_universe(
        self,
        watchlist: List[Dict[str, str]],
        text_feeds: Dict[str, str],
        custom_scores_by_code: Optional[Dict[str, Dict[str, int]]] = None,
    ) -> Tuple[List[str], Dict[str, dict]]:
        """全池定性过滤：Watchlist Universe U_t -> Filter CS >= 12 -> Candidate Set C_t."""
        candidate_codes: List[str] = []
        filter_reports: Dict[str, dict] = {}

        for item in watchlist:
            code = item["code"]
            name = item.get("name", "")
            feed = text_feeds.get(code, "")
            c_scores = (custom_scores_by_code or {}).get(code)
            report = self.evaluate_chokepoint_score(code, name, feed, custom_scores=c_scores)
            filter_reports[code] = report

            if report["passed_gate"]:
                candidate_codes.append(code)

        return candidate_codes, filter_reports
