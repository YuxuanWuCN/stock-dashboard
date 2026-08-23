"""
tools/rebalance_variants.py —— 策略进化衍生变体自动调仓系统

根据 weekly_champion_analysis.py 生成的衍生策略配置（位于 docs/data/paper/strategy_variants/），
读取其 parent_strategy 与 changes 参数，动态选股、分配权重并建仓。

用法：
    python tools/rebalance_variants.py             # 调仓所有活跃衍生组合
    python tools/rebalance_variants.py --dry-run   # 预览调仓结果
"""

import json
import os
import sys
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DATA_DIR
from src.utils import beijing_date_str, beijing_datetime_str

VARIANTS_DIR = os.path.join(DATA_DIR, "paper", "strategy_variants")
RANKING_FILE = os.path.join(DATA_DIR, "analysis", "ranking.json")
AGGRESSIVE_SCAN_FILE = os.path.join(DATA_DIR, "paper", "aggressive_scan.json")
MARKET_TEMP_FILE = os.path.join(DATA_DIR, "strategy", "market_temperature.json")


def load_ranking():
    if not os.path.exists(RANKING_FILE):
        return []
    try:
        with open(RANKING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("items", [])
    except Exception:
        return []


def load_aggressive_scan():
    if not os.path.exists(AGGRESSIVE_SCAN_FILE):
        try:
            from tools.aggressive_scan import scan
            return scan()
        except Exception:
            return []
    try:
        with open(AGGRESSIVE_SCAN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            items = data.get("all") or data.get("items", [])
            if not items:
                from tools.aggressive_scan import scan
                return scan()
            return items
    except Exception:
        return []


def load_market_temperature():
    if not os.path.exists(MARKET_TEMP_FILE):
        return None, 1.0
    try:
        with open(MARKET_TEMP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            ratio = data.get("position_ratio_adjusted", data.get("position_ratio", 1.0))
            return data.get("temperature"), float(ratio)
    except Exception:
        return None, 1.0


def _parse_float(val, default=0.0):
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().rstrip("%")
    try:
        return float(s)
    except Exception:
        return default


def select_variant_holdings(parent: str, changes: dict, scan_list: list, ranking_list: list):
    """根据 parent 策略和变体 changes 参数筛选标的并计算权重。"""
    changes = changes or {}
    parent = (parent or "aggressive").lower()

    # 1. 基础标的源
    if parent == "aggressive":
        candidates = list(scan_list)
    else:
        # 其他类型从 ranking 中取
        candidates = []
        for item in ranking_list:
            candidates.append({
                "code": item.get("code"),
                "name": item.get("name"),
                "aggressive_score": item.get("total_score", 0),
                "up3": (item.get("forecast") or {}).get("up_probability_3d_pct", 0),
                "up5": (item.get("forecast") or {}).get("up_probability_5d_pct", 0),
                "return_20d_pct": item.get("return_20d_pct", 0),
                "risk": (item.get("risk") or {}).get("score", 50),
            })

    if not candidates:
        return [], 0.0

    # 2. 解析 changes 中的各项过滤条件
    # 2.1 置信度/概率过滤 (支持中文与英文键)
    min_prob = _parse_float(
        changes.get("预测置信度阈值") or
        changes.get("min_prob") or
        changes.get("min_confidence") or
        changes.get("概率阈值")
    )
    # 若以小数 (如 0.6) 给出，转为百分制 60%
    if 0 < min_prob <= 1.0:
        min_prob *= 100.0

    if min_prob > 0:
        candidates = [c for c in candidates if c.get("up3", 0) >= min_prob or c.get("up5", 0) >= min_prob]

    # 2.2 预期收益阈值
    min_ret = _parse_float(
        changes.get("最低预期收益阈值") or
        changes.get("min_return") or
        changes.get("min_expected_return")
    )
    if min_ret > 0:
        candidates = [c for c in candidates if c.get("return_20d_pct", 0) >= min_ret]

    # 2.3 风险阈值过滤
    max_risk = _parse_float(
        changes.get("max_risk") or
        changes.get("max_risk_score") or
        changes.get("风险上限")
    )
    if max_risk > 0:
        candidates = [c for c in candidates if c.get("risk", 0) <= max_risk]

    # 2.4 排序逻辑
    if changes.get("momentum_only"):
        candidates.sort(key=lambda x: x.get("return_20d_pct", 0), reverse=True)
    else:
        # 默认按综合分/激进分排序
        candidates.sort(key=lambda x: x.get("aggressive_score", 0), reverse=True)

    # 2.5 选股数量
    top_n = int(changes.get("top_n") or changes.get("size") or 8)
    selected = candidates[:top_n]
    if not selected:
        return [], 0.0

    # 3. 权重分配
    weight_scheme = str(changes.get("权重分配方式") or changes.get("weight_scheme") or "").strip()
    cash_pct = _parse_float(changes.get("cash_pct"), default=0.0)
    invest_pct = 100.0 - cash_pct

    n = len(selected)
    if "排名加权" in weight_scheme or "Top10%权重翻倍" in weight_scheme or "top_heavy" in weight_scheme:
        # 头部加权：前半部分标的权重翻倍
        half = max(1, n // 2)
        raw_weights = [2.0 if i < half else 1.0 for i in range(n)]
        sum_w = sum(raw_weights)
        pcts = [round(invest_pct * (w / sum_w), 1) for w in raw_weights]
    else:
        # 等权配置
        pcts = [round(invest_pct / n, 1) for _ in range(n)]

    # 微调尾差
    diff = round(invest_pct - sum(pcts), 1)
    if pcts and diff != 0:
        pcts[0] = round(pcts[0] + diff, 1)

    items = []
    capital = 1000000
    stop_loss = changes.get("止损线", "")
    take_profit = changes.get("止盈线", "")
    risk_note = f" | 风控[损{stop_loss} 盈{take_profit}]" if (stop_loss or take_profit) else ""

    for s, pct in zip(selected, pcts):
        amount = int(capital * pct / 100.0)
        score = s.get('aggressive_score') or 0
        up3 = s.get('up3') or 0
        ret20 = s.get('return_20d_pct') or 0
        items.append({
            "code": s.get("code"),
            "name": s.get("name"),
            "amount": amount,
            "pct": pct,
            "reason": f"变体评分{score:.1f} | 3日↑{up3:.0f}% | 20日{ret20:+.1f}%{risk_note}"
        })

    return items, cash_pct


def rebalance_variants(dry_run: bool = False) -> int:
    """遍历所有活跃衍生组合，执行调仓并保存。"""
    if not os.path.exists(VARIANTS_DIR):
        print(f"📁 衍生策略目录不存在: {VARIANTS_DIR}")
        return 0

    scan_list = load_aggressive_scan()
    ranking_list = load_ranking()

    files = [f for f in os.listdir(VARIANTS_DIR) if f.startswith("portfolio_") and f.endswith(".json")]
    if not files:
        print("未找到衍生组合配置文件。")
        return 0

    print("=" * 80)
    print("🧬 策略进化衍生变体调仓系统")
    print(f"发现 {len(files)} 个衍生组合配置文件")
    print("=" * 80)

    updated_count = 0
    for filename in sorted(files):
        filepath = os.path.join(VARIANTS_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"❌ 读取 {filename} 失败: {e}")
            continue

        if data.get("status") not in ("active", "testing", None):
            print(f"⏸️ 跳过非活跃组合: {filename} (status={data.get('status')})")
            continue

        parent = data.get("parent_strategy", "aggressive")
        changes = data.get("changes", {})
        display_name = data.get("name", filename)

        items, cash_pct = select_variant_holdings(parent, changes, scan_list, ranking_list)
        if not items:
            print(f"⚠️ {display_name} ({filename}) 未能选出符合条件的标的，保留原持仓")
            continue

        data["items"] = items
        data["cash_pct"] = cash_pct
        data["cash"] = int(1000000 * cash_pct / 100.0)
        data["base_trade_date"] = beijing_date_str()
        data["rebalanced"] = True
        data["rebalance_date"] = beijing_date_str()
        data["updated_at"] = beijing_datetime_str()

        print(f"\n✅ 【{display_name}】选出 {len(items)} 只标的 (现金 {cash_pct}%):")
        for idx, it in enumerate(items, 1):
            print(f"   {idx}. {it['code']} {it['name']} ({it['pct']}%) - {it['reason']}")

        if not dry_run:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"💾 已更新持仓: {filename}")
        updated_count += 1

    print("\n" + "=" * 80)
    print(f"🎉 衍生组合调仓完成！共处理 {updated_count} 个组合")
    print("=" * 80)
    return 0


def main():
    parser = argparse.ArgumentParser(description="策略进化衍生变体调仓")
    parser.add_argument("--dry-run", action="store_true", help="预览调仓结果，不写文件")
    args = parser.parse_args()
    return rebalance_variants(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
