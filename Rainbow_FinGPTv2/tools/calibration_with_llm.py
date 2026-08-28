"""
LLM 增强校准系统 - 将传统量化分析与 LLM 深度洞察结合

流程：
1. 传统校准：数值计算（对齐率、收益、夏普比率）
2. LLM 分析：语义理解（为什么、怎么改、风险在哪）
3. 融合建议：量化证据 + 因果推理

使用方法：
    python tools/calibration_with_llm.py
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DATA_DIR
from src.utils import beijing_datetime_str

# 导入 Prompt 模板
from src.llm.strategy_optimization_prompts import (
    MARKET_REGIME_ANALYSIS,
    STRATEGY_FAILURE_DIAGNOSIS,
    PARAMETER_OPTIMIZATION,
    RISK_ALERT
)


def load_deepseek_client():
    """加载 DeepSeek API 客户端"""
    try:
        from openai import OpenAI

        # 读取 API key
        api_key_file = Path("api-key.txt")
        if not api_key_file.exists():
            print("⚠️  未找到 api-key.txt，LLM 分析将跳过")
            return None

        with open(api_key_file, 'r') as f:
            api_key = f.read().strip()

        client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1"
        )

        return client
    except Exception as e:
        print(f"⚠️  无法加载 DeepSeek 客户端: {e}")
        return None


def call_llm_with_retry(client, prompt, max_retries=3):
    """调用 LLM，带重试机制"""
    if client is None:
        return None

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="deepseek-v4-flash",  # 使用 v4-flash
                messages=[
                    {"role": "system", "content": "你是一个专业的量化投资分析师，精通技术分析和风险管理。"},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,  # 低温度，更确定性的输出
            )

            content = response.choices[0].message.content
            return json.loads(content)

        except Exception as e:
            print(f"⚠️  LLM 调用失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                return None

    return None


def analyze_market_regime(client, market_data):
    """市场环境识别"""
    print("\n🔍 分析市场环境...")

    prompt = MARKET_REGIME_ANALYSIS.format(
        index_returns=market_data.get('index_returns', '未知'),
        up_limit=market_data.get('up_limit', 0),
        down_limit=market_data.get('down_limit', 0),
        turnover_rate=market_data.get('turnover_rate', '未知'),
        market_temperature=market_data.get('temperature', 50)
    )

    result = call_llm_with_retry(client, prompt)

    if result:
        print(f"   市场状态: {result.get('regime', '未知')}")
        print(f"   市场风格: {result.get('style', '未知')}")
        print(f"   置信度: {result.get('confidence', 0)}%")
        print(f"   推荐策略: {', '.join(result.get('recommended_strategies', []))}")

    return result


def diagnose_poor_strategies(client, poor_strategies, benchmark_return):
    """诊断表现差的策略"""
    print("\n🔬 诊断表现不佳的策略...")

    diagnoses = []

    for strategy in poor_strategies:
        print(f"\n   分析: {strategy['name']}")

        prompt = STRATEGY_FAILURE_DIAGNOSIS.format(
            strategy_name=strategy['name'],
            strategy_logic=strategy.get('description', '未知'),
            returns_7d=strategy.get('returns', []),
            accuracy=strategy.get('accuracy', 50),
            worst_predictions=strategy.get('worst_cases', []),
            benchmark_returns=benchmark_return,
            other_strategies=', '.join([s['name'] for s in poor_strategies if s != strategy])
        )

        diagnosis = call_llm_with_retry(client, prompt)

        if diagnosis:
            print(f"      失效类型: {diagnosis.get('failure_type', '未知')}")
            print(f"      根本原因: {diagnosis.get('root_cause', '未知')}")
            print(f"      影响分数: {diagnosis.get('impact_score', 0)}/10")
            diagnoses.append({
                'strategy': strategy['name'],
                'diagnosis': diagnosis
            })

    return diagnoses


def optimize_strategy_parameters(client, strategy_data):
    """优化策略参数"""
    print(f"\n⚙️  优化策略参数: {strategy_data['name']}")

    prompt = PARAMETER_OPTIMIZATION.format(
        current_params=json.dumps(strategy_data.get('params', {}), ensure_ascii=False),
        cumulative_return=strategy_data.get('cumulative_return', 0),
        alignment_rate=strategy_data.get('alignment_rate', 50),
        sharpe_ratio=strategy_data.get('sharpe', 0),
        max_drawdown=strategy_data.get('max_drawdown', 0),
        best_params_history=json.dumps(strategy_data.get('best_params_history', {}), ensure_ascii=False),
        other_strategies_params=json.dumps(strategy_data.get('other_strategies_params', []), ensure_ascii=False)
    )

    optimization = call_llm_with_retry(client, prompt)

    if optimization:
        print(f"   优先级: {optimization.get('priority', 'medium')}")
        adjustments = optimization.get('adjustments', [])
        print(f"   建议调整: {len(adjustments)} 个参数")
        for adj in adjustments[:3]:  # 只显示前3个
            print(f"      - {adj.get('param')}: {adj.get('current')} → {adj.get('suggested')}")
            print(f"        理由: {adj.get('reason')}")

    return optimization


def check_risk_alerts(client, portfolio_data):
    """风险预警检查"""
    print("\n⚠️  风险预警检查...")

    prompt = RISK_ALERT.format(
        current_holdings=json.dumps(portfolio_data.get('holdings', []), ensure_ascii=False),
        daily_return=portfolio_data.get('daily_return', 0),
        return_3d=portfolio_data.get('return_3d', 0),
        current_drawdown=portfolio_data.get('drawdown', 0),
        max_single_weight=portfolio_data.get('max_weight', 0),
        industry_concentration=portfolio_data.get('industry_concentration', {}),
        consecutive_failures=portfolio_data.get('consecutive_failures', 0),
        anomaly_signals=json.dumps(portfolio_data.get('anomaly_signals', []), ensure_ascii=False)
    )

    risk_report = call_llm_with_retry(client, prompt)

    if risk_report:
        risk_level = risk_report.get('risk_level', '未知')
        risk_score = risk_report.get('risk_score', 0)

        print(f"   风险等级: {risk_level}")
        print(f"   风险分数: {risk_score}/10")

        alerts = risk_report.get('alerts', [])
        if alerts:
            print(f"   风险警报: {len(alerts)} 项")
            for alert in alerts[:3]:
                print(f"      - {alert.get('type')}: {alert.get('detail')}")

    return risk_report


def enhance_calibration_with_llm():
    """增强版校准系统主函数"""
    print("=" * 80)
    print("🧠 LLM 增强校准系统")
    print("=" * 80)

    # 1. 加载 DeepSeek 客户端
    print("\n📡 连接 DeepSeek API...")
    client = load_deepseek_client()

    if client is None:
        print("❌ 无法连接 LLM，将只运行传统校准")
        print("提示: 请确保 api-key.txt 文件存在且包含有效的 API key")
        return 1

    print("✅ API 连接成功")

    # 2. 加载传统校准结果
    print("\n📂 加载校准数据...")
    calibration_dir = Path("reports/calibration")
    if not calibration_dir.exists():
        print("❌ 未找到校准报告目录")
        return 1

    # 找最新的校准报告
    reports = list(calibration_dir.glob("calibration_report_*.json"))
    if not reports:
        print("❌ 未找到校准报告")
        return 1

    latest_report = max(reports, key=lambda p: p.stat().st_mtime)
    print(f"   加载: {latest_report.name}")

    with open(latest_report, 'r', encoding='utf-8') as f:
        calibration_data = json.load(f)

    # 3. 市场环境分析
    market_data = {
        'index_returns': calibration_data.get('market_data', {}).get('index_returns', '未知'),
        'up_limit': calibration_data.get('market_stats', {}).get('up_limit', 0),
        'down_limit': calibration_data.get('market_stats', {}).get('down_limit', 0),
        'turnover_rate': calibration_data.get('market_stats', {}).get('turnover', '未知'),
        'temperature': calibration_data.get('market_temperature', 50)
    }

    market_analysis = analyze_market_regime(client, market_data)

    # 4. 策略诊断
    strategies = calibration_data.get('strategies', [])
    poor_strategies = [s for s in strategies if s.get('score', 0) < 5.0]

    diagnoses = []
    if poor_strategies:
        diagnoses = diagnose_poor_strategies(
            client,
            poor_strategies,
            calibration_data.get('benchmark_return', 0)
        )

    # 5. 参数优化建议
    optimizations = []
    for strategy in strategies:
        if strategy.get('needs_optimization', False):
            opt = optimize_strategy_parameters(client, strategy)
            if opt:
                optimizations.append({
                    'strategy': strategy['name'],
                    'optimization': opt
                })

    # 6. 风险检查
    portfolio_data = calibration_data.get('portfolio_data', {})
    risk_report = check_risk_alerts(client, portfolio_data) if portfolio_data else None

    # 7. 生成增强报告
    print("\n💾 生成增强校准报告...")

    enhanced_report = {
        "generated_at": beijing_datetime_str(),
        "traditional_calibration": calibration_data,
        "llm_analysis": {
            "market_regime": market_analysis,
            "failure_diagnoses": diagnoses,
            "parameter_optimizations": optimizations,
            "risk_alerts": risk_report
        },
        "integrated_suggestions": merge_suggestions(
            calibration_data.get('calibration_suggestions', []),
            market_analysis,
            diagnoses,
            optimizations,
            risk_report
        )
    }

    # 保存增强报告
    output_file = calibration_dir / f"enhanced_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(enhanced_report, f, indent=2, ensure_ascii=False)

    print(f"✅ 报告已保存: {output_file}")

    # 8. 打印摘要
    print("\n" + "=" * 80)
    print("📊 LLM 分析摘要")
    print("=" * 80)

    if market_analysis:
        print(f"\n🌍 市场状态: {market_analysis.get('regime', '未知')}")
        print(f"   建议策略: {', '.join(market_analysis.get('recommended_strategies', []))}")

    if diagnoses:
        print(f"\n🔬 策略诊断: {len(diagnoses)} 个策略需要关注")

    if optimizations:
        print(f"\n⚙️  参数优化: {len(optimizations)} 个策略有优化建议")

    if risk_report:
        risk_level = risk_report.get('risk_level', '未知')
        print(f"\n⚠️  风险等级: {risk_level}")

    print("\n" + "=" * 80)

    return 0


def merge_suggestions(traditional, market_analysis, diagnoses, optimizations, risk_report):
    """融合传统校准建议和 LLM 分析"""
    merged = []

    # 1. 传统建议（保留）
    for sugg in traditional:
        merged.append({
            'source': 'traditional',
            'priority': sugg.get('priority', 'medium'),
            'suggestion': sugg
        })

    # 2. 市场环境建议
    if market_analysis:
        recommended = market_analysis.get('recommended_strategies', [])
        if recommended:
            merged.append({
                'source': 'market_regime',
                'priority': 'high',
                'suggestion': {
                    'type': '市场环境适配',
                    'content': f"当前市场状态为{market_analysis.get('regime')}，建议优先使用: {', '.join(recommended)}",
                    'reasoning': market_analysis.get('reasoning', '')
                }
            })

    # 3. 失效诊断建议
    for diag in diagnoses:
        diagnosis = diag.get('diagnosis', {})
        for fix in diagnosis.get('fix_suggestions', []):
            merged.append({
                'source': 'failure_diagnosis',
                'priority': 'high',
                'strategy': diag['strategy'],
                'suggestion': fix
            })

    # 4. 参数优化建议
    for opt in optimizations:
        optimization = opt.get('optimization', {})
        for adj in optimization.get('adjustments', []):
            merged.append({
                'source': 'parameter_optimization',
                'priority': optimization.get('priority', 'medium'),
                'strategy': opt['strategy'],
                'suggestion': adj
            })

    # 5. 风险预警建议
    if risk_report:
        for action in risk_report.get('immediate_actions', []):
            merged.append({
                'source': 'risk_alert',
                'priority': 'urgent',
                'suggestion': {
                    'type': '风险控制',
                    'action': action
                }
            })

    # 按优先级排序
    priority_order = {'urgent': 0, 'high': 1, 'medium': 2, 'low': 3}
    merged.sort(key=lambda x: priority_order.get(x.get('priority', 'medium'), 2))

    return merged


if __name__ == '__main__':
    sys.exit(enhance_calibration_with_llm())
