# Agent 3 任务卡：回测验证专家

## 角色定位
负责设计并执行全方位回测实验矩阵

## 本周目标
完成60个回测实验，生成综合性能报告

## 详细任务

### 任务1: 回测实验矩阵设计
**文件**: `scripts/run_pc5_backtest_matrix.py`

实验维度：
- **板块** (3): 存储超级周期、黄金、新能源
- **时间窗口** (4): 2025Q2-Q3, Q3-Q4, 2026Q1-Q2, Q2-Q3  
- **参数组合** (5):
  - alpha=[0.3, 0.4, 0.5]
  - half_life=[7, 14, 21]天
  - weight_schemes=["equal", "momentum_heavy", "sector_heavy"]

总计：3 × 4 × 5 = 60个实验

### 任务2: 关键指标追踪
每个回测输出：
```python
@dataclass
class BacktestMetrics:
    # 准确性
    hit_rate_1d: float
    hit_rate_5d: float
    hit_rate_20d: float
    coverage_rate: float  # 拒绝预测后的覆盖率
    
    # 稳定性
    hit_rate_first_half: float
    hit_rate_second_half: float
    temporal_stability_score: float  # |first - second|
    
    # 收益性
    sharpe_ratio: float
    max_drawdown: float
    calmar_ratio: float
    cumulative_return: float
    
    # 统计显著性
    t_test_pvalue: float
    mann_whitney_pvalue: float
```

### 任务3: 基准对比
实现3个基线：
1. **Baseline_NALE**: 原T-NALE（无PC5）
2. **Baseline_Static**: 静态因子评分
3. **Baseline_Random**: 蒙特卡洛随机策略（1000次）

### 任务4: 自动化报告生成
**输出**: `reports/pc5_backtest_comprehensive.md`

包含：
- 执行摘要（最佳配置 + 改进幅度）
- 性能对比表（所有60个实验）
- 可视化曲线图（净值、回撤、命中率演化）
- 统计检验结果
- 失败案例分析

## 验收清单
- [ ] 60个回测全部完成，无crash
- [ ] 每个实验有独立日志文件
- [ ] 性能对比表按夏普比率排序
- [ ] 至少3个配置显著优于基线 (p < 0.05)
- [ ] 诚实记录所有失败案例

## 技术提示
- 复用 `src/strategies/backtest_engine.py`
- 参考 `scripts/run_all_backtests_matrix.py` 的并行执行
- 使用 `tqdm` 显示进度条
- 保存中间结果防止断点重跑

## 时间安排
- Day 1: 实验设计 + 代码框架
- Day 2-3: 第一批20个回测
- Day 4-5: 第二批20个 + 第三批20个
- Day 6: 报告生成 + 可视化

## 协作接口
- 从Agent 1获取：特征数据
- 从Agent 2获取：评分API
- 向Agent 4提供：测试用例
