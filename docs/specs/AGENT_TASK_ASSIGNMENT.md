# 板块轮动系统 - 子 Agent 任务分配

**项目**: Rainbow-FinGPT 板块轮动系统 v1.0  
**总体时间**: 7 周  
**分阶段交付**

---

## 📋 任务分解

### 阶段 1: 基础框架（第 1-2 周）

#### 任务 1.1: 项目结构搭建

**分配给**: Agent-1 (工程师)  
**难度**: ⭐⭐  
**时间**: 2 天

**具体任务**：
1. 创建 `src/sector_rotation/` 目录结构
2. 创建 `src/sector_rotation/__init__.py`
3. 创建 `src/sector_rotation/config.py`（按 SPEC 复制）
4. 创建 `tests/sector_rotation/` 目录
5. 确保目录结构与 `SECTOR_ROTATION_SPEC.md` 一致

**验收标准**：
```
src/sector_rotation/
├── __init__.py ✓
├── config.py ✓
├── backtest/ ✓
└── utils/ ✓

tests/sector_rotation/ ✓
```

**输出物**：
- 完整的目录结构
- 配置文件模板

---

#### 任务 1.2: 板块情绪聚合模块

**分配给**: Agent-2 (数据处理)  
**难度**: ⭐⭐⭐  
**时间**: 5 天

**具体任务**：

1. **实现 `SectorSentimentAggregator` 类**（`src/sector_rotation/sector_sentiment_aggregator.py`）

```python
class SectorSentimentAggregator:
    """聚合个股情绪到板块情绪"""
    
    def aggregate(self, stocks, sector):
        """
        输入：股票列表 + 板块
        输出：板块情绪分数、趋势、波动率
        """
        pass
    
    def calculate_trend(self, historical_scores):
        """判断情绪趋势（上升/稳定/下降）"""
        pass
    
    def calculate_volatility(self, scores):
        """计算情绪波动率"""
        pass
```

2. **关键计算**：
   - 平均情绪分数（加权平均）
   - 趋势识别（3 日 MA vs 实际值）
   - 波动率（标准差）
   - 置信度（基于样本数量和一致性）

3. **单元测试**：
   - 测试基本聚合逻辑
   - 测试边界情况（单只股票、全部为 0 等）
   - 测试历史数据

**验收标准**：
- [ ] 代码完成，符合 PEP 8
- [ ] 单元测试覆盖 ≥ 90%
- [ ] 文档字符串完整
- [ ] 与 v2.6 情绪分析 API 兼容

**输出物**：
- `sector_sentiment_aggregator.py`
- `test_aggregator.py`

---

#### 任务 1.3: 轮动决策引擎基础

**分配给**: Agent-3 (算法)  
**难度**: ⭐⭐⭐⭐  
**时间**: 6 天

**具体任务**：

1. **实现 `SectorRotationEngine` 类**（`src/sector_rotation/sector_rotation_engine.py`）

```python
class SectorRotationEngine:
    """板块轮动决策引擎"""
    
    def decide(self, sector_sentiments, market_state):
        """
        主决策方法
        输入：各板块情绪、当前市场状态
        输出：轮动决策（是否轮动、目标板块、理由）
        """
        pass
    
    def _identify_declining(self, scores):
        """识别下沉板块"""
        pass
    
    def _calculate_scores(self, sentiments):
        """计算板块评分"""
        pass
    
    def _select_target(self, current, candidates):
        """选择目标板块"""
        pass
```

2. **决策规则**（按 SPEC 实现）：
   - 情绪 < -0.3 触发轮动
   - 趋势连续 3 日下降确认
   - 目标板块情绪 > 0.5

3. **边界处理**：
   - 所有板块都恶化 → 切换到黄金（防御）
   - 没有好的候选 → 保持持仓
   - 冷却期内 → 不轮动

4. **单元测试**：
   - 测试各种情绪组合
   - 测试决策一致性
   - 测试边界情况

**验收标准**：
- [ ] 代码完成
- [ ] 单元测试覆盖 ≥ 85%
- [ ] 决策规则与 SPEC 一致
- [ ] 性能满足要求（决策 < 100ms）

**输出物**：
- `sector_rotation_engine.py`
- `test_engine.py`

---

#### 任务 1.4: 集成测试

**分配给**: Agent-1 (QA)  
**难度**: ⭐⭐  
**时间**: 3 天

**具体任务**：
1. 集成情绪聚合 + 决策引擎
2. 测试端到端流程
3. 性能基准测试
4. 生成测试报告

**输出物**：
- 集成测试报告
- 性能基准

---

### 阶段 2: LLM 集成（第 3 周）

#### 任务 2.1: LLM 辅助决策模块

**分配给**: Agent-4 (LLM)  
**难度**: ⭐⭐⭐⭐  
**时间**: 5 天

**具体任务**：

1. **实现 `LLMDecisionAdvisor` 类**（`src/sector_rotation/llm_decision_advisor.py`）

```python
class LLMDecisionAdvisor:
    """LLM 辅助决策"""
    
    def validate_decision(self, quantitative_decision, sector_data):
        """
        LLM 验证量化决策
        输入：量化决策、板块数据
        输出：LLM 验证结果（同意/反对 + 理由）
        """
        pass
    
    def generate_reasoning(self, quantitative_scores):
        """生成决策理由"""
        pass
```

