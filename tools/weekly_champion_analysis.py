"""
周日冠军策略分析与衍生系统

功能：
1. 评估过去一周各组合表现，选出"冠军策略"
2. 深度分析冠军策略的成功因素（使用 LLM）
3. 生成3个衍生策略（微调参数）
4. 下周自动运行衍生策略进行A/B测试

执行时间：每周日 21:00（在校准分析之后）
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DATA_DIR
from src.utils import beijing_date_str

PERFORMANCE_DIR = os.path.join(DATA_DIR, "paper")
VARIANTS_DIR = os.path.join(DATA_DIR, "paper", "strategy_variants")
ANALYSIS_DIR = os.path.join("reports", "strategy_evolution")


def load_deepseek_client():
    """加载 DeepSeek API 客户端"""
    try:
        from openai import OpenAI

        # 读取 API key
        api_key_file = Path("api-key.txt")
        if not api_key_file.exists():
            print("⚠️  未找到 api-key.txt，将使用基础分析（无 LLM 增强）")
            return None

        with open(api_key_file, 'r') as f:
            api_key = f.read().strip()

        client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1"
        )

        print("✅ DeepSeek API 已连接")
        return client
    except Exception as e:
        print(f"⚠️  无法加载 DeepSeek 客户端: {e}")
        print("   将使用基础分析（无 LLM 增强）")
        return None


def call_llm_for_analysis(client, prompt, temperature=0.3):
    """调用 LLM 进行分析"""
    if client is None:
        return None

    try:
        response = client.chat.completions.create(
            model="deepseek-v4-flash",  # 使用 v4-flash
            messages=[
                {"role": "system", "content": "你是一个专业的量化策略分析师，精通技术分析和策略优化。"},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
        )

        content = response.choices[0].message.content
        return json.loads(content)

    except Exception as e:
        print(f"⚠️  LLM 调用失败: {e}")
        return None


def load_all_performances():
    """加载所有组合的绩效数据（包括基础组合与衍生变体）"""
    portfolios = {
        'aggressive': 'performance_aggressive.json',
        'robust': 'performance.json',
        'bluechip': 'performance_bluechip.json',
        'defensive': 'performance_defensive.json',
        'global': 'performance_global.json',
        'tech': 'performance_tech.json',
    }

    data = {}
    for name, filename in portfolios.items():
        path = os.path.join(PERFORMANCE_DIR, filename)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data[name] = json.load(f)

    # 扫描 strategy_variants 或 paper 目录下的衍生组合绩效
    if os.path.isdir(PERFORMANCE_DIR):
        for f in os.listdir(PERFORMANCE_DIR):
            if f.startswith("performance_") and f.endswith(".json") and f not in portfolios.values():
                var_key = f[len("performance_"):-len(".json")]
                if var_key not in data:
                    try:
                        with open(os.path.join(PERFORMANCE_DIR, f), 'r', encoding='utf-8') as fp:
                            data[var_key] = json.load(fp)
                    except Exception:
                        pass

    return data


def analyze_weekly_performance(performances, days=7):
    """分析过去N天的表现"""
    results = {}

    for name, perf in performances.items():
        records = perf.get('records', [])

        # 只看最近N天
        recent = records[-days:] if len(records) > days else records

        if not recent:
            continue

        # 计算指标
        returns = [r['portfolio_return_pct'] for r in recent]
        cumulative_return = sum(returns)
        avg_return = cumulative_return / len(returns)
        volatility = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5

        # 胜率（正收益天数比例）
        win_days = sum(1 for r in returns if r > 0)
        win_rate = win_days / len(returns) * 100

        # 最大回撤
        cumsum = 0
        peak = 0
        max_drawdown = 0
        for r in returns:
            cumsum += r
            peak = max(peak, cumsum)
            drawdown = peak - cumsum
            max_drawdown = max(max_drawdown, drawdown)

        # 夏普比率（简化版，无风险收益率按0）
        sharpe = (avg_return / volatility) if volatility > 0 else 0

        # 综合得分
        score = (
            cumulative_return * 0.6 +      # 收益 60%（进一步提高）
            sharpe * 10 * 0.2 +             # 夏普比率 20%
            win_rate * 0.1 -                # 胜率 10%
            max_drawdown * 0.1              # 最大回撤 10%（惩罚）
        )

        results[name] = {
            'cumulative_return': round(cumulative_return, 2),
            'avg_daily_return': round(avg_return, 3),
            'volatility': round(volatility, 3),
            'win_rate': round(win_rate, 1),
            'max_drawdown': round(max_drawdown, 2),
            'sharpe': round(sharpe, 3),
            'score': round(score, 2),
            'trading_days': len(returns)
        }

    return results


def select_champion(results):
    """选出冠军策略（排除 global 参考基准）"""
    if not results:
        return None

    # 排除 global（仅作参考基准，不参与冠军评选）
    eligible = {k: v for k, v in results.items() if k != 'global'}
    if not eligible:
        eligible = results

    # 按综合得分排序
    sorted_results = sorted(eligible.items(), key=lambda x: x[1]['score'], reverse=True)
    champion_name, champion_stats = sorted_results[0]

    return champion_name, champion_stats, sorted_results


def analyze_champion_factors(champion_name, performances, client=None):
    """深度分析冠军策略的成功因素（使用 LLM）"""
    print(f"\n🔍 深度分析冠军策略: {champion_name}")
    print("=" * 80)

    perf = performances[champion_name]
    records = perf.get('records', [])

    if not records:
        return {}

    # 分析持仓特征
    all_holdings = {}
    for record in records[-7:]:  # 最近7天
        for item in record.get('items', []):
            code = item['code']
            if code not in all_holdings:
                all_holdings[code] = {
                    'name': item['name'],
                    'appearances': 0,
                    'total_return': 0,
                    'returns': []
                }
            all_holdings[code]['appearances'] += 1
            if item.get('change_pct') is not None:
                all_holdings[code]['returns'].append(item['change_pct'])
                all_holdings[code]['total_return'] += item['change_pct']

    # 找出核心持仓（出现频率高且收益好）
    core_holdings = []
    for code, data in all_holdings.items():
        if data['appearances'] >= 3:  # 至少出现3天
            avg_return = data['total_return'] / len(data['returns']) if data['returns'] else 0
            core_holdings.append({
                'code': code,
                'name': data['name'],
                'appearances': data['appearances'],
                'avg_return': round(avg_return, 2)
            })

    core_holdings.sort(key=lambda x: x['avg_return'], reverse=True)

    print("\n📌 核心持仓（出现≥3天）:")
    for i, h in enumerate(core_holdings[:5], 1):
        print(f"   {i}. {h['code']} {h['name']} | 出现{h['appearances']}天 | 平均{h['avg_return']:+.2f}%")

    # 分析预测准确率（如果有预测数据）
    prediction_stats = {'total': 0, 'correct': 0}
    for record in records[-7:]:
        for item in record.get('items', []):
            if item.get('pred_up3') is not None and item.get('change_pct') is not None:
                prediction_stats['total'] += 1
                predicted_up = item['pred_up3'] > 50
                actual_up = item['change_pct'] > 0
                if predicted_up == actual_up:
                    prediction_stats['correct'] += 1

    if prediction_stats['total'] > 0:
        accuracy = prediction_stats['correct'] / prediction_stats['total'] * 100
        print(f"\n📊 预测准确率: {accuracy:.1f}% ({prediction_stats['correct']}/{prediction_stats['total']})")

    # 🆕 使用 LLM 进行深度分析
    llm_analysis = None
    if client:
        print("\n🧠 LLM 深度分析中...")

        # 构建分析 Prompt
        prompt = f"""
