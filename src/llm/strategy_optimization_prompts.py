# FinGPT 策略优化 Prompt 库

"""
类似 LangChain Skills 的设计，为策略优化提供可插拔的 Prompt 模板

参考：
- FinGPT 论文的 RLHF 思路
- LangChain 的 Agent/Tool 设计
- AutoGPT 的 Skill 系统
"""

# ============================================================================
# 1. 市场环境识别 Prompt
# ============================================================================

MARKET_REGIME_ANALYSIS = """
你是一个专业的市场环境分析师。根据以下数据判断当前市场状态：

数据输入：
- 过去7天上证指数涨跌：{index_returns}
- 过去7天涨跌停统计：涨停{up_limit}只，跌停{down_limit}只
- 过去7天换手率：{turnover_rate}
- 市场温度：{market_temperature}

分析任务：
1. 判断市场状态（牛市/熊市/震荡市/单边下跌）
2. 识别市场风格（大盘蓝筹/小盘成长/防御避险）
3. 给出置信度（0-100%）

输出格式（JSON）：
{{
  "regime": "震荡市",
  "style": "防御避险",
  "confidence": 75,
  "reasoning": "连续3天成交量萎缩，涨跌停比例1:3，市场情绪谨慎",
  "recommended_strategies": ["defensive", "bluechip"]
}}

请用中文回答，保持客观，基于数据不要臆测。
"""


# ============================================================================
# 2. 策略失效诊断 Prompt
# ============================================================================

STRATEGY_FAILURE_DIAGNOSIS = """
你是一个量化策略诊断专家。某策略最近表现不佳，请分析原因。

策略信息：
- 策略名称：{strategy_name}
- 策略逻辑：{strategy_logic}
- 过去7天收益：{returns_7d}
- 预测准确率：{accuracy}%
- 最大失误案例：{worst_predictions}

参考数据：
- 同期大盘表现：{benchmark_returns}
- 同期其他策略表现：{other_strategies}

诊断任务：
1. 识别失效原因（市场环境变化/策略逻辑缺陷/数据质量问题）
2. 量化影响程度
3. 给出修复建议

输出格式（JSON）：
{{
  "failure_type": "市场风格切换",
  "root_cause": "策略过度依赖动量因子，在震荡市失效",
  "impact_score": 8.5,
  "fix_suggestions": [
    {{"action": "降低动量权重", "from": 0.75, "to": 0.5}},
    {{"action": "增加均值回归因子", "weight": 0.3}}
  ],
  "expected_improvement": "+2-3%"
}}

请基于量化证据，不要主观臆断。
"""


# ============================================================================
# 3. 参数优化建议 Prompt
# ============================================================================

PARAMETER_OPTIMIZATION = """
你是一个参数优化专家。基于实盘反馈，给出参数调整建议。

策略参数：
{current_params}

实盘反馈：
- 过去7天累计收益：{cumulative_return}%
- 预测vs实际对齐率：{alignment_rate}%
- 夏普比率：{sharpe_ratio}
- 最大回撤：{max_drawdown}%

对比数据：
- 历史最佳参数：{best_params_history}
- 其他策略参数：{other_strategies_params}

优化目标：
1. 提高对齐率（预测准确性）
2. 降低回撤（风险控制）
3. 提升夏普比率（综合表现）

约束条件：
- 单次调整幅度 ≤ 20%
- 必须有量化依据
- 避免过拟合

输出格式（JSON）：
{{
  "adjustments": [
    {{
      "param": "top_n",
      "current": 8,
      "suggested": 10,
      "reason": "持仓集中度过高，单只股票权重12.5%风险大",
      "expected_impact": "降低波动率约15%"
    }},
    {{
      "param": "momentum_weight",
      "current": 0.75,
      "suggested": 0.6,
      "reason": "市场进入震荡期，动量因子失效",
      "expected_impact": "提升对齐率5-8%"
    }}
  ],
  "priority": "high",
  "estimated_improvement": "+1.5-2%收益，-3%回撤"
}}

要求：每个建议必须有清晰的因果逻辑和量化预期。
"""


# ============================================================================
# 4. 新策略创意生成 Prompt
# ============================================================================

NEW_STRATEGY_IDEATION = """
你是一个量化策略设计师。基于当前市场和历史数据，提出新策略想法。

市场背景：
- 当前市场状态：{market_regime}
- 表现最好的策略：{top_strategies}
- 表现最差的策略：{worst_strategies}

历史洞察：
- 核心成功因素：{success_factors}
- 常见失败模式：{failure_patterns}

约束条件：
- 必须可编程实现
- 必须有明确的选股逻辑
- 风险可控（回撤<15%）

创意任务：
提出1个创新策略想法，结合现有策略的优点，避免已知缺陷。

输出格式（JSON）：
{{
  "strategy_name": "动量反转混合策略",
  "core_idea": "牛市用动量，熊市用反转，震荡市用均值回归",
  "selection_logic": {{
    "bull_market": "20日涨幅 Top 8",
    "bear_market": "超跌股 + 低估值",
    "range_market": "布林带下轨反弹"
  }},
  "position_sizing": "根据市场温度动态调整：60%-100%",
  "expected_performance": {{
    "bull_return": "+15-20%",
    "bear_return": "-5-8%",
    "sharpe": "1.2-1.5"
  }},
  "implementation_difficulty": "medium",
  "novelty_score": 7.5
}}

要求：必须有创新性，不是简单组合现有策略。
"""


