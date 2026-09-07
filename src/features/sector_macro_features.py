# -*- coding: utf-8 -*-
"""src/features/sector_macro_features.py - 板块共振和宏观周期特征提取器

从现有模块提取P4板块共振和P5宏观周期特征
"""

from __future__ import annotations

import logging
from typing import Dict, Optional
import numpy as np

logger = logging.getLogger("sector_macro_features")


def extract_p4_sector_resonance(
    ticker: str,
    date: str,
    sector_engine
) -> float:
    """提取P4: 板块共振强度得分
    
    从sector_graph_engine提取:
    1. 板块协同广度 (sector breadth)
    2. 涨停龙头加成
    3. 标的在板块内的相对强度
    
    参数:
        ticker: 股票代码
        date: 日期
        sector_engine: SectorGraphEngine实例
    
    返回:
        float: P4得分，范围 [-1.0, 1.0]
    """
    try:
        # 获取板块状态
        sector_state = sector_engine.get_sector_state_by_ticker(ticker, date)
        
        if not sector_state:
            logger.debug(f"{ticker} 无板块数据，返回中性值")
            return 0.0
        
        # 1. 板块协同广度 (0.5是中性，>0.7强势，<0.3弱势)
        breadth = sector_state.get("breadth", 0.5)
        breadth_score = (breadth - 0.5) * 2.0  # 映射到[-1, 1]
        
        # 2. 涨停龙头加成
        has_limit_up = sector_state.get("has_limit_up_leader", False)
        leader_boost = 0.4 if has_limit_up else 0.0
        
        # 3. 标的在板块内的相对强度 (0-1之间，越接近1排名越高)
        relative_strength = sector_state.get("ticker_relative_rank", 0.5)
        strength_score = (relative_strength - 0.5) * 0.6
        
        # 综合得分
        p4_score = breadth_score + leader_boost + strength_score
        
        logger.debug(
            f"{ticker} P4: breadth={breadth:.2f}, "
            f"limit_up={has_limit_up}, rank={relative_strength:.2f} -> {p4_score:.3f}"
        )
        
        return float(np.clip(p4_score, -1.0, 1.0))
        
    except Exception as e:
        logger.warning(f"{ticker} P4提取失败: {e}")
        return 0.0


def extract_p5_macro_cycle(
    date: str,
    market_state_engine
) -> float:
    """提取P5: 宏观周期因子得分
    
    从市场状态机提取:
    1. 市场阶段 (牛市/震荡/熊市)
    2. Trend Gate C浪阻断状态
    
    参数:
        date: 日期
        market_state_engine: 市场状态机实例
    
    返回:
        float: P5得分，范围 [-1.0, 1.0]
    """
    try:
        # 获取市场状态
        state = market_state_engine.get_current_state(date)
        
        # 市场阶段映射
        phase = state.get("phase", "neutral")
        phase_score_map = {
            "bull": 0.7,       # 牛市
            "neutral": 0.0,    # 震荡
            "bear": -0.7,      # 熊市
            "recovery": 0.4,   # 复苏
            "decline": -0.4    # 下跌
        }
        
        p5_score = phase_score_map.get(phase, 0.0)
        
        # C浪阻断惩罚 (如果触发，强制降为-1.0)
        if state.get("c_wave_blocked", False):
            p5_score = -1.0
            logger.info(f"P5: C浪阻断触发，强制降为-1.0")
        
        logger.debug(f"P5: phase={phase}, c_wave_blocked={state.get('c_wave_blocked', False)} -> {p5_score:.3f}")
        
        return float(p5_score)
        
    except Exception as e:
        logger.warning(f"P5提取失败: {e}")
        return 0.0


# ========== 单元测试 ==========
if __name__ == "__main__":
    # Mock对象
    class MockSectorEngine:
        def get_sector_state_by_ticker(self, ticker, date):
            return {
                "breadth": 0.75,
                "has_limit_up_leader": True,
                "ticker_relative_rank": 0.8
            }
    
    class MockMarketState:
        def get_current_state(self, date):
            return {
                "phase": "bull",
                "c_wave_blocked": False
            }
    
    # 测试P4
    p4 = extract_p4_sector_resonance(
        "000001.SZ",
        "2026-08-01",
        MockSectorEngine()
    )
    print(f"P4板块共振得分: {p4:.3f}")
    assert -1.0 <= p4 <= 1.0, "P4超出范围"
    
    # 测试P5
    p5 = extract_p5_macro_cycle(
        "2026-08-01",
        MockMarketState()
    )
    print(f"P5宏观周期得分: {p5:.3f}")
    assert -1.0 <= p5 <= 1.0, "P5超出范围"
    
    print("✅ 板块宏观特征提取器测试通过")
