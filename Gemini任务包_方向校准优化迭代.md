# Rainbow-FinGPT 方向校准优化迭代任务包

**前置条件**：已完成《Gemini任务包_方向校准修复（优先）.md》的基础实现

**当前状态**：代码质量A-（85/100），核心逻辑正确，需要优化细节和完善验证

**预计工作量**：1-1.5天

---

## 一、当前代码评审结论

### ✅ 已完成且质量优秀的部分

1. **时间因果性**：严格防止前视偏差，T日决策只用T-1历史
2. **统计检验**：Binomial test实现正确，跨SciPy版本兼容
3. **拒绝预测**：置信度门控清晰，NaN处理得当
4. **单元测试**：10个测试全部通过，覆盖率高

### ⚠️ 需要优化的细节

1. **命中率计算逻辑**：去中心化处理在极端行情下可能有问题
2. **配置参数硬编码**：lookback_days、confidence_threshold等应该可配置
3. **验证报告缺失**：需要生成完整的markdown验证报告
4. **可视化缺失**：需要生成命中率时间序列图、覆盖率曲线图

---

## 二、优化任务清单

### 【任务1】改进命中率计算逻辑（2-3小时）

#### 问题诊断

**当前实现**（`rolling_direction_calibration.py`第115-125行）：
```python
# 若因子分全为正或全为负（未去中心化的截面分），进行截面去均值以便多空判断
score_col = merged["score"]
if len(score_col) > 1 and (score_col.min() >= 0 or score_col.max() <= 0):
    score_eval = score_col - score_col.mean()
else:
    score_eval = score_col

# 若收益率全为正或全为负（单边大盘行情），计算超额收益/去均值收益
ret_col = merged["return"]
if len(ret_col) > 1 and (ret_col.min() >= 0 or ret_col.max() <= 0):
    ret_eval = ret_col - ret_col.mean()
else:
    ret_eval = ret_col
```

**潜在问题**：
- **极端牛市**（6只股票都涨）：去均值后变成3涨3跌，强行制造50%命中率
- **极端熊市**（6只股票都跌）：去均值后变成3涨3跌，强行制造50%命中率
- **小样本偏差**：6只股票样本量太小，去均值可能引入噪声

#### 改进方案

**方案A（推荐）**：增加极端行情检测，单边行情时用绝对收益而非超额收益

```python
def calculate_hit_rate(
    factor_scores: pd.Series,
    actual_returns: pd.Series,
    direction: FactorDirection
) -> Tuple[float, int]:
    """计算单截面或单时点因子在给定方向下的预测命中率。
    
    改进点：
    1. 检测极端单边行情（涨跌比例 > 80%），此时不去均值
    2. 保留原始绝对方向判断，避免强行制造50%命中率
    3. 增加调试日志，记录去中心化触发情况
    """
    if direction == FactorDirection.INVALID:
        return 0.0, 0

    merged = pd.concat([factor_scores, actual_returns], axis=1, join="inner")
    merged.columns = ["score", "return"]
    merged = merged.dropna()

    if len(merged) == 0:
        return 0.0, 0

    score_col = merged["score"]
    ret_col = merged["return"]
    
    # ===== 改进：检测极端行情，避免过度去中心化 =====
    # 统计实际涨跌股票数
    up_count = (ret_col > 0).sum()
    down_count = (ret_col < 0).sum()
    total = len(ret_col)
    
    # 如果涨跌比例 > 80%，判定为极端单边行情，不去均值
    is_extreme_market = (up_count / total > 0.80) or (down_count / total > 0.80)
    
    if is_extreme_market:
        # 极端行情：保留绝对方向
        score_eval = score_col
        ret_eval = ret_col
        logger.debug(f"检测到极端行情（涨{up_count}/跌{down_count}/总{total}），保留绝对方向")
    else:
        # 正常行情：去均值计算超额收益
        # 因子分数去中心化（如果全正或全负）
        if len(score_col) > 1 and (score_col.min() >= 0 or score_col.max() <= 0):
            score_eval = score_col - score_col.mean()
        else:
            score_eval = score_col
        
        # 收益率去均值（计算超额收益）
        ret_eval = ret_col - ret_col.mean()
        logger.debug(f"正常行情（涨{up_count}/跌{down_count}），使用超额收益")

    if direction == FactorDirection.POSITIVE:
        prediction = score_eval > 0
    elif direction == FactorDirection.NEGATIVE:
        prediction = score_eval < 0
    else:
        return 0.0, 0

    actual_direction = ret_eval > 0
    correct = int((prediction == actual_direction).sum())
    hit_rate = float(correct / len(merged))

    return hit_rate, len(merged)
```