# ============================================================================
# 5. 风险预警 Prompt
# ============================================================================

RISK_ALERT = """
你是一个风险管理专家。监控策略运行，及时发现风险信号。

当前状态：
- 策略持仓：{current_holdings}
- 今日组合涨跌：{daily_return}%
- 最近3日累计：{return_3d}%
- 当前回撤：{current_drawdown}%

风险指标：
- 单只股票最大权重：{max_single_weight}%
- 行业集中度：{industry_concentration}
- 预测失误连续天数：{consecutive_failures}

异常信号：
{anomaly_signals}

风险评估任务：
1. 识别当前风险等级（低/中/高/极高）
2. 列出具体风险点
3. 给出应对措施

输出格式（JSON）：
{{
  "risk_level": "高",
  "risk_score": 8.2,
  "alerts": [
    {{
      "type": "持仓集中",
      "detail": "立新能源单只占比12.5%，连续2日单边下跌",
      "severity": "high",
      "action": "建议减仓至8%或止损"
    }},
    {{
      "type": "行业集中",
      "detail": "科技股占比45%，行业风险暴露过高",
      "severity": "medium",
      "action": "增加防御性资产配置"
    }}
  ],
  "immediate_actions": ["止损立新能源", "减少科技仓位"],
  "monitoring_focus": ["科技板块整体走势", "个股流动性"]
}}

要求：及时预警，果断建议，避免事后诸葛亮。
"""


# ============================================================================
# 6. 回测结果解读 Prompt
# ============================================================================

BACKTEST_INTERPRETATION = """
你是一个回测结果解读专家。帮助理解回测数据背后的含义。

回测结果：
- 策略名称：{strategy_name}
- 回测期间：{backtest_period}
- 累计收益：{total_return}%
- 年化收益：{annual_return}%
- 最大回撤：{max_drawdown}%
- 夏普比率：{sharpe_ratio}
- 胜率：{win_rate}%
- 盈亏比：{profit_loss_ratio}

详细表现：
{performance_detail}

解读任务：
1. 评估策略质量（优秀/良好/一般/差）
2. 识别优势和劣势
3. 对比行业基准
4. 给出实盘建议

输出格式（JSON）：
{{
  "overall_rating": "良好",
  "rating_score": 7.5,
  "strengths": [
    "胜率高达65%，选股能力强",
    "回撤控制在10%以内，风控良好"
  ],
  "weaknesses": [
    "盈亏比仅1.5，盈利幅度不够",
    "震荡市表现一般"
  ],
  "vs_benchmark": {{
    "vs_sp500": "+3.2%",
    "vs_equal_weight": "+1.8%"
  }},
  "live_trading_advice": {{
    "recommended": true,
    "initial_capital": "建议20-30%仓位试运行",
    "stop_loss": "累计回撤>15%时停止",
    "optimization_priority": ["提高盈亏比", "增强震荡市表现"]
  }}
}}

要求：客观评价，既不过度乐观也不过度悲观。
"""


# ============================================================================
# 7. 策略组合优化 Prompt
# ============================================================================

PORTFOLIO_OPTIMIZATION = """
你是一个投资组合优化专家。从多个策略中选出最优组合。

可选策略：
{available_strategies}

历史表现：
{strategies_performance}

相关性矩阵：
{correlation_matrix}

优化目标：
1. 最大化夏普比率
2. 控制回撤 < 12%
3. 策略间低相关（分散风险）

约束条件：
- 至少3个策略
- 单个策略权重 10-40%
- 总仓位 70-100%

输出格式（JSON）：
{{
  "optimal_portfolio": [
    {{"strategy": "aggressive", "weight": 30}},
    {{"strategy": "defensive", "weight": 25}},
    {{"strategy": "global", "weight": 25}},
    {{"strategy": "bluechip", "weight": 20}}
  ],
  "expected_metrics": {{
    "sharpe": 1.45,
    "max_drawdown": 10.5,
    "annual_return": 18.2
  }},
  "diversification_score": 8.3,
  "reasoning": "激进提供收益，防御降低波动，全球分散风险，蓝筹稳定底仓",
  "rebalance_frequency": "每月"
}}

要求：必须考虑策略间相关性，真正做到分散风险。
"""


# ============================================================================
# 使用示例
# ============================================================================

