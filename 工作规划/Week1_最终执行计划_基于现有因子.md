# Week 1 最终执行计划：PC5时效增强（基于现有因子数据）

## 🎯 目标
从现有因子矩阵 → PCA降维 → 提取PC5 → 加时效性 → 验证IC提升

**不涉及768维embedding**，先小规模验证方法论。

---

## 📊 数据来源

从你的现有数据文件：
```
data/raw/backtest_storage_2025q2_2026q3/factors.csv
data/raw/backtest_gold_2025q3_2026q8/factors.csv
data/raw/backtest_green_2025q3_2026q3/factors.csv
```

这些文件应该包含：
- 行：交易日期
- 列：因子（MKT, SMB, HML, MOM, Quality, Growth等）
- 值：各股票在各因子上的得分

---

## 👥 任务分配

### Day 1（今天）：数据准备

**IMIS数据 + 你**：

创建 `scripts/day1_prepare_factor_data.py`：

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Day 1: 准备因子数据用于PCA"""

import pandas as pd
from pathlib import Path

# 1. 加载现有因子数据
# 选择一个板块的回测数据（建议用存储板块，数据最新）
factors_df = pd.read_csv(
    "data/raw/backtest_storage_2025q2_2026q3/factors.csv",
    index_col=0,
    parse_dates=True
)

print(f"因子矩阵形状: {factors_df.shape}")
print(f"列名: {list(factors_df.columns)}")
print(f"日期范围: {factors_df.index.min()} 到 {factors_df.index.max()}")
print(f"\n前5行:\n{factors_df.head()}")

# 2. 数据清洗
# 删除缺失值过多的列
missing_ratio = factors_df.isnull().sum() / len(factors_df)
valid_cols = missing_ratio[missing_ratio < 0.2].index  # 保留缺失<20%的列
factors_clean = factors_df[valid_cols].copy()

# 填充剩余缺失值（用前值填充）
factors_clean = factors_clean.fillna(method='ffill').fillna(0)

print(f"\n清洗后形状: {factors_clean.shape}")
print(f"保留的因子: {list(factors_clean.columns)}")

# 3. 保存
output_dir = Path("data/week1_pca")
output_dir.mkdir(exist_ok=True, parents=True)

factors_clean.to_csv(output_dir / "factors_for_pca.csv")
print(f"\n✅ 已保存到: {output_dir / 'factors_for_pca.csv'}")

# 4. 基础统计
stats = factors_clean.describe()
stats.to_csv(output_dir / "factors_stats.csv")
print(f"\n因子统计:\n{stats}")
```

**验收**：
- [ ] `data/week1_pca/factors_for_pca.csv` 生成
- [ ] 确认因子数量 ≥ 5个
- [ ] 确认日期数量 ≥ 60天

---

### Day 2：PCA降维

**CS成员**：

创建 `scripts/day2_pca_extraction.py`：

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Day 2: PCA降维并提取PC5"""

import pandas as pd
import numpy as np
from pathlib import Path
from src.pricing.factor_orthogonalization import pca_factor_reduction

# 1. 加载因子数据
factors_df = pd.read_csv(
    "data/week1_pca/factors_for_pca.csv",
    index_col=0,
    parse_dates=True
)

print(f"输入因子矩阵: {factors_df.shape}")

# 2. PCA降维
# 提取10个主成分（如果因子数<10，则提取全部）
n_components = min(10, factors_df.shape[1])

pcs_df, loadings_df = pca_factor_reduction(
    factors_df,
    n_components=n_components,
    standardize=True,
    return_loadings=True
)

print(f"\n主成分矩阵: {pcs_df.shape}")
print(f"主成分列名: {list(pcs_df.columns)}")

# 3. 提取PC5（第5主成分）
if "PC5" in pcs_df.columns:
    pc5_series = pcs_df["PC5"]
    print(f"\n✅ PC5提取成功")
else:
    print(f"⚠️ 因子数不足10个，使用最后一个主成分")
    pc5_series = pcs_df.iloc[:, -1]
    pc5_series.name = "PC5"

