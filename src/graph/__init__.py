# -*- coding: utf-8 -*-
"""src/graph package —— 拓扑图谱、产业链网络与时空连续图扩散引擎 (T-NALE)"""

from src.graph.sector_graph_engine import SectorGraphEngine, SectorGraphState, SectorPeer
from src.graph.supply_chain_graph import SupplyChainGraph, EdgeLink
from src.graph.temporal_constants import (
    SupplyChainLagConfig,
    InformationHalfLifeConfig,
    INFORMATION_HALF_LIVES,
    INDUSTRY_LAG_PRIORS,
    get_supply_chain_lag,
    get_half_life,
)
from src.graph.temporal_nale import (
    TemporalNALEEngine,
    TemporalNALEResult,
    TrajectoryResult,
)

__all__ = [
    "SectorGraphEngine",
    "SectorGraphState",
    "SectorPeer",
    "SupplyChainGraph",
    "EdgeLink",
    "SupplyChainLagConfig",
    "InformationHalfLifeConfig",
    "INFORMATION_HALF_LIVES",
    "INDUSTRY_LAG_PRIORS",
    "get_supply_chain_lag",
    "get_half_life",
    "TemporalNALEEngine",
    "TemporalNALEResult",
    "TrajectoryResult",
]
