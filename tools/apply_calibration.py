"""
应用校准建议脚本

功能：
1. 读取最新的校准报告
2. 显示调参建议供用户确认
3. 备份当前参数
4. 应用新参数到配置文件
5. 记录调参日志

使用方法：
    python tools/apply_calibration.py                    # 交互式应用最新报告
    python tools/apply_calibration.py --report <file>    # 应用指定报告
    python tools/apply_calibration.py --auto             # 自动应用所有建议（谨慎使用）
"""

import json
import re
import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
CALIBRATION_DIR = PROJECT_ROOT / "reports" / "calibration"
BACKUP_DIR = PROJECT_ROOT / "reports" / "calibration" / "backups"
CONFIG_DIR = PROJECT_ROOT / "config"
PLANNING_DOC = PROJECT_ROOT / "项目规划" / "05-FinGPT后训练计划.md"

# 需要修改的文件
DAILY_BRIEF_FILE = PROJECT_ROOT / "src" / "strategies" / "daily_brief.py"
AGGRESSIVE_SCAN_FILE = PROJECT_ROOT / "tools" / "aggressive_scan.py"
SCORING_FILE = PROJECT_ROOT / "src" / "analysis" / "scoring.py"


class CalibrationApplier:
    """校准应用器"""

    def __init__(self, report_file: Path = None, auto_mode: bool = False):
        self.report_file = report_file
        self.auto_mode = auto_mode
        self.report = None
        self.backup_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 创建备份目录
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    def load_report(self) -> bool:
        """加载校准报告"""
        if self.report_file is None:
            # 查找最新报告
            report_files = sorted(CALIBRATION_DIR.glob("calibration_report_*.json"), reverse=True)
            if not report_files:
                print("❌ 未找到校准报告，请先运行 python tools/calibration.py")
                return False
            self.report_file = report_files[0]

        if not self.report_file.exists():
            print(f"❌ 报告文件不存在: {self.report_file}")
            return False

        try:
            with open(self.report_file, 'r', encoding='utf-8') as f:
                self.report = json.load(f)
            print(f"✅ 加载校准报告: {self.report_file}")
            return True
        except Exception as e:
            print(f"❌ 加载报告失败: {e}")
            return False

    def backup_file(self, file_path: Path) -> Path:
        """备份文件"""
        if not file_path.exists():
            return None

        backup_name = f"{file_path.stem}_{self.backup_timestamp}{file_path.suffix}"
        backup_path = BACKUP_DIR / backup_name

        shutil.copy2(file_path, backup_path)
        print(f"   💾 备份: {file_path.name} -> {backup_path.name}")
        return backup_path

    def apply_probability_threshold(self, suggestion: Dict[str, Any]) -> bool:
        """应用概率阈值调整"""
        print(f"\n📝 应用概率阈值调整...")
        print(f"   当前值: {suggestion['current_value']}%")
        print(f"   建议值: {suggestion['suggested_value']}%")
        print(f"   原因: {suggestion['reason']}")

        if not self.auto_mode:
            confirm = input("\n确认应用此调整? (y/n): ").strip().lower()
            if confirm != 'y':
                print("   ⏭️  跳过此调整")
                return False

        # 目标文件：稳健组合选股代码（真实门槛 up3 > N 所在地）
        file_str = suggestion['affected_files'][0]
        file_path = PROJECT_ROOT / file_str
        if not file_path.exists():
            print(f"   ❌ 目标文件不存在: {file_path}")
            return False

        self.backup_file(file_path)

        old_threshold = str(suggestion['current_value'])
        new_threshold = str(suggestion['suggested_value'])

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            new_content = re.sub(
                rf"(up3\s*>\s*){old_threshold}\b",
                rf"\g<1>{new_threshold}",
                content,
            )

            if new_content == content:
                print(f"   ⚠️ 未找到目标门槛模式 up3 > {old_threshold}（代码已变化），此建议未生效")
                return False

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            print(f"   ✅ 已更新 {file_path.name}: up3 > {old_threshold} → up3 > {new_threshold}")
            return True

        except Exception as e:
            print(f"   ❌ 应用失败: {e}")
            return False

    def apply_portfolio_strategy(self, suggestion: Dict[str, Any]) -> bool:
        """应用组合策略调整。

        spec-kit 004 修复：动量权重调整（momentum_old/momentum_new 字段存在时）
        实际落地替换；替换失败如实报未生效。其余（如止损纪律）仍需人工实现。
        """
        print(f"\n📝 应用组合策略调整...")
        print(f"   原因: {suggestion['reason']}")
        print(f"   实施: {suggestion['implementation']}")

        if not self.auto_mode:
            confirm = input("\n确认应用此调整? (y/n): ").strip().lower()
            if confirm != 'y':
                print("   ⏭️  跳过此调整")
                return False

        momentum_old = suggestion.get('momentum_old')
        momentum_new = suggestion.get('momentum_new')
        if momentum_old is not None and momentum_new is not None:
            file_path = PROJECT_ROOT / suggestion['affected_files'][0]
            if not file_path.exists():
                print(f"   ❌ 目标文件不存在: {file_path}")
                return False
            self.backup_file(file_path)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                new_content = content.replace(
                    f"momentum) * {momentum_old}",
                    f"momentum) * {momentum_new}",
                )
                if new_content == content:
                    print(f"   ⚠️ 未找到动量权重模式 momentum) * {momentum_old}（代码已变化），此建议未生效")
                    return False
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                print(f"   ✅ 已更新 {file_path.name}: 动量权重 {momentum_old} → {momentum_new}")
                return True
            except Exception as e:
                print(f"   ❌ 应用失败: {e}")
                return False

        print("   ⚠️  组合策略调整需要手动实现:")
        print(f"      {suggestion['implementation']}")
        print(f"      涉及文件: {', '.join(suggestion['affected_files'])}")
        return False

    def apply_scoring_weights(self, suggestion: Dict[str, Any]) -> bool:
        """应用评分权重调整"""
        print(f"\n📝 评分权重调整...")
        print(f"   原因: {suggestion['reason']}")
        print(f"   实施: {suggestion['implementation']}")

        if suggestion['priority'] == 'low':
            print("   ℹ️  优先级为低，建议等待更多数据后再调整")
            return False

        return False  # 非低优先级评分权重调整暂不支持自动应用

    def apply_suggestions(self):
        """应用所有调参建议"""
        suggestions = self.report.get('calibration_suggestions', [])

        if not suggestions:
            print("ℹ️  无调参建议")
            return

        print(f"\n📋 共有 {len(suggestions)} 条调参建议\n")

        applied_count = 0
        for i, suggestion in enumerate(suggestions, 1):
            print(f"{'='*80}")
            print(f"建议 {i}/{len(suggestions)}: [{suggestion['priority'].upper()}] {suggestion['type']}")
            print(f"{'='*80}")

            success = False
            if suggestion['type'] == 'probability_threshold':
                success = self.apply_probability_threshold(suggestion)
            elif suggestion['type'] == 'portfolio_strategy':
                success = self.apply_portfolio_strategy(suggestion)
            elif suggestion['type'] == 'scoring_weights':
                success = self.apply_scoring_weights(suggestion)
            else:
                print(f"   ⚠️  未知建议类型: {suggestion['type']}")

            if success:
                applied_count += 1

        print(f"\n{'='*80}")
        print(f"✅ 应用完成: {applied_count}/{len(suggestions)} 条建议已应用")
        print(f"{'='*80}")

    def log_calibration(self):
        """记录调参日志到规划文档"""
        if not PLANNING_DOC.exists():
            print(f"⚠️  规划文档不存在: {PLANNING_DOC}")
            return

        try:
            with open(PLANNING_DOC, 'r', encoding='utf-8') as f:
                content = f.read()

            # 查找调参日志部分
            log_section = "\n## 6. 调参日志\n"
            if log_section in content:
                # 追加日志
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                trading_days = self.report.get('trading_days', 0)
                suggestions = self.report.get('calibration_suggestions', [])

                log_entry = f"""
### 调参记录 - {timestamp}

**触发条件**: 累计 {trading_days} 个交易日

**市场反馈**:
- 对齐率: {self.report['market_feedback_summary'].get('alignment_rate', 0):.1%}
- 总样本数: {self.report['market_feedback_summary'].get('total', 0)}

**组合绩效**:
- 稳健组合: {self.report['portfolio_performance']['robust']['cumulative_return']:.2f}%
- 激进组合: {self.report['portfolio_performance']['aggressive']['cumulative_return']:.2f}%
- 等权基准: {self.report['portfolio_performance']['equal_weight']['cumulative_return']:.2f}%

**应用的调参**:
"""
                for sug in suggestions:
                    log_entry += f"- [{sug['priority'].upper()}] {sug['type']}: {sug['reason']}\n"

                log_entry += f"\n**备份时间戳**: {self.backup_timestamp}\n"
                log_entry += f"**校准报告**: `{self.report_file.name}`\n"

                # 插入到日志部分
                insert_pos = content.find(log_section) + len(log_section)
                if "等待首轮数据" in content[insert_pos:insert_pos+100]:
                    # 替换占位文本
                    content = content.replace("（等待首轮数据，2026-08-12 后填写）", log_entry)
                else:
                    # 追加新记录
                    content = content[:insert_pos] + log_entry + content[insert_pos:]

                with open(PLANNING_DOC, 'w', encoding='utf-8') as f:
                    f.write(content)

                print(f"\n✅ 调参日志已记录到: {PLANNING_DOC}")

        except Exception as e:
            print(f"⚠️  记录日志失败: {e}")

    def run(self):
        """执行应用流程"""
        print("="*80)
        print("🔧 FinGPT 后训练 - 应用校准建议")
        print("="*80)

        # 加载报告
        if not self.load_report():
            sys.exit(1)

        # 显示报告摘要
        print(f"\n📊 报告摘要:")
        print(f"   生成时间: {self.report['generated_at']}")
        print(f"   交易日数: {self.report['trading_days']}")
        print(f"   对齐率: {self.report['market_feedback_summary'].get('alignment_rate', 0):.1%}")

        # 应用建议
        self.apply_suggestions()

        # 记录日志
        self.log_calibration()

        print("\n🎉 调参应用完成！")
        print("\n📌 下一步:")
        print("   1. 继续运行 5 个交易日以验证效果")
        print("   2. 运行 python tools/verify_calibration.py 生成验证报告")
        print(f"\n💾 如需回滚，备份文件位于: {BACKUP_DIR}")


def main():
    parser = argparse.ArgumentParser(description="应用 FinGPT 后训练校准建议")
    parser.add_argument('--report', type=str, help='指定校准报告文件')
    parser.add_argument('--auto', action='store_true', help='自动应用所有建议（无需确认）')

    args = parser.parse_args()

    report_file = Path(args.report) if args.report else None
    applier = CalibrationApplier(report_file=report_file, auto_mode=args.auto)
    applier.run()


if __name__ == '__main__':
    main()