2. **Prompt 设计**（在 SPEC 基础上迭代）：
   - 系统提示词
   - Few-shot 示例
   - 输出格式

3. **LLM 集成**：
   - 与 v2.6 情绪分析系统复用 LLM 客户端
   - 使用轻量模型（Gemini Flash）
   - 重试机制

4. **单元测试**：
   - 模拟 LLM 响应
   - 验证响应解析
   - 边界测试

**验收标准**：
- [ ] LLM 调用成功率 ≥ 99%
- [ ] 响应延迟 ≤ 5 秒
- [ ] 决策理由清晰易懂
- [ ] 与量化决策一致性 ≥ 85%

**输出物**：
- `llm_decision_advisor.py`
- `test_advisor.py`

---

#### 任务 2.2: 决策融合

**分配给**: Agent-3 (算法)  
**难度**: ⭐⭐⭐  
**时间**: 3 天

**具体任务**：
1. 修改 `SectorRotationEngine`，集成 LLM 验证
2. 实现决策融合逻辑（量化 + LLM）
3. 可解释性增强
4. 测试决策质量

**输出物**：
- 更新后的 `sector_rotation_engine.py`
- 融合测试报告

---

### 阶段 3: 仓位管理（第 4 周）

#### 任务 3.1: 仓位管理模块

**分配给**: Agent-5 (交易)  
**难度**: ⭐⭐⭐  
**时间**: 5 天

**具体任务**：

1. **实现 `PositionManager` 类**（`src/sector_rotation/position_manager.py`）

```python
class PositionManager:
    """仓位管理"""
    
    def execute_rotation(self, from_sector, to_sector, capital):
        """执行板块轮动"""
        pass
    
    def _gradual_exit(self, sector, schedule):
        """渐进式卖出"""
        pass
    
    def _gradual_entry(self, sector, schedule):
        """渐进式买入"""
        pass
    
    def calculate_transaction_cost(self, volume, price):
        """计算交易成本"""
        pass
```

2. **渐进式切换**（3 日完成）：
   - 第 1 日：卖出 50%，买入 50%
   - 第 2 日：卖出 30%，买入 30%
   - 第 3 日：卖出 20%，买入 20%

3. **成本控制**：
   - 交易成本模拟（按 0.1% 计）
   - 滑点估算
   - 风险控制检查

4. **监控**：
   - 切换进度跟踪
   - 异常告警

**验收标准**：
- [ ] 切换成本 ≤ 1%
- [ ] 代码完成，测试覆盖 ≥ 85%
- [ ] 文档完整

**输出物**：
- `position_manager.py`
- `test_position_manager.py`

---

#### 任务 3.2: 风险控制

**分配给**: Agent-3 (算法)  
**难度**: ⭐⭐⭐  
**时间**: 3 天

**具体任务**：
1. 实现频率控制（每月 ≤ 3 次）
2. 实现最短持仓（≥ 5 日）
3. 实现冷却期机制
4. 测试风险场景

**输出物**：
- 风险控制模块
- 压力测试报告

---

### 阶段 4: 回测验证（第 5-6 周）

#### 任务 4.1: 回测引擎

**分配给**: Agent-6 (回测)  
**难度**: ⭐⭐⭐⭐  
**时间**: 7 天

**具体任务**：

1. **实现 `BacktestEngine` 类**（`src/sector_rotation/backtest/backtest_engine.py`）

```python
class BacktestEngine:
    """回测引擎"""
    
    def run(self, start_date, end_date, initial_capital):
        """运行回测"""
        pass
    
    def _simulate_day(self, date):
        """模拟单个交易日"""
        pass
    
    def calculate_metrics(self):
        """计算绩效指标"""
        pass
```

2. **回测流程**：
   - 加载历史新闻数据 → 重新计算情绪
   - 按日期逐日运行决策引擎
   - 模拟仓位变化、成本、收益
   - 生成绩效指标

3. **关键指标**：
   - 总收益率
   - 年化收益率
   - 夏普比率
   - 最大回撤
   - 胜率
   - 轮动次数

4. **数据准备**：
   - 获取 2024 年的新闻数据（如果有）
   - 获取 K 线数据（3 个板块的代表股）
   - 预处理数据

**验收标准**：
- [ ] 回测完整可运行
- [ ] 性能指标合理
- [ ] 代码无 bug
- [ ] 性能满足要求（< 5 秒）

**输出物**：
- `backtest_engine.py`
- 回测基础设施

---

#### 任务 4.2: 回测分析

**分配给**: Agent-6 (分析)  
**难度**: ⭐⭐⭐  
**时间**: 5 天

**具体任务**：

1. **运行标准回测场景**：
   - 整年 2024（如有数据）
   - 下半年 2024
   - 特定难市场环境

2. **分析结果**：
   - 性能对标基准
   - 轮动时机分析
   - 回撤原因分析
   - 参数敏感性

