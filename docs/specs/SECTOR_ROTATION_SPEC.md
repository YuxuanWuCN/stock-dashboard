# 板块轮动系统实现规范

**版本**: v1.0  
**创建日期**: 2025-01-12  
**状态**: 待实现

---

## 📋 需求概述

### 业务目标

实现一个基于 LLM 情绪分析的自适应板块轮动系统，能够：
1. 实时监控各板块的市场情绪
2. 当某个板块下沉时，自动识别并切换到其他板块
3. 决策过程可解释、可追溯
4. 与现有的 Rainbow-FinGPT v2.6 情绪分析系统无缝集成

### 成功标准

| 指标 | 目标值 |
|------|--------|
| 板块情绪识别准确率 | ≥ 85% |
| 切换决策延迟 | ≤ 1 个交易日 |
| 回测夏普比率提升 | ≥ 0.3 |
| 系统可用性 | ≥ 99% |

---

## 🏗️ 系统架构

### 整体架构图

```
┌─────────────────────────────────────────────────────────┐
│                   板块轮动系统                           │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────┐│
│  │ 数据采集层   │───▶│ 情绪分析层   │───▶│ 决策层    ││
│  └──────────────┘    └──────────────┘    └───────────┘│
│         │                    │                   │      │
│         ▼                    ▼                   ▼      │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────┐│
│  │ 新闻抓取     │    │ 情绪聚合     │    │ 轮动引擎  ││
│  │ K线数据      │    │ 板块评分     │    │ 仓位管理  ││
│  │ 行业指标     │    │ 风险评估     │    │ 执行监控  ││
│  └──────────────┘    └──────────────┘    └───────────┘│
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 核心模块

#### 1. 板块情绪聚合模块 (`sector_sentiment_aggregator.py`)

**职责**：
- 从个股情绪聚合到板块情绪
- 计算板块情绪分数、趋势、波动率
- 识别板块情绪转折点

**输入**：
```python
{
    "stocks": [
        {
            "code": "300750",
            "name": "宁德时代",
            "sector": "green",
            "sentiment_score": 0.75,  # [-1, 1]
            "sentiment_confidence": 0.88,
            "news_count": 15,
            "timestamp": "2025-01-12 15:00:00"
        },
        ...
    ]
}
```

**输出**：
```python
{
    "sectors": {
        "green": {
            "sentiment_score": 0.68,        # 板块平均情绪 [-1, 1]
            "sentiment_trend": "declining",  # rising | stable | declining
            "volatility": 0.15,              # 情绪波动率
            "stock_count": 6,
            "confidence": 0.82,
            "last_updated": "2025-01-12 15:00:00"
        },
        "storage": {...},
        "gold": {...}
    }
}
```

#### 2. 板块轮动决策引擎 (`sector_rotation_engine.py`)

**职责**：
- 基于板块情绪、技术指标、宏观因子做轮动决策
- 实现多种轮动策略（动量、均值回归、风险平价）
- LLM 辅助决策（可解释性）

**核心算法**：

```python
class SectorRotationEngine:
    def decide(self, sector_sentiments, market_state):
        """主决策逻辑"""
        
        # 步骤1: 量化评分
        scores = self._calculate_sector_scores(sector_sentiments)
        
        # 步骤2: 识别下沉板块
        declining_sectors = self._identify_declining(scores)
        
        # 步骤3: 选择目标板块
        target_sector = self._select_target_sector(
            current_sector=market_state.current_sector,
            scores=scores,
            declining_sectors=declining_sectors
        )
        
        # 步骤4: LLM 辅助决策（可解释性）
        decision = self._llm_validate_decision(
            current_sector=market_state.current_sector,
            target_sector=target_sector,
            reason=self._generate_reason(scores)
        )
        
        return decision
