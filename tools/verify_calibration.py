"""
校准验证脚本

功能：
1. 对比调参前后的效果
2. 计算调参前后的 alignment_rate 变化
3. 对比组合收益和风险指标
4. 生成验证报告

使用方法：
    python tools/verify_calibration.py
    python tools/verify_calibration.py --baseline <report_file>  # 指定基线报告
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Tuple
import numpy as np

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
CALIBRATION_DIR = PROJECT_ROOT / "reports" / "calibration"
DATA_DIR = PROJECT_ROOT / "docs" / "data"

# 数据文件路径
PERFORMANCE_ROBUST_FILE = DATA_DIR / "paper" / "performance.json"
PERFORMANCE_AGGRESSIVE_FILE = DATA_DIR / "paper" / "performance_aggressive.json"
MARKET_FEEDBACK_FILE = DATA_DIR / "llm" / "market_feedback.json"


class CalibrationVerifier:
    """校准验证器"""

    def __init__(self, baseline_report_file: Path = None):
        self.baseline_report = None
        self.baseline_report_file = baseline_report_file
        self.current_data = {}

    def load_baseline_report(self) -> bool:
        """加载基线报告（调参前）"""
        if self.baseline_report_file is None:
            # 查找最早的校准报告作为基线
            report_files = sorted(CALIBRATION_DIR.glob("calibration_report_*.json"))
            if not report_files:
                print("❌ 未找到基线校准报告")
                return False
            self.baseline_report_file = report_files[0]

        if not self.baseline_report_file.exists():
            print(f"❌ 基线报告不存在: {self.baseline_report_file}")
            return False

        try:
            with open(self.baseline_report_file, 'r', encoding='utf-8') as f:
                self.baseline_report = json.load(f)
            print(f"✅ 加载基线报告: {self.baseline_report_file.name}")
            print(f"   基线日期: {self.baseline_report['generated_at']}")
            print(f"   基线交易日数: {self.baseline_report['trading_days']}")
            return True
        except Exception as e:
            print(f"❌ 加载基线报告失败: {e}")
            return False

    def load_current_data(self) -> bool:
        """加载当前数据"""
        try:
            # 加载当前绩效数据
            if PERFORMANCE_ROBUST_FILE.exists():
                with open(PERFORMANCE_ROBUST_FILE, 'r', encoding='utf-8') as f:
                    self.current_data['performance_robust'] = json.load(f)

            if PERFORMANCE_AGGRESSIVE_FILE.exists():
                with open(PERFORMANCE_AGGRESSIVE_FILE, 'r', encoding='utf-8') as f:
                    self.current_data['performance_aggressive'] = json.load(f)

            # 加载市场反馈
            if MARKET_FEEDBACK_FILE.exists():
                with open(MARKET_FEEDBACK_FILE, 'r', encoding='utf-8') as f:
                    self.current_data['market_feedback'] = json.load(f)

            return True
        except Exception as e:
            print(f"❌ 加载当前数据失败: {e}")
            return False

    def extract_period_data(self, all_records: List[Dict], start_index: int, days: int) -> List[Dict]:
        """提取指定时期的数据"""
        if start_index + days > len(all_records):
            return all_records[start_index:]
        return all_records[start_index:start_index + days]

    def calculate_metrics(self, records: List[Dict]) -> Dict[str, float]:
        """计算绩效指标"""
        if not records:
            return {
                'cumulative_return': 0,
                'volatility': 0,
                'max_drawdown': 0,
                'sharpe_ratio': 0,
                'win_rate': 0
            }

        returns = [r['portfolio_return_pct'] for r in records]
        cumulative = np.cumprod([1 + r/100 for r in returns]) - 1

        # 波动率
        volatility = np.std(returns) if len(returns) > 1 else 0

        # 最大回撤
        cumulative_wealth = np.cumprod([1 + r/100 for r in returns])
        running_max = np.maximum.accumulate(cumulative_wealth)
        drawdowns = (cumulative_wealth - running_max) / running_max
        max_drawdown = np.min(drawdowns) * 100 if len(drawdowns) > 0 else 0

        # 夏普比率（假设无风险利率为 0）
        sharpe_ratio = (np.mean(returns) / volatility * np.sqrt(252)) if volatility > 0 else 0

        # 胜率
        win_rate = len([r for r in returns if r > 0]) / len(returns) if returns else 0

        return {
            'cumulative_return': cumulative[-1] * 100 if len(cumulative) > 0 else 0,
            'volatility': volatility,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'win_rate': win_rate
        }

    def compare_periods(self) -> Dict[str, Any]:
        """对比调参前后的表现"""
        baseline_days = self.baseline_report['trading_days']
        current_robust_records = self.current_data['performance_robust']['records']
        current_aggressive_records = self.current_data['performance_aggressive']['records']

        total_days = len(current_robust_records)

        if total_days <= baseline_days:
            print(f"⚠️  当前交易日数 ({total_days}) 不足以验证（需要 > {baseline_days}）")
            return None

        # 基线期（调参前）
        baseline_robust = self.extract_period_data(current_robust_records, 0, baseline_days)
        baseline_aggressive = self.extract_period_data(current_aggressive_records, 0, baseline_days)

        # 验证期（调参后）
        verification_days = total_days - baseline_days
        verify_robust = self.extract_period_data(current_robust_records, baseline_days, verification_days)
        verify_aggressive = self.extract_period_data(current_aggressive_records, baseline_days, verification_days)

        print(f"\n📊 时间划分:")
        print(f"   基线期: 第 1-{baseline_days} 个交易日（调参前）")
        print(f"   验证期: 第 {baseline_days+1}-{total_days} 个交易日（调参后，共 {verification_days} 天）")

        # 计算各期指标
        return {
            'baseline': {
                'days': baseline_days,
                'robust': self.calculate_metrics(baseline_robust),
                'aggressive': self.calculate_metrics(baseline_aggressive)
            },
            'verification': {
                'days': verification_days,
                'robust': self.calculate_metrics(verify_robust),
                'aggressive': self.calculate_metrics(verify_aggressive)
            }
        }

    def calculate_alignment_improvement(self) -> Dict[str, Any]:
        """计算对齐率改善"""
        baseline_alignment = self.baseline_report['market_feedback_summary'].get('alignment_rate', 0)
        current_alignment = self.current_data['market_feedback'].get('summary', {}).get('alignment_rate', 0)

        improvement = current_alignment - baseline_alignment
        improvement_pct = (improvement / baseline_alignment * 100) if baseline_alignment > 0 else 0

        return {
            'baseline_alignment': baseline_alignment,
            'current_alignment': current_alignment,
            'improvement': improvement,
            'improvement_pct': improvement_pct
        }

    def generate_verification_report(self) -> Dict[str, Any]:
        """生成验证报告"""
        print("\n📊 生成验证报告...")

        # 对比时期表现
        period_comparison = self.compare_periods()
        if period_comparison is None:
            return None

        # 计算对齐率改善
        alignment_improvement = self.calculate_alignment_improvement()

        # 判断调参是否有效
        robust_improved = (
            period_comparison['verification']['robust']['cumulative_return'] >
            period_comparison['baseline']['robust']['cumulative_return']
        )
        alignment_improved = alignment_improvement['improvement'] > 0

        is_effective = robust_improved and alignment_improved

        # 组装报告
        report = {
            'generated_at': datetime.now().isoformat(),
            'baseline_report': str(self.baseline_report_file.name),
            'baseline_date': self.baseline_report['generated_at'],
            'period_comparison': period_comparison,
            'alignment_improvement': alignment_improvement,
            'calibration_effective': is_effective,
            'conclusion': self._generate_conclusion(period_comparison, alignment_improvement, is_effective)
        }

        return report

    def _generate_conclusion(self, period_comp: Dict, alignment_imp: Dict, is_effective: bool) -> str:
        """生成结论"""
        if is_effective:
            conclusion = "✅ 调参有效：对齐率提升且组合收益改善\n\n"
        else:
            conclusion = "⚠️  调参效果待观察\n\n"

        # 对齐率变化
        conclusion += f"**对齐率变化**: {alignment_imp['baseline_alignment']:.1%} → {alignment_imp['current_alignment']:.1%} "
        conclusion += f"({'+' if alignment_imp['improvement'] > 0 else ''}{alignment_imp['improvement']:.1%}, "
        conclusion += f"{'+' if alignment_imp['improvement_pct'] > 0 else ''}{alignment_imp['improvement_pct']:.1f}%)\n\n"

        # 稳健组合变化
        baseline_robust = period_comp['baseline']['robust']
        verify_robust = period_comp['verification']['robust']
        conclusion += f"**稳健组合**:\n"
        conclusion += f"- 累计收益: {baseline_robust['cumulative_return']:.2f}% → {verify_robust['cumulative_return']:.2f}%\n"
        conclusion += f"- 波动率: {baseline_robust['volatility']:.2f}% → {verify_robust['volatility']:.2f}%\n"
        conclusion += f"- 夏普比率: {baseline_robust['sharpe_ratio']:.2f} → {verify_robust['sharpe_ratio']:.2f}\n"
        conclusion += f"- 胜率: {baseline_robust['win_rate']:.1%} → {verify_robust['win_rate']:.1%}\n\n"

        # 激进组合变化
        baseline_aggressive = period_comp['baseline']['aggressive']
        verify_aggressive = period_comp['verification']['aggressive']
        conclusion += f"**激进组合**:\n"
        conclusion += f"- 累计收益: {baseline_aggressive['cumulative_return']:.2f}% → {verify_aggressive['cumulative_return']:.2f}%\n"
        conclusion += f"- 波动率: {baseline_aggressive['volatility']:.2f}% → {verify_aggressive['volatility']:.2f}%\n"
        conclusion += f"- 夏普比率: {baseline_aggressive['sharpe_ratio']:.2f} → {verify_aggressive['sharpe_ratio']:.2f}\n"
        conclusion += f"- 胜率: {baseline_aggressive['win_rate']:.1%} → {verify_aggressive['win_rate']:.1%}\n"

        return conclusion

    def save_report(self, report: Dict[str, Any]) -> Path:
        """保存验证报告"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = CALIBRATION_DIR / f"verification_report_{timestamp}.json"

        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"\n✅ 验证报告已保存: {report_file}")
        return report_file

    def print_summary(self, report: Dict[str, Any]):
        """打印验证摘要"""
        print("\n" + "="*80)
        print("📊 FinGPT 后训练验证报告")
        print("="*80)

        print(f"\n📅 验证时间: {report['generated_at']}")
        print(f"📄 基线报告: {report['baseline_report']} ({report['baseline_date']})")

        print("\n" + "="*80)
        print(report['conclusion'])
        print("="*80)

        if report['calibration_effective']:
            print("\n🎉 建议: 保持当前参数，继续监控")
        else:
            print("\n⚠️  建议: 考虑进一步调参或回滚")

    def run(self):
        """执行验证流程"""
        print("="*80)
        print("📊 FinGPT 后训练 - 校准验证")
        print("="*80)

        # 加载基线报告
        if not self.load_baseline_report():
            sys.exit(1)

        # 加载当前数据
        print("\n📂 加载当前数据...")
        if not self.load_current_data():
            sys.exit(1)

        # 生成验证报告
        report = self.generate_verification_report()
        if report is None:
            print("\n⏸️  数据不足，无法生成验证报告")
            sys.exit(0)

        # 保存报告
        report_file = self.save_report(report)

        # 打印摘要
        self.print_summary(report)

        print(f"\n📄 完整报告: {report_file}")


def main():
    parser = argparse.ArgumentParser(description="验证 FinGPT 后训练校准效果")
    parser.add_argument('--baseline', type=str, help='指定基线校准报告文件')

    args = parser.parse_args()

    baseline_file = Path(args.baseline) if args.baseline else None
    verifier = CalibrationVerifier(baseline_report_file=baseline_file)
    verifier.run()


if __name__ == '__main__':
    main()