def analyze_market_with_gpt(api_client, market_data):
    """使用 GPT 分析市场环境"""
    prompt = MARKET_REGIME_ANALYSIS.format(
        index_returns=market_data['index_returns'],
        up_limit=market_data['up_limit'],
        down_limit=market_data['down_limit'],
        turnover_rate=market_data['turnover_rate'],
        market_temperature=market_data['temperature']
    )

    response = api_client.chat.completions.create(
        model="deepseek-v4-flash",  # 使用 v4-flash
        messages=[
            {"role": "system", "content": "你是一个专业的量化分析师。"},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )

    return json.loads(response.choices[0].message.content)


def diagnose_strategy_failure(api_client, strategy_data):
    """诊断策略失效原因"""
    prompt = STRATEGY_FAILURE_DIAGNOSIS.format(**strategy_data)

    response = api_client.chat.completions.create(
        model="deepseek-v4-flash",  # 使用 v4-flash
        messages=[
            {"role": "system", "content": "你是一个量化策略诊断专家。"},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )

    return json.loads(response.choices[0].message.content)


def optimize_parameters(api_client, params_data):
    """优化策略参数"""
    prompt = PARAMETER_OPTIMIZATION.format(**params_data)

    response = api_client.chat.completions.create(
        model="deepseek-v4-flash",  # 使用 v4-flash
        messages=[
            {"role": "system", "content": "你是一个参数优化专家。"},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )

    return json.loads(response.choices[0].message.content)


# ============================================================================
# 集成到校准系统
# ============================================================================

def enhanced_calibration_with_llm(calibration_report, api_client):
    """
    在传统校准基础上，增加 LLM 深度分析

    流程：
    1. 传统校准：数值计算（对齐率、收益、回撤）
    2. LLM 分析：语义理解（为什么、怎么改、如何避免）
    3. 融合建议：量化 + 质化
    """

    # 1. 市场环境识别
    market_analysis = analyze_market_with_gpt(api_client, {
        'index_returns': calibration_report['market_data']['index_returns'],
        'up_limit': calibration_report['market_data']['up_limit'],
        'down_limit': calibration_report['market_data']['down_limit'],
        'turnover_rate': calibration_report['market_data']['turnover'],
        'temperature': calibration_report['market_temperature']
    })

    # 2. 策略失效诊断（如果有表现差的策略）
    poor_strategies = [s for s in calibration_report['strategies'] if s['score'] < 3.0]
    diagnoses = []
    for strategy in poor_strategies:
        diagnosis = diagnose_strategy_failure(api_client, {
            'strategy_name': strategy['name'],
            'strategy_logic': strategy['logic'],
            'returns_7d': strategy['returns'],
            'accuracy': strategy['accuracy'],
            'worst_predictions': strategy['worst_cases'],
            'benchmark_returns': calibration_report['benchmark_return'],
            'other_strategies': [s['name'] for s in calibration_report['strategies'] if s != strategy]
        })
        diagnoses.append(diagnosis)

    # 3. 参数优化建议
    for strategy in calibration_report['strategies']:
        if strategy['needs_optimization']:
            optimization = optimize_parameters(api_client, {
                'current_params': strategy['params'],
                'cumulative_return': strategy['cumulative_return'],
                'alignment_rate': strategy['alignment_rate'],
                'sharpe_ratio': strategy['sharpe'],
                'max_drawdown': strategy['max_drawdown'],
                'best_params_history': strategy['historical_best_params'],
                'other_strategies_params': [s['params'] for s in calibration_report['strategies']]
            })
            strategy['llm_optimization'] = optimization

    # 4. 融合传统校准 + LLM 分析
    enhanced_report = {
        **calibration_report,
        'market_analysis': market_analysis,
        'failure_diagnoses': diagnoses,
        'llm_insights': {
            'market_regime': market_analysis['regime'],
            'recommended_strategies': market_analysis['recommended_strategies'],
            'failure_root_causes': [d['root_cause'] for d in diagnoses],
            'optimization_priorities': [s.get('llm_optimization', {}).get('priority') for s in calibration_report['strategies']]
        }
    }

    return enhanced_report


# ============================================================================
# 开源参考
# ============================================================================

"""
类似项目参考：

1. LangChain (https://github.com/langchain-ai/langchain)
   - 可组合的 LLM 应用框架
   - Agent + Tool 设计模式
   - 借鉴：Prompt 模板化、Tool 可插拔

2. AutoGPT (https://github.com/Significant-Gravitas/AutoGPT)
   - 自主 Agent 系统
   - Skill 动态加载
   - 借鉴：自主决策、技能扩展

3. FinGPT (https://github.com/AI4Finance-Foundation/FinGPT)
   - 金融领域 LLM
   - 数据 + 模型 + RLHF
   - 借鉴：市场反馈驱动、领域特化

4. FinRL (https://github.com/AI4Finance-Foundation/FinRL)
   - 强化学习金融库
   - 环境 + Agent + 训练
   - 借鉴：状态-动作-奖励设计

5. Optuna (https://github.com/optuna/optuna)
   - 超参数优化框架
   - 贝叶斯优化
   - 借鉴：参数搜索策略

本系统设计：
- 借鉴 LangChain 的模块化
- 借鉴 FinGPT 的市场反馈
- 借鉴 AutoGPT 的自主决策
- 结合传统量化的严谨性
"""