```

**决策规则**：

| 条件 | 动作 | 理由 |
|------|------|------|
| 当前板块情绪 < -0.3 | 触发轮动 | 板块明显恶化 |
| 情绪连续 3 日下降 | 触发轮动 | 趋势确认 |
| 目标板块情绪 > 0.5 | 切换到目标板块 | 新板块吸引力强 |
| 所有板块情绪 < 0 | 切换到防御板块（黄金） | 市场整体恶化 |

#### 3. LLM 辅助决策模块 (`llm_decision_advisor.py`)

**职责**：
- 用 LLM 解释轮动决策
- 生成可读的决策报告
- 异常情况预警

**Prompt 设计**：

```python
DECISION_PROMPT = """
你是 Rainbow-FinGPT 的板块轮动决策顾问。

当前状态：
- 持仓板块: {current_sector}
- 板块情绪: {current_sentiment:.2f}
- 情绪趋势: {trend}

候选板块：
{candidate_sectors}

请分析：
1. 当前板块是否需要轮动？（是/否）
2. 如果需要，推荐切换到哪个板块？
3. 决策理由（150字以内）

输出格式：
{{
    "should_rotate": true/false,
    "target_sector": "板块代码",
    "reason": "决策理由",
    "confidence": 0.0-1.0
}}
"""
```

#### 4. 仓位管理模块 (`position_manager.py`)

**职责**：
- 管理板块切换时的仓位调整
- 实现渐进式切换（避免冲击成本）
- 风险控制

**切换策略**：

```python
class PositionManager:
    def execute_rotation(self, from_sector, to_sector, capital):
        """执行板块轮动"""
        
        # 渐进式切换（3日完成）
        schedule = [
            {"day": 1, "sell_ratio": 0.5, "buy_ratio": 0.5},
            {"day": 2, "sell_ratio": 0.3, "buy_ratio": 0.3},
            {"day": 3, "sell_ratio": 0.2, "buy_ratio": 0.2},
        ]
        
        for step in schedule:
            # 卖出旧板块
            self._sell_sector(from_sector, capital * step["sell_ratio"])
            # 买入新板块
            self._buy_sector(to_sector, capital * step["buy_ratio"])
            # 等待 1 个交易日
            time.sleep(ONE_TRADING_DAY)
```

---

## 📐 数据模型

### 板块定义

```python
SECTORS = {
    "green": {
        "name": "绿电公用事业与新能源",
        "stocks": ["001258", "002459", "002466", "601012", "600438", "300750"],
        "benchmark": "000688",  # 科创50
        "characteristics": ["政策驱动", "长期趋势", "周期性波动"],
    },
    "storage": {
        "name": "存储芯片超级周期",
        "stocks": ["688525", "688123", "603986", "688041", "688008", "002049"],
        "benchmark": "000688",  # 科创50
        "characteristics": ["美股传导", "供需周期", "技术迭代"],
    },
    "gold": {
        "name": "黄金地缘避险与大宗慢牛",
        "stocks": ["600547", "601899", "600489", "002155", "000975", "600988", "600362"],
        "benchmark": "000001",  # 上证指数
        "characteristics": ["避险属性", "美元反向", "地缘政治"],
    },
}
```

### 板块状态

```python
@dataclass
class SectorState:
    """板块状态"""
    sector_id: str
    sentiment_score: float          # [-1, 1]
    sentiment_trend: str            # rising | stable | declining
    momentum: float                 # 动量指标
    volatility: float               # 波动率
    confidence: float               # 置信度
    stock_sentiments: List[float]   # 个股情绪列表
    last_updated: datetime
```

### 轮动决策

```python
@dataclass
class RotationDecision:
    """轮动决策"""
    timestamp: datetime
    from_sector: str
    to_sector: str
    reason: str
    confidence: float
    llm_validation: dict
    metrics: dict  # 决策时的各项指标
```

---

## 🔧 技术实现细节

### 依赖库

```python
# 核心依赖
pandas>=2.0.0
numpy>=1.24.0
akshare>=1.12.0

# LLM 相关（已有）
openai>=1.0.0
anthropic>=0.7.0

# 可视化（可选）
matplotlib>=3.7.0
plotly>=5.14.0
```

### 配置文件

**`src/sector_rotation/config.py`**

```python
# 板块轮动配置
ROTATION_ENABLED = True

