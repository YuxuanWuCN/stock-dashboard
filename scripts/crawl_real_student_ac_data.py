# -*- coding: utf-8 -*-
"""scripts/crawl_real_student_ac_data.py

Fetch authentic announcements and news for Student A (100 tech/manufacturing stocks)
and Student C (100 finance/consumer stocks) via AkShare real financial APIs.

Key features:
1. AkShare real APIs:
   - ak.stock_individual_notice_report(security=code, symbol='全部', begin_date='2024-01-01')
   - ak.stock_news_em(symbol=code)
2. Strict 6-digit stock codes preserving leading zeros (e.g., '000001', '002594') via str(code).zfill(6).
3. Resilient networking:
   - Global socket timeout (15s)
   - Exponential retry with jitter (up to 3 retries)
   - Polite delay (0.2s - 0.3s) between requests
   - Concurrent thread pool (3-5 workers)
4. Atomic file writes:
   - Target: data/raw/student_ac_crawled/{code}.jsonl
   - Companion: data/raw/student_ac_crawled/{code}.meta.json
   - Manifest: data/raw/student_ac_crawled/manifest.json
5. Zero synthetic data:
   - 100% genuine announcements and news
   - Strict assertion: announcement_count > 0 for all 200 stocks
   - Cryptographic SHA256 hash of canonical items
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import hashlib
import json
import logging
import os
import random
import re
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

# Global socket timeout to prevent hang / deadlock at TCP layer
socket.setdefaulttimeout(15.0)

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
TASK_SPLIT_DIR = DATA_DIR / "task_split"
DEFAULT_OUTPUT_DIR = DATA_DIR / "raw" / "student_ac_crawled"

STUDENT_A_CSV = TASK_SPLIT_DIR / "student_A_tech_manufacturing_100.csv"
STUDENT_C_CSV = TASK_SPLIT_DIR / "student_C_finance_consumer_100.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("crawl_real_student_ac")


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _first(row: Dict[str, Any], names: Iterable[str]) -> str:
    for name in names:
        val = _text(row.get(name))
        if val:
            return val
    return ""


def _records_from_frame(frame: Any, item_type: str) -> List[Dict[str, str]]:
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    result: List[Dict[str, str]] = []
    for row in frame.to_dict(orient="records"):
        title = _first(row, ("新闻标题", "公告标题", "title", "Title"))
        content = _first(row, ("新闻内容", "公告内容", "content", "Content"))
        if not title and not content:
            continue
        result.append(
            {
                "item_type": item_type,
                "title": title,
                "content": content,
                "source": _first(row, ("文章来源", "source", "来源")),
                "publish_time": _first(row, ("发布时间", "公告日期", "publish_time", "date")),
                "url": _first(row, ("新闻链接", "公告链接", "url", "链接")),
            }
        )
    return result


def _corpus_text(items: List[Dict[str, str]]) -> str:
    parts = []
    for item in items[:40]:
        parts.append(f"[{item['item_type']}] {item['title']} {item['content']}")
    text = "\n".join(parts).strip()
    return text[:12000]


def _corpus_hash(items: List[Dict[str, str]]) -> str:
    canonical = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_stock_targets() -> List[Dict[str, Any]]:
    """读取同学 A 与同学 C 各 100 支标的清单，严格保留 6 位字符串代码。"""
    stocks: List[Dict[str, Any]] = []

    if not STUDENT_A_CSV.exists():
        raise FileNotFoundError(f"Missing Student A file: {STUDENT_A_CSV}")
    if not STUDENT_C_CSV.exists():
        raise FileNotFoundError(f"Missing Student C file: {STUDENT_C_CSV}")

    df_a = pd.read_csv(STUDENT_A_CSV, dtype={"code": str}, encoding="utf-8-sig")
    for _, row in df_a.iterrows():
        code = str(row["code"]).strip().zfill(6)
        stocks.append(
            {
                "code": code,
                "name": str(row["name"]).strip(),
                "cohort": "student_A",
                "sector": str(row.get("sector", "tech")).strip(),
                "sub_industry": str(row.get("sub_industry", "硬科技与半导体")).strip(),
            }
        )

    df_c = pd.read_csv(STUDENT_C_CSV, dtype={"code": str}, encoding="utf-8-sig")
    for _, row in df_c.iterrows():
        code = str(row["code"]).strip().zfill(6)
        stocks.append(
            {
                "code": code,
                "name": str(row["name"]).strip(),
                "cohort": "student_C",
                "sector": str(row.get("sector", "bluechip")).strip(),
                "sub_industry": str(row.get("sub_industry", "大金融与央国企")).strip(),
            }
        )

    if len(stocks) != 200:
        raise ValueError(f"Expected exactly 200 stocks, got {len(stocks)}")

    return stocks


def is_already_crawled(code: str, output_dir: Path) -> Optional[Dict[str, Any]]:
    """检查标的是否已被完整抓取且内容可独立校验。"""
    jsonl_path = output_dir / f"{code}.jsonl"
    meta_path = output_dir / f"{code}.meta.json"
    if not jsonl_path.exists() or not meta_path.exists():
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("announcement_count", 0) <= 0:
            return None
        if not meta.get("input_sha256"):
            return None

        # 校验 jsonl 完整性
        with open(jsonl_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        if len(lines) != meta.get("total_items", -1):
            return None

        # 重新计算哈希一致性
        canonical = json.dumps(lines, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        calc_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if calc_hash != meta["input_sha256"]:
            return None

        return meta
    except Exception:
        return None


def fetch_stock_data(
    stock: Dict[str, Any],
    begin_date: str = "2024-01-01",
    max_retries: int = 3,
) -> Dict[str, Any]:
    """从 AkShare 抓取真实新闻与公告。带超时、抖动重试与零伪造断言。"""
    import akshare as ak

    code = str(stock["code"]).strip().zfill(6)
    name = str(stock["name"]).strip()
    cohort = str(stock["cohort"]).strip()
    sector = str(stock.get("sector", "")).strip()
    sub_industry = str(stock.get("sub_industry", "")).strip()

    news_items: List[Dict[str, str]] = []
    ann_items: List[Dict[str, str]] = []

    # 1. 抓取新闻（东财新闻偶尔因频控返回空或报错，支持重试）
    for attempt in range(1, max_retries + 1):
        try:
            time.sleep(random.uniform(0.2, 0.3))
            df_news = ak.stock_news_em(symbol=code)
            news_items = _records_from_frame(df_news, "news")
            break
        except Exception as exc:
            if attempt == max_retries:
                logger.warning(
                    f"[{code} {name}] 新闻抓取在第 {max_retries} 次重试后失败: {exc}。继续尝试公告抓取。"
                )
                news_items = []
            else:
                wait_time = (1.5 ** attempt) + random.uniform(0.1, 0.3)
                logger.info(
                    f"[{code} {name}] 新闻尝试 {attempt} 发生异常: {exc}，将在 {wait_time:.2f}s 后重试..."
                )
                time.sleep(wait_time)

    # 2. 抓取公告（强制要求：上市公司必有法定公告，announcement_count 必须 > 0）
    for attempt in range(1, max_retries + 1):
        try:
            time.sleep(random.uniform(0.2, 0.3))
            df_ann = ak.stock_individual_notice_report(
                security=code,
                symbol="全部",
                begin_date=begin_date,
            )
            ann_items = _records_from_frame(df_ann, "announcement")
            if ann_items:
                break
            if attempt < max_retries:
                wait_time = (1.5 ** attempt) + random.uniform(0.1, 0.3)
                logger.warning(
                    f"[{code} {name}] 公告返回空列表 (尝试 {attempt}/{max_retries})，将在 {wait_time:.2f}s 后重试..."
                )
                time.sleep(wait_time)
            else:
                raise ValueError(
                    f"[{code} {name}] 公告在第 {max_retries} 次重试后仍然为空"
                )
        except Exception as exc:
            # 若因早年吸收合并/退市导致在 2024 年后无公告而触发 AkShare KeyError 或空，尝试放宽时间段获取真实法定公告
            if isinstance(exc, (KeyError, ValueError)) or "代码" in str(exc) or attempt == max_retries:
                try:
                    logger.info(
                        f"[{code} {name}] 尝试放宽公告起始日期至 2020-01-01 抓取历史公告..."
                    )
                    df_ann = ak.stock_individual_notice_report(
                        security=code,
                        symbol="全部",
                        begin_date="2020-01-01",
                    )
                    ann_items = _records_from_frame(df_ann, "announcement")
                    if ann_items:
                        break
                except Exception as inner_exc:
                    logger.warning(f"[{code} {name}] 2020-01-01 放宽抓取失败: {inner_exc}")

            if attempt == max_retries and not ann_items:
                logger.error(
                    f"[{code} {name}] 公告抓取在第 {max_retries} 次重试后失败: {exc}"
                )
                raise
            wait_time = (1.5 ** attempt) + random.uniform(0.1, 0.3)
            logger.warning(
                f"[{code} {name}] 公告尝试 {attempt} 发生异常: {exc}，将在 {wait_time:.2f}s 后重试..."
            )
            time.sleep(wait_time)

    if not ann_items:
        raise ValueError(f"[{code} {name}] 零伪造门禁拦截: 公告记录数必须 > 0！")

    all_items = news_items + ann_items
    raw_text = _corpus_text(all_items)
    input_sha256 = _corpus_hash(all_items)
    retrieved_at_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

    return {
        "code": code,
        "name": name,
        "cohort": cohort,
        "sector": sector,
        "sub_industry": sub_industry,
        "news_count": len(news_items),
        "announcement_count": len(ann_items),
        "total_items": len(all_items),
        "input_sha256": input_sha256,
        "retrieved_at_utc": retrieved_at_utc,
        "raw_text": raw_text,
        "items": all_items,
    }


def save_stock_atomic(result: Dict[str, Any], output_dir: Path) -> Tuple[Path, Path]:
    """原子写入单只股票的 JSONL 数据与 companion meta JSON。"""
    code = result["code"]
    output_dir.mkdir(parents=True, exist_ok=True)

    jsonl_path = output_dir / f"{code}.jsonl"
    tmp_jsonl = output_dir / f"{code}.jsonl.tmp"

    meta_path = output_dir / f"{code}.meta.json"
    tmp_meta = output_dir / f"{code}.meta.json.tmp"

    # 1. 写入 raw items jsonl
    items = result["items"]
    with open(tmp_jsonl, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())

    # 2. 写入 companion meta json
    meta_dict = {
        "code": result["code"],
        "name": result["name"],
        "cohort": result["cohort"],
        "sector": result["sector"],
        "sub_industry": result["sub_industry"],
        "news_count": result["news_count"],
        "announcement_count": result["announcement_count"],
        "total_items": result["total_items"],
        "input_sha256": result["input_sha256"],
        "retrieved_at_utc": result["retrieved_at_utc"],
        "raw_text": result["raw_text"],
    }
    with open(tmp_meta, "w", encoding="utf-8") as f:
        json.dump(meta_dict, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())

    # 3. 原子替换
    tmp_jsonl.replace(jsonl_path)
    tmp_meta.replace(meta_path)

    return jsonl_path, meta_path


def verify_all_crawled_stocks(
    output_dir: Path, stocks: List[Dict[str, Any]]
) -> Tuple[bool, List[str]]:
    """对所有 200 支标的执行严格独立验收审计。"""
    errors: List[str] = []
    logger.info("=== 开始对爬取结果执行全量独立审计与验证 ===")

    re_sha256 = re.compile(r"^[a-f0-9]{64}$")

    for stock in stocks:
        code = stock["code"]
        name = stock["name"]
        jsonl_path = output_dir / f"{code}.jsonl"
        meta_path = output_dir / f"{code}.meta.json"

        if not jsonl_path.exists():
            errors.append(f"[{code} {name}] 缺失 JSONL 文件: {jsonl_path}")
            continue
        if not meta_path.exists():
            errors.append(f"[{code} {name}] 缺失 companion meta JSON 文件: {meta_path}")
            continue

        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as e:
            errors.append(f"[{code} {name}] meta JSON 解析失败: {e}")
            continue

        if meta.get("announcement_count", 0) <= 0:
            errors.append(
                f"[{code} {name}] announcement_count 必须为正数，实际为 {meta.get('announcement_count')}"
            )

        sha = meta.get("input_sha256", "")
        if not re_sha256.match(sha):
            errors.append(f"[{code} {name}] input_sha256 不是合法的 64 位小写十六进制: '{sha}'")

        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]
        except Exception as e:
            errors.append(f"[{code} {name}] JSONL 行解析失败: {e}")
            continue

        if len(records) != meta.get("total_items"):
            errors.append(
                f"[{code} {name}] JSONL 行数 ({len(records)}) 与 meta total_items ({meta.get('total_items')}) 不符"
            )

        # 校验哈希重算
        canonical = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        calc_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if calc_sha != sha:
            errors.append(f"[{code} {name}] 存储 SHA256 与现场重算值不一致")

        # 检查是否包含伪造模板文本
        for rec in records:
            title = rec.get("title", "")
            content = rec.get("content", "")
            if "处于综合工业赛道" in title or "处于综合工业赛道" in content:
                errors.append(f"[{code} {name}] 包含伪造模板文本！")

    passed = len(errors) == 0
    if passed:
        logger.info(f"[AUDIT PASS] 全部 {len(stocks)} 支标的数据真实完整，SHA256 存证 100% 校验通过！")
    else:
        logger.error(f"[AUDIT FAIL] 发现 {len(errors)} 项异常:\n" + "\n".join(errors[:10]))

    return passed, errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch authentic announcements and news for Student A & C (200 stocks)"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Thread pool concurrency workers (recommended 3-5, default: 4)",
    )
    parser.add_argument(
        "--begin-date",
        type=str,
        default="2024-01-01",
        help="Announcement begin date (default: '2024-01-01')",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to save raw crawled JSONL files",
    )
    parser.add_argument(
        "--force-recrawl",
        action="store_true",
        help="Force re-crawl even if valid crawled file exists",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only run verification on existing output files",
    )

    args = parser.parse_args()
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    stocks = load_stock_targets()
    logger.info(
        f"成功加载 {len(stocks)} 支目标标的 (同学 A: 100 支, 同学 C: 100 支)。"
    )

    if args.verify_only:
        passed, _ = verify_all_crawled_stocks(output_dir, stocks)
        return 0 if passed else 1

    # 检查断点缓存
    to_crawl: List[Dict[str, Any]] = []
    cached_metas: List[Dict[str, Any]] = []

    for s in stocks:
        code = s["code"]
        if not args.force_recrawl:
            cached = is_already_crawled(code, output_dir)
            if cached:
                cached_metas.append(cached)
                continue
        to_crawl.append(s)

    logger.info(
        f"断点检测: 已缓存就绪 {len(cached_metas)}/200 支标的，待抓取 {len(to_crawl)}/200 支标的。"
    )

    completed_lock = threading.Lock()
    all_results: List[Dict[str, Any]] = list(cached_metas)
    errors: List[Tuple[str, str]] = []

    start_time = time.time()

    def worker_fn(stock: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        t0 = time.time()
        try:
            res = fetch_stock_data(stock, begin_date=args.begin_date, max_retries=3)
            save_stock_atomic(res, output_dir)
            elapsed = time.time() - t0

            # 剔除 items 以节约内存并便于汇总
            meta_res = {k: v for k, v in res.items() if k != "items"}
            with completed_lock:
                all_results.append(meta_res)
                curr_done = len(all_results)
                logger.info(
                    f"[{curr_done:3d}/200] [{stock['cohort']}] {stock['code']} ({stock['name']}): "
                    f"{res['announcement_count']} 公告, {res['news_count']} 新闻, "
                    f"SHA256: {res['input_sha256'][:10]}... (耗时 {elapsed:.2f}s)"
                )
            return meta_res
        except Exception as exc:
            elapsed = time.time() - t0
            logger.error(
                f"[FAILED] [{stock['cohort']}] {stock['code']} ({stock['name']}): {exc} (耗时 {elapsed:.2f}s)"
            )
            with completed_lock:
                errors.append((stock["code"], str(exc)))
            return None

    if to_crawl:
        logger.info(f"启动多线程爬虫流水线 (workers={args.max_workers})...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = [executor.submit(worker_fn, s) for s in to_crawl]
            for f in concurrent.futures.as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    logger.error(f"线程执行发生未捕获异常: {e}")

    total_elapsed = time.time() - start_time
    logger.info(
        f"抓取流程结束。总耗时: {total_elapsed:.1f}s, 成功: {len(all_results)}/200, 失败: {len(errors)}"
    )

    if errors:
        logger.error(f"存在失败标的: {errors}")
        return 1

    # 写入全局汇总清单 manifest.json
    manifest = {
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_stocks": len(all_results),
        "student_a_count": sum(1 for r in all_results if r["cohort"] == "student_A"),
        "student_c_count": sum(1 for r in all_results if r["cohort"] == "student_C"),
        "total_announcements": sum(r["announcement_count"] for r in all_results),
        "total_news": sum(r["news_count"] for r in all_results),
        "stocks": sorted(all_results, key=lambda x: x["code"]),
    }
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    logger.info(f"已生成全局爬取清单: {manifest_path}")

    # 严格验收验证
    passed, verify_errors = verify_all_crawled_stocks(output_dir, stocks)
    if not passed:
        logger.error(f"验证发现 {len(verify_errors)} 个问题，请复核！")
        return 1

    logger.info("[SUCCESS] Milestone 1 真实数据抓取与验证 100% 圆满完成！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
