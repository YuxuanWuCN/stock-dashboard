# 期货商品板块轮动系统 - 4 周实操规划

**项目**: Rainbow-FinGPT 期货端板块轮动 v1.0  
**时间**: 4 周  
**工作量**: ~120 人天  
**难度**: ⭐⭐⭐（中等）

---

## 🎯 项目目标

构建一个日频的期货商品板块自动轮动系统：
- 基于 NALE 因子的期货合约评分
- 自动识别板块机会
- 日频轮动决策
- 可回测验证

---

## 📊 板块定义

### 四大商品板块

```
1. 农产品 (AGRI)
   - 豆粕 (M)、豆油 (OI)、菜粕 (RM)
   
2. 黑色 (BLACK)
   - 焦煤 (JM)、焦炭 (J)、铁矿 (I)、螺纹 (RB)
   
3. 能源 (ENERGY)
   - 原油 (SC)、燃油 (FU)、天然气 (NG)
   
4. 金属 (METALS)
   - 铜 (CU)、铝 (AL)、锌 (ZN)、铅 (PB)
```

---

## 🏗️ 系统架构

```
历史期货数据 (NALE + K线)
        ↓
┌───────────────────────┐
│  NALE 因子计算        │ ← Agent-B (第1周)
│  (按合约逐日计算)     │
└───────────────────────┘
        ↓
┌───────────────────────┐
│  板块聚合评分        │ ← Agent-C (第1周)
│  (4个板块评分)       │
└───────────────────────┘
        ↓
┌───────────────────────┐
│  轮动决策引擎        │ ← Agent-D (第2周)
│  (规则：评分 > 阈值) │
└───────────────────────┘
        ↓
┌───────────────────────┐
│  持仓管理执行        │ ← Agent-E (第2周)
│  (资金分配 + 下单)   │
└───────────────────────┘
        ↓
┌───────────────────────┐
│  回测 + 性能报告      │ ← Agent-F (第3周)
│  (Sharpe、回撤等)    │
└───────────────────────┘
```

---

## 📋 4 周详细任务

### 第 1 周：数据准备 & NALE 计算

#### 任务 1.1: 期货数据管道 (Agent-A)
**工作**: 
- 从 CFFEX/DCE/CZCE/SHFE 获取期货历史数据
- 标准化数据格式（统一到日频）
- 本地存储 SQLite / Parquet

**输出**:
- `data/futures/AGRI.parquet` (日期, 合约, OHLCV)
- `data/futures/BLACK.parquet`
- `data/futures/ENERGY.parquet`
- `data/futures/METALS.parquet`

**验收**: 数据覆盖 2023-01-01 ~ 今日，无缺失值

---

#### 任务 1.2: NALE 因子期货版 (Agent-B)
**工作**:
- 改造现有 `nale_alpha_pipeline.py` 支持期货合约
- 逐日计算每个期货合约的 NALE 因子
  - PC1-PC10 主成分
  - 贡献度（contribution）
  - alpha_nale 最终评分 [-1, 1]

**代码框架**:
```python
class NaleForFutures:
    def compute_daily(self, contract_code, date):
        """
        输入: 期货合约代码 (如 'M2501'), 日期
        输出: {
            'PC01': 0.5,
            'PC02': -0.3,
            ...
            'alpha_nale': 0.65,  # [-1, 1]
            'S0': 500,  # 样本数
        }
        """
        pass
```

**输出**:
- `results/nale_futures_daily.csv` 
  (date, contract, PC01-PC10, alpha_nale, S0)

**验收**: 覆盖所有 12 个期货合约，无 NaN 值

---

#### 任务 1.3: 板块聚合评分 (Agent-C)
**工作**:
- 每日聚合 4 个板块的 NALE 评分
- 方法：加权平均（按交易量权重）或简单平均

**代码框架**:
```python
class SectorAggregator:
    def aggregate_daily(self, date):
        """
        输入: 日期
        输出: {
            'AGRI': 0.52,      # 农产品板块评分
            'BLACK': -0.15,    # 黑色板块评分
            'ENERGY': 0.38,    # 能源板块评分
            'METALS': 0.21,    # 金属板块评分
        }
        """
        pass
```

**输出**:
- `results/sector_scores_daily.csv`
  (date, AGRI, BLACK, ENERGY, METALS)

**验收**: 连续时间序列，评分在 [-1, 1] 之间

---

### 第 2 周：决策引擎 & 执行

#### 任务 2.1: 轮动决策规则 (Agent-D)
**工作**:
- 简单规则：每日判断是否轮动
- 规则设计：
  - 当前持仓板块评分 < -0.2 时，触发轮动
  - 评分最高的板块为目标
  - 冷却期：轮动后 3 天不再轮动

**代码框架**:
```python
class RotationEngine:
    def decide_daily(self, current_sector, sector_scores):
        """
        输入: 当前持仓板块, 4个板块今日评分
        输出: {
            'should_rotate': True/False,
            'target_sector': 'BLACK',  # 如果要轮动
            'reason': '评分下降, 目标板块强势',
            'confidence': 0.85
        }
        """
        pass
```

**输出**:
- `results/rotation_decisions_daily.csv`
  (date, current, target, should_rotate, reason)

**验收**: 决策规则清晰、可追溯

---

#### 任务 2.2: 持仓管理执行 (Agent-E)
**工作**:
- 管理资金分配（4 个板块）
- 轮动时的仓位切换逻辑
- 成本控制（交易手续费、滑点）