# 4. 分析PC5的特性
print(f"\nPC5统计:")
print(f"  均值: {pc5_series.mean():.4f}")
print(f"  标准差: {pc5_series.std():.4f}")
print(f"  最小值: {pc5_series.min():.4f}")
print(f"  最大值: {pc5_series.max():.4f}")

# 5. 查看PC5的因子构成（载荷）
if "PC5" in loadings_df.columns:
    pc5_loadings = loadings_df["PC5"].sort_values(ascending=False)
    print(f"\nPC5的因子载荷（前5名）:")
    print(pc5_loadings.head())

# 6. 保存
output_dir = Path("data/week1_pca")
pc5_series.to_csv(output_dir / "pc5_raw.csv", header=True)
pcs_df.to_csv(output_dir / "all_pcs.csv")
loadings_df.to_csv(output_dir / "pca_loadings.csv")

print(f"\n✅ 已保存:")
print(f"  - PC5原始序列: {output_dir / 'pc5_raw.csv'}")
print(f"  - 所有主成分: {output_dir / 'all_pcs.csv'}")
print(f"  - 因子载荷: {output_dir / 'pca_loadings.csv'}")
```

**验收**：
- [ ] `data/week1_pca/pc5_raw.csv` 生成
- [ ] PC5均值接近0，标准差接近1
- [ ] 查看因子载荷，理解PC5的金融含义

---

### Day 3：PC5时效增强算法

**CS成员**：

创建 `src/pricing/pc5_temporal_enhancement.py`：

```python
# -*- coding: utf-8 -*-
"""src/pricing/pc5_temporal_enhancement.py - PC5时效增强器"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from typing import Optional

logger = logging.getLogger("pc5_temporal")


class PC5TemporalEnhancer:
    """PC5时效增强器
    
    公式:
        PC5_temporal = w1*衰减项 + w2*动量项 + w3*状态调节
        
    其中:
        衰减项 = PC5_raw * exp(-ln2 * age / half_life)
        动量项 = PC5_raw - EMA_20d(PC5)
        状态调节 = 基于波动率的政权识别
    """
    
    def __init__(
        self,
        half_life_days: float = 14.0,
        momentum_weight: float = 0.3,
        decay_weight: float = 0.6,
        regime_weight: float = 0.1
    ):
        """
        参数:
            half_life_days: 半衰期（天）
            momentum_weight: 动量项权重
            decay_weight: 衰减项权重
            regime_weight: 状态调节权重
        """
        self.half_life = half_life_days
        self.w_momentum = momentum_weight
        self.w_decay = decay_weight
        self.w_regime = regime_weight
        
        # 历史序列（用于计算EMA和波动率）
        self.history = pd.Series(dtype=float)
    
    def enhance(
        self,
        pc5_raw: float,
        current_date: pd.Timestamp,
        age_days: float = 0.0
    ) -> float:
        """增强PC5
        
        参数:
            pc5_raw: 原始PC5得分
            current_date: 当前日期
            age_days: 信息年龄（天），默认0
        
        返回:
            pc5_temporal: 时效增强后的PC5
        """
        # 1. 衰减项（信息年龄衰减）
        decay = np.exp(-np.log(2) * age_days / self.half_life)
        pc5_decayed = pc5_raw * decay
        
        # 2. 动量项（短期偏离）
        ema_20d = self._get_ema(current_date, span=20)
        if ema_20d is not None:
            pc5_momentum = pc5_raw - ema_20d
        else:
            pc5_momentum = 0.0
        
        # 3. 状态调节（波动率政权）
        volatility = self._get_volatility(current_date, window=20)
        if volatility > 1.5:  # 高波动期
            regime_factor = 0.7  # 降低权重
        else:
            regime_factor = 1.0
        
        # 4. 加权组合
        pc5_temporal = (
            self.w_decay * pc5_decayed * regime_factor +
            self.w_momentum * pc5_momentum
        )
        
        # 5. 记录历史
        self.history[current_date] = pc5_raw
        
        return pc5_temporal
    
    def enhance_series(
        self,
        pc5_series: pd.Series,
        age_series: Optional[pd.Series] = None
    ) -> pd.Series:
        """批量增强PC5序列
        
        参数:
            pc5_series: PC5原始序列（index为日期）
            age_series: 信息年龄序列（可选）
        
        返回:
            pc5_temporal_series: 增强后的序列
        """
        if age_series is None:
            age_series = pd.Series(0.0, index=pc5_series.index)
        
        results = []
        for date in pc5_series.index:
            pc5_t = self.enhance(
                pc5_raw=pc5_series[date],
                current_date=date,
                age_days=age_series[date]
            )
            results.append(pc5_t)
        
        return pd.Series(results, index=pc5_series.index, name="PC5_temporal")
    
    def _get_ema(self, date: pd.Timestamp, span: int = 20) -> Optional[float]:
        """计算指数移动平均"""
        recent = self.history[self.history.index < date].tail(span)
        if len(recent) < 5:
            return None
        return recent.ewm(span=span, adjust=False).mean().iloc[-1]
    
    def _get_volatility(self, date: pd.Timestamp, window: int = 20) -> float:
        """计算滚动波动率"""
        recent = self.history[self.history.index < date].tail(window)
        if len(recent) < 5:
            return 1.0
        return recent.std()


# ========== 测试代码 ==========
if __name__ == "__main__":
    # 测试
    import matplotlib.pyplot as plt
    
    # 加载PC5原始数据
    pc5_raw = pd.read_csv(
        "data/week1_pca/pc5_raw.csv",
        index_col=0,
        parse_dates=True
    ).squeeze()
    
    print(f"PC5原始序列: {pc5_raw.shape}")
    
    # 创建增强器
    enhancer = PC5TemporalEnhancer(
        half_life_days=14.0,
        momentum_weight=0.3,
        decay_weight=0.6
    )
    
    # 增强
    pc5_temporal = enhancer.enhance_series(pc5_raw)
    
    # 对比
    comparison_df = pd.DataFrame({
        "PC5_raw": pc5_raw,
        "PC5_temporal": pc5_temporal
    })
    
    print(f"\n对比统计:")
    print(comparison_df.describe())
    
    # 保存
    comparison_df.to_csv("data/week1_pca/pc5_comparison.csv")
    print(f"\n✅ 已保存: data/week1_pca/pc5_comparison.csv")
    
    # 可视化
    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    
    # 子图1：原始 vs 增强
    axes[0].plot(pc5_raw.index, pc5_raw, label="PC5_raw", alpha=0.7)
    axes[0].plot(pc5_temporal.index, pc5_temporal, label="PC5_temporal", alpha=0.7)
    axes[0].legend()
    axes[0].set_title("PC5: Raw vs Temporal")
    axes[0].grid(True, alpha=0.3)
    
    # 子图2：差异
    diff = pc5_temporal - pc5_raw
    axes[1].plot(diff.index, diff, label="Temporal - Raw", color="green")
    axes[1].axhline(0, color="black", linestyle="--", linewidth=0.5)
    axes[1].legend()
    axes[1].set_title("Difference")
    axes[1].grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig("data/week1_pca/pc5_comparison.png", dpi=150)
    print(f"✅ 已保存: data/week1_pca/pc5_comparison.png")
```

**验收**：
- [ ] `data/week1_pca/pc5_comparison.csv` 生成
- [ ] 可视化图显示PC5_temporal跟踪PC5_raw但有差异
- [ ] 单元测试通过

---

### Day 4：集成到评分系统（可选）

**你**：

如果时间充足，可以尝试将PC5_temporal集成到 `build_ranking.py`：

```python
# 在 build_ranking.py 中添加

from src.pricing.pc5_temporal_enhancement import PC5TemporalEnhancer

# 初始化增强器
pc5_enhancer = PC5TemporalEnhancer(half_life_days=14.0)

# 在评分时使用
pc5_temporal_score = pc5_enhancer.enhance(
    pc5_raw=某个因子得分,  # 需要确定用哪个
    current_date=当前日期,
    age_days=0
)
```

---

### Day 5：验证与决策 🚨

**你（主力）**：

创建 `scripts/day5_validate_ic.py`：

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Day 5: 验证PC5时效增强的有效性"""

