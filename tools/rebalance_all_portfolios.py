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


# ============================================================================
# 市场温度联动
# ============================================================================

MARKET_TEMP_FILE = os.path.join(DATA_DIR, "strategy", "market_temperature.json")
PORTFOLIO_CONFIG_FILE = os.path.join("config", "strategy_params.json")

# 温度档位（与 src/strategies/market_temperature.py 的 STATUS_THRESHOLDS 保持一致）
TEMPERATURE_TIERS = [
    (80, 1.0),    # 活跃
    (65, 0.8),    # 正常
    (50, 0.5),    # 偏冷
    (30, 0.25),   # 寒冷
    (15, 0.1),    # 冰封
    (0, 0.0),     # 极端
]


def load_market_temperature():
    """加载当日市场温度，返回 (temperature, position_ratio)。

    优先使用均值回归调整后的仓位系数（position_ratio_adjusted），
    温度文件缺失或异常时返回 (None, 1.0)（兜底满仓，等同原行为），不阻塞调仓。
    """
    if not os.path.exists(MARKET_TEMP_FILE):
        print("⚠️  未找到 market_temperature.json，按满仓处理")
        return None, 1.0
    try:
        with open(MARKET_TEMP_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        ratio = data.get('position_ratio_adjusted', data.get('position_ratio'))
        if ratio is None:
            print("⚠️  市场温度缺少 position_ratio，按满仓处理")
            return data.get('temperature'), 1.0
        return data.get('temperature'), float(ratio)
    except Exception as exc:
        print(f"⚠️  读取市场温度失败 ({exc})，按满仓处理")
        return None, 1.0


def position_ratio_for_temperature(temperature):
    """按温度档位返回仓位系数（温度缺失或 None 时返回 1.0）。"""
    if temperature is None:
        return 1.0
    for threshold, ratio in TEMPERATURE_TIERS:
        if temperature >= threshold:
            return ratio
    return TEMPERATURE_TIERS[-1][1]


def load_portfolio_config():
    """读取 config/strategy_params.json 中的 portfolios 段；缺省时返回空 dict。"""
    try:
        with open(PORTFOLIO_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f).get('portfolios', {})
    except Exception as exc:
        print(f"⚠️  读取组合配置失败 ({exc})，使用默认值")
        return {}


def portfolio_settings(key, config, temperature, defaults=None):
    """解析某组合的温度联动设置，返回 (enabled, size, base_ratio)。

    - 配置缺失该组合：返回默认设置（enabled=False，保持原行为）
    - 配置 enabled=False：返回 (False, defaults.size, defaults.base_ratio)
    - 配置 enabled=True：持仓数 = max(min_size, round(max_size × 仓位系数))
    """
    defaults = defaults or {}
    cfg = config.get(key) or {}
    enabled = bool(cfg.get('enabled', False))
    base_ratio = float(cfg.get('base_ratio', defaults.get('base_ratio', 1.0)))

    if not enabled:
        return False, defaults.get('size', 10), base_ratio

    max_size = int(cfg.get('max_size', defaults.get('max_size', 20)))
    min_size = int(cfg.get('min_size', defaults.get('min_size', 5)))
    ratio = position_ratio_for_temperature(temperature)
    size = max(min_size, round(max_size * ratio))
    return True, size, base_ratio


def allocate_regions(total, region_ratios):
    """按区域比例把总持仓数分配到各市场，返回 {region: count}（取整修正到总和）。

    region_ratios 如 {"stock": 0.3, "hk": 0.2, "us": 0.3, "kr": 0.2}。
    """
    if not region_ratios:
        return {}
    total_weight = sum(float(v) for v in region_ratios.values())
    if total_weight <= 0:
        return {}
    raw = {k: total * float(v) / total_weight for k, v in region_ratios.items()}
    # 先按整数部分分配，余数补给小数部分最大者
    counts = {k: int(v) for k, v in raw.items()}
    remainder = total - sum(counts.values())
    for k in sorted(raw, key=lambda x: raw[x] - int(raw[x]), reverse=True):
        if remainder <= 0:
            break
        counts[k] += 1
        remainder -= 1
    return counts


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

def rebalance_aggressive(scan_results, dry_run=False, temperature=None, config=None):
    """激进组合：激进分 Top N（温度联动），仓位随温度缩放"""
    print("\n" + "="*80)
    print("🔥 激进组合 - 全库扫描版")
    print("="*80)

    enabled, size, base_ratio = portfolio_settings(
        'aggressive', config or {}, temperature,
        defaults={'size': 8, 'max_size': 20, 'min_size': 5, 'base_ratio': 1.0})

    # 按激进分排序
    sorted_stocks = sorted(scan_results, key=lambda x: x.get('aggressive_score', 0), reverse=True)
    selected = sorted_stocks[:size]

    if not selected:
        print("❌ 无可用股票")
        return

    print(f"✅ 选出 {len(selected)} 只 (温度联动={'开' if enabled else '关'}):")
    for i, s in enumerate(selected, 1):
        print(f"   {i}. {s['code']} {s['name']} | 激进分 {s['aggressive_score']:.1f}")

    # 等权配置（总仓位 = base_ratio × 温度系数）
    position_pct = base_ratio * 100.0 * position_ratio_for_temperature(temperature) if enabled else base_ratio * 100.0
    pct = position_pct / len(selected)
    amount = int(1000000 * position_pct / 100.0) / len(selected)

    items = []
    for s in selected:
        items.append({
            "code": s['code'],
            "name": s['name'],
            "amount": int(amount),
            "pct": round(pct, 1),
            "reason": f"激进分{s['aggressive_score']:.1f} | 5日↑{s['up5']:.0f}% | 20日{s['return_20d_pct']:+.1f}%"
        })

    cash_pct = round(100.0 - position_pct, 1)
    portfolio = {
        "schema_version": "1.1",
        "name": "激进组合-全库扫描版",
        "risk_profile": "aggressive",
        "capital": 1000000,
        "created_at": beijing_datetime_str(),
        "base_trade_date": beijing_date_str(),
        "rebalanced": True,
        "rebalance_date": beijing_date_str(),
        "cash_pct": cash_pct,
        "items": items,
        "cash": int(1000000 * (100.0 - position_pct) / 100.0),
        "color": "#d97706",
        "description": f"激进进攻：每日自动调仓，温度联动持仓 {len(selected)} 只",
        "temperature_ratio": position_ratio_for_temperature(temperature) if enabled else None,
    }

    filepath = os.path.join(DATA_DIR, "paper", "portfolio_aggressive.json")
    if not dry_run:
        backup_portfolio(filepath)
    save_portfolio(portfolio, filepath, dry_run)
    print(f"✅ 已更新: portfolio_aggressive.json")


def robust_candidates(ranking):
    """稳健组合候选：风险分 < 40 且 3日上涨概率 > 60%，按综合分降序。

    spec-kit 004b 修复：读取嵌套字段 risk.score 与 total_score，
    不再误读不存在的顶层 risk_score / score（旧 bug 导致永远选不出标的）。
    """
    candidates = []
    for item in ranking:
        risk = (item.get('risk') or {}).get('score', 100)
        fc = item.get('forecast', {})
        up3 = fc.get('up_probability_3d_pct', 0)

        if risk < 40 and up3 > 60:
            candidates.append({
                'code': item['code'],
                'name': item['name'],
                'risk': risk,
                'up3': up3,
                'score': item.get('total_score', 0),
            })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates


def rebalance_robust(ranking, dry_run=False, temperature=None, config=None):
    """稳健组合：低风险 + 高概率，仓位随温度缩放"""
    print("\n" + "="*80)
    print("🛡️  稳健组合 - 防守型")
    print("="*80)

    enabled, size, base_ratio = portfolio_settings(
        'robust', config or {}, temperature,
        defaults={'size': 6, 'max_size': 15, 'min_size': 4, 'base_ratio': 0.8})

    candidates = robust_candidates(ranking)
    selected = candidates[:size]

    if not selected:
        print("❌ 无符合条件的股票（风险<40 且 3日概率>60%）")
        return

    print(f"✅ 选出 {len(selected)} 只 (温度联动={'开' if enabled else '关'}):")
    for i, s in enumerate(selected, 1):
        print(f"   {i}. {s['code']} {s['name']} | 风险{s['risk']:.1f} | 3日↑{s['up3']:.0f}%")

    # 仓位随温度缩放（基准 80% × 温度系数）
    position_pct = base_ratio * 100.0 * position_ratio_for_temperature(temperature) if enabled else base_ratio * 100.0
    pct = position_pct / len(selected)
    amount = int(1000000 * position_pct / 100.0) / len(selected)

    items = []
    for s in selected:
        items.append({
            "code": s['code'],
            "name": s['name'],
            "amount": int(amount),
            "pct": round(pct, 1),
            "reason": f"综合分{s['score']:.1f} | 风险{s['risk']:.0f} | 3日↑{s['up3']:.0f}%"
        })

    cash_pct = round(100.0 - position_pct, 1)
    portfolio = {
        "schema_version": "1.0",
        "name": "稳健组合-防守型",
        "risk_profile": "defensive",
        "capital": 1000000,
        "created_at": beijing_datetime_str(),
        "base_trade_date": beijing_date_str(),
        "rebalanced": True,
        "rebalance_date": beijing_date_str(),
        "cash_pct": cash_pct,
        "items": items,
        "cash": int(1000000 * (100.0 - position_pct) / 100.0),
        "color": "#2f9e6e",
        "description": f"稳健防守：温度联动仓位 {position_pct:.0f}%",
        "temperature_ratio": position_ratio_for_temperature(temperature) if enabled else None,
    }

    filepath = os.path.join(DATA_DIR, "paper", "portfolio.json")
    if not dry_run:
        backup_portfolio(filepath)
    save_portfolio(portfolio, filepath, dry_run)
    print(f"✅ 已更新: portfolio.json")


def rebalance_bluechip(ranking, dry_run=False, temperature=None, config=None):
    """蓝筹组合：大盘蓝筹，低波动"""
    print("\n" + "="*80)
    print("💎 蓝筹组合")
    print("="*80)

    enabled, size, base_ratio = portfolio_settings(
        'bluechip', config or {}, temperature,
        defaults={'size': 10, 'max_size': 20, 'min_size': 5, 'base_ratio': 1.0})

    # 蓝筹标准：市值大、波动低
    bluechip_codes = ['600519', '601318', '600036', '000858', '300750',
                      '00700', 'AAPL', 'MSFT', '601899', '600887']

    candidates = []
    for item in ranking:
        if item['code'] in bluechip_codes:
            candidates.append({
                'code': item['code'],
                'name': item['name'],
                'score': item.get('total_score', 0),
                'risk': (item.get('risk') or {}).get('score', 0)
            })

    # 按综合分排序，取 Top N
    candidates.sort(key=lambda x: x['score'], reverse=True)
    selected = candidates[:size]

    if not selected:
        print("❌ 无可用蓝筹股")
        return

    print(f"✅ 选出 {len(selected)} 只 (温度联动={'开' if enabled else '关'}):")
    for i, s in enumerate(selected, 1):
        print(f"   {i}. {s['code']} {s['name']} | 分数{s['score']:.1f}")

    position_pct = base_ratio * 100.0 * position_ratio_for_temperature(temperature) if enabled else base_ratio * 100.0
    pct = position_pct / len(selected)
    amount = int(1000000 * position_pct / 100.0) / len(selected)

    items = []
    for s in selected:
        items.append({
            "code": s['code'],
            "name": s['name'],
            "amount": int(amount),
            "pct": round(pct, 1),
            "reason": f"蓝筹 | 分数{s['score']:.1f} | 风险{s['risk']:.0f}"
        })

    cash_pct = round(100.0 - position_pct, 1)
    portfolio = {
        "schema_version": "1.0",
        "name": "蓝筹组合",
        "risk_profile": "conservative",
        "capital": 1000000,
        "created_at": beijing_datetime_str(),
        "base_trade_date": beijing_date_str(),
        "rebalanced": True,
        "rebalance_date": beijing_date_str(),
        "cash_pct": cash_pct,
        "items": items,
        "cash": int(1000000 * (100.0 - position_pct) / 100.0),
        "color": "#3b82f6",
        "description": f"蓝筹稳健：温度联动持仓 {len(selected)} 只",
        "temperature_ratio": position_ratio_for_temperature(temperature) if enabled else None,
    }

    filepath = os.path.join(DATA_DIR, "paper", "portfolio_bluechip.json")
    if not dry_run:
        backup_portfolio(filepath)
    save_portfolio(portfolio, filepath, dry_run)
    print(f"✅ 已更新: portfolio_bluechip.json")


def rebalance_defensive(ranking, dry_run=False, temperature=None, config=None):
    """防御组合：银行 + 黄金 + 公用事业"""
    print("\n" + "="*80)
    print("🛡️  防御组合")
    print("="*80)

    enabled, size, base_ratio = portfolio_settings(
        'defensive', config or {}, temperature,
        defaults={'size': 10, 'max_size': 20, 'min_size': 5, 'base_ratio': 1.0})

    # 防御性行业
    defensive_codes = ['601398', '601288', '600028', '601088', '600900',
                       '00941', '00005', '518880', '510050', '601857']

    candidates = []
    for item in ranking:
        if item['code'] in defensive_codes:
            candidates.append({
                'code': item['code'],
                'name': item['name'],
                'score': item.get('total_score', 0)
            })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    selected = candidates[:size]

    if not selected:
        print("❌ 无可用防御性股票")
        return

    print(f"✅ 选出 {len(selected)} 只 (温度联动={'开' if enabled else '关'}):")
    for i, s in enumerate(selected, 1):
        print(f"   {i}. {s['code']} {s['name']}")

    position_pct = base_ratio * 100.0 * position_ratio_for_temperature(temperature) if enabled else base_ratio * 100.0
    pct = position_pct / len(selected)
    amount = int(1000000 * position_pct / 100.0) / len(selected)

    items = []
    for s in selected:
        items.append({
            "code": s['code'],
            "name": s['name'],
            "amount": int(amount),
            "pct": round(pct, 1),
            "reason": f"防御 | 分数{s['score']:.1f}"
        })

    cash_pct = round(100.0 - position_pct, 1)
    portfolio = {
        "schema_version": "1.0",
        "name": "防御组合",
        "risk_profile": "defensive",
        "capital": 1000000,
        "created_at": beijing_datetime_str(),
        "base_trade_date": beijing_date_str(),
        "rebalanced": True,
        "rebalance_date": beijing_date_str(),
        "cash_pct": cash_pct,
        "items": items,
        "cash": int(1000000 * (100.0 - position_pct) / 100.0),
        "color": "#10b981",
        "description": f"防御配置：温度联动持仓 {len(selected)} 只",
        "temperature_ratio": position_ratio_for_temperature(temperature) if enabled else None,
    }

    filepath = os.path.join(DATA_DIR, "paper", "portfolio_defensive.json")
    if not dry_run:
        backup_portfolio(filepath)
    save_portfolio(portfolio, filepath, dry_run)
    print(f"✅ 已更新: portfolio_defensive.json")


def rebalance_global(ranking, dry_run=False, temperature=None, config=None):
    """全球组合：全球分散配置"""
    print("\n" + "="*80)
    print("🌍 全球组合")
    print("="*80)

    enabled, size, base_ratio = portfolio_settings(
        'global', config or {}, temperature,
        defaults={'size': 10, 'max_size': 20, 'min_size': 5, 'base_ratio': 1.0})
    cfg = (config or {}).get('global', {})
    region_ratios = cfg.get('regions') or {'stock': 0.3, 'hk': 0.2, 'us': 0.3, 'kr': 0.2}

    # 分市场选择
    cn_stocks = []
    hk_stocks = []
    us_stocks = []
    kr_stocks = []

    for item in ranking:
        stock_type = item.get('type', 'stock')
        score = item.get('total_score', 0)

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

    # 每市场按分数排序
    cn_stocks.sort(key=lambda x: x['score'], reverse=True)
    hk_stocks.sort(key=lambda x: x['score'], reverse=True)
    us_stocks.sort(key=lambda x: x['score'], reverse=True)
    kr_stocks.sort(key=lambda x: x['score'], reverse=True)

    # 按区域比例分配持仓数（温度联动时按缩放后的总持仓数分配）
    region_pool = {'stock': cn_stocks, 'hk': hk_stocks, 'us': us_stocks, 'kr': kr_stocks}
    counts = allocate_regions(size, region_ratios)
    selected = []
    for region, n in counts.items():
        selected.extend(region_pool.get(region, [])[:n])

    if len(selected) < 5:
        print("❌ 全球股票数量不足")
        return

    print(f"✅ 选出 {len(selected)} 只 (温度联动={'开' if enabled else '关'})（A股{counts.get('stock',0)} + 港股{counts.get('hk',0)} + 美股{counts.get('us',0)} + 韩股{counts.get('kr',0)}）:")
    for i, s in enumerate(selected, 1):
        print(f"   {i}. {s['code']} {s['name']}")

    position_pct = base_ratio * 100.0 * position_ratio_for_temperature(temperature) if enabled else base_ratio * 100.0
    pct = position_pct / len(selected)
    amount = int(1000000 * position_pct / 100.0) / len(selected)

    items = []
    for s in selected:
        items.append({
            "code": s['code'],
            "name": s['name'],
            "amount": int(amount),
            "pct": round(pct, 1),
            "reason": f"全球配置 | 分数{s['score']:.1f}"
        })

    cash_pct = round(100.0 - position_pct, 1)
    portfolio = {
        "schema_version": "1.0",
        "name": "全球组合",
        "risk_profile": "moderate",
        "capital": 1000000,
        "created_at": beijing_datetime_str(),
        "base_trade_date": beijing_date_str(),
        "rebalanced": True,
        "rebalance_date": beijing_date_str(),
        "cash_pct": cash_pct,
        "items": items,
        "cash": int(1000000 * (100.0 - position_pct) / 100.0),
        "color": "#8b5cf6",
        "description": f"全球分散：温度联动持仓 {len(selected)} 只",
        "temperature_ratio": position_ratio_for_temperature(temperature) if enabled else None,
    }

    filepath = os.path.join(DATA_DIR, "paper", "portfolio_global.json")
    if not dry_run:
        backup_portfolio(filepath)
    save_portfolio(portfolio, filepath, dry_run)
    print(f"✅ 已更新: portfolio_global.json")


def rebalance_tech(ranking, dry_run=False, temperature=None, config=None):
    """科技组合：科技股集中"""
    print("\n" + "="*80)
    print("💻 科技组合")
    print("="*80)

    enabled, size, base_ratio = portfolio_settings(
        'tech', config or {}, temperature,
        defaults={'size': 10, 'max_size': 20, 'min_size': 5, 'base_ratio': 1.0})

    # 科技股代码
    tech_codes = ['AAPL', 'MSFT', 'GOOGL', 'NVDA', '00700',
                  '300750', '688981', '601012', '513100', '005930']

    candidates = []
    for item in ranking:
        if item['code'] in tech_codes:
            candidates.append({
                'code': item['code'],
                'name': item['name'],
                'score': item.get('total_score', 0)
            })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    selected = candidates[:size]

    if not selected:
        print("❌ 无可用科技股")
        return

    print(f"✅ 选出 {len(selected)} 只 (温度联动={'开' if enabled else '关'}):")
    for i, s in enumerate(selected, 1):
        print(f"   {i}. {s['code']} {s['name']}")

    position_pct = base_ratio * 100.0 * position_ratio_for_temperature(temperature) if enabled else base_ratio * 100.0
    pct = position_pct / len(selected)
    amount = int(1000000 * position_pct / 100.0) / len(selected)

    items = []
    for s in selected:
        items.append({
            "code": s['code'],
            "name": s['name'],
            "amount": int(amount),
            "pct": round(pct, 1),
            "reason": f"科技 | 分数{s['score']:.1f}"
        })

    cash_pct = round(100.0 - position_pct, 1)
    portfolio = {
        "schema_version": "1.0",
        "name": "科技组合",
        "risk_profile": "aggressive",
        "capital": 1000000,
        "created_at": beijing_datetime_str(),
        "base_trade_date": beijing_date_str(),
        "rebalanced": True,
        "rebalance_date": beijing_date_str(),
        "cash_pct": cash_pct,
        "items": items,
        "cash": int(1000000 * (100.0 - position_pct) / 100.0),
        "color": "#ec4899",
        "description": f"科技集中：温度联动持仓 {len(selected)} 只",
        "temperature_ratio": position_ratio_for_temperature(temperature) if enabled else None,
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
    temperature, position_ratio = load_market_temperature()
    config = load_portfolio_config()

    print(f"   排行榜: {len(ranking)} 只")
    print(f"   激进扫描: {len(aggressive_scan)} 只")
    if temperature is not None:
        print(f"   市场温度: {temperature:.1f} | 仓位系数: {position_ratio:.2f}")

    if args.dry_run:
        print("\n🔍 预览模式（不实际修改文件）")

    # 调仓
    portfolios = {
        'aggressive': lambda: rebalance_aggressive(aggressive_scan, args.dry_run, temperature, config),
        'robust': lambda: rebalance_robust(ranking, args.dry_run, temperature, config),
        'bluechip': lambda: rebalance_bluechip(ranking, args.dry_run, temperature, config),
        'defensive': lambda: rebalance_defensive(ranking, args.dry_run, temperature, config),
        'global': lambda: rebalance_global(ranking, args.dry_run, temperature, config),
        'tech': lambda: rebalance_tech(ranking, args.dry_run, temperature, config),
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