# 决策阈值
SENTIMENT_DECLINE_THRESHOLD = -0.3   # 情绪下降阈值
TREND_CONFIRM_DAYS = 3               # 趋势确认天数
MIN_TARGET_SENTIMENT = 0.5           # 目标板块最低情绪

# 仓位管理
ROTATION_EXECUTION_DAYS = 3          # 轮动执行天数
TRANSACTION_COST_RATE = 0.001        # 交易成本率

# LLM 辅助
LLM_VALIDATION_ENABLED = True        # 是否使用 LLM 验证
LLM_TIMEOUT = 30                     # LLM 调用超时（秒）

# 风险控制
MAX_ROTATION_PER_MONTH = 3           # 每月最多轮动次数
MIN_HOLDING_DAYS = 5                 # 最短持仓天数
```

---

## 🧪 测试计划

### 单元测试

#### 1. 情绪聚合测试

```python
def test_sentiment_aggregation():
    """测试板块情绪聚合"""
    stocks = [
        {"code": "300750", "sentiment": 0.8},
        {"code": "600438", "sentiment": 0.6},
        {"code": "601012", "sentiment": 0.7},
    ]
    
    aggregator = SectorSentimentAggregator()
    result = aggregator.aggregate(stocks, sector="green")
    
    assert result.sentiment_score == pytest.approx(0.7, abs=0.01)
    assert result.confidence > 0.8
```

#### 2. 决策引擎测试

```python
def test_rotation_decision():
    """测试轮动决策逻辑"""
    engine = SectorRotationEngine()
    
    # 模拟板块情绪数据
    sentiments = {
        "green": {"sentiment": -0.4, "trend": "declining"},
        "gold": {"sentiment": 0.6, "trend": "rising"},
    }
    
    decision = engine.decide(sentiments, current_sector="green")
    
    assert decision.should_rotate == True
    assert decision.target_sector == "gold"
    assert decision.confidence > 0.7
```

### 回测验证

#### 回测场景

| 场景 | 时间段 | 市场环境 | 预期结果 |
|------|--------|----------|----------|
| 场景1 | 2024-01-01 ~ 2024-12-31 | 板块轮动明显 | 夏普比率 ↑ 0.3 |
| 场景2 | 2024-06-01 ~ 2024-12-31 | 市场震荡 | 回撤 ↓ 15% |
| 场景3 | 2024-09-01 ~ 2024-12-31 | 单边下跌 | 避险成功 |

#### 回测指标

```python
backtest_metrics = {
    "total_return": 0.0,        # 总收益率
    "sharpe_ratio": 0.0,        # 夏普比率
    "max_drawdown": 0.0,        # 最大回撤
    "win_rate": 0.0,            # 胜率
    "rotation_count": 0,        # 轮动次数
    "avg_holding_days": 0,      # 平均持仓天数
}
```

---

## 📂 文件结构

```
src/sector_rotation/
├── __init__.py
├── config.py                       # 配置文件
├── sector_sentiment_aggregator.py  # 板块情绪聚合
├── sector_rotation_engine.py       # 轮动决策引擎
├── llm_decision_advisor.py         # LLM 辅助决策
├── position_manager.py             # 仓位管理
├── backtest/
│   ├── __init__.py
│   ├── backtest_engine.py          # 回测引擎
│   └── performance_metrics.py      # 绩效指标
└── utils/
    ├── __init__.py
    └── sector_utils.py              # 工具函数

tests/sector_rotation/
├── test_aggregator.py
├── test_engine.py
├── test_advisor.py
├── test_position_manager.py
└── test_backtest.py

