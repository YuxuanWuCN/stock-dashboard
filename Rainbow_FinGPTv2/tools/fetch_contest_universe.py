# -*- coding: utf-8 -*-
"""tools/fetch_contest_universe.py —— 参赛实证矩阵专用标的抓取器

用途：为「存储超级周期」与「黄金避险（地缘冲突驱动）」两大板块补齐最新 K 线数据，
写入 docs/data/kline/{code}.json（沿用 fetch_data 的既有 JSON 契约与前复权口径）。

不覆盖已有其他标的，不修改原始数据格式；仅按 --codes 指定范围增量更新。
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import REQUEST_INTERVAL, LOOKBACK_DAYS_5Y  # noqa: E402
from src.utils import beijing_today, calc_start_date  # noqa: E402
from src.fetch_data import (  # noqa: E402
    build_kline_json,
    compute_derived,
    fetch_one,
    save_kline_json,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fetch_contest_universe")


# ============================================================
# 参赛实证矩阵标的池（板块分组）
# ============================================================

STORAGE_SUPERCYCLE = [
    {"code": "688525", "name": "佰维存储", "type": "stock", "category": "存储-模组"},
    {"code": "301308", "name": "江波龙", "type": "stock", "category": "存储-模组"},
    {"code": "001309", "name": "德明利", "type": "stock", "category": "存储-模组"},
    {"code": "300475", "name": "香农芯创", "type": "stock", "category": "存储-分销"},
    {"code": "603986", "name": "兆易创新", "type": "stock", "category": "存储-原厂"},
    {"code": "688110", "name": "东芯股份", "type": "stock", "category": "存储-原厂"},
    {"code": "688766", "name": "普冉股份", "type": "stock", "category": "存储-原厂"},
    {"code": "300223", "name": "北京君正", "type": "stock", "category": "存储-车规"},
    {"code": "000021", "name": "深科技", "type": "stock", "category": "存储-封测"},
    {"code": "600667", "name": "太极实业", "type": "stock", "category": "存储-长鑫概念"},
    {"code": "002156", "name": "通富微电", "type": "stock", "category": "存储-封测"},
    {"code": "688200", "name": "华峰测控", "type": "stock", "category": "存储-测试设备"},
]

GOLD_SAFE_HAVEN = [
    {"code": "600547", "name": "山东黄金", "type": "stock", "category": "黄金-龙头"},
    {"code": "600489", "name": "中金黄金", "type": "stock", "category": "黄金-央企"},
    {"code": "000975", "name": "山金国际", "type": "stock", "category": "黄金-弹性"},
    {"code": "002155", "name": "湖南黄金", "type": "stock", "category": "黄金-锑金"},
    {"code": "600988", "name": "赤峰黄金", "type": "stock", "category": "黄金-成长"},
    {"code": "601899", "name": "紫金矿业", "type": "stock", "category": "黄金-铜金"},
    {"code": "601069", "name": "西部黄金", "type": "stock", "category": "黄金-小盘"},
    {"code": "518880", "name": "黄金ETF", "type": "etf", "category": "黄金-商品"},
    {"code": "159562", "name": "黄金股ETF", "type": "etf", "category": "黄金-股票"},
]

GROUPS = {
    "storage": STORAGE_SUPERCYCLE,
    "gold": GOLD_SAFE_HAVEN,
    "all": STORAGE_SUPERCYCLE + GOLD_SAFE_HAVEN,
}


def fetch_and_save(item: dict, start_date: str, end_date: str) -> tuple[str, bool, str]:
    """抓取单只标的并落盘。返回 (code, ok, message)。"""
    code = item["code"]
    name = item["name"]
    try:
        df = fetch_one(item, start_date, end_date)
        if df is None or df.empty:
            return code, False, "抓取失败或空数据"

        df = compute_derived(df)
        payload = build_kline_json(item, df)
        save_kline_json(item, payload)

        first = payload["dates"][0]
        last = payload["dates"][-1]
        return code, True, f"{name} {len(df)} 行 [{first} ~ {last}]"
    except Exception as exc:  # noqa: BLE001
        return code, False, f"异常: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description="参赛实证矩阵标的 K 线抓取")
    parser.add_argument(
        "--group",
        choices=sorted(GROUPS.keys()),
        default="all",
        help="抓取板块分组：storage / gold / all（默认 all）",
    )
    parser.add_argument(
        "--codes",
        type=str,
        default="",
        help="仅抓取指定代码，逗号分隔（覆盖 --group）",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=LOOKBACK_DAYS_5Y,
        help=f"回溯自然日数，默认 {LOOKBACK_DAYS_5Y}（约 5 年，覆盖上一轮超级周期）",
    )
    args = parser.parse_args()

    universe = GROUPS[args.group]
    if args.codes.strip():
        wanted = {c.strip() for c in args.codes.split(",") if c.strip()}
        by_code = {it["code"]: it for it in GROUPS["all"]}
        universe = []
        for code in wanted:
            if code in by_code:
                universe.append(by_code[code])
            else:
                universe.append({"code": code, "name": f"标的{code}", "type": "stock", "category": "自定义"})

    today = beijing_today()
    start_date = calc_start_date(today, args.lookback_days)
    end_date = today.strftime("%Y%m%d")

    logger.info("=" * 64)
    logger.info("参赛实证矩阵抓取：group=%s，共 %d 只标的", args.group, len(universe))
    logger.info("日期范围：%s ~ %s（%d 自然日，前复权）", start_date, end_date, args.lookback_days)
    logger.info("=" * 64)

    ok_list: list[str] = []
    fail_list: list[str] = []

    for idx, item in enumerate(universe, start=1):
        logger.info("[%d/%d] 抓取 %s(%s) ...", idx, len(universe), item["name"], item["code"])
        code, ok, msg = fetch_and_save(item, start_date, end_date)
        if ok:
            logger.info("  ✓ %s", msg)
            ok_list.append(f"{code} {item['name']}")
        else:
            logger.warning("  ✗ %s %s", code, msg)
            fail_list.append(f"{code} {item['name']}: {msg}")

        if idx < len(universe):
            time.sleep(REQUEST_INTERVAL)

    logger.info("=" * 64)
    logger.info("抓取完成：成功 %d / 失败 %d", len(ok_list), len(fail_list))
    if fail_list:
        for line in fail_list:
            logger.warning("  失败明细: %s", line)
    logger.info("=" * 64)

    return 0 if not fail_list else 1


if __name__ == "__main__":
    sys.exit(main())
