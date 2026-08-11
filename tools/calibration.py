"""
FinGPT 后训练校准分析脚本

功能：
1. 加载模拟盘数据（稳健/激进/等权基准）
2. 计算 alignment_rate（预测方向 vs 实际方向一致率）
3. 分析单只股票、分行业、分市场的校准表现
4. 生成完整校准报告
5. 输出调参建议（概率阈值/评分权重/提示词/组合策略）

触发条件：≥3 个交易日的模拟盘数据
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Tuple
import numpy as np

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "docs" / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
CALIBRATION_DIR = REPORTS_DIR / "calibration"

# 数据文件路径
MARKET_FEEDBACK_FILE = DATA_DIR / "llm" / "market_feedback.json"
PERFORMANCE_ROBUST_FILE = DATA_DIR / "paper" / "performance.json"
PERFORMANCE_AGGRESSIVE_FILE = DATA_DIR / "paper" / "performance_aggressive.json"
AGGRESSIVE_SCAN_FILE = DATA_DIR / "paper" / "aggressive_scan.json"

# 配置文件路径
CONFIG_DIR = PROJECT_ROOT / "config"
STRATEGY_PARAMS_FILE = CONFIG_DIR / "strategy_params.json"


class CalibrationAnalyzer:
    """校准分析器"""

    def __init__(self):
        self.market_feedback = None
        self.performance_robust = None
        self.performance_aggressive = None
        self.aggressive_scan = None

        # 创建报告目录
        CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)

    def load_data(self) -> bool:
        """加载所有数据文件"""
        try:
            # 加载市场反馈
            if MARKET_FEEDBACK_FILE.exists():
                with open(MARKET_FEEDBACK_FILE, 'r', encoding='utf-8') as f:
                    self.market_feedback = json.load(f)
            else:
                print(f"⚠️  市场反馈文件不存在: {MARKET_FEEDBACK_FILE}")
                return False

            # 加载稳健组合绩效
            if PERFORMANCE_ROBUST_FILE.exists():
                with open(PERFORMANCE_ROBUST_FILE, 'r', encoding='utf-8') as f:
                    self.performance_robust = json.load(f)
            else:
                print(f"⚠️  稳健组合绩效文件不存在: {PERFORMANCE_ROBUST_FILE}")
                return False

            # 加载激进组合绩效
            if PERFORMANCE_AGGRESSIVE_FILE.exists():
                with open(PERFORMANCE_AGGRESSIVE_FILE, 'r', encoding='utf-8') as f:
                    self.performance_aggressive = json.load(f)
            else:
                print(f"⚠️  激进组合绩效文件不存在: {PERFORMANCE_AGGRESSIVE_FILE}")
                return False

            # 加载激进扫描（可选）
            if AGGRESSIVE_SCAN_FILE.exists():
                with open(AGGRESSIVE_SCAN_FILE, 'r', encoding='utf-8') as f:
                    self.aggressive_scan = json.load(f)

            return True

        except Exception as e:
            print(f"❌ 加载数据失败: {e}")
            return False

    def check_trigger_condition(self) -> Tuple[bool, int, str]:
        """
        检查是否满足触发条件

        Returns:
            (是否满足, 交易日数, 原因说明)
        """
        if not self.performance_robust or 'records' not in self.performance_robust:
            return False, 0, "稳健组合数据为空"

        trading_days = len(self.performance_robust['records'])

        if trading_days < 3:
            return False, trading_days, f"交易日数不足（当前 {trading_days} 天，需要 ≥3 天）"

        return True, trading_days, f"满足触发条件（已有 {trading_days} 个交易日）"

    def calculate_alignment_rate(self, predictions: List[Dict], actuals: List[Dict]) -> Dict[str, Any]:
        """
        计算对齐率（预测方向 vs 实际方向）

        Args:
            predictions: 预测数据列表 [{'code': ..., 'pred_up3': ..., 'pred_up5': ...}, ...]
            actuals: 实际数据列表 [{'code': ..., 'change_pct': ...}, ...]

        Returns:
            对齐率统计信息
        """
        matched_3d = []
        matched_5d = []

        for pred in predictions:
            code = pred.get('code')
            pred_up3 = pred.get('pred_up3')
            pred_up5 = pred.get('pred_up5')

            # 查找对应的实际数据
            actual = next((a for a in actuals if a.get('code') == code), None)
            if not actual:
                continue

            change_pct = actual.get('change_pct')
            if change_pct is None:
                continue

            # 3日预测对齐
            if pred_up3 is not None:
                pred_direction = pred_up3 >= 50  # 预测上涨
                actual_direction = change_pct > 0  # 实际上涨
                matched_3d.append(1 if pred_direction == actual_direction else 0)

            # 5日预测对齐
            if pred_up5 is not None:
                pred_direction = pred_up5 >= 50
                actual_direction = change_pct > 0
                matched_5d.append(1 if pred_direction == actual_direction else 0)

        return {
            'alignment_3d': np.mean(matched_3d) if matched_3d else None,
            'alignment_5d': np.mean(matched_5d) if matched_5d else None,
            'sample_count_3d': len(matched_3d),
            'sample_count_5d': len(matched_5d)
        }

    def analyze_portfolio_performance(self) -> Dict[str, Any]:
        """分析组合绩效"""
        robust_records = self.performance_robust.get('records', [])
        aggressive_records = self.performance_aggressive.get('records', [])

        # 计算累计收益
        robust_returns = [r['portfolio_return_pct'] for r in robust_records]
        aggressive_returns = [r['portfolio_return_pct'] for r in aggressive_records]
        equal_weight_returns = [r.get('equal_weight_return_pct', 0) for r in robust_records]

        robust_cumulative = np.cumprod([1 + r/100 for r in robust_returns]) - 1
        aggressive_cumulative = np.cumprod([1 + r/100 for r in aggressive_returns]) - 1
        equal_weight_cumulative = np.cumprod([1 + r/100 for r in equal_weight_returns]) - 1

        # 计算波动率
        robust_volatility = np.std(robust_returns) if len(robust_returns) > 1 else 0
        aggressive_volatility = np.std(aggressive_returns) if len(aggressive_returns) > 1 else 0

        # 计算最大回撤
        def max_drawdown(returns):
            cumulative = np.cumprod([1 + r/100 for r in returns])
            running_max = np.maximum.accumulate(cumulative)
            drawdowns = (cumulative - running_max) / running_max
            return np.min(drawdowns) * 100 if len(drawdowns) > 0 else 0

        return {
            'robust': {
                'cumulative_return': robust_cumulative[-1] * 100 if len(robust_cumulative) > 0 else 0,
                'volatility': robust_volatility,
                'max_drawdown': max_drawdown(robust_returns),
                'daily_returns': robust_returns
            },
            'aggressive': {
                'cumulative_return': aggressive_cumulative[-1] * 100 if len(aggressive_cumulative) > 0 else 0,
                'volatility': aggressive_volatility,
                'max_drawdown': max_drawdown(aggressive_returns),
                'daily_returns': aggressive_returns
            },
            'equal_weight': {
                'cumulative_return': equal_weight_cumulative[-1] * 100 if len(equal_weight_cumulative) > 0 else 0,
                'daily_returns': equal_weight_returns
            }
        }

    def analyze_stock_accuracy(self) -> Dict[str, Any]:
        """分析单只股票的预测准确率"""
        stock_stats = {}

        # 从所有记录中收集预测和实际数据
        for record in self.performance_robust.get('records', []):
            for item in record.get('items', []):
                code = item.get('code')
                name = item.get('name', code)

                if code not in stock_stats:
                    stock_stats[code] = {
                        'name': name,
                        'predictions': [],
                        'actuals': []
                    }

                stock_stats[code]['predictions'].append(item)
                stock_stats[code]['actuals'].append(item)

        # 计算每只股票的对齐率
        results = []
        for code, data in stock_stats.items():
            alignment = self.calculate_alignment_rate(
                data['predictions'],
                data['actuals']
            )

            if alignment['sample_count_5d'] > 0:
                results.append({
                    'code': code,
                    'name': data['name'],
                    'alignment_3d': alignment['alignment_3d'],
                    'alignment_5d': alignment['alignment_5d'],
                    'sample_count': alignment['sample_count_5d']
                })

        # 按对齐率排序
        results.sort(key=lambda x: x['alignment_5d'] or 0, reverse=True)

        return {
            'total_stocks': len(results),
            'top_performers': results[:10],
            'bottom_performers': results[-10:] if len(results) >= 10 else results
        }

    def generate_calibration_suggestions(self, analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成调参建议"""
        suggestions = []

        # 从市场反馈获取当前 alignment_rate
        current_alignment = self.market_feedback.get('summary', {}).get('alignment_rate', 0)

        # 建议1：概率阈值调整
        if current_alignment < 0.5:
            suggestions.append({
                'type': 'probability_threshold',
                'priority': 'high',
                'current_value': 50,
                'suggested_value': 60,
                'reason': f'当前对齐率 {current_alignment:.1%} < 50%，存在乐观偏差，建议提高概率阈值',
                'affected_files': [
                    'src/strategies/daily_brief.py',
                    'tools/aggressive_scan.py'
                ],
                'implementation': '将候选股票的 pred_up5 阈值从 50% 提高到 60%'
            })

        # 建议2：组合策略调整
        portfolio_perf = analysis['portfolio_performance']
        if portfolio_perf['aggressive']['cumulative_return'] > portfolio_perf['robust']['cumulative_return'] * 1.5:
            suggestions.append({
                'type': 'portfolio_strategy',
                'priority': 'medium',
                'reason': f"激进组合跑赢稳健组合 {portfolio_perf['aggressive']['cumulative_return'] - portfolio_perf['robust']['cumulative_return']:.2f}%，可提高动量权重",
                'affected_files': ['tools/aggressive_scan.py'],
                'implementation': '在 aggressive_scan.py 中增加动量因子权重 10-20%'
            })
        elif portfolio_perf['aggressive']['max_drawdown'] < -10:
            suggestions.append({
                'type': 'portfolio_strategy',
                'priority': 'high',
                'reason': f"激进组合最大回撤 {portfolio_perf['aggressive']['max_drawdown']:.2f}% 过大，建议加入止损纪律",
                'affected_files': ['tools/aggressive_scan.py'],
                'implementation': '添加单日跌幅 > 5% 或累计回撤 > 8% 的止损规则'
            })

        # 建议3：评分权重调整（需要更多数据分析）
        suggestions.append({
            'type': 'scoring_weights',
            'priority': 'low',
            'reason': '需要更多交易日数据（建议 ≥10 天）才能准确评估各因子贡献',
            'affected_files': ['src/analysis/scoring.py'],
            'implementation': '待数据积累后，通过特征重要性分析调整 TECHNICAL_WEIGHT / FUNDAMENTAL_WEIGHT'
        })

        return suggestions

    def generate_report(self) -> Dict[str, Any]:
        """生成完整校准报告"""
        print("📊 开始生成校准报告...")

        # 检查触发条件
        triggered, trading_days, reason = self.check_trigger_condition()
        if not triggered:
            print(f"⚠️  {reason}")
            return None

        print(f"✅ {reason}")

        # 分析组合绩效
        print("📈 分析组合绩效...")
        portfolio_performance = self.analyze_portfolio_performance()

        # 分析股票准确率
        print("🎯 分析单只股票准确率...")
        stock_accuracy = self.analyze_stock_accuracy()

        # 生成调参建议
        print("💡 生成调参建议...")
        analysis = {
            'portfolio_performance': portfolio_performance,
            'stock_accuracy': stock_accuracy
        }
        suggestions = self.generate_calibration_suggestions(analysis)

        # 组装完整报告
        report = {
            'generated_at': datetime.now().isoformat(),
            'trading_days': trading_days,
            'trigger_condition': 'met',
            'market_feedback_summary': self.market_feedback.get('summary', {}),
            'portfolio_performance': portfolio_performance,
            'stock_accuracy': stock_accuracy,
            'calibration_suggestions': suggestions,
            'next_steps': [
                '1. 审核调参建议，确认是否合理',
                '2. 运行 python tools/apply_calibration.py 应用参数调整',
                '3. 继续运行 5 个交易日以验证效果',
                '4. 运行 python tools/verify_calibration.py 生成验证报告'
            ]
        }

        return report

    def save_report(self, report: Dict[str, Any]) -> Path:
        """保存报告到文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = CALIBRATION_DIR / f"calibration_report_{timestamp}.json"

        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"\n✅ 校准报告已保存: {report_file}")
        return report_file

    def print_summary(self, report: Dict[str, Any]):
        """打印报告摘要"""
        print("\n" + "="*80)
        print("📊 FinGPT 后训练校准报告摘要")
        print("="*80)

        print(f"\n📅 生成时间: {report['generated_at']}")
        print(f"📈 累计交易日数: {report['trading_days']} 天")

        # 市场反馈
        mf = report['market_feedback_summary']
        print(f"\n🎯 市场反馈对齐率: {mf.get('alignment_rate', 0):.1%}")
        print(f"   - 总样本数: {mf.get('total', 0)}")
        print(f"   - 正向惊喜: {mf.get('positive_surprise', 0)}")
        print(f"   - 负向惊喜: {mf.get('negative_surprise', 0)}")

        # 组合绩效
        perf = report['portfolio_performance']
        print(f"\n📊 组合绩效对比:")
        print(f"   - 稳健组合: {perf['robust']['cumulative_return']:.2f}% (波动率 {perf['robust']['volatility']:.2f}%, 最大回撤 {perf['robust']['max_drawdown']:.2f}%)")
        print(f"   - 激进组合: {perf['aggressive']['cumulative_return']:.2f}% (波动率 {perf['aggressive']['volatility']:.2f}%, 最大回撤 {perf['aggressive']['max_drawdown']:.2f}%)")
        print(f"   - 等权基准: {perf['equal_weight']['cumulative_return']:.2f}%")

        # 调参建议
        suggestions = report['calibration_suggestions']
        print(f"\n💡 调参建议 ({len(suggestions)} 条):")
        for i, sug in enumerate(suggestions, 1):
            print(f"\n   {i}. [{sug['priority'].upper()}] {sug['type']}")
            print(f"      原因: {sug['reason']}")
            print(f"      实施: {sug['implementation']}")

        print("\n" + "="*80)


def main():
    """主函数"""
    analyzer = CalibrationAnalyzer()

    # 加载数据
    print("📂 加载数据文件...")
    if not analyzer.load_data():
        print("❌ 数据加载失败，退出")
        sys.exit(1)

    # 生成报告
    report = analyzer.generate_report()

    if report is None:
        print("\n⏸️  未满足触发条件，等待更多交易日数据")
        sys.exit(0)

    # 保存报告
    report_file = analyzer.save_report(report)

    # 打印摘要
    analyzer.print_summary(report)

    print(f"\n📄 完整报告: {report_file}")
    print("\n🚀 下一步: 审核报告后，运行 python tools/apply_calibration.py 应用调参")


if __name__ == '__main__':
    main()