docs/sector_rotation/
├── DESIGN.md                        # 设计文档
├── API.md                           # API 文档
└── BACKTEST_REPORT.md               # 回测报告
```

---

## 🎯 实现里程碑

### 阶段 1: 基础框架（第 1-2 周）

**任务**：
- [ ] 创建模块文件结构
- [ ] 实现板块情绪聚合模块
- [ ] 实现基础的轮动决策逻辑
- [ ] 编写单元测试

**交付物**：
- `sector_sentiment_aggregator.py` ✓
- `sector_rotation_engine.py` ✓
- 单元测试覆盖率 ≥ 80%

### 阶段 2: LLM 集成（第 3 周）

**任务**：
- [ ] 实现 LLM 辅助决策模块
- [ ] 设计决策 Prompt
- [ ] 集成到轮动引擎
- [ ] 验证决策质量

**交付物**：
- `llm_decision_advisor.py` ✓
- LLM 决策准确率 ≥ 85%

### 阶段 3: 仓位管理（第 4 周）

**任务**：
- [ ] 实现渐进式切换逻辑
- [ ] 风险控制机制
- [ ] 交易成本模拟
- [ ] 执行监控

**交付物**：
- `position_manager.py` ✓
- 切换成本 ≤ 1%

### 阶段 4: 回测验证（第 5-6 周）

**任务**：
- [ ] 实现回测引擎
- [ ] 运行历史数据回测
- [ ] 性能指标分析
- [ ] 生成回测报告

**交付物**：
- `backtest_engine.py` ✓
- 回测报告 ✓
- 夏普比率提升 ≥ 0.3

### 阶段 5: 上线部署（第 7 周）

**任务**：
- [ ] 集成到主系统
- [ ] 实盘模拟测试
- [ ] 监控告警
- [ ] 文档完善

**交付物**：
- 生产环境部署 ✓
- 监控面板 ✓
- 用户文档 ✓

---

## 🚨 风险与应对

### 风险 1: LLM 决策不稳定

**表现**：LLM 对同样输入给出不同决策  
**影响**：决策一致性差，回测难以复现  
**应对**：
1. 降低 temperature 到 0.2
2. 使用确定性种子
3. LLM 只做辅助，量化指标为主

### 风险 2: 频繁轮动

**表现**：系统频繁切换板块  
**影响**：交易成本高，影响收益  
**应对**：
1. 设置 `MIN_HOLDING_DAYS = 5`
2. 提高情绪阈值（更严格）
3. 引入"冷却期"机制

### 风险 3: 数据延迟

**表现**：新闻数据更新不及时  
**影响**：决策滞后，错过时机  
**应对**：
1. 使用多数据源
2. 设置数据新鲜度检查
3. 失败时用历史数据降级

### 风险 4: 回测过拟合

**表现**：回测表现好，实盘表现差  
**影响**：系统不可用  
**应对**：
1. Walk-forward 测试
2. 不同市场环境验证
3. 参数稳健性测试

---

## 📚 参考文献

### 核心论文

1. **Sector Rotation Strategies in the TSX 60** (2025)
   - 板块轮动实证研究
   - https://www.mdpi.com/1911-8074/19/1/70

2. **Language Model Guided Reinforcement Learning in Quantitative Trading** (2024)
   - LLM 指导 RL 做决策
   - https://arxiv.org/html/2508.02366v1

3. **FinSentLLM: Multi-LLM and Structured Semantic Signals** (2024)
   - 多 LLM 情绪预测
   - https://arxiv.org/pdf/2509.12638

### 技术文档

1. **Rainbow-FinGPT v2.6 改进文档**
   - `docs/IMPROVEMENT_V2.6.md`

2. **情绪分析 API 文档**
   - `src/llm/llm_sentiment.py`

---

## ✅ 验收标准

### 功能验收

- [ ] 能实时监控 3 个板块的情绪
- [ ] 能自动识别板块下沉并触发轮动
- [ ] 能生成可解释的决策报告
- [ ] 能执行渐进式仓位切换

### 性能验收

- [ ] 板块情绪识别准确率 ≥ 85%
- [ ] 决策延迟 ≤ 1 个交易日
- [ ] 回测夏普比率提升 ≥ 0.3
- [ ] 系统可用性 ≥ 99%

### 代码验收

- [ ] 单元测试覆盖率 ≥ 80%
- [ ] 代码符合 PEP 8 规范
- [ ] 所有函数有类型注解和文档字符串
- [ ] 无明显性能瓶颈

---

**创建者**: Claude (Kiro AI Assistant)  
**审核者**: 待指定  
**最后更新**: 2025-01-12
