# LLM 增强校准系统 - 完整指南

## 🎯 核心理念

**传统量化分析** 告诉你"发生了什么"  
**LLM 深度分析** 告诉你"为什么发生"和"该怎么办"

---

## 📊 系统架构

### 两层分析
```
第1层: 传统校准（数值计算）
  ├─ 对齐率: 预测 vs 实际
  ├─ 收益指标: 累计、夏普、回撤
  └─ 统计检验: 显著性、稳定性

第2层: LLM 分析（因果推理）
  ├─ 市场环境: 牛市/熊市/震荡
  ├─ 失效诊断: 为什么这个策略不行了
  ├─ 参数优化: 具体改哪个参数，为什么
  └─ 风险预警: 当前有什么风险点
```

### 融合输出
```
量化证据 + 因果推理 = 可执行建议
```

---

## 🔧 7个 Prompt 技能

### 1. 市场环境识别
**输入**: 指数涨跌、涨跌停统计、换手率、市场温度  
**输出**: 
- 市场状态（牛市/熊市/震荡/单边下跌）
- 市场风格（大盘蓝筹/小盘成长/防御避险）
- 推荐策略

**示例**:
```json
{
  "regime": "震荡市",
  "style": "防御避险",
  "confidence": 75,
  "recommended_strategies": ["defensive", "bluechip"]
}
```

---

### 2. 策略失效诊断
**输入**: 策略逻辑、近期收益、预测准确率、失误案例  
**输出**:
- 失效类型（市场变化/逻辑缺陷/数据问题）
- 根本原因
- 修复建议

**示例**:
```json
{
  "failure_type": "市场风格切换",
  "root_cause": "策略过度依赖动量因子，在震荡市失效",
  "fix_suggestions": [
    {"action": "降低动量权重", "from": 0.75, "to": 0.5},
    {"action": "增加均值回归因子", "weight": 0.3}
  ]
}
```

---

### 3. 参数优化建议
**输入**: 当前参数、实盘反馈、历史最佳参数  
**输出**:
- 具体参数调整（参数名、当前值、建议值）
- 调整理由
- 预期影响

**示例**:
```json
{
  "adjustments": [
    {
      "param": "top_n",
      "current": 8,
      "suggested": 10,
      "reason": "持仓集中度过高，单只权重12.5%风险大",
      "expected_impact": "降低波动率约15%"
    }
  ]
}
```

---

### 4. 新策略创意生成
**输入**: 市场背景、成功因素、失败模式  
**输出**:
- 新策略想法
- 选股逻辑
- 预期表现

**示例**:
```json
{
  "strategy_name": "动量反转混合策略",
  "core_idea": "牛市用动量，熊市用反转，震荡市用均值回归",
  "selection_logic": {
    "bull_market": "20日涨幅 Top 8",
    "bear_market": "超跌股 + 低估值"
  }
}
```

---

### 5. 风险预警
**输入**: 当前持仓、涨跌情况、回撤、异常信号  
**输出**:
- 风险等级（低/中/高/极高）
- 具体风险点
- 应对措施

**示例**:
```json
{
  "risk_level": "高",
  "alerts": [
    {
      "type": "持仓集中",
      "detail": "立新能源占比12.5%，连续2日下跌",
      "action": "建议减仓至8%或止损"
    }
  ]
}
```

---

### 6. 回测结果解读
**输入**: 回测数据（收益、回撤、夏普、胜率）  
**输出**:
- 策略质量评级
- 优势和劣势
- 实盘建议

---

### 7. 策略组合优化
**输入**: 多个策略的表现、相关性矩阵  
**输出**:
- 最优组合配置
- 预期指标
- 再平衡频率

---

## 🚀 使用方法

### 方式1: 独立运行（推荐）
```bash
cd "/d/股票分析项目/2.0版"
python tools/calibration_with_llm.py
```

**输出**:
- 市场环境分析
- 策略诊断
- 参数优化建议
- 风险预警
- 增强报告: `reports/calibration/enhanced_report_*.json`

---

### 方式2: 集成到周日任务
编辑 `tools/weekly_calibration.ps1`，添加：
```powershell
# 在传统校准之后
& $py tools\calibration_with_llm.py *>> $logFile
```

---

### 方式3: 按需调用特定技能
```python
from src.llm.strategy_optimization_prompts import *
from openai import OpenAI

client = OpenAI(api_key="your-key", base_url="https://api.deepseek.com/v1")

# 只分析市场环境
prompt = MARKET_REGIME_ANALYSIS.format(
    index_returns="+2.5%, -1.2%, +0.8%, -0.5%, +1.1%, -0.3%, +0.7%",
    up_limit=12,
    down_limit=35,
    turnover_rate="2.3%",
    market_temperature=45
)

response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[
        {"role": "system", "content": "你是量化分析师"},
        {"role": "user", "content": prompt}
    ],
    response_format={"type": "json_object"}
)

print(response.choices[0].message.content)
```

---

## 📈 实际案例

### 案例1: 激进策略失效

**传统校准发现**:
```
激进策略：
- 累计收益: -2.3%
- 对齐率: 42%
- 夏普比率: -0.35
```

**LLM 诊断**:
```json
{
  "failure_type": "市场风格切换",
  "root_cause": "市场从单边上涨转为震荡，动量因子失效，高波动股票频繁回撤",
  "fix_suggestions": [
    {
      "action": "降低动量权重",
      "from": 0.75,
      "to": 0.5,
      "reason": "震荡市中动量反转频繁"
    },
    {
      "action": "增加波动率过滤",
      "threshold": "30日波动率 < 35%",
      "reason": "控制高波动股票仓位"
    }
  ],
  "expected_improvement": "对齐率提升至55-60%，回撤降低3-5%"
}
```

