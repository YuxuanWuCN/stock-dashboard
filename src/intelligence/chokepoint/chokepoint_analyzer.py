# src/intelligence/chokepoint/chokepoint_analyzer.py
"""
Rainbow-FinGPT v4.0 供应链瓶颈 (Chokepoint) 因果拓扑分析引擎
Inherited and refined from Serenity Chokepoint Investing Framework (v2.1).

核心功能:
1. 供应链工艺增值节点瓶颈评分 (Chokepoint Bottleneck Score, 0-100)
2. 瓶颈四大维度诊断:
   - 工艺节点稀缺性与壁垒 (Node Scarcity & Barrier)
   - 估值偏差与预期差 (Mispricing Gap)
   - 催化剂与资本开支周期 (Catalyst & Capex Cycle)
   - 流动性与上市标的敞口 (Listed Exposure & Liquidity)
3. 结构化命题对接: 生成满足 ADR-0001 规范的 QualitativeProposition 实体
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import numpy as np

from src.intelligence.two_layer_engine import QualitativeProposition


@dataclass
class ChokepointProfile:
    """供应链节点瓶颈评估档案"""
    node_id: str
    node_name: str
    sector: str
    scarcity_score: float      # 0 - 100: 技术专利壁垒、设备替换周期、集中度
    pricing_gap_score: float   # 0 - 100: 市场预期差、盈利上修空间
    catalyst_score: float      # 0 - 100: 行业扩产、限产政策、涨价传导
    liquidity_score: float     # 0 - 100: 股票/期货成交活跃度
    listed_symbols: List[str]  # 对应标的 (如 ['688041', '688012'] 或 ['000683', 'SA0'])
    is_bottleneck: bool = False
    overall_quality_score: float = 0.0


class ChokepointAnalyzer:
    """
    供应链卡脖子瓶颈拓扑分析器
    """
    
    def __init__(self, bottleneck_threshold: float = 65.0):
        self.threshold = bottleneck_threshold

    def evaluate_node(
        self,
        node_id: str,
        node_name: str,
        sector: str,
        scarcity: float,
        pricing_gap: float,
        catalyst: float,
        liquidity: float,
        symbols: List[str]
    ) -> ChokepointProfile:
        """
        评估单一供应链节点的瓶颈质量得分。
        加权模型:
        - 稀缺性壁垒 40%
        - 催化剂驱动 25%
        - 预期差估值 20%
        - 标的流动性 15%
        """
        scarcity = float(np.clip(scarcity, 0.0, 100.0))
        pricing_gap = float(np.clip(pricing_gap, 0.0, 100.0))
        catalyst = float(np.clip(catalyst, 0.0, 100.0))
        liquidity = float(np.clip(liquidity, 0.0, 100.0))
        
        overall = (
            0.40 * scarcity +
            0.25 * catalyst +
            0.20 * pricing_gap +
            0.15 * liquidity
        )
        
        is_bn = bool(overall >= self.threshold and scarcity >= 60.0)
        
        return ChokepointProfile(
            node_id=node_id,
            node_name=node_name,
            sector=sector,
            scarcity_score=scarcity,
            pricing_gap_score=pricing_gap,
            catalyst_score=catalyst,
            liquidity_score=liquidity,
            listed_symbols=symbols,
            is_bottleneck=is_bn,
            overall_quality_score=round(overall, 2)
        )

    def generate_qualitative_proposition(
        self,
        profile: ChokepointProfile,
        target_symbol: str,
        evidence_fact: str
    ) -> QualitativeProposition:
        """
        生成对接 ADR-0001 两层解耦代码门禁的定性命题。
        自动注入强制 [FACT] 标签，严禁生成数值 Alpha。
        """
        direction = "LONG" if profile.is_bottleneck else "NEUTRAL"
        prop_id = f"PROP_{profile.node_id}_{target_symbol}"
        
        tags = [
            f"[FACT] {evidence_fact}",
            f"[INFERENCE] 瓶颈综合评级得分 {profile.overall_quality_score:.1f}, 稀缺性壁垒 {profile.scarcity_score:.1f}",
            f"[OPINION] 节点处于高景气扩张/涨价传导周期"
        ]
        
        return QualitativeProposition(
            proposition_id=prop_id,
            symbol=target_symbol,
            node_id=profile.node_id,
            driver_logic=f"{profile.node_name} 供应链高壁垒瓶颈驱动",
            direction=direction,
            evidence_tags=tags,
            source_title="Serenity Chokepoint Quantitative Topology Engine",
            target_commodities=profile.listed_symbols
        )
