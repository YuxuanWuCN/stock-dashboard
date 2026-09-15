# -*- coding: utf-8 -*-
"""src/graph/pc5_fusion.py - PC5五维融合算子

将P1-P5五维特征融合为增强版S₀（原生事实得分）
替代原来的GFCA.composite_score

核心公式:
    S_0_enhanced = Σ w_i * P_i * decay_i(horizon_days)
    
    其中:
    - w_i: 每维权重 (sum = 1.0)
    - P_i: 第i维得分 [-1, 1]
    - decay_i(t) = exp(-ln2 * t / half_life_i): 指数半衰期衰减
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger("pc5_fusion")

# 默认配置
DEFAULT_WEIGHTS = {
    "P1": 0.25,   # 基本面 (权重最高，因为时效最慢)
    "P2": 0.10,   # 情绪 (权重最低，需要评估LLM质量)
    "P3": 0.30,   # 动量 (权重最高，A股动量效应明显)
    "P4": 0.25,   # 板块共振 (权重高，涨停溢出效应强)
    "P5": 0.10    # 宏观周期 (权重低，变化慢)
}

DEFAULT_HALF_LIVES = {
    "P1": 90,     # 基本面: 3个月半衰期
    "P2": 3,      # 情绪: 3天半衰期
    "P3": 10,     # 动量: 10天半衰期
    "P4": 7,      # 板块共振: 7天半衰期
    "P5": 60      # 宏观周期: 2个月半衰期
}

ALL_DIMS = ["P1", "P2", "P3", "P4", "P5"]


class PC5Fusion:
    """PC5五维融合算子"""
    
    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        half_lives: Optional[Dict[str, float]] = None,
        enable_p2: bool = True
    ):
        """
        参数:
            weights: 每维权重，默认None使用DEFAULT_WEIGHTS
            half_lives: 每维半衰期(天)，默认None使用DEFAULT_HALF_LIVES
            enable_p2: 是否启用P2情绪维度 (如果LLM API不可用则关闭)
        """
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        self.half_lives = half_lives or DEFAULT_HALF_LIVES.copy()
        self.enable_p2 = enable_p2
        
        # 如果P2关闭，权重重新分配
        if not enable_p2:
            self.weights.pop("P2", None)
            self.half_lives.pop("P2", None)
            self._rebalance_weights()
        
        # 验证权重
        self._validate()
    
    def fuse(self, pc5_vector: Dict[str, float], horizon_days: float = 5.0) -> float:
        """融合五维向量为增强版S₀
        
        参数:
            pc5_vector: 五维得分字典，如 {"P1": 0.5, "P3": 0.3, ...}
            horizon_days: 预测视界天数（默认5天）
        
        返回:
            float: 增强版S₀，范围[-1.0, 1.0]
        """
        s0_enhanced = 0.0
        
        for dim, value in pc5_vector.items():
            if dim not in self.weights:
                continue
            
            weight = self.weights[dim]
            half_life = self.half_lives.get(dim, 30.0)
            
            # 计算时效衰减
            decay = self._exponential_decay(horizon_days, half_life)
            
            s0_enhanced += weight * value * decay
        
        return float(np.clip(s0_enhanced, -1.0, 1.0))
    
    def fuse_with_dimension_breakdown(
        self,
        pc5_vector: Dict[str, float],
        horizon_days: float = 5.0
    ) -> Dict[str, float]:
        """融合并返回各维度贡献明细（用于诊断和可视化）
        
        返回:
            dict: {
                "weighted_P1": 0.12,
                "weighted_P2": 0.03,
                "weighted_P3": 0.15,
                "weighted_P4": 0.10,
                "weighted_P5": 0.02,
                "s0_enhanced": 0.42,
                "decay_P1": 0.96,
                "decay_P3": 0.71,
                ...
            }
        """
        result = {}
        s0 = 0.0
        
        for dim, value in pc5_vector.items():
            if dim not in self.weights:
                continue
            
            weight = self.weights[dim]
            half_life = self.half_lives.get(dim, 30.0)
            decay = self._exponential_decay(horizon_days, half_life)
            
            weighted = weight * value * decay
            s0 += weighted
            
            result[f"weighted_{dim}"] = round(weighted, 4)
            result[f"decay_{dim}"] = round(decay, 4)
        
        result["s0_enhanced"] = float(np.clip(s0, -1.0, 1.0))
        return result
    
    def update_weights(self, new_weights: Dict[str, float]):
        """动态更新权重"""
        self.weights.update(new_weights)
        self._rebalance_weights()
        self._validate()
    
    def get_weight_summary(self) -> Dict[str, float]:
        """返回当前权重和半衰期"""
        return {
            "weights": self.weights.copy(),
            "half_lives": self.half_lives.copy()
        }
    
    # ========== 内部方法 ==========
    
    def _exponential_decay(self, t: float, half_life: float) -> float:
        """指数半衰期衰减
        
        公式: decay(t) = exp(-ln(2) * t / half_life)
        
        当 t = half_life 时，衰减到50%
        当 t = 0 时，衰减到100%
        """
        if half_life <= 0 or t <= 0:
            return 1.0
        return float(np.exp(-np.log(2) * t / half_life))
    
    def _rebalance_weights(self):
        """重新平衡权重（确保和为1.0）"""
        total = sum(self.weights.values())
        if total > 0:
            for dim in self.weights:
                self.weights[dim] /= total
    
    def _validate(self):
        """验证配置"""
        total = sum(self.weights.values())
        if not (0.99 <= total <= 1.01):
            logger.warning(f"权重之和为{total:.3f}，不等于1.0，自动重平衡")
            self._rebalance_weights()
        
        for dim, hl in self.half_lives.items():
            if hl <= 0:
                logger.warning(f"{dim}半衰期{hl}<=0，重置为30天")
                self.half_lives[dim] = 30.0


class PC5Extractor:
    """PC5五维特征提取器
    
    整合CSMAR、板块引擎、市场状态机等多个数据源
    """
    
    def __init__(
        self,
        csmar_extractor,
        sector_engine,
        market_state_engine,
        llm_sentiment_api=None
    ):
        """
        参数:
            csmar_extractor: CSMARFeatureExtractor实例
            sector_engine: SectorGraphEngine实例
            market_state_engine: 市场状态机实例
            llm_sentiment_api: LLM情绪API (可选)
        """
        self.csmar = csmar_extractor
        self.sector_engine = sector_engine
        self.market_state = market_state_engine
        self.llm_api = llm_sentiment_api
    
    def extract(
        self,
        ticker: str,
        date: str,
        horizon_days: float = 5.0
    ) -> Dict[str, float]:
        """提取五维向量
        
        参数:
            ticker: 股票代码
            date: 日期
            horizon_days: 预测视界（用于P2/P3的衰减）
        
        返回:
            dict: {"P1": 0.5, "P2": 0.0, "P3": 0.3, "P4": 0.6, "P5": 0.1}
        """
        pc5 = {}
        
        # P1: 基本面 (从CSMAR)
        pc5["P1"] = self.csmar.extract_p1_fundamental(ticker, date)
        
        # P2: 情绪 (如果LLM API可用)
        if self.llm_api:
            pc5["P2"] = self._extract_p2_sentiment(ticker, date, horizon_days)
        else:
            pc5["P2"] = 0.0
        
        # P3: 动量 (从CSMAR)
        pc5["P3"] = self.csmar.extract_p3_momentum(ticker, date)
        
        # P4: 板块共振
        from src.features.sector_macro_features import extract_p4_sector_resonance
        pc5["P4"] = extract_p4_sector_resonance(ticker, date, self.sector_engine)
        
        # P5: 宏观周期
        from src.features.sector_macro_features import extract_p5_macro_cycle
        pc5["P5"] = extract_p5_macro_cycle(date, self.market_state)
        
        return pc5
    
    def _extract_p2_sentiment(
        self,
        ticker: str,
        date: str,
        horizon_days: float
    ) -> float:
        """提取P2: 情绪传导得分"""
        try:
            # TODO: 替换为实际LLM API调用
            # sentiment = self.llm_api.analyze_sentiment(ticker, date)
            
            # 临时mock
            sentiment = 0.2
            
            # 情绪时效衰减最快
            decay = np.exp(-np.log(2) * horizon_days / 3.0)  # 3天半衰期
            
            return float(np.clip(sentiment * decay, -1.0, 1.0))
            
        except Exception as e:
            logger.warning(f"{ticker} P2提取失败: {e}")
            return 0.0


# ========== 单元测试 ==========
if __name__ == "__main__":
    # 测试1: 基础融合
    fusion = PC5Fusion()
    pc5 = {"P1": 0.5, "P2": 0.3, "P3": 0.6, "P4": 0.7, "P5": 0.2}
    
    s0 = fusion.fuse(pc5, horizon_days=5.0)
    print(f"测试1 - 基础融合: S₀ = {s0:.4f}")
    assert -1.0 <= s0 <= 1.0, "S₀超出范围"
    
    # 测试2: 时效衰减 (horizon越大，S₀应该越小)
    s0_1d = fusion.fuse(pc5, horizon_days=1.0)
    s0_20d = fusion.fuse(pc5, horizon_days=20.0)
    print(f"测试2 - 时效衰减: 1d={s0_1d:.4f}, 20d={s0_20d:.4f}, 衰减={s0_20d/s0_1d:.2f}")
    assert s0_20d < s0_1d, "时效衰减不成立"
    
    # 测试3: 维度明细
    breakdown = fusion.fuse_with_dimension_breakdown(pc5, horizon_days=5.0)
    print(f"测试3 - 维度明细: {breakdown}")
    assert "s0_enhanced" in breakdown
    
    # 测试4: 边界值
    pc5_extreme = {"P1": 1.0, "P2": 1.0, "P3": 1.0, "P4": 1.0, "P5": 1.0}
    s0_max = fusion.fuse(pc5_extreme, horizon_days=0.0)
    print(f"测试4 - 边界值(全1): S₀ = {s0_max:.4f}")
    assert s0_max <= 1.0, "最大值超出范围"
    
    pc5_extreme_neg = {"P1": -1.0, "P2": -1.0, "P3": -1.0, "P4": -1.0, "P5": -1.0}
    s0_min = fusion.fuse(pc5_extreme_neg, horizon_days=0.0)
    print(f"测试4 - 边界值(全-1): S₀ = {s0_min:.4f}")
    assert s0_min >= -1.0, "最小值超出范围"
    
    # 测试5: P2关闭
    fusion_no_p2 = PC5Fusion(enable_p2=False)
    s0_no_p2 = fusion_no_p2.fuse(pc5, horizon_days=5.0)
    print(f"测试5 - 关闭P2: S₀ = {s0_no_p2:.4f}")
    # 权重应该和为1.0
    weights = fusion_no_p2.get_weight_summary()
    total = sum(weights["weights"].values())
    print(f"  权重和: {total:.4f}")
    assert 0.99 <= total <= 1.01, "权重和不为1"
    
    print("\n✅ PC5Fusion所有测试通过!")
