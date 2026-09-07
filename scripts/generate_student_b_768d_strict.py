# -*- coding: utf-8 -*-
"""严格真实来源的同学 B 768D 文本因子生成器。

与任务单中的宽松脚本不同，本脚本没有模板新闻、哈希向量或静默降级：

1. 新闻/公告必须来自 AkShare 的真实外部接口；
2. Stage 1 必须由 DeepSeek Chat 返回摘要；
3. Stage 2 必须由 FastEmbed 的真实中文模型返回 768 维向量；
4. 任一标的失败都会使本次全量任务失败，不覆盖旧的最终文件。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.crawl_and_extract_768d_factors import (  # noqa: E402
    COHORT_FILES,
    call_openai_chat_with_retry,
    get_llm_config,
    load_cohort_stocks,
)


EMBEDDING_MODEL = "jinaai/jina-embeddings-v2-base-zh"
DIMENSION = 768


class StrictSourceError(RuntimeError):
    """真实新闻/公告源不可用或返回空数据。"""


class StrictGenerationError(RuntimeError):
    """DeepSeek 或真实 Embedding 生成失败。"""


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _first(row: dict[str, Any], names: Iterable[str]) -> str:
    for name in names:
        value = _text(row.get(name))
        if value:
            return value
    return ""


def _records_from_frame(frame: Any, item_type: str) -> list[dict[str, str]]:
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    result: list[dict[str, str]] = []
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


def collect_real_news_corpus(code: str, name: str, ak_module: Any = None) -> list[dict[str, str]]:
    """抓取真实新闻/公告；没有真实记录时严格失败。"""
    if ak_module is None:
        try:
            import akshare as ak_module  # type: ignore
        except ImportError as exc:
            raise StrictSourceError("akshare 未安装，无法取得真实新闻/公告") from exc

    errors: list[str] = []
    items: list[dict[str, str]] = []
    try:
        items.extend(_records_from_frame(ak_module.stock_news_em(symbol=code), "news"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"news:{type(exc).__name__}")
    try:
        items.extend(
            _records_from_frame(
                ak_module.stock_individual_notice_report(
                    security=code, symbol="全部", begin_date=None, end_date=None
                ),
                "announcement",
            )
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"announcement:{type(exc).__name__}")

    if not items:
        detail = ",".join(errors) if errors else "empty_response"
        raise StrictSourceError(f"{code} 没有真实新闻/公告记录 ({detail})")
    return items


def _corpus_text(items: list[dict[str, str]]) -> str:
    parts = []
    for item in items[:40]:
        parts.append(
            f"[{item['item_type']}] {item['title']} {item['content']}"
        )
    text = "\n".join(parts).strip()
    return text[:12000]


def _corpus_hash(items: list[dict[str, str]]) -> str:
    canonical = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _prompt(row: pd.Series, corpus_text: str) -> str:
    return (
        f"股票 {str(row['name'])}({str(row['code']).zfill(6)})，"
        f"行业 {row.get('sector', 'unknown')}/{row.get('sub_industry', '综合行业')}。\n"
        f"以下是从外部新闻与公告接口抓取的真实文本：\n{corpus_text}\n\n"
        "请作为量化投资分析师，提炼三项可复核的短摘要："
        "机构博弈动向、业绩弹性/技术壁垒、多空情绪评分（-1 到 +1）。"
        "不要编造未出现在文本中的数字。"
    )


def generate_strict_record(
    row: pd.Series,
    llm_config: dict[str, Any],
    embedder: Any,
    ak_module: Any = None,
    chat_call: Callable[[str, dict[str, Any]], str | None] | None = None,
) -> dict[str, Any]:
    if not llm_config.get("is_valid_key"):
        raise StrictGenerationError("DeepSeek API Key 不可用")
    code = str(row["code"]).zfill(6)
    name = str(row["name"])
    items = collect_real_news_corpus(code, name, ak_module=ak_module)
    corpus_text = _corpus_text(items)
    chat = chat_call or call_openai_chat_with_retry
    summary = chat(_prompt(row, corpus_text), llm_config)
    if not summary:
        raise StrictGenerationError(f"{code} DeepSeek 摘要生成失败")

    try:
        vectors = list(embedder.embed([summary]))
    except Exception as exc:  # noqa: BLE001
        raise StrictGenerationError(f"{code} 真实 Embedding 失败: {type(exc).__name__}") from exc
    if len(vectors) != 1:
        raise StrictGenerationError(f"{code} Embedding 返回数量错误")
    vector = np.asarray(vectors[0], dtype=np.float32)
    if vector.shape != (DIMENSION,) or not np.isfinite(vector).all():
        raise StrictGenerationError(f"{code} Embedding 不是有限的 768 维向量")

    record: dict[str, Any] = {
        "code": code,
        "name": name,
        "sub_industry": str(row.get("sub_industry", "综合行业")),
        "sector": str(row.get("sector", "unknown")),
        "cohort_key": str(row.get("cohort_key", "student_B")),
        "feature_source": "llm_deepseek_extracted_strict",
        "embedding_source": f"fastembed:{EMBEDDING_MODEL}",
        "news_count": sum(item["item_type"] == "news" for item in items),
        "announcement_count": sum(item["item_type"] == "announcement" for item in items),
        "input_sha256": _corpus_hash(items),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "llm_summary": summary[:240],
    }
    for i, value in enumerate(vector):
        record[f"dim_{i:03d}"] = float(value)
    return record


def _create_embedder() -> Any:
    try:
        from fastembed import TextEmbedding
        return TextEmbedding(model_name=EMBEDDING_MODEL)
    except Exception as exc:  # noqa: BLE001
        raise StrictGenerationError(
            f"无法加载真实中文 768D Embedding 模型 {EMBEDDING_MODEL}: {type(exc).__name__}"
        ) from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="严格真实来源的同学 B 768D 因子生成")
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument("--output", type=Path, default=ROOT_DIR / "data/task_split/factors_768d_student_B.csv")
    parser.add_argument(
        "--provenance",
        type=Path,
        default=ROOT_DIR / "data/task_split/factors_768d_student_B_provenance.json",
    )
    parser.add_argument("--interval", type=float, default=0.5)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    config = get_llm_config()
    if not config.get("is_valid_key"):
        raise StrictGenerationError("DEEPSEEK_API_KEY 不存在或无效")
    stocks = load_cohort_stocks("student_B")
    if args.sample:
        stocks = stocks.head(args.sample).copy()
    embedder = _create_embedder()
    records: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    for _, row in stocks.iterrows():
        record = generate_strict_record(row, config, embedder)
        records.append(record)
        provenance.append({k: record[k] for k in ("code", "news_count", "announcement_count", "input_sha256", "retrieved_at_utc")})
        time.sleep(max(0.0, args.interval))

    if len(records) != len(stocks):
        raise StrictGenerationError("全量严格生成未覆盖全部任务标的")
    output = pd.DataFrame(records)
    dimension_columns = [f"dim_{i:03d}" for i in range(DIMENSION)]
    if output["feature_source"].ne("llm_deepseek_extracted_strict").any():
        raise StrictGenerationError("输出中存在非严格 DeepSeek 来源")
    if output[dimension_columns].isna().any().any():
        raise StrictGenerationError("输出包含空向量")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False, encoding="utf-8-sig")
    manifest = {
        "schema_version": 1,
        "source_contract": "strict_real_external_news_and_announcements",
        "cohort": "student_B",
        "stocks": len(output),
        "llm_backend": config.get("model", "deepseek-chat"),
        "embedding_backend": f"fastembed:{EMBEDDING_MODEL}",
        "fallbacks_allowed": False,
        "provenance": provenance,
    }
    args.provenance.parent.mkdir(parents=True, exist_ok=True)
    args.provenance.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"严格真实来源 768D 文件已写出: {args.output} ({len(output)} rows x {len(output.columns)} columns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
