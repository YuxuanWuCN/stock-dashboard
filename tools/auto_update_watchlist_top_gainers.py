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
import json
import logging
import os
import ssl
import sys
import urllib.request
from typing import List, Dict, Set

# 清理环境变量代理干扰
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import WATCHLIST_PATH, DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("auto_watchlist")

MAX_WATCHLIST_SIZE = 400
TOP_GAINERS_TO_ADD = 5  # 每日吸纳的新龙头数量
MIN_AMOUNT_THRESHOLD = 150000000.0  # 成交额门槛：1.5 亿元


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


def evaluate_lowest_priority_stocks(current_items: List[Dict], count_to_remove: int) -> Set[str]:
    """当池子满 400 只时，根据成交额及活跃度淘汰末位冷门标的。"""
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

    scored_items = []
    for item in current_items:
        code = item["code"]
        # ETF 指数类核心标的豁免淘汰
        if item.get("type") == "etf" or code.startswith("51") or code.startswith("15") or code.startswith("58"):
            score = 999999999
        else:
            score = amount_map.get(code, 0)
        scored_items.append((code, score))

    scored_items.sort(key=lambda x: x[1])
    to_remove_codes = set(code for code, _ in scored_items[:count_to_remove])
    return to_remove_codes


def update_watchlist_with_top_gainers(max_size: int = MAX_WATCHLIST_SIZE, top_k: int = TOP_GAINERS_TO_ADD) -> int:
    logger.info("=== 启动自选股热点龙头自动沉淀机制 (动态上限 %d 只) ===", max_size)
    current_items = read_current_watchlist(WATCHLIST_PATH)
    current_codes = {it["code"] for it in current_items}
    logger.info("当前自选股存量: %d 只", len(current_items))

    # 1. 抓取今日全市场涨幅榜
    top_candidates = fetch_top_gainers_sina()
    if not top_candidates:
        logger.warning("未能获取到有效市场涨幅榜数据，跳过本次更新。")
        return 0

    # 2. 筛选出尚未在自选股池中的龙头
    new_to_add = []
    for cand in top_candidates:
        if cand["code"] not in current_codes:
            new_to_add.append(cand)
            if len(new_to_add) >= top_k:
                break

    if not new_to_add:
        logger.info("今日前列热点龙头已全部存在于自选股池中。")
        return 0

    logger.info("今日发现并吸纳新龙头 (%d 只): %s", len(new_to_add), ", ".join(f"{c['name']}({c['code']}) +{c['change_pct']}%" for c in new_to_add))

    # 3. 动态滑窗淘汰
    updated_items = list(current_items)
    for c in new_to_add:
        updated_items.append({
            "code": c["code"],
            "name": c["name"],
            "type": c["type"],
            "category": c["category"],
        })

    if len(updated_items) > max_size:
        excess = len(updated_items) - max_size
        logger.info("自选股总数 (%d) 超出上限 (%d)，执行末位淘汰 (%d 只)...", len(updated_items), max_size, excess)
        remove_codes = evaluate_lowest_priority_stocks(updated_items, excess)
        final_items = [it for it in updated_items if it["code"] not in remove_codes]
        logger.info("已淘汰低活跃标的: %s", ", ".join(remove_codes))
    else:
        final_items = updated_items

    # 4. 落盘保存
    write_watchlist(WATCHLIST_PATH, final_items)
    logger.info("✅ 自选股沉淀完成！当前自选股总数: %d 只", len(final_items))
    return len(new_to_add)


if __name__ == "__main__":
    update_watchlist_with_top_gainers()