import pandas as pd
import numpy as np
from scipy.stats import spearmanr
from pathlib import Path

print("="*60)
print("PC5时效增强验证")
print("="*60)

# 1. 加载PC5对比数据
pc5_df = pd.read_csv(
    "data/week1_pca/pc5_comparison.csv",
    index_col=0,
    parse_dates=True
)

print(f"\nPC5数据: {pc5_df.shape}")
print(f"日期范围: {pc5_df.index.min()} 到 {pc5_df.index.max()}")

# 2. 加载未来收益数据
# TODO: 你需要提供未来5日收益数据
# 这里假设从回测数据中提取

# 方法1: 从回测结果中读取
# returns_5d = pd.read_csv("data/raw/backtest_storage_2025q2_2026q3/returns_5d.csv")

# 方法2: 从价格数据计算
try:
    prices = pd.read_csv(
        "data/raw/backtest_storage_2025q2_2026q3/market_prices.csv",
        index_col=0,
        parse_dates=True
    )
    
    # 计算未来5日收益
    returns_5d = (prices.shift(-5) / prices - 1).loc[pc5_df.index]
    
    print(f"\n未来5日收益: {returns_5d.shape}")
    
except Exception as e:
    print(f"\n⚠️ 无法加载收益数据: {e}")
    print("\n请手动提供未来收益数据文件")
    
    # Mock数据用于演示
    print("\n使用Mock数据演示...")
    np.random.seed(42)
    returns_5d = pd.Series(
        np.random.randn(len(pc5_df)) * 0.05,
        index=pc5_df.index,
        name="returns_5d"
    )