**预期效果**：
- 极端牛市/熊市：保留绝对方向判断，不强行制造50%
- 正常震荡市：使用超额收益，判断相对强弱
- 更真实的命中率统计

#### 交付物
- 修改后的 `src/pricing/rolling_direction_calibration.py`
- 增加测试用例 `test_calculate_hit_rate_extreme_market()`

---

### 【任务2】配置参数化与可调试性增强（1-2小时）

#### 问题
当前关键参数硬编码：
- `lookback_days=30`
- `min_samples=50`
- `significance_level=0.05`
- `confidence_threshold=0.7`

虽然任务要求"不刷参数"，但应该**支持配置化**以便：
1. 诚实测试不同窗口的稳定性
2. 在验证报告中说明"已测试20/30/40天窗口，30天最稳定"
3. 未来省赛时可快速调整

#### 改进方案

**新建配置文件**：`src/pricing/calibration_config.py`

```python
# -*- coding: utf-8 -*-
"""src/pricing/calibration_config.py —— 滚动方向校准配置参数"""

from dataclasses import dataclass


@dataclass
class CalibrationConfig:
    """滚动方向校准配置。
    
    注意：修改这些参数后，必须重新运行完整验证，不允许仅在验证期调参。
    """
    # 回溯窗口长度（交易日数）
    lookback_days: int = 30
    
    # 最小有效样本量门槛
    min_samples: int = 50
    
    # 统计显著性阈值（p-value）
    significance_level: float = 0.05
    
    # 置信度门槛（低于此值拒绝预测）
    confidence_threshold: float = 0.7
    
    # 最小命中率要求（低于此值拒绝预测）
    min_hit_rate: float = 0.52
    
    # 极端行情检测阈值（单边涨跌比例 > 此值不去均值）
    extreme_market_threshold: float = 0.80
    
    # 是否启用调试日志（记录每日校准细节）
    debug_logging: bool = False
    
    def validate(self):
        """参数合理性检查。"""
        assert 10 <= self.lookback_days <= 60, "lookback_days应在10-60天范围"
        assert 20 <= self.min_samples <= 200, "min_samples应在20-200范围"
        assert 0.01 <= self.significance_level <= 0.10, "significance_level应在0.01-0.10范围"
        assert 0.50 <= self.confidence_threshold <= 0.95, "confidence_threshold应在0.50-0.95范围"
        assert 0.50 <= self.min_hit_rate <= 0.60, "min_hit_rate应在0.50-0.60范围"


# 默认配置（用于回测）
DEFAULT_CONFIG = CalibrationConfig()

# 高覆盖率配置（降低门槛，提高覆盖率）
HIGH_COVERAGE_CONFIG = CalibrationConfig(
    confidence_threshold=0.60,
    min_hit_rate=0.51,
    min_samples=30
)

# 高置信度配置（提高门槛，降低覆盖率但提高命中率）
HIGH_CONFIDENCE_CONFIG = CalibrationConfig(
    confidence_threshold=0.80,
    min_hit_rate=0.53,
    min_samples=80
)
```

**修改函数签名**：在所有相关函数中增加 `config: CalibrationConfig = None` 参数

```python
def calibrate_factor_direction(
    factor_scores_history: pd.DataFrame,
    returns_history: pd.DataFrame,
    current_date: Any,
    config: Optional[CalibrationConfig] = None  # 新增
) -> CalibrationResult:
    """滚动方向校准核心算法。"""
    if config is None:
        config = DEFAULT_CONFIG
    config.validate()
    
    lookback_days = config.lookback_days
    min_samples = config.min_samples
    significance_level = config.significance_level
    # ... 后续使用config中的参数 ...
```

