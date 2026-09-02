# 阶段1任务：市场状态机与动态仓位实现

**优先级**：🔴 P0（最高，致命差距修复）  
**预计时间**：3-4天  
**负责人**：DeepSeek  
**目标**：将绿电板块Sharpe从1.19提升至1.31+（>10%提升）

---

## 任务背景

### 当前问题
- ✅ 方向校准已完成，命中率57.6%，稳定性4.4%
- ❌ Sharpe Ratio未提升（维持1.19，未达到10%提升目标）
- ❌ 比赛要求：至少1个板块Sharpe提升>10%

### 根因分析
方向校准主要改善了**稳定性**和**风控**（回撤从33.05%降至13.97%），但未实现**Alpha增强**。需要通过市场状态机和动态仓位管理来提升收益能力。

### 预期效果
- Sharpe: 1.19 → **1.31+** (提升10%+) ✅ 达标
- 年化收益: 26.49% → **30%+**
- 最大回撤: 保持13.97%或更优

---

## 任务清单

### 任务A1：实现市场状态机模块

**文件路径**：`Rainbow_FinGPTv2/src/risk/market_regime_detector.py`

**核心功能**：
1. 三状态检测（BULL/BEAR/SIDEWAYS）
2. 基于动量（MA20/MA60交叉）+ 波动率（ATR）的综合判断
3. 状态转换逻辑（带滞后防抖）

**接口要求**：
```python
class MarketRegimeDetector:
    """市场状态机检测器"""
    
    def detect_regime(self, prices: pd.DataFrame) -> pd.Series:
        """
        检测市场状态
        
        Args:
            prices: DataFrame with columns ['close', 'high', 'low']
                   index: DatetimeIndex
        
        Returns:
            Series of regime labels: 'BULL' | 'BEAR' | 'SIDEWAYS'
            index: DatetimeIndex (aligned with prices)
        """
        pass
    
    def get_regime_statistics(self) -> Dict[str, Any]:
        """
        获取状态统计信息
        
        Returns:
            {
                'bull_days': int,
                'bear_days': int,
                'sideways_days': int,
                'avg_bull_duration': float,  # 平均牛市持续天数
                'avg_bear_duration': float,
                'transition_matrix': np.ndarray  # 状态转移矩阵
            }
        """
        pass
```

**判断逻辑**：
```python
# 1. 计算技术指标
MA20 = prices['close'].rolling(20).mean()
MA60 = prices['close'].rolling(60).mean()
ATR = calculate_atr(prices, period=14)  # 平均真实波幅

# 2. 动量信号
momentum_signal = (MA20 - MA60) / MA60

# 3. 波动率信号
volatility = ATR / prices['close']

# 4. 状态判断
if momentum_signal > 0.02 and volatility < 0.03:
    regime = 'BULL'
elif momentum_signal < -0.02 and volatility < 0.03:
    regime = 'BEAR'
else:
    regime = 'SIDEWAYS'

# 5. 防抖处理（状态至少持续3天）
regime = apply_hysteresis(regime, min_duration=3)
```

**测试要求**：
- 至少5个单元测试（状态判断正确性、边界条件、防抖逻辑）
- 历史数据回放测试（验证238个交易日的状态序列合理性）

**参考资料**：
- 《Gemini任务包_系统优化.md》中的"市场状态机设计"章节
- 已有代码：`Rainbow_FinGPTv2/src/pricing/rolling_direction_calibration.py`（参考结构）

---

### 任务A2：实现动态仓位管理模块

**文件路径**：`Rainbow_FinGPTv2/src/risk/dynamic_position_sizer.py`

**核心功能**：
1. 基于市场状态的仓位系数
2. 回撤惩罚机制
3. 波动率自适应调整

**接口要求**：
```python
class DynamicPositionSizer:
    """动态仓位管理器"""
    
    def __init__(self, 
                 base_position: float = 1.0,
                 bull_multiplier: float = 1.2,
                 bear_multiplier: float = 0.6,
                 sideways_multiplier: float = 0.9):
        """
        Args:
            base_position: 基础仓位系数
            bull_multiplier: 牛市仓位倍数
            bear_multiplier: 熊市仓位倍数
            sideways_multiplier: 震荡市仓位倍数
        """
        pass
    
    def calculate_position(self,
                          regime: str,
                          current_drawdown: float,
                          volatility: float) -> float:
        """
        计算当前仓位系数
        
        Args:
            regime: 市场状态 ('BULL' | 'BEAR' | 'SIDEWAYS')
            current_drawdown: 当前回撤 (0.0-1.0)
            volatility: 当前波动率 (ATR/Price)
        
        Returns:
            position_size: 仓位系数 (0.0-2.0)
        """
        pass
    
    def get_position_history(self) -> pd.DataFrame:
        """
        获取历史仓位记录
        
        Returns:
            DataFrame with columns ['date', 'regime', 'position', 'drawdown']
        """
        pass
```

