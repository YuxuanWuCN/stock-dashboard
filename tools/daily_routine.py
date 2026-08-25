#!/usr/bin/env python3
"""
tools/daily_routine.py —— 统一每日全自动量化投研与行情流水线 (Daily Routine Pipeline)

功能特性：
1. 模块化流水线执行：
   [1/9] 龙头股动态淘汰沉淀 (auto_update_watchlist_top_gainers)
   [2/9] 全市场行情并发抓取 (src.fetch_data)
   [3/9] 多因子排行榜与 Fama-MacBeth 资产定价 (src.build_ranking)
   [4/9] 策略选股、狩猎场与市场温度联动 (src.strategies.main)
   [5/9] 明日决策简报与 AI 研报增量生成 (src.strategies.daily_brief)
   [6/9] 市场情绪诊断与逆向反转检测 (tools.daily_market_sentiment)
   [7/9] 模拟盘 6 大组合温度联动调仓与对照组同步 (paper_portfolio / rebalance / benchmark)
   [8/9] 策略进化与量化成果同步 (weekly_champion_analysis -> docs/data/quantitative)
   [9/9] Git 数据自动提交与推送 (git_push_with_fallback)
2. 跨平台兼容（Windows / Linux / GitHub Actions / macOS）
3. 毫秒级性能计时分析与高可读终端仪表盘
4. 容错隔离：单个非关键模块异常不中断整体流水线
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 强制 UTF-8 编码
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

LOG_DIR = ROOT_DIR / ".quality-state"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "daily_routine.log"


class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def log_message(msg: str, color: str = "") -> None:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    plain = f"[{now_str}] {msg}"
    colored = f"{color}[{now_str}] {msg}{Colors.RESET}" if color else plain
    print(colored)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(plain + "\n")
    except Exception:
        pass


def run_step(step_name: str, cmd_args: list[str], timeout_sec: int = 600, allow_fail: bool = False) -> bool:
    """运行流水线单个步骤并记录耗时与退出码。"""
    t0 = time.time()
    log_message(f"🚀 开始执行: {step_name} ...", Colors.CYAN)

    cmd_display = " ".join(cmd_args)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["STOCK_PROXY"] = env.get("STOCK_PROXY", "direct")
    env["LLM_DAILY_CALL_LIMIT"] = env.get("LLM_DAILY_CALL_LIMIT", "800")

    try:
        proc = subprocess.Popen(
            cmd_args,
            cwd=str(ROOT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        
        # 实时流式输出关键行并写入日志
        output_lines = []
        if proc.stdout:
            for line in proc.stdout:
                line_clean = line.rstrip()
                output_lines.append(line_clean)
                if any(k in line_clean for k in ["[", "✅", "❌", "⚠️", "===", "Saved:", "PASSED", "Pass"]):
                    print(f"   {line_clean}")

        proc.wait(timeout=timeout_sec)
        elapsed = time.time() - t0

        # 保存完整日志
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n--- {step_name} Output ({cmd_display}) ---\n")
            f.write("\n".join(output_lines) + "\n")

        if proc.returncode == 0:
            log_message(f"✅ {step_name} 成功完成 (耗时: {elapsed:.2f}s)", Colors.GREEN)
            return True
        else:
            if allow_fail:
                log_message(f"⚠️ {step_name} 非关键警告 (退出码: {proc.returncode}, 耗时: {elapsed:.2f}s)", Colors.YELLOW)
                return True
            else:
                log_message(f"❌ {step_name} 执行失败 (退出码: {proc.returncode}, 耗时: {elapsed:.2f}s)", Colors.RED)
                return False

    except subprocess.TimeoutExpired:
        proc.kill()
        elapsed = time.time() - t0
        log_message(f"❌ {step_name} 超时已终止 (>{timeout_sec}s)", Colors.RED)
        return allow_fail
    except Exception as exc:
        elapsed = time.time() - t0
        log_message(f"❌ {step_name} 异常: {exc}", Colors.RED)
        return allow_fail


def sync_dashboard_data() -> None:
    """同步所有量化计算成果与基准到 docs/data/quantitative 目录。"""
    log_message("📦 正在同步量化数据到前端 Dashboard...", Colors.CYAN)
    dst_dir = ROOT_DIR / "docs" / "data" / "quantitative"
    dst_dir.mkdir(parents=True, exist_ok=True)

    paper_dir = ROOT_DIR / "docs" / "data" / "paper"
    if paper_dir.exists():
        for f in paper_dir.glob("performance_*.json"):
            shutil.copy2(f, dst_dir / f.name)

        robust_perf = paper_dir / "performance.json"
        if robust_perf.exists():
            shutil.copy2(robust_perf, dst_dir / "performance_robust.json")
            shutil.copy2(robust_perf, dst_dir / "performance.json")

        for name in ["manifest.json", "benchmark.json", "random_control.json", "market_benchmark.json"]:
            src = paper_dir / name
            if src.exists():
                shutil.copy2(src, dst_dir / name)

    # 复制最新市场情绪
    sentiment_dir = ROOT_DIR / "reports" / "market_sentiment"
    if sentiment_dir.exists():
        files = sorted(sentiment_dir.glob("sentiment_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            shutil.copy2(files[0], dst_dir / "latest_sentiment.json")

    # 复制最新策略进化
    evolution_dir = ROOT_DIR / "reports" / "strategy_evolution"
    if evolution_dir.exists():
        files = sorted(evolution_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            shutil.copy2(files[0], dst_dir / "latest_evolution.json")

    log_message("✅ Dashboard 量化数据同步完成", Colors.GREEN)


def main() -> None:
    parser = argparse.ArgumentParser(description="StockDashboard 每日自动化全量流水线")
    parser.add_argument("--skip-fetch", action="store_true", help="跳过行情抓取步骤")
    parser.add_argument("--skip-ranking", action="store_true", help="跳过排行榜与定价分析")
    parser.add_argument("--skip-paper", action="store_true", help="跳过模拟盘调仓与回测")
    parser.add_argument("--skip-push", action="store_true", help="跳过 Git 自动推送")
    parser.add_argument("--dry-run", action="store_true", help="演练模式，不落库不推送")
    args = parser.parse_args()

    t_start = time.time()
    py_exec = sys.executable

    print("\n" + "=" * 80)
    print(f"{Colors.HEADER}{Colors.BOLD}🌟 StockDashboard v3.0 每日量化自动化流水线启动{Colors.RESET}")
    print(f"工作目录: {ROOT_DIR} | Python: {py_exec}")
    print("=" * 80 + "\n")

    steps_executed = 0
    steps_passed = 0

    # Step 1: 龙头股动态滑窗沉淀
    if not args.skip_fetch:
        steps_executed += 1
        if run_step("1/9 龙头股动态滑窗沉淀", [py_exec, "tools/auto_update_watchlist_top_gainers.py"], allow_fail=True):
            steps_passed += 1

    # Step 2: 抓取行情数据
    if not args.skip_fetch:
        steps_executed += 1
        if run_step("2/9 全市场行情并发抓取", [py_exec, "-m", "src.fetch_data"], allow_fail=False):
            steps_passed += 1

    # Step 3: 排行榜 + Fama-MacBeth 资产定价
    if not args.skip_ranking:
        steps_executed += 1
        if run_step("3/9 多因子排行榜与 Fama-MacBeth 定价", [py_exec, "-m", "src.build_ranking"], allow_fail=False):
            steps_passed += 1

    # Step 4: 策略选股与市场温度
    steps_executed += 1
    if run_step("4/9 策略选股与市场温度联动", [py_exec, "-m", "src.strategies.main", "--scope", "watchlist"], allow_fail=True):
        steps_passed += 1

    # Step 5: 明日决策简报与 AI 研报
    steps_executed += 1
    if run_step("5/9 明日决策简报与 AI 研报增量生成", [py_exec, "-m", "src.strategies.daily_brief"], allow_fail=True):
        steps_passed += 1

    # Step 6: 市场情绪诊断
    steps_executed += 1
    if run_step("6/9 每日市场情绪诊断与反转检测", [py_exec, "tools/daily_market_sentiment.py"], allow_fail=True):
        steps_passed += 1

    # Step 7: 模拟盘绩效记录与温度联动调仓
    if not args.skip_paper:
        steps_executed += 1
        paper_ok = True
        paper_ok &= run_step("7a/9 模拟盘旧持仓绩效日结", [py_exec, "tools/paper_portfolio.py", "report"], allow_fail=True)
        paper_ok &= run_step("7b/9 全库激进动量扫描", [py_exec, "tools/aggressive_scan.py"], allow_fail=True)
        paper_ok &= run_step("7c/9 6大基础模拟盘温度联动调仓", [py_exec, "tools/rebalance_all_portfolios.py"], allow_fail=True)
        paper_ok &= run_step("7d/9 衍生变体组合自动调仓", [py_exec, "tools/rebalance_variants.py"], allow_fail=True)
        paper_ok &= run_step("7e/9 全池等权基准对照计算", [py_exec, "tools/paper_portfolio.py", "benchmark"], allow_fail=True)
        paper_ok &= run_step("7f/9 随机对照组(100次抽样)统计", [py_exec, "tools/random_control.py"], allow_fail=True)
        paper_ok &= run_step("7g/9 宽基指数市场级对照统计", [py_exec, "tools/market_benchmark.py"], allow_fail=True)
        paper_ok &= run_step("7h/9 模拟盘清单导出", [py_exec, "tools/paper_portfolio.py", "manifest"], allow_fail=True)
        if paper_ok:
            steps_passed += 1

    # Step 8: 策略进化与数据同步
    steps_executed += 1
    run_step("8/9 策略进化分析与前端格式导出", [py_exec, "tools/weekly_champion_analysis.py", "export"], allow_fail=True)
    sync_dashboard_data()
    steps_passed += 1

    # Step 9: 自动 Git 提交与推送
    if not args.skip_push and not args.dry_run:
        steps_executed += 1
        git_push_ok = run_step("9/9 自动 Git 提交与云端推送", [py_exec, "tools/git_push_with_fallback.py"], allow_fail=True)
        if git_push_ok:
            steps_passed += 1

    total_time = time.time() - t_start
    print("\n" + "=" * 80)
    print(f"{Colors.GREEN}{Colors.BOLD}🎉 每日自动化全量流水线执行完毕！{Colors.RESET}")
    print(f"📊 阶段统计: {steps_passed}/{steps_executed} 成功 | 总耗时: {total_time:.2f} 秒 ({total_time/60:.1f} 分钟)")
    print(f"📝 完整日志请查阅: {LOG_FILE}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