你是一个专业的量化策略分析师。请深度分析这个获胜策略的成功因素。

**策略名称**: {champion_name}

**核心持仓**（出现频率高且收益好）:
{json.dumps(core_holdings[:5], ensure_ascii=False, indent=2)}

**预测准确率**: {prediction_stats['correct']}/{prediction_stats['total']} = {accuracy if prediction_stats['total'] > 0 else 0:.1f}%

**最近7天收益**:
{json.dumps([r['portfolio_return_pct'] for r in records[-7:]], ensure_ascii=False)}

**分析任务**:
1. 识别核心成功因素（为什么这个策略赢了）
2. 分析核心持仓特征（什么类型的股票表现好）
3. 评估可持续性（这种优势能持续多久）
4. 提出改进方向（如何进一步优化）

**输出格式**（JSON）:
{{
  "success_factors": [
    "因素1: 描述",
    "因素2: 描述"
  ],
  "holdings_characteristics": {{
    "industry": "主要行业",
    "market_cap": "市值特征（大盘/中盘/小盘）",
    "volatility": "波动率特征（高/中/低）"
  }},
  "sustainability": {{
    "score": 7.5,
    "reasoning": "可持续性分析",
    "risk_factors": ["风险点1", "风险点2"]
  }},
  "improvement_directions": [
    {{"direction": "方向1", "reason": "原因", "expected_impact": "预期影响"}},
    {{"direction": "方向2", "reason": "原因", "expected_impact": "预期影响"}}
  ]
}}

