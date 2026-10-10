"""
tools/auto_update_watchlist_top_gainers.py —— 动态热点股自动沉淀与淘汰机制 (模式 B)

功能：
1. 每天盘后抓取全市场涨幅排名前列的强势股票（直连新浪财经原生接口，抗封锁能力极强）。
2. 过滤规则：
   - 过滤 ST / *ST 股票
   - 过滤北交所等非沪深主流标的（代码必须为 60/00/30/688 开头）
   - 过滤成交额过小（< 1.5 亿元）的流动性不足标的
3. 动态滑窗维护：
   - 上限设定为 400 只。
   - 每天将合格的 Top N 新龙头追加进 watchlist.csv。
   - 若总数超出上限（> 400 只），根据最近 60 日综合成交额与活跃度，淘汰末位冷门标的。
"""

import csv
from datetime import datetime, timedelta
import json
import logging
import os
import ssl
import sys
import urllib.request
from typing import List, Dict, Set, Optional, Any

# 清理环境变量代理干扰
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import (
    WATCHLIST_PATH,
    DATA_DIR,
    OBSERVATION_POOL_PATH,
    WATCHLIST_LOCK_STATE_PATH,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("auto_watchlist")

MAX_WATCHLIST_SIZE = 400
TOP_GAINERS_TO_ADD = 5  # 每日吸纳的新龙头数量
MIN_AMOUNT_THRESHOLD = 150000000.0  # 成交额门槛：1.5 亿元
MAX_OBSERVATION_SIZE = 100  # 观察池容纳候选数量上限


def fetch_top_gainers_sina() -> List[Dict]:
    """从新浪财经获取全市场涨幅前列股票。"""
    url = (
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "Market_Center.getHQNodeData?page=1&num=60&sort=changepercent&asc=0&node=hs_a&symbol=&_s_r_a=sort"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.sina.com.cn/",
    }
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as res:
            raw = res.read().decode("gbk", errors="ignore")
            items = json.loads(raw)
            
            candidates = []
            for it in items:
                code = str(it.get("code", "")).strip()
                name = str(it.get("name", "")).strip()
                pct = float(it.get("changepercent", 0.0))
                amount = float(it.get("amount", 0.0))
                
                if not code or not name:
                    continue
                if "ST" in name or "退" in name:
                    continue
                if amount < MIN_AMOUNT_THRESHOLD:
                    continue
                if not (code.startswith("60") or code.startswith("00") or code.startswith("30") or code.startswith("688")):
                    continue
                
                candidates.append({
                    "code": code,
                    "name": name,
                    "type": "stock",
                    "category": "热点龙头",
                    "change_pct": pct,
                    "amount": amount,
                })
            return candidates
    except Exception as e:
        logger.error("新浪涨幅榜抓取失败: %s", e)
        return []


def read_current_watchlist(path: str) -> List[Dict]:
    if not os.path.exists(path):
        return []
    items = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("code") and row.get("name"):
                items.append({
                    "code": row["code"].strip(),
                    "name": row["name"].strip(),
                    "type": row.get("type", "stock").strip(),
                    "category": row.get("category", "").strip() or "通用",
                })
    return items


def write_watchlist(path: str, items: List[Dict]):
    fieldnames = ["code", "name", "type", "category"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in items:
            writer.writerow({
                "code": item["code"],
                "name": item["name"],
                "type": item.get("type", "stock"),
                "category": item.get("category", "通用"),
            })


def read_lock_state(path: str = WATCHLIST_LOCK_STATE_PATH) -> Dict[str, Dict]:
    """读取核心池标的时序锁定状态字典。"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("读取锁定状态文件失败: %s", e)
        return {}


def save_lock_state(state: Dict[str, Dict], path: str = WATCHLIST_LOCK_STATE_PATH):
    """持久化核心池标的时序锁定状态。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("保存锁定状态失败: %s", e)


def is_stock_locked(code: str, as_of_date: Optional[str] = None, lock_state: Optional[Dict] = None) -> bool:
    """检查标的是否处于 3~5 日时序因果预测锁定期内。"""
    if lock_state is None:
        lock_state = read_lock_state()
    info = lock_state.get(code)
    if not info:
        return False
    lock_until = info.get("locked_until_date")
    if not lock_until:
        return False
    if as_of_date is None:
        as_of_date = datetime.now().strftime("%Y-%m-%d")
    return as_of_date <= lock_until


def lock_stock_for_days(code: str, days: int = 5, as_of_date: Optional[str] = None) -> Dict[str, Any]:
    """为标的加锁 N 个交易日（约自然日 7 天），防止在时序预测周期结束前被意外淘汰。"""
    now = datetime.now() if as_of_date is None else datetime.strptime(as_of_date, "%Y-%m-%d")
    entry_date = now.strftime("%Y-%m-%d")
    lock_until = (now + timedelta(days=max(days + 2, 7))).strftime("%Y-%m-%d")
    state = read_lock_state()
    state[code] = {
        "entry_date": entry_date,
        "locked_until_date": lock_until,
        "lock_days": days,
    }
    save_lock_state(state)
    return state[code]


def read_observation_pool(path: str = OBSERVATION_POOL_PATH) -> List[Dict]:
    """读取独立动态候选观察池。"""
    if not os.path.exists(path):
        return []
    items = []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("code") and row.get("name"):
                    items.append({
                        "code": row["code"].strip(),
                        "name": row["name"].strip(),
                        "type": row.get("type", "stock").strip(),
                        "category": row.get("category", "热点候选").strip(),
                        "added_date": row.get("added_date", "").strip(),
                        "change_pct": float(row.get("change_pct", 0.0) or 0.0),
                        "amount": float(row.get("amount", 0.0) or 0.0),
                    })
    except Exception as e:
        logger.warning("读取观察池失败: %s", e)
    return items


def write_observation_pool(path: str, items: List[Dict]):
    """写入独立动态候选观察池。"""
    fieldnames = ["code", "name", "type", "category", "added_date", "change_pct", "amount"]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for item in items:
                writer.writerow({
                    "code": item["code"],
                    "name": item["name"],
                    "type": item.get("type", "stock"),
                    "category": item.get("category", "热点候选"),
                    "added_date": item.get("added_date", datetime.now().strftime("%Y-%m-%d")),
                    "change_pct": round(float(item.get("change_pct", 0.0) or 0.0), 2),
                    "amount": round(float(item.get("amount", 0.0) or 0.0), 2),
                })
    except Exception as e:
        logger.warning("写入观察池失败: %s", e)


def evaluate_lowest_priority_stocks(
    current_items: List[Dict], count_to_remove: int, as_of_date: Optional[str] = None
) -> Set[str]:
    """当核心池超额时，根据成交额及活跃度淘汰末位标的。处于 5 日预测窗口锁定期内的标的豁免淘汰。"""
    summary_path = os.path.join(DATA_DIR, "summary.json")
    amount_map = {}
    if os.path.exists(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                sdata = json.load(f)
                for it in sdata.get("items", []):
                    amount_map[it.get("code")] = it.get("amount", 0)
        except Exception:
            pass

    lock_state = read_lock_state()
    today_str = as_of_date or datetime.now().strftime("%Y-%m-%d")

    scored_items = []
    for item in current_items:
        code = item["code"]
        # 1. ETF 指数类核心标的豁免淘汰
        if item.get("type") == "etf" or code.startswith("51") or code.startswith("15") or code.startswith("58"):
            score = 999999999
        # 2. 处于 3~5 日时序因果预测锁定期内的标的豁免淘汰，确保完成回测验证闭环
        elif is_stock_locked(code, as_of_date=today_str, lock_state=lock_state):
            score = 999999999
        else:
            score = amount_map.get(code, 0)
        scored_items.append((code, score))

    scored_items.sort(key=lambda x: x[1])
    # 仅从非豁免标的中挑选淘汰对象
    eligible_to_remove = [code for code, score in scored_items if score < 999999999]
    to_remove_codes = set(eligible_to_remove[:count_to_remove])
    return to_remove_codes


def update_observation_pool_with_top_gainers(
    pool_path: str = OBSERVATION_POOL_PATH,
    max_observation_size: int = MAX_OBSERVATION_SIZE,
    top_k: int = 15,
) -> int:
    """从市场涨幅榜吸纳新龙头进入独立候选观察池（完全不污染核心自选池）。"""
    logger.info("=== 启动独立候选观察池更新机制 (上限 %d 只) ===", max_observation_size)
    existing_items = read_observation_pool(pool_path)
    existing_map = {it["code"]: it for it in existing_items}
    core_watchlist_codes = {it["code"] for it in read_current_watchlist(WATCHLIST_PATH)}

    candidates = fetch_top_gainers_sina()
    if not candidates:
        logger.warning("未能获取到有效市场涨幅榜数据，跳过观察池更新。")
        return 0

    today_str = datetime.now().strftime("%Y-%m-%d")
    added_or_updated = 0

    for cand in candidates:
        code = cand["code"]
        # 已经在核心自选池的标的不必重复堆积到观察池
        if code in core_watchlist_codes:
            continue

        cand["added_date"] = today_str
        existing_map[code] = cand
        added_or_updated += 1
        if added_or_updated >= top_k:
            break

    # 按加入日期及成交额降序排序截取上限
    all_observed = list(existing_map.values())
    all_observed.sort(key=lambda x: (x.get("added_date", ""), x.get("amount", 0.0)), reverse=True)
    all_observed = all_observed[:max_observation_size]

    write_observation_pool(pool_path, all_observed)
    logger.info("✅ 动态候选观察池更新完成: 存量 %d 只 (本次新增/刷新 %d 只)", len(all_observed), added_or_updated)
    return added_or_updated


def promote_to_core_watchlist(
    codes: List[str],
    watchlist_path: str = WATCHLIST_PATH,
    observation_path: str = OBSERVATION_POOL_PATH,
    max_size: int = MAX_WATCHLIST_SIZE,
    lock_days: int = 5,
) -> int:
    """当策略买点触发时，将观察池中的黑马标的晋级至核心跟踪池，并激活 5 日时序窗口锁定。"""
    if not codes:
        return 0
    current_items = read_current_watchlist(watchlist_path)
    current_codes = {it["code"] for it in current_items}
    obs_items = {it["code"]: it for it in read_observation_pool(observation_path)}

    promoted_items = []
    for c in codes:
        if c in current_codes:
            continue
        info = obs_items.get(c, {"code": c, "name": c, "type": "stock", "category": "策略晋级"})
        promoted_items.append({
            "code": info["code"],
            "name": info["name"],
            "type": info.get("type", "stock"),
            "category": "策略晋级",
        })
        lock_stock_for_days(c, days=lock_days)

    if not promoted_items:
        return 0

    logger.info(
        "🎯 策略买点触发，成功晋级 %d 只标的至核心池 (锁定 %d 日预测周期): %s",
        len(promoted_items),
        lock_days,
        ", ".join(f"{it['name']}({it['code']})" for it in promoted_items),
    )
    updated_items = current_items + promoted_items

    if len(updated_items) > max_size:
        excess = len(updated_items) - max_size
        remove_codes = evaluate_lowest_priority_stocks(updated_items, excess)
        final_items = [it for it in updated_items if it["code"] not in remove_codes]
        logger.info("已淘汰低活跃非锁定标的: %s", ", ".join(remove_codes))
    else:
        final_items = updated_items

    write_watchlist(watchlist_path, final_items)
    return len(promoted_items)


def update_watchlist_with_top_gainers(max_size: int = MAX_WATCHLIST_SIZE, top_k: int = TOP_GAINERS_TO_ADD) -> int:
    """流水线主入口：自动刷新候选观察池，同时维护核心池的 5 日窗口锁定与淘汰保护。"""
    # 1. 刷新候选观察池（不暴力塞入核心池，避免破坏预测时序与产生 Token 浪费）
    added_obs = update_observation_pool_with_top_gainers(top_k=top_k)

    # 2. 检查核心自选池是否超出上限，如果超出则在保护锁定标的的前提下末位淘汰
    current_items = read_current_watchlist(WATCHLIST_PATH)
    if len(current_items) > max_size:
        excess = len(current_items) - max_size
        remove_codes = evaluate_lowest_priority_stocks(current_items, excess)
        if remove_codes:
            final_items = [it for it in current_items if it["code"] not in remove_codes]
            write_watchlist(WATCHLIST_PATH, final_items)
            logger.info("核心自选池末位淘汰 (%d 只，时序锁定标的已受保护): %s", len(remove_codes), ", ".join(remove_codes))

    return added_obs


if __name__ == "__main__":
    update_watchlist_with_top_gainers()