#### 交付物
- 新建 `src/pricing/calibration_config.py`
- 修改 `rolling_direction_calibration.py` 支持配置传入
- 修改 `green_backtest_runner.py` 传入配置对象

---

### 【任务3】生成完整验证报告（3-4小时）

#### 目标
按照任务包第四节"验证与报告"的格式，生成完整的markdown报告

#### 实现文件

**新建**：`scripts/generate_validation_report.py`

```python
# -*- coding: utf-8 -*-
"""scripts/generate_validation_report.py —— 生成方向校准验证报告"""

import json
from pathlib import Path
import pandas as pd
import numpy as np

from src.analysis.green_backtest_runner import GreenBacktestRunner
from src.pricing.rolling_direction_calibration import generate_calibration_report


def generate_markdown_report(output_path: str = "reports/方向校准修复验证报告.md"):
    """生成完整验证报告。"""
    
    # 1. 运行回测
    runner = GreenBacktestRunner()
    result = runner.run_walk_forward_backtest()
    
    metrics = result["metrics"]
    calibration_records = result["calibration_records"]
    
    # 2. 数据分割：前40日校准期，后20日验证期
    df_cal = pd.DataFrame(calibration_records)
    split_idx = len(df_cal) - 20
    
    train_period = df_cal.iloc[:split_idx]
    validation_period = df_cal.iloc[split_idx:]
    
    # 3. 计算统计指标
    # 验证期前后半段
    val_first_half = validation_period.iloc[:10]
    val_second_half = validation_period.iloc[10:]
    
    # 提取命中率（需要从实际收益率计算）
    # 这里简化处理，实际应该从prices_df计算
    
    # 4. 生成markdown报告
    report = f"""# 方向校准修复验证报告

## 数据概况
- 总样本: {len(df_cal)}个交易日（2025-Q3至2026-Q3）
- 校准期: 前{split_idx}日
- 验证期: 后20日（严格留出）

## 整体表现

### 方向校准统计

| 指标 | 校准期 | 验证期 | 变化 |
|------|--------|--------|------|
| 平均覆盖率 | {train_period['coverage_rate'].mean():.1%} | {validation_period['coverage_rate'].mean():.1%} | {(validation_period['coverage_rate'].mean() - train_period['coverage_rate'].mean()):.1%} |
| 平均置信度 | {train_period['confidence'].mean():.2f} | {validation_period['confidence'].mean():.2f} | {(validation_period['confidence'].mean() - train_period['confidence'].mean()):+.2f} |
| 有效预测天数 | {(train_period['valid_count'] > 0).sum()} | {(validation_period['valid_count'] > 0).sum()} | {(validation_period['valid_count'] > 0).sum() - (train_period['valid_count'] > 0).sum()} |

### 策略表现指标

| 指标 | 修复前（假设） | 修复后 | 改善 |
|------|--------------|--------|------|
| 年化收益率 | - | {metrics.get('strategy_annual_return', 0):.2%} | - |
| 夏普比率 | 1.19 | {metrics.get('strategy_sharpe', 0):.2f} | {metrics.get('strategy_sharpe', 0) - 1.19:+.2f} |
| 最大回撤 | 24.9% | {metrics.get('strategy_max_drawdown', 0):.2%} | {metrics.get('strategy_max_drawdown', 0) - 0.249:+.1%} |

## 验证期表现（后20日）

| 指标 | 数值 | 是否达标 |
|------|------|----------|
| 平均覆盖率 | {validation_period['coverage_rate'].mean():.1%} | {'✅ 在20-30%范围' if 0.20 <= validation_period['coverage_rate'].mean() <= 0.30 else '⚠️ 超出目标范围'} |
| 前10日覆盖率 | {val_first_half['coverage_rate'].mean():.1%} | - |
| 后10日覆盖率 | {val_second_half['coverage_rate'].mean():.1%} | - |
| 覆盖率稳定性（差异） | {abs(val_first_half['coverage_rate'].mean() - val_second_half['coverage_rate'].mean()):.1%} | {'✅ 小于10%' if abs(val_first_half['coverage_rate'].mean() - val_second_half['coverage_rate'].mean()) < 0.10 else '⚠️ 波动较大'} |

## 方向使用统计

| 日期区间 | 正向使用 | 反向使用 | 拒绝预测 |
|----------|----------|----------|----------|
| 校准期（前{split_idx}日） | {(train_period['direction'] == 'positive').sum()}天 | {(train_period['direction'] == 'negative').sum()}天 | {(train_period['direction'] == 'invalid').sum()}天 |
| 验证期（后20日） | {(validation_period['direction'] == 'positive').sum()}天 | {(validation_period['direction'] == 'negative').sum()}天 | {(validation_period['direction'] == 'invalid').sum()}天 |

**关键发现**: {'后半段反向使用增加，验证了因子方向确实在时间上漂移' if (validation_period['direction'] == 'negative').sum() > (train_period['direction'] == 'negative').sum() / split_idx * 20 else '方向使用保持稳定'}

## 拒绝预测原因分析

| 原因 | 次数 | 占比 |
|------|------|------|
| 历史数据不足 | {df_cal['reason'].str.contains('历史数据不足').sum()} | {df_cal['reason'].str.contains('历史数据不足').mean():.1%} |
| 样本量不足 | {df_cal['reason'].str.contains('有效样本不足').sum()} | {df_cal['reason'].str.contains('有效样本不足').mean():.1%} |
| 置信度不足 | {(df_cal['confidence'] < 0.70).sum()} | {(df_cal['confidence'] < 0.70).mean():.1%} |
| 命中率低于52% | {df_cal['reason'].str.contains('命中率不足52%').sum()} | {df_cal['reason'].str.contains('命中率不足52%').mean():.1%} |

## 结论

### 是否达到预设目标

目标标准：
- ✅ 覆盖率 20-30%
- ✅ 命中率 ≥53%（需要补充实际计算）
- ✅ 前后差异 <5%（需要补充实际计算）

### 已知限制

⚠️ **数据量限制**：
- 验证期仅20日，样本量偏小
- 建议持续监控未来30-60日表现

⚠️ **覆盖率权衡**：
- 当前覆盖率约{validation_period['coverage_rate'].mean():.1%}，意味着约{(1-validation_period['coverage_rate'].mean()):.1%}的时间无法预测
- 这是诚实口径的代价，宁可少预测、准确率高

⚠️ **命中率边际优势**：
- 即使达到54%命中率，也仅略优于随机（50%）
- 不能夸大为"高精度预测"

## 下一步建议

1. **持续监控**：继续观察未来30日表现，验证稳定性
2. **条件执行任务包A**：如果持续有效，可考虑叠加市场状态机
3. **诚实宣传**：答辩时同时展示命中率和覆盖率，不隐瞒限制

---

**报告生成时间**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    
    # 5. 保存报告
    output_dir = Path("reports")
    output_dir.mkdir(exist_ok=True)
    
    with open(output_dir / "方向校准修复验证报告.md", "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"✅ 验证报告已生成: {output_dir / '方向校准修复验证报告.md'}")
    
    return report


if __name__ == "__main__":
    generate_markdown_report()
```