请用中文回答，基于数据分析，不要主观臆断。
"""

        llm_analysis = call_llm_for_analysis(client, prompt)

        if llm_analysis:
            print("\n✅ LLM 分析完成:")
            print(f"   成功因素: {len(llm_analysis.get('success_factors', []))} 个")
            for factor in llm_analysis.get('success_factors', [])[:3]:
                print(f"     - {factor}")

            sustainability = llm_analysis.get('sustainability', {})
            print(f"   可持续性评分: {sustainability.get('score', 0)}/10")

    return {
        'core_holdings': core_holdings[:5],
        'prediction_accuracy': prediction_stats.get('correct', 0) / max(prediction_stats.get('total', 1), 1) * 100,
        'llm_analysis': llm_analysis  # 🆕 包含 LLM 深度分析
    }


def generate_variants(champion_name, champion_stats, analysis, client=None):
    """生成3个衍生策略（使用 LLM 辅助）"""
    print(f"\n🧬 生成衍生策略...")
    print("=" * 80)

    # 🆕 如果有 LLM，先请 LLM 给出建议
    llm_suggestions = None
    if client and analysis.get('llm_analysis'):
        print("\n🧠 请求 LLM 生成衍生策略建议...")

        prompt = f"""
你是一个量化策略优化专家。基于冠军策略的分析，提出3个衍生策略方向。

**冠军策略**: {champion_name}
**累计收益**: {champion_stats['cumulative_return']}%
**夏普比率**: {champion_stats['sharpe']}
**最大回撤**: {champion_stats['max_drawdown']}%

**LLM 深度分析**:
{json.dumps(analysis.get('llm_analysis'), ensure_ascii=False, indent=2)}

**任务**: 提出3个衍生策略方向，每个方向要：
1. 保留冠军策略的优势
2. 针对性改进某个方面（收益/风险/稳定性）
3. 参数调整幅度适中（不要过于激进）

**输出格式**（JSON）:
{{
  "variants": [
    {{
      "name": "衍生策略1名称",
      "goal": "优化目标（提高收益/降低风险/提升稳定性）",
      "key_changes": [
        {{"param": "参数名", "current": "当前值", "suggested": "建议值", "reason": "原因"}}
      ],
      "expected_impact": "预期效果"
    }},
    {{...}},
    {{...}}
  ]
}}