# 3. 计算IC（信息系数）
ic_raw = spearmanr(pc5_df["PC5_raw"], returns_5d)[0]
ic_temporal = spearmanr(pc5_df["PC5_temporal"], returns_5d)[0]

print(f"\n{'='*60}")
print("信息系数 (IC)")
print(f"{'='*60}")
print(f"原始PC5的IC:      {ic_raw:.4f}")
print(f"时效PC5的IC:      {ic_temporal:.4f}")
print(f"IC提升:           {(ic_temporal - ic_raw):.4f}")
print(f"提升幅度:         {((ic_temporal/ic_raw - 1)*100 if ic_raw != 0 else 0):.1f}%")

# 4. 计算命中率
def calculate_hit_rate(factor, returns):
    """方向一致率"""
    return ((factor > 0) == (returns > 0)).mean()

hit_raw = calculate_hit_rate(pc5_df["PC5_raw"], returns_5d)
hit_temporal = calculate_hit_rate(pc5_df["PC5_temporal"], returns_5d)

print(f"\n{'='*60}")
print("方向命中率")
print(f"{'='*60}")
print(f"原始PC5命中率:    {hit_raw:.2%}")
print(f"时效PC5命中率:    {hit_temporal:.2%}")
print(f"命中率提升:       {(hit_temporal - hit_raw):.2%}")

# 5. 分段检验（前半段 vs 后半段）
mid = len(pc5_df) // 2
ic_first = spearmanr(pc5_df["PC5_temporal"].iloc[:mid], returns_5d.iloc[:mid])[0]
ic_second = spearmanr(pc5_df["PC5_temporal"].iloc[mid:], returns_5d.iloc[mid:])[0]

print(f"\n{'='*60}")
print("时间稳定性")
print(f"{'='*60}")
print(f"前半段IC:         {ic_first:.4f}")
print(f"后半段IC:         {ic_second:.4f}")
print(f"IC差异:           {abs(ic_first - ic_second):.4f}")

# 6. 决策
print(f"\n{'='*60}")
print("Week 1 验收决策")
print(f"{'='*60}")

success = False

if ic_temporal - ic_raw >= 0.02:
    print("✅ 成功！IC提升 ≥ 0.02")
    print("\n建议:")
    print("  - Week 2: 实现768维embedding完整版")
    print("  - Week 3: 全面回测 + 学术论文")
    success = True
    
elif ic_temporal - ic_raw >= 0.01:
    print("⚠️ 微弱改进。IC提升 0.01-0.02")
    print("\n建议:")
    print("  - 调整参数: half_life, 权重")
    print("  - 尝试其他主成分 (PC1, PC3)")
    print("  - 或继续用当前结果准备论文")
    