#### 交付物
- `scripts/generate_validation_report.py`（完整实现）
- `reports/方向校准修复验证报告.md`（自动生成）

---

### 【任务4】生成可视化图表（2-3小时）

#### 目标
生成任务包要求的图表：
1. 命中率时间序列图
2. 覆盖率-命中率权衡曲线
3. 方向使用时序图

#### 实现文件

**新建**：`scripts/generate_calibration_figures.py`

```python
# -*- coding: utf-8 -*-
"""scripts/generate_calibration_figures.py —— 生成方向校准可视化图表"""

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from pathlib import Path

from src.analysis.green_backtest_runner import GreenBacktestRunner

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def plot_hit_rate_over_time(calibration_records, save_path: str):
    """命中率时间序列图（需要补充实际命中率计算）。"""
    df = pd.DataFrame(calibration_records)
    df["date"] = pd.to_datetime(df["date"])
    
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    
    # 子图1：方向使用
    direction_colors = {"positive": "green", "negative": "red", "invalid": "gray"}
    colors = [direction_colors[d] for d in df["direction"]]
    axes[0].scatter(df["date"], [1]*len(df), c=colors, s=100, alpha=0.6)
    axes[0].set_ylabel("方向使用", fontsize=12)
    axes[0].set_ylim(0.5, 1.5)
    axes[0].set_yticks([1])
    axes[0].set_yticklabels([""])
    axes[0].legend(handles=[
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='green', markersize=10, label='正向'),
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='red', markersize=10, label='反向'),
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='gray', markersize=10, label='拒绝')
    ], loc='upper left')
    axes[0].grid(True, alpha=0.3)
    
    # 子图2：置信度
    axes[1].plot(df["date"], df["confidence"], marker='o', linewidth=2, markersize=4)
    axes[1].axhline(y=0.7, color='red', linestyle='--', label='置信度阈值0.7')
    axes[1].set_ylabel("置信度", fontsize=12)
    axes[1].set_ylim(0, 1)
    axes[1].legend(loc='upper left')
    axes[1].grid(True, alpha=0.3)
    
    # 子图3：覆盖率
    axes[2].plot(df["date"], df["coverage_rate"] * 100, marker='o', linewidth=2, markersize=4, color='orange')
    axes[2].axhline(y=20, color='green', linestyle='--', alpha=0.5, label='目标下限20%')
    axes[2].axhline(y=30, color='green', linestyle='--', alpha=0.5, label='目标上限30%')
    axes[2].fill_between(df["date"], 20, 30, alpha=0.1, color='green')
    axes[2].set_ylabel("覆盖率 (%)", fontsize=12)
    axes[2].set_xlabel("日期", fontsize=12)
    axes[2].set_ylim(0, 100)
    axes[2].legend(loc='upper left')
    axes[2].grid(True, alpha=0.3)
    
    # 格式化x轴
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    plt.setp(axes[2].xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    plt.suptitle("滚动方向校准时间序列分析", fontsize=14, fontweight='bold')
    plt.tight_layout()
    
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"✅ 时间序列图已保存: {save_path}")
    plt.close()


def plot_coverage_vs_performance(calibration_records, save_path: str):
    """覆盖率-命中率权衡曲线（模拟不同置信度阈值）。"""
    df = pd.DataFrame(calibration_records)
    
    # 模拟不同置信度阈值下的覆盖率和命中率
    thresholds = np.arange(0.50, 0.95, 0.05)
    results = []
    
    for threshold in thresholds:
        # 筛选置信度 >= threshold 的预测
        valid = df[df["confidence"] >= threshold]
        coverage = len(valid) / len(df) if len(df) > 0 else 0.0
        
        # 这里需要实际命中率数据，暂时用历史命中率均值模拟
        avg_hit_rate = valid["hit_rate"].mean() if len(valid) > 0 else 0.50
        
        results.append({
            "threshold": threshold,
            "coverage": coverage * 100,
            "hit_rate": avg_hit_rate * 100
        })
    
    df_results = pd.DataFrame(results)
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    scatter = ax.scatter(
        df_results["coverage"],
        df_results["hit_rate"],
        c=df_results["threshold"],
        s=100,
        cmap='viridis',
        edgecolors='black',
        linewidths=1
    )
    
    # 标注关键点
    for i, row in df_results.iterrows():
        if i % 2 == 0:  # 每隔一个标注，避免拥挤
            ax.annotate(
                f"{row['threshold']:.2f}",
                (row['coverage'], row['hit_rate']),
                textcoords="offset points",
                xytext=(0, 8),
                ha='center',
                fontsize=8
            )
    
    # 目标区域
    ax.axhline(y=53, color='red', linestyle='--', alpha=0.5, label='命中率目标53%')
    ax.axvline(x=20, color='green', linestyle='--', alpha=0.5, label='覆盖率下限20%')
    ax.axvline(x=30, color='green', linestyle='--', alpha=0.5, label='覆盖率上限30%')
    ax.fill_betweenx([50, 60], 20, 30, alpha=0.1, color='green')
    
    ax.set_xlabel("覆盖率 (%)", fontsize=12)
    ax.set_ylabel("命中率 (%)", fontsize=12)
    ax.set_title("置信度阈值 vs 覆盖率-命中率权衡曲线", fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='best')
    
    # 颜色条
    cbar = plt.colorbar(scatter, ax=ax)
    cbar.set_label('置信度阈值', fontsize=10)
    
    plt.tight_layout()
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"✅ 权衡曲线图已保存: {save_path}")
    plt.close()


def plot_direction_usage_timeline(calibration_records, save_path: str):
    """方向使用时序图（堆叠柱状图）。"""
    df = pd.DataFrame(calibration_records)
    df["date"] = pd.to_datetime(df["date"])
    
    # 按周聚合
    df["week"] = df["date"].dt.to_period('W')
    weekly = df.groupby("week")["direction"].value_counts().unstack(fill_value=0)
    
    if "positive" not in weekly.columns:
        weekly["positive"] = 0
    if "negative" not in weekly.columns:
        weekly["negative"] = 0
    if "invalid" not in weekly.columns:
        weekly["invalid"] = 0
    
    fig, ax = plt.subplots(figsize=(12, 6))
    
    weekly[["positive", "negative", "invalid"]].plot(
        kind='bar',
        stacked=True,
        ax=ax,
        color=["green", "red", "gray"],
        alpha=0.7
    )
    
    ax.set_xlabel("周", fontsize=12)
    ax.set_ylabel("天数", fontsize=12)
    ax.set_title("方向使用时序分布（按周统计）", fontsize=14, fontweight='bold')
    ax.legend(["正向", "反向", "拒绝"], loc='upper left')
    ax.grid(True, alpha=0.3, axis='y')
    
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"✅ 方向时序图已保存: {save_path}")
    plt.close()


def generate_all_figures():
    """生成所有可视化图表。"""
    runner = GreenBacktestRunner()
    result = runner.run_walk_forward_backtest()
    
    calibration_records = result["calibration_records"]
    
    figures_dir = Path("reports/figures")
    figures_dir.mkdir(parents=True, exist_ok=True)
    
    plot_hit_rate_over_time(calibration_records, figures_dir / "calibration_time_series.png")
    plot_coverage_vs_performance(calibration_records, figures_dir / "coverage_vs_performance.png")
    plot_direction_usage_timeline(calibration_records, figures_dir / "direction_usage_timeline.png")
    
    print("✅ 所有图表生成完成！")


if __name__ == "__main__":
    generate_all_figures()
```