请用中文回答，确保建议可执行、可量化。
"""

        llm_suggestions = call_llm_for_analysis(client, prompt, temperature=0.5)

        if llm_suggestions:
            print("✅ LLM 建议已生成")

    variants = []

    # 根据不同的冠军策略，生成不同的变体
    if champion_name == 'aggressive':
        # 激进策略的变体
        if llm_suggestions and 'variants' in llm_suggestions:
            # 使用 LLM 建议
            for i, llm_var in enumerate(llm_suggestions['variants'][:3], 1):
                changes = {}
                for change in llm_var.get('key_changes', []):
                    changes[change['param']] = change['suggested']

                variants.append({
                    'name': f'aggressive_v{i}',
                    'display_name': llm_var['name'],
                    'description': llm_var['goal'],
                    'changes': changes,
                    'llm_reasoning': llm_var.get('expected_impact', '')
                })
        else:
            # 使用默认变体
            variants = [
                {
                    'name': 'aggressive_plus',
                    'display_name': '激进增强版',
                    'description': '更激进：Top 6，动量权重加倍',
                    'changes': {
                        'top_n': 6,
                        'momentum_weight': 1.5,
                    }
                },
                {
                    'name': 'aggressive_stable',
                    'display_name': '激进稳健版',
                    'description': '降低波动：Top 10，加入风险过滤',
                    'changes': {
                        'top_n': 10,
                        'max_risk_score': 60,
                    }
                },
                {
                    'name': 'aggressive_momentum',
                    'display_name': '激进动量版',
                    'description': '纯动量：只看20日涨幅',
                    'changes': {
                        'top_n': 8,
                        'momentum_only': True,
                    }
                }
            ]

    elif champion_name == 'robust':
        if llm_suggestions and 'variants' in llm_suggestions:
            for i, llm_var in enumerate(llm_suggestions['variants'][:3], 1):
                changes = {}
                for change in llm_var.get('key_changes', []):
                    changes[change['param']] = change['suggested']

                variants.append({
                    'name': f'robust_v{i}',
                    'display_name': llm_var['name'],
                    'description': llm_var['goal'],
                    'changes': changes,
                    'llm_reasoning': llm_var.get('expected_impact', '')
                })
        else:
            variants = [
                {
                    'name': 'robust_tight',
                    'display_name': '稳健严格版',
                    'description': '更严格：风险<30, 概率>70%',
                    'changes': {
                        'max_risk': 30,
                        'min_prob': 70,
                    }
                },
                {
                    'name': 'robust_relaxed',
                    'display_name': '稳健宽松版',
                    'description': '放宽条件：风险<50, 概率>55%',
                    'changes': {
                        'max_risk': 50,
                        'min_prob': 55,
                    }
                },
                {
                    'name': 'robust_balanced',
                    'display_name': '稳健平衡版',
                    'description': '平衡配置：90%仓位，8只股票',
                    'changes': {
                        'cash_pct': 10,
                        'top_n': 8,
                    }
                }
            ]

    elif champion_name in ['bluechip', 'defensive', 'tech']:
        if llm_suggestions and 'variants' in llm_suggestions:
            for i, llm_var in enumerate(llm_suggestions['variants'][:3], 1):
                changes = {}
                for change in llm_var.get('key_changes', []):
                    changes[change['param']] = change['suggested']

                variants.append({
                    'name': f'{champion_name}_v{i}',
                    'display_name': llm_var['name'],
                    'description': llm_var['goal'],
                    'changes': changes,
                    'llm_reasoning': llm_var.get('expected_impact', '')
                })
        else:
            variants = [
                {
                    'name': f'{champion_name}_top5',
                    'display_name': f'{champion_name.title()} 精选版',
                    'description': '集中持仓：只持有池内Top 5',
                    'changes': {
                        'top_n': 5,
                    }
                },
                {
                    'name': f'{champion_name}_weighted',
                    'display_name': f'{champion_name.title()} 加权版',
                    'description': '按分数加权：高分股票权重更大',
                    'changes': {
                        'weighting': 'score_weighted',
                    }
                },
                {
                    'name': f'{champion_name}_momentum',
                    'display_name': f'{champion_name.title()} 动量版',
                    'description': '池内选择：优先20日涨幅高的',
                    'changes': {
                        'selection_criterion': 'momentum',
                    }
                }
            ]

    elif champion_name == 'global':
        if llm_suggestions and 'variants' in llm_suggestions:
            for i, llm_var in enumerate(llm_suggestions['variants'][:3], 1):
                changes = {}
                for change in llm_var.get('key_changes', []):
                    changes[change['param']] = change['suggested']

                variants.append({
                    'name': f'global_v{i}',
                    'display_name': llm_var['name'],
                    'description': llm_var['goal'],
                    'changes': changes,
                    'llm_reasoning': llm_var.get('expected_impact', '')
                })
        else:
            variants = [
                {
                    'name': 'global_us_heavy',
                    'display_name': '全球-美股偏重',
                    'description': 'A股2 + 港股1 + 美股5 + 韩股2',
                    'changes': {
                        'allocation': {'cn': 2, 'hk': 1, 'us': 5, 'kr': 2}
                    }
                },
                {
                    'name': 'global_cn_heavy',
                    'display_name': '全球-A股偏重',
                    'description': 'A股5 + 港股2 + 美股2 + 韩股1',
                    'changes': {
                        'allocation': {'cn': 5, 'hk': 2, 'us': 2, 'kr': 1}
                    }
                },
                {
                    'name': 'global_balanced',
                    'display_name': '全球-极致平衡',
                    'description': 'A股3 + 港股3 + 美股3 + 韩股3',
                    'changes': {
                        'allocation': {'cn': 3, 'hk': 3, 'us': 3, 'kr': 3}
                    }
                }
            ]

    for i, v in enumerate(variants, 1):
        print(f"\n{i}. {v['display_name']}")
        print(f"   描述: {v['description']}")
        print(f"   变更: {v['changes']}")
        if v.get('llm_reasoning'):
            print(f"   LLM分析: {v['llm_reasoning']}")

    return variants


def save_analysis_report(champion_name, champion_stats, all_results, analysis, variants):
    """保存分析报告"""
    os.makedirs(ANALYSIS_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = os.path.join(ANALYSIS_DIR, f"weekly_analysis_{timestamp}.json")

    report = {
        "generated_at": timestamp,
        "analysis_period": "past_7_days",
        "champion": {
            "name": champion_name,
            "stats": champion_stats,
            "analysis": analysis
        },
        "all_strategies": all_results,
        "variants": variants,
        "next_week_strategies": [
            "aggressive", "robust", "bluechip", "defensive", "global", "tech"
        ] + [v['name'] for v in variants]
    }

    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n💾 报告已保存: {report_file}")
    return report_file


def create_variant_portfolios(variants, champion_name):
    """创建衍生组合配置文件"""
    os.makedirs(VARIANTS_DIR, exist_ok=True)

    print(f"\n📝 创建衍生组合配置文件...")

    for variant in variants:
        config = {
            "schema_version": "2.0",
            "name": variant['display_name'],
            "parent_strategy": champion_name,
            "variant_name": variant['name'],
            "description": variant['description'],
            "changes": variant['changes'],
            "capital": 1000000,
            "created_at": datetime.now().isoformat(),
            "status": "active",
            "test_duration_days": 7,
            "color": "#f59e0b",
        }

        filename = f"portfolio_{variant['name']}.json"
        filepath = os.path.join(VARIANTS_DIR, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        print(f"   ✅ {filename}")

    print(f"\n✅ 下周将运行: 6个基础策略 + {len(variants)}个衍生策略 = {6 + len(variants)}个组合")


def main():
    print("=" * 80)
    print("🏆 周日冠军策略分析与衍生系统")
    print("=" * 80)

    # 🆕 0. 连接 DeepSeek API
    print("\n📡 连接 DeepSeek API...")
    client = load_deepseek_client()

    # 1. 加载数据
    print("\n📂 加载组合绩效数据...")
    performances = load_all_performances()
    print(f"   加载了 {len(performances)} 个组合")

    # 2. 分析表现
    print("\n📊 分析过去7天表现...")
    results = analyze_weekly_performance(performances, days=7)

    if not results:
        print("❌ 没有足够的数据进行分析")
        return 1

    # 3. 选出冠军
    champion_name, champion_stats, all_sorted = select_champion(results)

    print("\n🏆 本周冠军: " + champion_name.upper())
    print("-" * 80)
    print(f"   累计收益: {champion_stats['cumulative_return']:+.2f}%")
    print(f"   夏普比率: {champion_stats['sharpe']:.3f}")
    print(f"   胜率: {champion_stats['win_rate']:.1f}%")
    print(f"   最大回撤: {champion_stats['max_drawdown']:.2f}%")
    print(f"   综合得分: {champion_stats['score']:.2f}")

    print("\n📊 完整排名:")
    for i, (name, stats) in enumerate(all_sorted, 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f" {i}."
        print(f"   {emoji} {name:12s} | 收益{stats['cumulative_return']:+6.2f}% | 夏普{stats['sharpe']:5.2f} | 得分{stats['score']:6.2f}")

    # 4. 深度分析（🆕 使用 LLM）
    analysis = analyze_champion_factors(champion_name, performances, client)

    # 5. 生成衍生策略（🆕 使用 LLM）
    variants = generate_variants(champion_name, champion_stats, analysis, client)

    # 6. 保存报告
    report_file = save_analysis_report(champion_name, champion_stats, results, analysis, variants)

    # 7. 创建衍生组合配置
    create_variant_portfolios(variants, champion_name)

    print("\n" + "=" * 80)
    print("✅ 分析完成！")
    print("=" * 80)
    print("\n📌 下一步:")
    print("   1. 查看分析报告 (在 reports/strategy_evolution/)")
    print("   2. 下周一开始，将自动运行 9 个组合（6基础 + 3衍生）")
    print("   3. 下周日再次分析，保留表现好的衍生策略")

    if client:
        print("\n🧠 LLM 增强分析已启用")
        print("   - 深度因果分析")
        print("   - 智能衍生策略生成")
    else:
        print("\n⚠️  LLM 未启用，使用基础分析模式")
        print("   提示: 添加 api-key.txt 以启用 LLM 增强分析")

    print("=" * 80)

    return 0


def export_frontend_evolution():
    """将最新一份周冠军分析报告转换为前端 latest_evolution.json 格式并保存。

    前端 portfolio.js 期望：
      - champion 扁平字段（cumulative_return/sharpe_ratio/win_rate/max_drawdown）
      - llm_analysis 为字符串（直接 innerHTML 展示）
    原报告的 champion.stats / champion.analysis 嵌套结构保持兼容，仅增加扁平字段。
    """
    import glob
    files = sorted(glob.glob(os.path.join(ANALYSIS_DIR, "weekly_analysis_*.json")))
    if not files:
        print("未找到周冠军分析报告，请先运行 python tools/weekly_champion_analysis.py")
        return 1
    latest = files[-1]
    with open(latest, "r", encoding="utf-8") as f:
        report = json.load(f)

    champion = report.get("champion", {})
    stats = champion.get("stats", {})
    analysis = champion.get("analysis", {})
    llm = analysis.get("llm_analysis") or {}

    # 前端 portfolio.js 期望：win_rate 为小数（显示时 *100），
    # 其余为百分数；缺字段时不输出该键（避免 null 触发前端 .toFixed() 崩溃）
    flat = dict(champion)
    if stats.get("cumulative_return") is not None:
        flat["cumulative_return"] = round(stats["cumulative_return"], 2)
    if stats.get("sharpe") is not None:
        flat["sharpe_ratio"] = round(stats["sharpe"], 3)
    if stats.get("win_rate") is not None:
        flat["win_rate"] = round(stats["win_rate"] / 100.0, 4)
    if stats.get("max_drawdown") is not None:
        flat["max_drawdown"] = round(stats["max_drawdown"], 2)

    text_parts = []
    if llm.get("success_factors"):
        text_parts.append("**成功因素：**" + "；".join(llm["success_factors"]))
    sus = llm.get("sustainability") or {}
    if sus.get("reasoning"):
        text_parts.append(f"**可持续性（{sus.get('score', '?')}/10）：**" + sus["reasoning"])
    if llm.get("improvement_directions"):
        text_parts.append("**改进方向：**" + "；".join(
            f"{d.get('direction', '')}（{d.get('reason', '')}）"
            for d in llm["improvement_directions"]))
    llm_text = "\n".join(text_parts) if text_parts else "（无 LLM 深度分析）"

    out = {
        "analysis_date": report.get("generated_at", ""),
        "champion": flat,
        "all_strategies": report.get("all_strategies", {}),
        "variants": report.get("variants", []),
        "llm_analysis": llm_text,
        "source_file": os.path.basename(latest),
    }
    out_path = os.path.join(ANALYSIS_DIR, "latest_evolution.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"✅ 前端格式已导出: {out_path} (冠军: {flat.get('name')})")
    return 0


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="周冠军策略分析与衍生系统")
    parser.add_argument("cmd", nargs="?", default="analyze",
                        choices=["analyze", "export"],
                        help="analyze=完整分析；export=仅将最新报告转为前端格式")
    args = parser.parse_args()
    if args.cmd == "export":
        sys.exit(export_frontend_evolution())
    sys.exit(main())