3. **生成报告**（`docs/sector_rotation/BACKTEST_REPORT.md`）：
   - 概述
   - 关键指标
   - 性能图表
   - 改进建议

**验收标准**：
- [ ] 夏普比率提升 ≥ 0.3（相比基准）
- [ ] 回撤 ≤ 20%
- [ ] 报告完整清晰

**输出物**：
- 完整的回测报告
- 性能分析图表

---

### 阶段 5: 上线部署（第 7 周）

#### 任务 5.1: 系统集成

**分配给**: Agent-1 (工程师)  
**难度**: ⭐⭐  
**时间**: 3 天

**具体任务**：
1. 集成到 Rainbow-FinGPT 主系统
2. 集成到报告生成流程
3. 集成到数据管道
4. 验证集成测试

**输出物**：
- 完整集成
- 集成测试报告

---

#### 任务 5.2: 监控与告警

**分配给**: Agent-5 (交易)  
**难度**: ⭐⭐  
**时间**: 2 天

**具体任务**：
1. 实现决策监控
2. 实现异常告警
3. 实现仓位监控
4. 创建监控面板

**输出物**：
- 监控模块
- 监控面板原型

---

#### 任务 5.3: 文档完善

**分配给**: Agent-4 (文档)  
**难度**: ⭐  
**时间**: 2 天

**具体任务**：
1. 完善 API 文档
2. 编写用户指南
3. 编写部署指南
4. 编写故障排查指南

**输出物**：
- 完整的用户文档
- 部署指南

---

## 🎯 并行执行计划

```
第1-2周:
  ├─ Agent-1: 项目结构搭建 (2天) + 集成测试 (3天)
  ├─ Agent-2: 情绪聚合模块 (5天)
  └─ Agent-3: 决策引擎基础 (6天) → 决策融合 (3天) → 风险控制 (3天)

第3周:
  ├─ Agent-4: LLM 决策模块 (5天)
  └─ Agent-3: 决策融合 (3天)

第4周:
  ├─ Agent-5: 仓位管理 (5天)
  └─ Agent-3: 风险控制 (3天)

第5-6周:
  ├─ Agent-6: 回测引擎 (7天)
  └─ Agent-6: 回测分析 (5天)

第7周:
  ├─ Agent-1: 系统集成 (3天)
  ├─ Agent-5: 监控告警 (2天)
  └─ Agent-4: 文档完善 (2天)
```

---

## 📋 交付物清单

### 代码文件

- [ ] `src/sector_rotation/__init__.py`
- [ ] `src/sector_rotation/config.py`
- [ ] `src/sector_rotation/sector_sentiment_aggregator.py`
- [ ] `src/sector_rotation/sector_rotation_engine.py`
- [ ] `src/sector_rotation/llm_decision_advisor.py`
- [ ] `src/sector_rotation/position_manager.py`
- [ ] `src/sector_rotation/backtest/backtest_engine.py`
- [ ] `src/sector_rotation/backtest/performance_metrics.py`
- [ ] `src/sector_rotation/utils/sector_utils.py`

### 测试文件

- [ ] `tests/sector_rotation/test_aggregator.py`
- [ ] `tests/sector_rotation/test_engine.py`
- [ ] `tests/sector_rotation/test_advisor.py`
- [ ] `tests/sector_rotation/test_position_manager.py`
- [ ] `tests/sector_rotation/test_backtest.py`

### 文档

- [ ] `docs/sector_rotation/DESIGN.md`
- [ ] `docs/sector_rotation/API.md`
- [ ] `docs/sector_rotation/BACKTEST_REPORT.md`
- [ ] `docs/sector_rotation/USER_GUIDE.md`
- [ ] `docs/sector_rotation/DEPLOYMENT.md`

---

## 👥 Team 角色

| Agent | 角色 | 责任 | 周期 |
|-------|------|------|------|
| Agent-1 | 工程师 | 项目结构、集成、部署 | 全周期 |
| Agent-2 | 数据处理 | 情绪聚合模块 | 第1-2周 |
| Agent-3 | 算法 | 决策引擎、融合、风险 | 第1-4周 |
| Agent-4 | LLM/文档 | LLM 集成、文档 | 第2-3周、第7周 |
| Agent-5 | 交易/风险 | 仓位管理、监控 | 第4周、第7周 |
| Agent-6 | 回测 | 回测引擎、分析 | 第5-6周 |

---

## ✅ 完成标准

所有任务完成后，需要验证：

1. **代码质量**：
   - [ ] 单元测试覆盖 ≥ 85%
   - [ ] 代码符合 PEP 8
   - [ ] 无明显 bug

2. **功能完整性**：
   - [ ] 所有模块实现完成
   - [ ] 集成测试通过
   - [ ] 回测运行成功

3. **性能指标**：
   - [ ] 决策延迟 ≤ 1 秒
   - [ ] 回测夏普比率提升 ≥ 0.3
   - [ ] 系统可用性 ≥ 99%

4. **文档完整**：
   - [ ] API 文档完整
   - [ ] 用户指南清晰
   - [ ] 部署指南可行

---

**项目始日期**: 2025-01-12  
**预计完成日期**: 2025-03-02  
**项目经理**: Claude (Kiro)
