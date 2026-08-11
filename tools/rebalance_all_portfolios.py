"""
多组合自动调仓系统 - 根据每日分析结果更新所有模拟盘组合

功能：
1. 根据不同策略自动调仓所有组合
2. 每个组合有独立的选股逻辑和风险配置
3. 保留历史版本备份

调仓策略：
- 激进组合：激进分 Top 8，满仓
- 稳健组合：低风险 + 高概率，80% 仓位
- 蓝筹组合：大盘蓝筹，低波动
- 防御组合：银行 + 黄金 + 公用事业
- 全球组合：全球分散配置
- 科技组合：科技股集中

用法：
    python tools/rebalance_all_portfolios.py              # 调仓所有组合
    python tools/rebalance_all_portfolios.py --dry-run    # 预览调仓
    python tools/rebalance_all_portfolios.py --only aggressive  # 只调仓激进组合
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

RANKING_FILE = os.path.join(DATA_DIR, "analysis", "ranking.json")
AGGRESSIVE_SCAN_FILE = os.path.join(DATA_DIR, "paper", "aggressive_scan.json")
BACKUP_DIR = os.path.join(DATA_DIR, "paper", "portfolio_history")


def load_ranking():
    """加载排行榜数据"""
    if not os.path.exists(RANKING_FILE):
        print(f"❌ 排行榜文件不存在: {RANKING_FILE}")
        return []

    with open(RANKING_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    return data.get('items', [])


def load_aggressive_scan():
    """加载激进扫描结果"""
    if not os.path.exists(AGGRESSIVE_SCAN_FILE):
        print(f"❌ 激进扫描文件不存在: {AGGRESSIVE_SCAN_FILE}")
        return []

    with open(AGGRESSIVE_SCAN_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 兼容 'items' 或 'all' 字段
    items = data.get('items') or data.get('all', [])
    return items


def backup_portfolio(portfolio_file):
    """备份当前组合"""
    if not os.path.exists(portfolio_file):
        return None

    os.makedirs(BACKUP_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.basename(portfolio_file)
    backup_file = os.path.join(BACKUP_DIR, f"{filename.replace('.json', '')}_{timestamp}.json")

    shutil.copy2(portfolio_file, backup_file)
    return backup_file


def save_portfolio(portfolio, portfolio_file, dry_run=False):
    """保存组合"""
    if dry_run:
        return

    with open(portfolio_file, 'w', encoding='utf-8') as f:
        json.dump(portfolio, f, indent=2, ensure_ascii=False)


# ============================================================================
# 各组合的选股逻辑
# ============================================================================

def rebalance_aggressive(scan_results, dry_run=False):
    """激进组合：激进分 Top 8，满仓"""
    print("\n" + "="*80)
    print("🔥 激进组合 - 全库扫描版")
    print("="*80)

    # 按激进分排序
    sorted_stocks = sorted(scan_results, key=lambda x: x.get('aggressive_score', 0), reverse=True)
    selected = sorted_stocks[:8]

    if not selected:
        print("❌ 无可用股票")
        return

    print(f"✅ 选出 {len(selected)} 只:")
    for i, s in enumerate(selected, 1):
        print(f"   {i}. {s['code']} {s['name']} | 激进分 {s['aggressive_score']:.1f}")

    # 等权配置
    pct = 100.0 / len(selected)
    amount = 1000000 / len(selected)

    items = []
    for s in selected:
        items.append({
            "code": s['code'],
            "name": s['name'],
            "amount": int(amount),
            "pct": round(pct, 1),
            "reason": f"激进分{s['aggressive_score']:.1f} | 5日↑{s['up5']:.0f}% | 20日{s['return_20d_pct']:+.1f}%"
        })

    portfolio = {
        "schema_version": "1.1",
        "name": "激进组合-全库扫描版",
        "risk_profile": "aggressive",
        "capital": 1000000,
        "created_at": beijing_datetime_str(),
        "base_trade_date": beijing_date_str(),
        "rebalanced": True,
        "rebalance_date": beijing_date_str(),
        "cash_pct": 0,
        "items": items,
        "cash": 0,
        "color": "#d97706",
        "description": "激进进攻：每日自动调仓，满仓8只高弹性标的"
    }

    filepath = os.path.join(DATA_DIR, "paper", "portfolio_aggressive.json")
    if not dry_run:
        backup_portfolio(filepath)
    save_portfolio(portfolio, filepath, dry_run)
    print(f"✅ 已更新: portfolio_aggressive.json")


def rebalance_robust(ranking, dry_run=False):
    """稳健组合：低风险 + 高概率，80% 仓位"""
    print("\n" + "="*80)
    print("🛡️  稳健组合 - 防守型")
    print("="*80)

    # 选股标准：风险分 < 40，3日上涨概率 > 60%
    candidates = []
    for item in ranking:
        risk = item.get('risk_score', 100)
        fc = item.get('forecast', {})
        up3 = fc.get('up_probability_3d_pct', 0)

        if risk < 40 and up3 > 60:
            candidates.append({
                'code': item['code'],
                'name': item['name'],
                'risk': risk,
                'up3': up3,
                'score': item.get('score', 0)
            })

    # 按综合分排序，取 Top 6
    candidates.sort(key=lambda x: x['score'], reverse=True)
    selected = candidates[:6]

    if not selected:
        print("❌ 无符合条件的股票（风险<40 且 3日概率>60%）")
        return

    print(f"✅ 选出 {len(selected)} 只:")
    for i, s in enumerate(selected, 1):
        print(f"   {i}. {s['code']} {s['name']} | 风险{s['risk']:.1f} | 3日↑{s['up3']:.0f}%")

    # 80% 仓位，等权分配
    pct = 80.0 / len(selected)
    amount = 800000 / len(selected)

    items = []
    for s in selected:
        items.append({
            "code": s['code'],
            "name": s['name'],
            "amount": int(amount),
            "pct": round(pct, 1),
            "reason": f"综合分{s['score']:.1f} | 风险{s['risk']:.0f} | 3日↑{s['up3']:.0f}%"
        })

    portfolio = {
        "schema_version": "1.0",
        "name": "稳健组合-防守型",
        "risk_profile": "defensive",
        "capital": 1000000,
        "created_at": beijing_datetime_str(),
        "base_trade_date": beijing_date_str(),
        "rebalanced": True,
        "rebalance_date": beijing_date_str(),
        "cash_pct": 20,
        "items": items,
        "cash": 200000,
        "color": "#2f9e6e",
        "description": "稳健防守：80%仓位+20%现金，低风险高概率标的"
    }

    filepath = os.path.join(DATA_DIR, "paper", "portfolio.json")
    if not dry_run:
        backup_portfolio(filepath)
    save_portfolio(portfolio, filepath, dry_run)
    print(f"✅ 已更新: portfolio.json")


def rebalance_bluechip(ranking, dry_run=False):
    """蓝筹组合：大盘蓝筹，低波动"""
    print("\n" + "="*80)
    print("💎 蓝筹组合")
    print("="*80)

    # 蓝筹标准：市值大、波动低
    bluechip_codes = ['600519', '601318', '600036', '000858', '300750',
                      '00700', 'AAPL', 'MSFT', '601899', '600887']

    candidates = []
    for item in ranking:
        if item['code'] in bluechip_codes:
            candidates.append({
                'code': item['code'],
                'name': item['name'],
                'score': item.get('score', 0),
                'risk': item.get('risk_score', 0)
            })

    # 按综合分排序，取 Top 10
    candidates.sort(key=lambda x: x['score'], reverse=True)
    selected = candidates[:10]

    if not selected:
        print("❌ 无可用蓝筹股")
        return

    print(f"✅ 选出 {len(selected)} 只:")
    for i, s in enumerate(selected, 1):
        print(f"   {i}. {s['code']} {s['name']} | 分数{s['score']:.1f}")

    pct = 100.0 / len(selected)
    amount = 1000000 / len(selected)

    items = []
    for s in selected:
        items.append({
            "code": s['code'],
            "name": s['name'],
            "amount": int(amount),
            "pct": round(pct, 1),
            "reason": f"蓝筹 | 分数{s['score']:.1f} | 风险{s['risk']:.0f}"
        })

    portfolio = {
        "schema_version": "1.0",
        "name": "蓝筹组合",
        "risk_profile": "conservative",
        "capital": 1000000,
        "created_at": beijing_datetime_str(),
        "base_trade_date": beijing_date_str(),
        "rebalanced": True,
        "rebalance_date": beijing_date_str(),
        "cash_pct": 0,
        "items": items,
        "cash": 0,
        "color": "#3b82f6",
        "description": "蓝筹稳健：大盘蓝筹，低波动"
    }

    filepath = os.path.join(DATA_DIR, "paper", "portfolio_bluechip.json")
    if not dry_run:
        backup_portfolio(filepath)
    save_portfolio(portfolio, filepath, dry_run)
    print(f"✅ 已更新: portfolio_bluechip.json")


def rebalance_defensive(ranking, dry_run=False):
    """防御组合：银行 + 黄金 + 公用事业"""
    print("\n" + "="*80)
    print("🛡️  防御组合")
    print("="*80)

    # 防御性行业
    defensive_codes = ['601398', '601288', '600028', '601088', '600900',
                       '00941', '00005', '518880', '510050', '601857']

    candidates = []
    for item in ranking:
        if item['code'] in defensive_codes:
            candidates.append({
                'code': item['code'],
                'name': item['name'],
                'score': item.get('score', 0)
            })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    selected = candidates[:10]

    if not selected:
        print("❌ 无可用防御性股票")
        return

    print(f"✅ 选出 {len(selected)} 只:")
    for i, s in enumerate(selected, 1):
        print(f"   {i}. {s['code']} {s['name']}")

    pct = 100.0 / len(selected)
    amount = 1000000 / len(selected)

    items = []
    for s in selected:
        items.append({
            "code": s['code'],
            "name": s['name'],
            "amount": int(amount),
            "pct": round(pct, 1),
            "reason": f"防御 | 分数{s['score']:.1f}"
        })

    portfolio = {
        "schema_version": "1.0",
        "name": "防御组合",
        "risk_profile": "defensive",
        "capital": 1000000,
        "created_at": beijing_datetime_str(),
        "base_trade_date": beijing_date_str(),
        "rebalanced": True,
        "rebalance_date": beijing_date_str(),
        "cash_pct": 0,
        "items": items,
        "cash": 0,
        "color": "#10b981",
        "description": "防御配置：银行+黄金+公用事业"
    }

    filepath = os.path.join(DATA_DIR, "paper", "portfolio_defensive.json")
    if not dry_run:
        backup_portfolio(filepath)
    save_portfolio(portfolio, filepath, dry_run)
    print(f"✅ 已更新: portfolio_defensive.json")


def rebalance_global(ranking, dry_run=False):
    """全球组合：全球分散配置"""
    print("\n" + "="*80)
    print("🌍 全球组合")
    print("="*80)

    # 分市场选择
    cn_stocks = []
    hk_stocks = []
    us_stocks = []
    kr_stocks = []

    for item in ranking:
        stock_type = item.get('type', 'stock')
        score = item.get('score', 0)

        stock = {
            'code': item['code'],
            'name': item['name'],
            'score': score
        }

        if stock_type == 'stock':
            cn_stocks.append(stock)
        elif stock_type == 'hk':
            hk_stocks.append(stock)
        elif stock_type == 'us':
            us_stocks.append(stock)
        elif stock_type == 'kr':
            kr_stocks.append(stock)

    # 每个市场选 Top 2-3
    cn_stocks.sort(key=lambda x: x['score'], reverse=True)
    hk_stocks.sort(key=lambda x: x['score'], reverse=True)
    us_stocks.sort(key=lambda x: x['score'], reverse=True)
    kr_stocks.sort(key=lambda x: x['score'], reverse=True)

    selected = cn_stocks[:3] + hk_stocks[:2] + us_stocks[:3] + kr_stocks[:2]

    if len(selected) < 5:
        print("❌ 全球股票数量不足")
        return

    print(f"✅ 选出 {len(selected)} 只（A股{len(cn_stocks[:3])} + 港股{len(hk_stocks[:2])} + 美股{len(us_stocks[:3])} + 韩股{len(kr_stocks[:2])}）:")
    for i, s in enumerate(selected, 1):
        print(f"   {i}. {s['code']} {s['name']}")

    pct = 100.0 / len(selected)
    amount = 1000000 / len(selected)

    items = []
    for s in selected:
        items.append({
            "code": s['code'],
            "name": s['name'],
            "amount": int(amount),
            "pct": round(pct, 1),
            "reason": f"全球配置 | 分数{s['score']:.1f}"
        })

    portfolio = {
        "schema_version": "1.0",
        "name": "全球组合",
        "risk_profile": "moderate",
        "capital": 1000000,
        "created_at": beijing_datetime_str(),
        "base_trade_date": beijing_date_str(),
        "rebalanced": True,
        "rebalance_date": beijing_date_str(),
        "cash_pct": 0,
        "items": items,
        "cash": 0,
        "color": "#8b5cf6",
        "description": "全球分散：A股+港股+美股+韩股"
    }

    filepath = os.path.join(DATA_DIR, "paper", "portfolio_global.json")
    if not dry_run:
        backup_portfolio(filepath)
    save_portfolio(portfolio, filepath, dry_run)
    print(f"✅ 已更新: portfolio_global.json")


def rebalance_tech(ranking, dry_run=False):
    """科技组合：科技股集中"""
    print("\n" + "="*80)
    print("💻 科技组合")
    print("="*80)

    # 科技股代码
    tech_codes = ['AAPL', 'MSFT', 'GOOGL', 'NVDA', '00700',
                  '300750', '688981', '601012', '513100', '005930']

    candidates = []
    for item in ranking:
        if item['code'] in tech_codes:
            candidates.append({
                'code': item['code'],
                'name': item['name'],
                'score': item.get('score', 0)
            })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    selected = candidates[:10]

    if not selected:
        print("❌ 无可用科技股")
        return

    print(f"✅ 选出 {len(selected)} 只:")
    for i, s in enumerate(selected, 1):
        print(f"   {i}. {s['code']} {s['name']}")

    pct = 100.0 / len(selected)
    amount = 1000000 / len(selected)

    items = []
    for s in selected:
        items.append({
            "code": s['code'],
            "name": s['name'],
            "amount": int(amount),
            "pct": round(pct, 1),
            "reason": f"科技 | 分数{s['score']:.1f}"
        })

    portfolio = {
        "schema_version": "1.0",
        "name": "科技组合",
        "risk_profile": "aggressive",
        "capital": 1000000,
        "created_at": beijing_datetime_str(),
        "base_trade_date": beijing_date_str(),
        "rebalanced": True,
        "rebalance_date": beijing_date_str(),
        "cash_pct": 0,
        "items": items,
        "cash": 0,
        "color": "#ec4899",
        "description": "科技集中：全球科技龙头"
    }

    filepath = os.path.join(DATA_DIR, "paper", "portfolio_tech.json")
    if not dry_run:
        backup_portfolio(filepath)
    save_portfolio(portfolio, filepath, dry_run)
    print(f"✅ 已更新: portfolio_tech.json")


# ============================================================================
# 主函数
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="多组合自动调仓系统")
    parser.add_argument('--dry-run', action='store_true', help='预览调仓，不实际修改文件')
    parser.add_argument('--only', type=str, help='只调仓指定组合 (aggressive/robust/bluechip/defensive/global/tech)')

    args = parser.parse_args()

    print("="*80)
    print("🔄 多组合自动调仓系统")
    print("="*80)

    # 加载数据
    print("\n📂 加载数据...")
    ranking = load_ranking()
    aggressive_scan = load_aggressive_scan()

    print(f"   排行榜: {len(ranking)} 只")
    print(f"   激进扫描: {len(aggressive_scan)} 只")

    if args.dry_run:
        print("\n🔍 预览模式（不实际修改文件）")

    # 调仓
    portfolios = {
        'aggressive': lambda: rebalance_aggressive(aggressive_scan, args.dry_run),
        'robust': lambda: rebalance_robust(ranking, args.dry_run),
        'bluechip': lambda: rebalance_bluechip(ranking, args.dry_run),
        'defensive': lambda: rebalance_defensive(ranking, args.dry_run),
        'global': lambda: rebalance_global(ranking, args.dry_run),
        'tech': lambda: rebalance_tech(ranking, args.dry_run),
    }

    if args.only:
        if args.only in portfolios:
            portfolios[args.only]()
        else:
            print(f"❌ 未知组合: {args.only}")
            print(f"   可选: {', '.join(portfolios.keys())}")
            sys.exit(1)
    else:
        # 调仓所有组合
        for name, func in portfolios.items():
            try:
                func()
            except Exception as e:
                print(f"❌ {name} 调仓失败: {e}")

    print("\n" + "="*80)
    if not args.dry_run:
        print("✅ 调仓完成！")
    else:
        print("🔍 预览完成（未修改文件）")
    print("="*80)


if __name__ == '__main__':
    main()