**计算逻辑**：
```python
# 1. 基础仓位（根据市场状态）
if regime == 'BULL':
    base_pos = base_position * bull_multiplier  # 1.0 * 1.2 = 1.2
elif regime == 'BEAR':
    base_pos = base_position * bear_multiplier  # 1.0 * 0.6 = 0.6
else:  # SIDEWAYS
    base_pos = base_position * sideways_multiplier  # 1.0 * 0.9 = 0.9

# 2. 回撤惩罚
if current_drawdown > 0.10:  # 回撤超过10%
    drawdown_penalty = 1 - (current_drawdown - 0.10) * 2
    drawdown_penalty = max(0.5, drawdown_penalty)  # 最低0.5
else:
    drawdown_penalty = 1.0

# 3. 波动率调整
if volatility > 0.05:  # 高波动
    volatility_adj = 0.8
elif volatility < 0.02:  # 低波动
    volatility_adj = 1.1
else:
    volatility_adj = 1.0

# 4. 最终仓位
position = base_pos * drawdown_penalty * volatility_adj
position = np.clip(position, 0.3, 2.0)  # 限制在0.3-2.0之间
```

**测试要求**：
- 至少6个单元测试（各状态仓位计算、回撤惩罚、波动率调整、边界限制）

---

### 任务A3：集成到绿电板块回测

**文件路径**：`Rainbow_FinGPTv2/src/analysis/green_backtest_runner.py`

**修改点**：

#### 1. 导入新模块
```python
from Rainbow_FinGPTv2.src.risk.market_regime_detector import MarketRegimeDetector
from Rainbow_FinGPTv2.src.risk.dynamic_position_sizer import DynamicPositionSizer
```

#### 2. 在回测循环中集成（约在第220-250行）
```python
# 初始化模块
regime_detector = MarketRegimeDetector()
position_sizer = DynamicPositionSizer(
    base_position=1.0,
    bull_multiplier=1.2,
    bear_multiplier=0.6,
    sideways_multiplier=0.9
)

# 在每日循环中
for date in trading_dates:
    # ... 现有的因子计算和方向校准代码 ...
    
    # === 新增：市场状态检测 ===
    history_window = prices.loc[:date]  # 历史数据
    regime = regime_detector.detect_regime(history_window).iloc[-1]
    
    # === 新增：动态仓位计算 ===
    current_drawdown = calculate_drawdown(equity_curve)  # 当前回撤
    current_volatility = calculate_volatility(history_window)  # 当前波动率
    position_size = position_sizer.calculate_position(
        regime=regime,
        current_drawdown=current_drawdown,
        volatility=current_volatility
    )
    
    # === 修改：应用动态仓位到信号 ===
    # 原代码：signal = calibrated_factor_value
    # 新代码：
    signal = calibrated_factor_value * position_size
    
    # ... 后续的持仓更新和收益计算 ...
    
    # 记录状态和仓位（用于后续分析）
    regime_history.append({'date': date, 'regime': regime, 'position': position_size})
```

#### 3. 新增辅助函数
```python
def calculate_drawdown(equity_curve: pd.Series) -> float:
    """计算当前回撤"""
    running_max = equity_curve.expanding().max()
    drawdown = (equity_curve - running_max) / running_max
    return abs(drawdown.iloc[-1])

def calculate_volatility(prices: pd.DataFrame, period: int = 14) -> float:
    """计算ATR波动率"""
    high_low = prices['high'] - prices['low']
    high_close = np.abs(prices['high'] - prices['close'].shift())
    low_close = np.abs(prices['low'] - prices['close'].shift())
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = true_range.rolling(period).mean().iloc[-1]
    return atr / prices['close'].iloc[-1]
```

---

### 任务A4：生成增强版回测报告

**目标**：更新回测结果，验证Sharpe提升

**输出文件**：
1. `reports/绿电板块_增强版回测报告.md`
2. `reports/backtest_results_enhanced.json`
3. `reports/figures/enhanced_*.png`（至少4张图）

**报告内容**：

#### 1. 核心指标对比表
```markdown
| 指标 | 基线版本 | 方向校准版本 | 增强版本（本次） | 提升幅度 |
|------|---------|-------------|-----------------|---------|
| Sharpe Ratio | 1.19 | 1.19 | **1.31** | **+10.1%** ✅ |
| 年化收益率 | 26.49% | 26.49% | **30.2%** | +14.0% |
| 最大回撤 | 33.05% | 13.97% | **12.8%** | -61.3% |
| 胜率 | 49.08% | 57.6% | **59.2%** | +20.6% |
| 卡尔玛比率 | 0.80 | 1.90 | **2.36** | +195% |
```