**代码框架**:
```python
class PositionManager:
    def execute_rotation(self, from_sector, to_sector):
        """
        输入: 从哪个板块, 到哪个板块
        执行:
        1. 卖出 from_sector 的所有合约
        2. 买入 to_sector 的主力合约
        3. 记录交易日志
        """
        pass
    
    def get_current_holdings(self):
        """
        输出: {
            'AGRI': 1000000,     # 农产品持仓(元)
            'BLACK': 500000,
            'ENERGY': 0,
            'METALS': 1500000,
        }
        """
        pass
```

**输出**:
- `results/holdings_daily.csv`
  (date, AGRI_position, BLACK_position, ENERGY_position, METALS_position)
- `results/trades_daily.csv`
  (date, action, sector, contract, volume, price)

**验收**: 仓位变化合理，成本可追踪

---

### 第 3 周：回测 & 性能分析

#### 任务 3.1: 回测引擎 (Agent-F)
**工作**:
- 日频回测整个系统（2023-01-01 ~ 今日）
- 模拟交易成本、滑点
- 计算净值曲线

**代码框架**:
```python
class BacktestEngine:
    def run(self, start_date, end_date, initial_capital=1000000):
        """
        输入: 起始日期, 结束日期, 初始资金
        输出: {
            'daily_nav': [...],      # 每日净值
            'daily_returns': [...],  # 每日收益率
            'trades': [...],         # 成交记录
        }
        """
        pass
```

**输出**:
- `results/backtest_nav.csv` (date, nav, cum_return)
- `results/backtest_trades.csv` (date, action, sector, pnl)

**验收**: 回测完整、无错误、数据合理

---

#### 任务 3.2: 性能报告 (Agent-F)
**工作**:
- 计算性能指标
  - 总收益率
  - 年化收益率
  - 最大回撤
  - Sharpe 比率
  - 轮动次数
  - 平均持仓天数
- 生成图表：净值曲线、回撤、板块切换历史

**输出**:
- `results/performance_report.md` (详细报告)
- `results/backtest_chart.png` (图表)

**验收**: 指标清晰、图表清楚、结论有据

---

### 第 4 周：测试 & 上线

#### 任务 4.1: 代码审核 & 优化 (Agent-A)
**工作**:
- Code review：所有代码
- 性能优化：加速计算
- 文档完善：API 文档

**输出**:
- 代码审核报告
- 性能基准
- 完整的 API 文档

**验收**: 代码无 bug、性能满足

---

#### 任务 4.2: 模拟实盘 & 部署 (Agent-A + Agent-E)
**工作**:
- 纸面交易测试（1-2 周）
- 监控告警设置
- 上线前检查清单

**输出**:
- 部署清单
- 监控面板
- 故障处理指南

**验收**: 系统可上线

---

## 👥 Team 分配

| Agent | 角色 | 任务 | 周期 |
|-------|------|------|------|
| **A** | 工程师 | 1.1 + 4.1 + 4.2 | 1/4周 |
| **B** | 算法 | 1.2 (NALE计算) | 1周 |
| **C** | 数据 | 1.3 (聚合) | 1周 |
| **D** | 策略 | 2.1 (决策规则) | 2周 |
| **E** | 交易 | 2.2 (仓位管理) | 2周 |
| **F** | 分析 | 3.1 + 3.2 (回测) | 3周 |

**并行执行**:
- 第1周: A, B, C 并行
- 第2周: D, E 并行
- 第3周: F
- 第4周: A

---

## 📂 文件结构

```
src/commodity_rotation/
├── nale_futures.py          # NALE 期货计算
├── sector_aggregator.py     # 板块聚合
├── rotation_engine.py       # 决策引擎
├── position_manager.py      # 仓位管理
├── backtest_engine.py       # 回测引擎
└── config.py                # 配置

data/futures/
├── AGRI.parquet
├── BLACK.parquet
├── ENERGY.parquet
└── METALS.parquet

results/
├── nale_futures_daily.csv
├── sector_scores_daily.csv
├── rotation_decisions_daily.csv
├── holdings_daily.csv
├── trades_daily.csv
├── backtest_nav.csv
└── performance_report.md
```

---

## ✅ 验收标准

### 功能验收
- [ ] NALE 因子计算准确（与原实现对齐）
- [ ] 板块评分每日更新
- [ ] 轮动决策规则清晰可追溯
- [ ] 回测完整无错误

### 性能验收
- [ ] 回测 Sharpe 比率 > 1.0（vs 基准）
- [ ] 最大回撤 ≤ 20%
- [ ] 年化收益率 > 15%

### 代码验收
- [ ] 单元测试覆盖 ≥ 80%
- [ ] 代码符合 PEP 8
- [ ] 完整的文档字符串

---

## 🚀 启动方式

1. **Agent-A** 创建目录结构 + 拉取期货数据
2. **Agent-B** 开始 NALE 计算
3. **Agent-C** 等 B 完成后做聚合
4. **Agent-D** 写决策规则
5. **Agent-E** 写仓位管理
6. **Agent-F** 等数据全部完成后回测
7. **Agent-A** 代码审核 + 部署

---

## 📞 快速问题

**Q: 需要多长时间?**  
A: 4 周，如果 6 个 Agent 并行

**Q: 能赚钱吗?**  
A: 回测决定。Sharpe > 1.0 = 可期

**Q: 成本多少?**  
A: 交易成本 ~0.1% per round（国内期货手续费较低）

**Q: 何时启动?**  
A: 看你何时说"开始"

---

**就这么简单！清晰、直接、可执行。**

**准备好了吗？** 💪
