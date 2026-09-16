# Agent 2 任务卡：算法工程师

## 角色定位
负责PC5向量与T-NALE的融合算法与数学公式验证

## 本周目标
设计并实现PC5-NALE融合引擎，完成数学理论推导

## 详细任务

### 任务1: PC5-NALE融合引擎
**文件**: `src/graph/pc5_nale_fusion.py`

核心算法：
```python
class PC5NALEFusion:
    def calculate_fused_score(
        self,
        pc5_vector: PC5Vector,
        nale_result: TemporalNALEResult,
        horizon_days: float,
        alpha_weights: Dict[str, float]
    ) -> FusedScore:
        """
        融合公式：
        S_final = w1*P1 + w2*P2*decay(t) + w3*P3*momentum(h) 
                + w4*P4*NALE_spillover + w5*P5*macro_state
        
        约束条件：
        - sum(wi) = 1.0
        - 所有wi ∈ [0, 1]
        - S_final ∈ [-1, 1]
        """
        pass
```

### 任务2: 滚动方向校准集成
修改 `src/pricing/rolling_direction_calibration.py`：

```python
def calibrate_pc5_direction(
    pc5_scores: List[float],
    actual_returns: List[float],
    window_days: int = 30
) -> CalibrationResult:
    """
    30天滚动窗口校准PC5因子方向
    返回：
    - direction: 1 (正向) 或 -1 (反向)
    - confidence: p-value from binomial test
    - should_reject: bool (是否拒绝预测)
    """
    pass
```

### 任务3: 数学推导文档
**文件**: `docs/pc5_nale_mathematics.md`

包含章节：
1. **问题定义** - PC5向量的数学形式化
2. **融合算子** - 加权平均与动态调整
3. **时效性机制** - 衰减核与半衰期推导
4. **定理与证明**
   - 定理1: 融合评分的有界性
   - 定理2: 时效性衰减的单调性
   - 定理3: 方向校准的统计显著性条件

## 验收清单
- [ ] 融合算子通过边界测试（空值、极值、NaN）
- [ ] 数值稳定性测试：10000次蒙特卡洛模拟
- [ ] 代码注释包含LaTeX公式
- [ ] 数学文档至少5页，3个定理
- [ ] 与Agent 1的接口联调通过

## 技术提示
- 参考 `src/graph/temporal_nale.py` 的gaussian_impulse_kernel
- 使用 `scipy.stats.binom_test` 进行显著性检验
- 权重优化可用网格搜索或贝叶斯优化

## 时间安排
- Day 1-2: 融合算子原型
- Day 3: 滚动校准集成
- Day 4: 数学文档撰写

## 协作接口
- 从Agent 1接收：PC5Vector
- 向Agent 3提供：评分计算API
- 向Agent 4提供：算法复杂度分析