#### 交付物
- `scripts/generate_calibration_figures.py`
- `reports/figures/calibration_time_series.png`
- `reports/figures/coverage_vs_performance.png`
- `reports/figures/direction_usage_timeline.png`

---

### 【任务5】补充实际命中率计算（2小时）

#### 问题
当前代码只记录了**历史窗口的命中率**（用于校准），但没有记录**当前预测的实际命中率**（用于验证）

#### 改进方案

在 `green_backtest_runner.py` 的回测循环中，增加实际命中率计算：

```python
# 在第200行后，增加实际命中率追踪
self.actual_hit_records: List[Dict[str, Any]] = []

# 在回测循环中（约第300行），增加：
if t >= 21:  # 确保有前一天的预测结果
    prev_date = dates[t-1]
    prev_calibration = self.calibration_records[-2] if len(self.calibration_records) >= 2 else None
    
    if prev_calibration and prev_calibration["valid_count"] > 0:
        # 获取T-1日的预测分数
        prev_scores = self.factor_scores_history.loc[prev_date]
        
        # 获取T-1到T的实际收益率
        actual_rets = prices_df[self.GREEN_TICKERS].iloc[t] / prices_df[self.GREEN_TICKERS].iloc[t-1] - 1.0
        
        # 计算命中率
        merged = pd.concat([prev_scores, actual_rets], axis=1, join='inner').dropna()
        if len(merged) > 0:
            pred_direction = (merged.iloc[:, 0] - merged.iloc[:, 0].mean()) > 0
            actual_direction = (merged.iloc[:, 1] - merged.iloc[:, 1].mean()) > 0
            hit_rate = (pred_direction == actual_direction).mean()
            
            self.actual_hit_records.append({
                "date": str(prev_date.date()),
                "hit_rate": float(hit_rate),
                "sample_size": len(merged),
                "direction_used": prev_calibration["direction"]
            })
```

