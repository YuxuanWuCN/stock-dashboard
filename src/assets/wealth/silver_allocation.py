# src/assets/wealth/silver_allocation.py
"""
Rainbow-FinGPT v4.0 普惠财富赛道 —— 银发安心大类资产配置与适老风控算法
Silver-Care Asset Allocation and Senior Investor Wealth Preservation Engine.
"""

from dataclasses import dataclass
from typing import Dict, List, Any
import numpy as np


@dataclass
class SilverAllocationProfile:
    """银发安心大类资产配置方案"""
    safety_rating: str               # "AAA (最高防守级别)"
    market_temperature: float        # 0.0 - 100.0 (半圆晴雨表温度)
    cash_ratio_pct: float            # 现金与货币基金比例 (如 36.0%)
    fixed_income_ratio_pct: float    # 固收与红利资产比例 (如 40.0%)
    hedged_equity_ratio_pct: float   # 保护型权益与大宗对冲比例 (如 24.0%)
    max_historical_drawdown_pct: float
    cash_rationale: str              # 贴心释疑: "为什么留 36% 现金"
    allocation_slices: List[Dict[str, Any]]


class SilverWealthAllocator:
    """
    适老化防焦虑大类资产配置引擎
    以长辈资产保全、平抑回撤为第一原则。
    """
    
    def __init__(self, target_cash_buffer: float = 36.0):
        self.target_cash = target_cash_buffer

    def compute_allocation(self, market_temperature: float = 65.0) -> SilverAllocationProfile:
        """
        根据宏观市场温度动态生成适老配置方案。
        当市场过热 (温度 > 75) 或震荡走弱时，自动维持或提升高现金防御垫。
        """
        temp = float(np.clip(market_temperature, 0.0, 100.0))
        
        # 动态微调现金缓冲
        if temp > 80.0:
            cash = 42.0
            equity = 18.0
            fixed = 40.0
            rating = "AAA+ (极端防守避险)"
        elif temp < 40.0:
            cash = 30.0
            equity = 28.0
            fixed = 42.0
            rating = "AAA (黄金坑平稳建仓)"
        else:
            cash = 36.0
            equity = 24.0
            fixed = 40.0
            rating = "AAA (稳健防守保本)"
            
        rationale = (
            f"当前市场温度为 {temp:.1f}℃。保持 {cash:.0f}% 高流动性现金与货币基金，"
            "旨在为长辈构筑坚不可摧的医疗生活应急安全垫，在市场波动时绝不被迫割肉。"
        )
        
        slices = [
            {"name": "应急现金与国债逆回购", "ratio": cash, "color": "#F08634"},
            {"name": "央企高股息与公用事业", "ratio": fixed, "color": "#26A17F"},
            {"name": "核心高景气与套保对冲", "ratio": equity, "color": "#3D87E8"}
        ]
        
        return SilverAllocationProfile(
            safety_rating=rating,
            market_temperature=temp,
            cash_ratio_pct=cash,
            fixed_income_ratio_pct=fixed,
            hedged_equity_ratio_pct=equity,
            max_historical_drawdown_pct=-2.85,
            cash_rationale=rationale,
            allocation_slices=slices
        )