#### 2. 市场状态分析
```markdown
### 市场状态分布（238个交易日）
- 牛市：95天（39.9%）
- 熊市：68天（28.6%）
- 震荡市：75天（31.5%）

### 各状态下的策略表现
| 状态 | 交易次数 | 胜率 | 平均收益 | Sharpe |
|------|---------|------|---------|--------|
| 牛市 | 45 | 68.9% | +1.8% | 2.1 |
| 熊市 | 32 | 43.8% | -0.6% | 0.8 |
| 震荡市 | 38 | 55.3% | +0.9% | 1.2 |
```

#### 3. 仓位使用分析
- 平均仓位：0.92（基线：1.0）
- 仓位中位数：0.95
- 仓位范围：0.48 - 1.44
- 高仓位日（>1.2）：23天（牛市集中）
- 低仓位日（<0.7）：18天（熊市集中）

#### 4. 必需图表（300dpi PNG）
1. **增强版净值曲线**（对比基线版、方向校准版、增强版）
2. **市场状态时间轴**（彩色柱状图，BULL=绿，BEAR=红，SIDEWAYS=灰）
3. **动态仓位时间序列**（折线图，叠加市场状态背景色）
4. **各状态收益箱线图**（Box plot，展示收益分布）

---

### 任务A5：运行测试并验证

**测试步骤**：

#### 1. 单元测试
```bash
# 运行新模块测试
pytest Rainbow_FinGPTv2/tests/test_market_regime_detector.py -v
pytest Rainbow_FinGPTv2/tests/test_dynamic_position_sizer.py -v

# 预期结果：至少11个测试全部通过
```

#### 2. 集成测试
```bash
# 运行完整回测
python Rainbow_FinGPTv2/src/analysis/green_backtest_runner.py

# 检查输出
cat reports/绿电板块_增强版回测报告.md
```

#### 3. 验收标准
- ✅ 单元测试全部通过（至少11个）
- ✅ Sharpe Ratio ≥ 1.31（提升>10%）
- ✅ 最大回撤 ≤ 15%（不能因追求收益而恶化风控）
- ✅ 生成完整报告（Markdown + JSON + 4张图）
- ✅ 代码无警告，无硬编码路径

---

## 技术约束

### 1. 时间因果性（零前视偏差）
⚠️ **关键要求**：市场状态检测和仓位计算必须只使用**历史数据**

```python
# ✅ 正确：只使用截至date的历史数据
history = prices.loc[:date]
regime = detector.detect_regime(history).iloc[-1]

# ❌ 错误：使用了未来数据
regime = detector.detect_regime(prices).loc[date]  # prices包含未来数据
```

### 2. 代码复用
- 复用 `rolling_direction_calibration.py` 的代码结构
- 复用测试框架（pytest fixture, parametrize）
- 复用配置管理模式（参考 `calibration_config.py`）

### 3. 性能要求
- 市场状态检测：单次调用 <100ms
- 动态仓位计算：单次调用 <10ms
- 完整回测（238日）：总耗时 <5分钟

### 4. 代码质量
- Type hints必须完整
- Docstring必须包含Args/Returns/Raises
- 关键逻辑必须有注释（为什么这样判断）
- 变量命名清晰（no `x`, `tmp`, `data`）

---

## 参考文件

### 1. 已完成的方向校准模块（参考结构）
- `Rainbow_FinGPTv2/src/pricing/rolling_direction_calibration.py`
- `Rainbow_FinGPTv2/src/pricing/calibration_config.py`
- `Rainbow_FinGPTv2/tests/test_rolling_direction_calibration.py`

### 2. 回测框架（集成点）
- `Rainbow_FinGPTv2/src/analysis/green_backtest_runner.py`（第200-250行）

### 3. 设计文档
- `Gemini任务包_系统优化.md`（市场状态机设计章节）
- `specs/contest-2026/spec.md`（功能规格）
- `specs/contest-2026/gap-analysis.md`（差距分析，刚生成）

### 4. 数据路径
- 绿电板块数据：`data/processed/green_energy/`
- 因子数据：`data/factors/`

---

## 常见陷阱与预防

### 陷阱1：前视偏差
❌ **错误示例**：
```python
# 在全部数据上计算MA，再取某日的值
ma60 = prices['close'].rolling(60).mean()
regime = detect_regime(ma60).loc[date]  # 包含未来数据
```

✅ **正确做法**：
```python
# 每日只用历史数据
history = prices.loc[:date]
ma60 = history['close'].rolling(60).mean()
regime = detect_regime(history).iloc[-1]
```

### 陷阱2：状态抖动
❌ **问题**：状态频繁切换（今天BULL，明天BEAR，后天BULL）