else:
    print("❌ 失败。IC无提升或下降")
    print("\n建议:")
    print("  - 分析失败原因:")
    print("    1. PC5本身预测力太弱")
    print("    2. 时效增强公式不适用")
    print("    3. 因子数据质量问题")
    print("  - 考虑pivot到其他方向")

print(f"{'='*60}")

# 7. 生成报告
report = {
    "date": pd.Timestamp.now().strftime("%Y-%m-%d"),
    "ic_raw": ic_raw,
    "ic_temporal": ic_temporal,
    "ic_improvement": ic_temporal - ic_raw,
    "hit_rate_raw": hit_raw,
    "hit_rate_temporal": hit_temporal,
    "ic_first_half": ic_first,
    "ic_second_half": ic_second,
    "success": success
}

output_dir = Path("data/week1_pca")
pd.Series(report).to_json(output_dir / "validation_report.json", indent=2)

print(f"\n✅ 验证报告已保存: {output_dir / 'validation_report.json'}")
```

**决策标准**：
- ✅ **IC提升 ≥ 0.02** → 成功，Week 2做768维版本
- ⚠️ **IC提升 0.01-0.02** → 调整参数重试
- ❌ **IC无提升** → 分析原因，考虑pivot

---

## 📊 Week 1交付物清单

| 文件 | 内容 | 负责人 |
|------|------|--------|
| `data/week1_pca/factors_for_pca.csv` | 清洗后的因子矩阵 | IMIS数据 |
| `data/week1_pca/pc5_raw.csv` | PC5原始序列 | CS |
| `data/week1_pca/pca_loadings.csv` | PCA因子载荷 | CS |
| `src/pricing/pc5_temporal_enhancement.py` | 时效增强算法 | CS |
| `data/week1_pca/pc5_comparison.csv` | 原始vs增强对比 | CS |
| `data/week1_pca/validation_report.json` | 验证报告 | 你 |
| `tests/test_pc5_temporal.py` | 单元测试 | CS |

---

## 🚨 风险与应对

### 风险1: factors.csv结构不符合预期
**症状**: 列名不是因子，而是股票代码

**应对**: 
- 检查CSV文件结构
- 可能需要转置 `.T`
- 或者从其他文件读取

### 风险2: 未来收益数据缺失
**症状**: Day 5找不到returns_5d

**应对**:
- 从 `market_prices.csv` 手动计算
- 或者用当前收益做反向验证
- 或者先用mock数据验证公式正确性

### 风险3: IC提升不明显
**症状**: Day 5验证IC提升<0.01

**应对**:
- 调整 `half_life` (尝试7天、14天、21天)
- 调整权重 (`decay_weight`, `momentum_weight`)
- 尝试其他主成分 (PC1, PC3)
- 或承认方法局限，准备"Negative Result"论文

---

## 📞 今晚会议要讲的（5分钟）

### 1. 明确目标（1分钟）
"Week 1从现有factors.csv做PCA，提取PC5，加时效性，验证IC提升"

### 2. 为什么不做768维embedding（1分钟）
"768维需要3-5天，Week 1时间不够。先小规模验证，成功了Week 2再做"

### 3. 任务分配（2分钟）
```
Day 1: IMIS数据 + 你    → 准备factors.csv
Day 2: CS              → PCA提取PC5
Day 3: CS              → 实现时效增强算法
Day 4: (可选) 集成测试
Day 5: 你              → 验证IC提升，做决策
```

### 4. 成功标准（1分钟）
"Day 5看IC提升 ≥ 0.02就成功"

---

## 🎯 现在立即做的事

1. **检查factors.csv存在吗**：
   ```bash
   ls data/raw/backtest_storage_2025q2_2026q3/factors.csv
   ```

2. **查看文件结构**：
   ```python
   import pandas as pd
   df = pd.read_csv("data/raw/backtest_storage_2025q2_2026q3/factors.csv")
   print(df.head())
   print(df.columns)
   ```

3. **今晚开会**，讲清楚Week 1计划

---

**Week 1计划已完成！你确认没问题了吗？** ✅