然后在 `_calculate_calibration_performance` 中使用 `self.actual_hit_records` 计算真实命中率。

#### 交付物
- 修改后的 `green_backtest_runner.py`（增加实际命中率追踪）
- 修改后的 `generate_validation_report.py`（使用实际命中率）

---

## 三、执行顺序与验收标准

### 执行顺序
1. **任务1**：改进命中率计算逻辑（2-3小时）
2. **任务5**：补充实际命中率计算（2小时）← **优先，依赖关系**
3. **任务2**：配置参数化（1-2小时）
4. **任务3**：生成验证报告（3-4小时）
5. **任务4**：生成可视化图表（2-3小时）

### 验收标准

#### 代码质量
- ✅ 所有pytest测试通过
- ✅ 新增测试用例覆盖极端行情场景
- ✅ 配置参数可以正确传递和生效

#### 功能完整性
- ✅ 生成完整的markdown验证报告
- ✅ 生成3张高质量可视化图表（300 dpi）
- ✅ 实际命中率计算正确且可验证

#### 诚实性检查
- ✅ 报告中明确说明验证期样本量限制
- ✅ 同时展示命中率、覆盖率、前后稳定性
- ✅ 不夸大效果，诚实报告已知限制

---

## 四、交付清单

### 代码文件
- ✅ 修改后的 `src/pricing/rolling_direction_calibration.py`（改进命中率计算）
- ✅ 新建 `src/pricing/calibration_config.py`（配置管理）
- ✅ 修改后的 `src/analysis/green_backtest_runner.py`（实际命中率追踪）
- ✅ 新建 `scripts/generate_validation_report.py`（报告生成）
- ✅ 新建 `scripts/generate_calibration_figures.py`（图表生成）

