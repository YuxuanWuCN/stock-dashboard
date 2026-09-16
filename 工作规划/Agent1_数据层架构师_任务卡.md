# Agent 1 任务卡：数据层架构师

## 角色定位
负责PC5向量的数据采集、特征工程和存储设计

## 本周目标
构建五维时效复合向量(PC5-Temporal)的数据基础设施

## 详细任务

### 任务1: 特征提取模块开发
**文件**: `src/features/pc5_temporal_features.py`

实现5个维度的特征计算：
1. **P1_fundamental_stability()** - 基本面稳健性
2. **P2_sentiment_propagation()** - 市场情绪传导  
3. **P3_technical_momentum()** - 技术动量时效
4. **P4_sector_resonance()** - 板块共振强度
5. **P5_macro_cycle()** - 宏观周期因子

每个函数签名：
```python
def P1_fundamental_stability(code: str, date: str) -> float:
    """计算基本面稳健性评分 [-1.0, 1.0]"""
    pass
```

### 任务2: 时效性衰减内核
**文件**: `src/features/temporal_decay.py`

```python
class TemporalDecayKernel:
    def exponential_decay(self, age_days: float, half_life: float) -> float:
        """指数半衰期衰减"""
        
    def gaussian_decay(self, age_days: float, peak_days: float, sigma: float) -> float:
        """高斯型衰减"""
        
    def multi_scale_decay(self, age_days: float, horizons: List[float]) -> Dict[str, float]:
        """多尺度衰减（1日/5日/20日）"""
```

### 任务3: 数据持久化
设计JSON schema：
```json
{
  "code": "001309",
  "date": "2026-09-06",
  "pc5_vector": {
    "P1": 0.65,
    "P2": 0.42,
    "P3": 0.78,
    "P4": 0.85,
    "P5": 0.53
  },
  "metadata": {
    "version": "1.0",
    "timestamp": "2026-09-06T10:30:00Z",
    "data_sources": ["tushare", "eastmoney", "llm_news"]
  }
}
```

## 验收清单
- [ ] `tests/test_pc5_features.py` 覆盖率 ≥ 90%
- [ ] 生成50只股票的PC5向量样本
- [ ] 特征值范围检查：所有值在 [-1, 1] 区间
- [ ] 缺失值处理：文档说明3种策略
- [ ] 文档：`docs/pc5_features_spec.md` 完成

## 技术提示
- 复用 `src/graph/temporal_nale.py` 的衰减函数
- 对接 `src/data_loader.py` 获取行情数据
- 参考 `src/analysis/scoringv3.py` 的评分归一化方法

## 时间安排
- Day 1: 完成P1-P3特征
- Day 2: 完成P4-P5 + 衰减内核
- Day 3: 数据持久化 + 单元测试

## 协作接口
- 向Agent 2提供：`PC5Vector` dataclass
- 向Agent 3提供：批量特征计算接口
- 向Agent 4提供：测试夹具数据
