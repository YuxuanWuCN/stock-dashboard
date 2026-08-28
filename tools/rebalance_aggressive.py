"""
自动调仓脚本 - 根据每日扫描结果更新激进组合持仓

功能：
1. 读取 aggressive_scan.json（全库扫描结果）
2. 选出 Top 8 只股票
3. 更新 portfolio_aggressive.json
4. 保留历史版本备份

调仓策略：
- 每日收盘后自动调仓
- 满仓 8 只，等权配置（每只 12.5%）
- 选股标准：激进分 Top 8

用法：
    python tools/rebalance_aggressive.py              # 自动调仓
    python tools/rebalance_aggressive.py --dry-run    # 预览调仓（不实际修改）
"""

import json
import os
import sys
import argparse
import shutil
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DATA_DIR
from src.utils import beijing_date_str, beijing_datetime_str

AGGRESSIVE_SCAN_FILE = os.path.join(DATA_DIR, "paper", "aggressive_scan.json")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "paper", "portfolio_aggressive.json")
BACKUP_DIR = os.path.join(DATA_DIR, "paper", "portfolio_history")


def load_aggressive_scan():
    """加载激进扫描结果"""
    if not os.path.exists(AGGRESSIVE_SCAN_FILE):
        print(f"❌ 激进扫描文件不存在: {AGGRESSIVE_SCAN_FILE}")
        print("   请先运行: python tools/aggressive_scan.py")
        sys.exit(1)

    with open(AGGRESSIVE_SCAN_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 尝试 'items' 或 'all' 字段（兼容不同版本）
    items = data.get('items') or data.get('all', [])
    return items


def load_current_portfolio():
    """加载当前组合"""
    if not os.path.exists(PORTFOLIO_FILE):
        return None

    with open(PORTFOLIO_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def select_top_stocks(scan_results, top_n=8):
    """选出 Top N 只股票"""
    # 按激进分排序
    sorted_stocks = sorted(scan_results, key=lambda x: x.get('aggressive_score', 0), reverse=True)

    # 取前 N 只
    return sorted_stocks[:top_n]


def build_portfolio(selected_stocks, capital=1000000):
    """构建新组合"""
    # 等权配置
    pct_per_stock = 100.0 / len(selected_stocks)
    amount_per_stock = capital / len(selected_stocks)

    items = []
    for stock in selected_stocks:
        items.append({
            "code": stock['code'],
            "name": stock['name'],
            "amount": int(amount_per_stock),
            "pct": round(pct_per_stock, 1),
            "reason": f"激进分{stock['aggressive_score']:.1f} | 5日↑{stock['up5']:.0f}% | 3日↑{stock['up3']:.0f}% | 20日动量{stock['return_20d_pct']:+.1f}%"
        })

    portfolio = {
        "schema_version": "1.1",
        "name": "激进组合-全库扫描版",
        "risk_profile": "aggressive",
        "capital": capital,
        "created_at": beijing_datetime_str(),
        "base_trade_date": beijing_date_str(),
        "rebalanced": True,
        "rebalance_date": beijing_date_str(),
        "cash_pct": 0,
        "strategy_note": f"每日自动调仓：全库扫描Top{len(selected_stocks)}，等权满仓配置",
        "scan_method": "tools/aggressive_scan.py自动调仓",
        "items": items,
        "cash": 0,
        "disclaimer": "本组合为模拟交易，仅供研究参考，不构成投资建议。每日自动调仓会产生高频交易成本。",
        "color": "#d97706",
        "description": "激进进攻：每日自动调仓，满仓8只高弹性标的"
    }

    return portfolio


def backup_portfolio(portfolio_file):
    """备份当前组合"""
    if not os.path.exists(portfolio_file):
        return None

    os.makedirs(BACKUP_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(BACKUP_DIR, f"portfolio_aggressive_{timestamp}.json")

    shutil.copy2(portfolio_file, backup_file)
    print(f"💾 备份当前组合: {backup_file}")

    return backup_file


def compare_portfolios(old_portfolio, new_portfolio):
    """对比新旧组合"""
    if old_portfolio is None:
        print("\n📊 组合对比: 无旧组合（首次创建）")
        return

    old_codes = {item['code']: item for item in old_portfolio.get('items', [])}
    new_codes = {item['code']: item for item in new_portfolio.get('items', [])}

    # 剔除的股票
    removed = [code for code in old_codes if code not in new_codes]
    # 新增的股票
    added = [code for code in new_codes if code not in old_codes]
    # 保留的股票
    kept = [code for code in old_codes if code in new_codes]

    print("\n📊 组合变动:")
    if removed:
        print(f"   ❌ 剔除 ({len(removed)}只):")
        for code in removed:
            stock = old_codes[code]
            print(f"      {code} {stock['name']} ({stock['pct']}%)")

    if added:
        print(f"   ✅ 新增 ({len(added)}只):")
        for code in added:
            stock = new_codes[code]
            print(f"      {code} {stock['name']} ({stock['pct']}%)")

    if kept:
        print(f"   ⏸️  保留 ({len(kept)}只):")
        for code in kept:
            print(f"      {code} {old_codes[code]['name']}")

    if not removed and not added:
        print("   ℹ️  组合未变动（持仓与上次相同）")


def save_portfolio(portfolio, portfolio_file, dry_run=False):
    """保存新组合"""
    if dry_run:
        print("\n🔍 预览模式（不实际修改文件）")
        print(json.dumps(portfolio, indent=2, ensure_ascii=False))
        return

    with open(portfolio_file, 'w', encoding='utf-8') as f:
        json.dump(portfolio, f, indent=2, ensure_ascii=False)

    print(f"\n✅ 组合已更新: {portfolio_file}")


def main():
    parser = argparse.ArgumentParser(description="激进组合自动调仓")
    parser.add_argument('--top', type=int, default=8, help='选择 Top N 只股票（默认8）')
    parser.add_argument('--dry-run', action='store_true', help='预览调仓，不实际修改文件')

    args = parser.parse_args()

    print("="*80)
    print("🔄 激进组合自动调仓")
    print("="*80)

    # 1. 加载扫描结果
    print("\n📂 加载激进扫描结果...")
    scan_results = load_aggressive_scan()
    print(f"   共 {len(scan_results)} 只股票")

    # 2. 选择 Top N
    print(f"\n🎯 选择 Top {args.top} 只股票...")
    selected = select_top_stocks(scan_results, args.top)
    print(f"   已选出 {len(selected)} 只:")
    for i, stock in enumerate(selected, 1):
        print(f"   {i}. {stock['code']} {stock['name']} | 激进分 {stock['aggressive_score']:.1f}")

    # 3. 构建新组合
    print("\n🏗️  构建新组合...")
    new_portfolio = build_portfolio(selected)

    # 4. 加载当前组合并对比
    old_portfolio = load_current_portfolio()
    compare_portfolios(old_portfolio, new_portfolio)

    # 5. 备份旧组合
    if old_portfolio and not args.dry_run:
        backup_portfolio(PORTFOLIO_FILE)

    # 6. 保存新组合
    save_portfolio(new_portfolio, PORTFOLIO_FILE, args.dry_run)

    print("\n" + "="*80)
    if not args.dry_run:
        print("✅ 调仓完成！")
        print("\n📌 下一步:")
        print("   1. 运行: python tools/paper_portfolio.py report")
        print("   2. 查看新组合绩效")
    else:
        print("🔍 预览完成（未修改文件）")
        print("   移除 --dry-run 参数以实际调仓")
    print("="*80)


if __name__ == '__main__':
    main()
