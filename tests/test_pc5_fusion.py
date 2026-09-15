# -*- coding: utf-8 -*-
"""tests/test_pc5_fusion.py - PC5Fusion单元测试"""

from __future__ import annotations

import pytest
import numpy as np
from src.graph.pc5_fusion import PC5Fusion


class TestPC5Fusion:
    """PC5Fusion单元测试"""
    
    def setup_method(self):
        self.fusion = PC5Fusion(enable_p2=False)
        self.pc5_vector = {
            "P1": 0.5,
            "P3": 0.6,
            "P4": 0.7,
            "P5": 0.2
        }
    
    def test_fuse_basic(self):
        """测试基础融合"""
        s0 = self.fusion.fuse(self.pc5_vector, horizon_days=5.0)
        assert -1.0 <= s0 <= 1.0, "S₀超出[-1, 1]范围"
    
    def test_fuse_horizon_decay(self):
        """测试时效衰减: horizon越大，S₀越小"""
        s0_1d = self.fusion.fuse(self.pc5_vector, horizon_days=1.0)
        s0_20d = self.fusion.fuse(self.pc5_vector, horizon_days=20.0)
        assert s0_20d < s0_1d, "时效衰减不成立"
    
    def test_fuse_zero_horizon(self):
        """测试horizon=0时没有衰减"""
        s0 = self.fusion.fuse(self.pc5_vector, horizon_days=0.0)
        assert -1.0 <= s0 <= 1.0
    
    def test_fuse_all_positive(self):
        """测试全正向量"""
        pc5 = {"P1": 1.0, "P3": 1.0, "P4": 1.0, "P5": 1.0}
        s0 = self.fusion.fuse(pc5, horizon_days=0.0)
        assert s0 > 0.0, "全正向量应得正分"
        assert s0 <= 1.0, "全正向量应<=1.0"
    
    def test_fuse_all_negative(self):
        """测试全负向量"""
        pc5 = {"P1": -1.0, "P3": -1.0, "P4": -1.0, "P5": -1.0}
        s0 = self.fusion.fuse(pc5, horizon_days=0.0)
        assert s0 < 0.0, "全负向量应得负分"
        assert s0 >= -1.0, "全负向量应>=-1.0"
    
    def test_fuse_mixed(self):
        """测试混合向量"""
        pc5 = {"P1": 0.5, "P3": -0.3, "P4": 0.7, "P5": -0.2}
        s0 = self.fusion.fuse(pc5, horizon_days=5.0)
        assert -1.0 <= s0 <= 1.0
    
    def test_fuse_empty_vector(self):
        """测试空向量"""
        s0 = self.fusion.fuse({}, horizon_days=5.0)
        assert s0 == 0.0, "空向量应得0.0"
    
    def test_fuse_unknown_dimension(self):
        """测试未知维度（应被忽略）"""
        pc5 = {"P1": 0.5, "P999": 1.0, "P3": 0.6, "P4": 0.7, "P5": 0.2}
        s0 = self.fusion.fuse(pc5, horizon_days=5.0)
        assert -1.0 <= s0 <= 1.0
    
    def test_breakdown_contains_s0(self):
        """测试维度明细包含s0_enhanced"""
        breakdown = self.fusion.fuse_with_dimension_breakdown(
            self.pc5_vector, horizon_days=5.0
        )
        assert "s0_enhanced" in breakdown
    
    def test_breakdown_sums_to_s0(self):
        """测试维度明细的和等于S₀"""
        breakdown = self.fusion.fuse_with_dimension_breakdown(
            self.pc5_vector, horizon_days=5.0
        )
        s0_direct = self.fusion.fuse(self.pc5_vector, horizon_days=5.0)
        assert abs(breakdown["s0_enhanced"] - s0_direct) < 1e-6
    
    def test_update_weights(self):
        """测试权重更新"""
        self.fusion.update_weights({"P3": 0.5})
        s0 = self.fusion.fuse(self.pc5_vector, horizon_days=5.0)
        assert -1.0 <= s0 <= 1.0
    
    def test_weights_sum_to_one(self):
        """测试权重和为1"""
        weights = self.fusion.get_weight_summary()["weights"]
        total = sum(weights.values())
        assert 0.99 <= total <= 1.01, f"权重和{total}不为1"
    
    def test_negative_half_life(self):
        """测试负半衰期（应自动修正）"""
        fusion = PC5Fusion(
            half_lives={"P1": -1, "P3": 10, "P4": 7, "P5": 60},
            enable_p2=False
        )
        s0 = fusion.fuse(self.pc5_vector, horizon_days=5.0)
        assert -1.0 <= s0 <= 1.0
    
    def test_extreme_weights(self):
        """测试极端权重"""
        fusion = PC5Fusion(
            weights={"P1": 1.0, "P3": 0.0, "P4": 0.0, "P5": 0.0},
            enable_p2=False
        )
        pc5 = {"P1": 0.8, "P3": -0.5, "P4": 0.3, "P5": 0.1}
        s0 = fusion.fuse(pc5, horizon_days=5.0)
        # P1权重=1, 其他=0, 所以S₀应该接近P1 * decay
        expected = 0.8 * np.exp(-np.log(2) * 5.0 / 90.0)  # P1半衰期90天
        assert abs(s0 - expected) < 0.01, f"S₀={s0} 预期={expected}"


class TestPC5FusionWithP2:
    """测试启用P2的融合器"""
    
    def test_fuse_with_p2(self):
        fusion = PC5Fusion(enable_p2=True)
        pc5 = {"P1": 0.5, "P2": 0.3, "P3": 0.6, "P4": 0.7, "P5": 0.2}
        s0 = fusion.fuse(pc5, horizon_days=5.0)
        assert -1.0 <= s0 <= 1.0
    
    def test_p2_weights(self):
        fusion = PC5Fusion(enable_p2=True)
        weights = fusion.get_weight_summary()["weights"]
        assert "P2" in weights, "P2应在权重中"
        assert abs(sum(weights.values()) - 1.0) < 0.01, "权重和应为1"


class TestPC5FusionMonteCarlo:
    """蒙特卡洛稳定性测试"""
    
    def test_random_vectors(self):
        fusion = PC5Fusion(enable_p2=False)
        
        np.random.seed(42)
        for _ in range(100):
            pc5 = {
                "P1": np.random.uniform(-1, 1),
                "P3": np.random.uniform(-1, 1),
                "P4": np.random.uniform(-1, 1),
                "P5": np.random.uniform(-1, 1)
            }
            s0 = fusion.fuse(pc5, horizon_days=np.random.uniform(0, 30))
            assert -1.0 <= s0 <= 1.0, f"随机向量S₀={s0}超出范围"
    
    def test_monotonic_decay(self):
        fusion = PC5Fusion(enable_p2=False)
        pc5 = {"P1": 0.6, "P3": 0.5, "P4": 0.4, "P5": 0.3}
        
        horizons = sorted(np.random.uniform(0, 60, 10))
        s0_values = [fusion.fuse(pc5, h) for h in horizons]
        
        # 检查单调递减
        for i in range(len(s0_values) - 1):
            assert s0_values[i] >= s0_values[i+1], f"非单调: h={horizons[i]}->{horizons[i+1]}"


# ========== 运行测试 ==========
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