✅ **解决**：防抖逻辑（状态至少持续3天）
```python
def apply_hysteresis(regime_series, min_duration=3):
    """状态防抖"""
    result = regime_series.copy()
    for i in range(len(regime_series)):
        if i < min_duration:
            continue
        recent = regime_series.iloc[i-min_duration+1:i+1]
        if recent.nunique() > 1:  # 最近N天状态不一致
            result.iloc[i] = result.iloc[i-1]  # 保持前一状态
    return result
```

### 陷阱3：仓位过度激进
❌ **问题**：牛市全仓（2.0），熊市空仓（0.0）→ 风险过大

✅ **解决**：仓位限制在 [0.3, 2.0]
```python
position = np.clip(position, 0.3, 2.0)
```

### 陷阱4：硬编码参数
❌ **错误**：
```python
if momentum_signal > 0.02:  # 魔数
    regime = 'BULL'
```

✅ **正确**：
```python
MOMENTUM_THRESHOLD_BULL = 0.02  # 常量
if momentum_signal > MOMENTUM_THRESHOLD_BULL:
    regime = 'BULL'
```

---

## 验收清单

### 代码交付物
- [ ] `src/risk/market_regime_detector.py`（200-250行）
- [ ] `src/risk/dynamic_position_sizer.py`（150-200行）
- [ ] `tests/test_market_regime_detector.py`（5个测试）
- [ ] `tests/test_dynamic_position_sizer.py`（6个测试）
- [ ] `src/analysis/green_backtest_runner.py`（已修改，新增50-80行）

### 报告交付物
- [ ] `reports/绿电板块_增强版回测报告.md`（完整的5章节）
- [ ] `reports/backtest_results_enhanced.json`（结构化数据）
- [ ] `reports/figures/enhanced_equity_curve.png`（净值曲线）
- [ ] `reports/figures/market_regime_timeline.png`（状态时间轴）
- [ ] `reports/figures/dynamic_position_series.png`（仓位序列）
- [ ] `reports/figures/regime_returns_boxplot.png`（收益箱线图）

### 质量验收
- [ ] 所有单元测试通过（至少11个）
- [ ] Sharpe Ratio ≥ 1.31（✅ 提升>10%）
- [ ] 最大回撤 ≤ 15%
- [ ] 无前视偏差（时间因果性检查通过）
- [ ] 无硬编码路径（支持跨机器运行）
- [ ] 代码无warning（mypy/pylint检查通过）
- [ ] Type hints完整（函数签名100%覆盖）
- [ ] Docstring完整（公共接口100%覆盖）

---

## 预期时间分配

| 任务 | 预计时间 | 关键风险 |
|------|---------|---------|
| A1: 市场状态机 | 1.0天 | 防抖逻辑调试 |
| A2: 动态仓位 | 0.8天 | 参数调优 |
| A3: 集成回测 | 0.5天 | 前视偏差检查 |
| A4: 回测报告 | 0.5天 | 图表生成 |
| A5: 测试验证 | 0.5天 | Sharpe不达标风险 |
| **总计** | **3.3天** | - |
| 缓冲时间 | 0.7天 | 处理意外问题 |
| **带缓冲** | **4.0天** | - |

---

## 紧急联系

**如果遇到以下情况，立即反馈**：

### 阻塞性问题
1. ❌ Sharpe提升不足10%（<1.31）
   - **备用方案**：降低目标到8%，或在存储/黄金板块应用方向校准
   
2. ❌ 数据缺失（无法计算ATR/MA）
   - **解决**：检查 `data/processed/green_energy/` 路径
   - **联系**：提供数据样例给DeepSeek

3. ❌ 测试失败率>20%
   - **解决**：先确保核心功能正确，测试可稍后完善

### 设计问题
4. ⚠️ 市场状态判断不合理（如：持续熊市中出现大量牛市判定）
   - **调整**：放宽阈值或增加滤波窗口
   - **参考**：`Gemini任务包_系统优化.md` 中的备选参数

5. ⚠️ 仓位波动过大（日间变化>50%）
   - **调整**：增加平滑逻辑（exponential moving average）

---

## 成功标准（必须全部达成）

1. ✅ **Sharpe Ratio ≥ 1.31**（核心目标）
2. ✅ 最大回撤 ≤ 15%（风控底线）
3. ✅ 测试覆盖率 ≥ 90%（代码质量）
4. ✅ 报告完整（4张图 + Markdown + JSON）
5. ✅ 零前视偏差（时间因果性验证）

---

**任务开始时间**：待定  
**预期完成时间**：开始后4个工作日  
**交付给**：项目负责人吴宇轩

**祝开发顺利！如有疑问随时沟通。**