### 输出文件
- ✅ `reports/方向校准修复验证报告.md`（完整验证报告）
- ✅ `reports/figures/calibration_time_series.png`（时间序列图）
- ✅ `reports/figures/coverage_vs_performance.png`（权衡曲线图）
- ✅ `reports/figures/direction_usage_timeline.png`（方向时序图）
- ✅ `docs/data/paper/calibration_validation.json`（数值结果JSON）

### 文档文件
- ✅ 更新 `README.md`（增加使用说明）
- ✅ 更新 `specs/contest-2026/quickstart.md`（增加验证报告章节）

---

## 五、常见问题

**Q1：为什么要改进命中率计算逻辑？**
A：当前的去中心化逻辑在极端行情（6只股票全涨/全跌）下会强行制造50%命中率，掩盖真实预测能力。改进后保留绝对方向判断，更真实。

**Q2：配置参数化是否违反"不刷参数"原则？**
A：不违反。配置化是为了**诚实测试不同窗口的稳定性**，并在报告中说明。最终交付时固定为DEFAULT_CONFIG（lookback=30, threshold=0.7），不在验证期调参。

**Q3：实际命中率和历史命中率有什么区别？**
A：
- **历史命中率**（hit_rate字段）：回溯窗口内用于校准的命中率
- **实际命中率**（actual_hit_records）：T日预测在T+1的真实命中情况，用于验证

**Q4：如果验证报告显示未达标怎么办？**
A：诚实保留"暂无优势"结论，不刷参数。在报告中分析可能原因：
- 因子本身是否有效？
- 6只股票样本量是否太小？
- 是否需要更长时间验证？

**Q5：图表生成失败怎么办？**
A：检查：
- matplotlib中文字体是否安装（SimHei/Microsoft YaHei）
- reports/figures目录是否有写权限
- 数据是否完整（calibration_records不为空）

---

## 六、与后续任务的关系

**当前迭代（优化）**：
- 完善基础实现，生成验证报告
- 目标：达到覆盖率20-30%，命中率53%+

**下一步（条件执行）**：
- 如果验证通过 → 执行《Gemini任务包_系统优化.md》（市场状态机+因子正交化）
- 如果验证未通过 → 诚实保留结论，不继续叠加复杂模型

---

**任务包准备完毕，预计完成时间：1-1.5天**

**关键原则：诚实口径，完善验证，不过度优化**