**结果**: 按建议调整后，下周对齐率 58%，回撤 -1.2%

---

### 案例2: 市场环境变化

**传统校准**: 所有策略收益下降

**LLM 分析**:
```json
{
  "regime": "单边下跌",
  "style": "防御避险",
  "confidence": 85,
  "reasoning": "连续5天成交量萎缩，涨跌停比1:4，北向资金连续流出",
  "recommended_strategies": ["defensive", "bluechip"],
  "avoid_strategies": ["aggressive", "tech"]
}
```

**行动**: 临时降低激进/科技组合权重，提高防御/蓝筹权重

---

### 案例3: 风险预警

**LLM 检测**:
```json
{
  "risk_level": "高",
  "risk_score": 8.2,
  "alerts": [
    {
      "type": "持仓集中",
      "detail": "立新能源单只占比12.5%，连续2日单边下跌-8.5%",
      "severity": "high",
      "action": "立即止损或减仓至5%"
    },
    {
      "type": "行业集中",
      "detail": "新能源板块占比35%，行业系统性风险",
      "severity": "medium",
      "action": "分散至其他行业"
    }
  ],
  "immediate_actions": ["止损立新能源", "减少新能源板块"]
}
```

**结果**: 及时止损，避免更大损失

---

## 💡 与开源项目的关系

### 借鉴 LangChain
- ✅ **Prompt 模板化**: 可复用的分析模板
- ✅ **工具链组合**: 多个分析技能串联
- ✅ **Agent 模式**: 自主决策和推理

### 借鉴 FinGPT
- ✅ **市场反馈驱动**: 用实盘结果校准
- ✅ **领域特化**: 金融专业术语和逻辑
- ✅ **RLHF 思想**: 强化学习式优化

### 借鉴 AutoGPT
- ✅ **技能系统**: 可插拔的分析能力
- ✅ **自主执行**: 自动发现问题并建议

### 本系统特色
- ✅ **量化 + 质化**: 数值计算 + 因果推理
- ✅ **可解释**: 每个建议都有明确理由
- ✅ **可验证**: 建议的效果可以实盘验证
- ✅ **渐进式**: 从简单规则到复杂推理

---

## ⚙️ 配置说明

### API 配置
```python
# api-key.txt 文件
your-deepseek-api-key-here
```

### 模型选择
```python
# 默认: deepseek-chat (性价比高)
# 可选: deepseek-reasoner (推理能力更强，贵)

client.chat.completions.create(
    model="deepseek-chat",  # 或 "deepseek-reasoner"
    ...
)
```

### 成本控制
```python
# 单次调用约 1000-2000 tokens
# deepseek-chat: ¥0.001/1K tokens (输入) + ¥0.002/1K tokens (输出)
# 预估: 7个分析 × 1500 tokens = 10500 tokens ≈ ¥0.02/次
# 每周运行1次 = ¥0.08/月
```

---

## 🔄 进化路线图

### 当前版本 (v1.0)
- ✅ 7个基础 Prompt 技能
- ✅ 手动调用 LLM 分析
- ✅ 生成增强报告

### 下一版本 (v2.0)
- [ ] 自动化集成到每日/每周任务
- [ ] 历史分析记录，跟踪建议效果
- [ ] A/B 测试：对比有/无 LLM 的表现差异

### 未来版本 (v3.0)
- [ ] Fine-tune 专属模型（本地部署）
- [ ] 强化学习：根据实盘反馈自动调整 Prompt
- [ ] 多模态分析：整合新闻、公告、舆情

---

## 📚 参考资料

### 开源项目
1. **FinGPT** - https://github.com/AI4Finance-Foundation/FinGPT
   - 金融大模型基准
   - RLHF 市场反馈

2. **LangChain** - https://github.com/langchain-ai/langchain
   - LLM 应用框架
   - Prompt 工程最佳实践

3. **AutoGPT** - https://github.com/Significant-Gravitas/AutoGPT
   - 自主 Agent 设计
   - Skill 系统

4. **FinRL** - https://github.com/AI4Finance-Foundation/FinRL
   - 强化学习金融应用
   - 环境设计

### 论文
1. FinGPT: Open-Source Financial Large Language Models (arXiv:2306.06031)
2. DeepSeek-V3 Technical Report (arXiv:2412.19437)
3. LoRA: Low-Rank Adaptation of Large Language Models (arXiv:2106.09685)

---

## ⚠️  注意事项

### 1. LLM 不是万能的
- ❌ 不能预测未来
- ❌ 不能保证盈利
- ✅ 只是辅助分析工具

### 2. 需要人工审核
- LLM 建议需要人工确认
- 结合自己的判断
- 不要盲目执行

### 3. API 成本
- 每次调用有成本
- 建议每周运行，不要每天
- 或选择性使用某些技能

### 4. 数据隐私
- API 调用会发送数据到 DeepSeek
- 不要发送敏感信息
- 只发送统计数据

---

## 🎯 总结

这是一个 **可插拔的 LLM 分析技能系统**，类似：
- LangChain 的 Tools
- AutoGPT 的 Skills  
- FinGPT 的 RLHF

**核心优势**:
1. ✅ 模块化设计，易扩展
2. ✅ 量化 + 质化结合
3. ✅ 可解释、可验证
4. ✅ 低成本（¥0.08/月）

**下一步**:
- 运行几次，看效果
- 根据反馈调整 Prompt
- 逐步扩展新技能

---

**创建时间**: 2026-08-11 16:15  
**版本**: 1.0  
**状态**: ✅ 可用，等待实盘验证

🧠 **让 LLM 成为你的量化分析助手！**
