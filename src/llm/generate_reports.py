# src/llm/generate_reports.py —— 独立研究报告生成入口
#
# 读取 docs/data/analysis/{code}.json（规则引擎已生成的个股详情），
# 为其抓取近期新闻、运行情感分析、RAG 检索、生成研究报告，并保存。
#
# 设计原则：
#   - 附加非阻塞：报告生成失败不影响已有排行数据
#   - 独立运行：可在 analysis.yml 之后单独执行，也可手动运行
#   - LLM 不可用时自动降级为模板报告
#
# 用法:
#   python -m src.llm.generate_reports                    # 全部成功标的
#   python -m src.llm.generate_reports --codes 600519 000001
#   python -m src.llm.generate_reports --top-k 5          # 只处理排名前5
#   python -m src.llm.generate_reports --no-llm           # 强制降级模板（离线测试）

import argparse
import json
import logging
import os
import sys
from typing import Optional

from .config import (
    DATA_DIR,
    DEEPSEEK_V4_FLASH_MODEL,
    REPORT_DIR,
    NEWS_ENABLED,
)
from src.analysis.config import ANALYSIS_DIR_NAME
from .fingpt_deepseek_adapter import FinGPTDeepSeekAdapter
from .llm_client import LLMClient
from .news_fetcher import NewsFetcher
from .report_generator import ReportGenerator
from .rag_engine import RAGEngine
from .embeddings import Embedder
from src.market_feedback import MarketFeedbackTracker, realized_return
from src.llm.config import FEEDBACK_PATH
from src.utils import setup_logging, beijing_date_str

logger = setup_logging()


def _is_verified_deepseek_report(report: object) -> bool:
    """返回报告是否确认为本项目允许的真实 DeepSeek V4 Flash 输出。"""
    if not isinstance(report, dict):
        return False
    metadata = report.get("llm_metadata")
    if not isinstance(metadata, dict):
        return False
    return (
        metadata.get("mode") == "deepseek_api"
        and metadata.get("model") == DEEPSEEK_V4_FLASH_MODEL
    )


def _load_detail(code: str) -> Optional[dict]:
    """读取单只标的的个股详情 JSON。"""
    path = os.path.join(DATA_DIR, ANALYSIS_DIR_NAME, f"{code}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.warning("读取详情失败: %s", code, exc_info=True)
        return None


def _load_all_details(codes: list[str]) -> list[dict]:
    """加载多个标的详情，跳过失败项。"""
    details = []
    for code in codes:
        d = _load_detail(code)
        if d is not None:
            details.append(d)
    return details


def _scores_from_detail(detail: dict) -> dict:
    """从详情 JSON 提取评分字段。"""
    scores = detail.get("scores", {}) or {}
    return {
        "fundamental": (
            detail.get("fundamental", {}).get("score")
            if isinstance(detail.get("fundamental"), dict)
            else None
        ),
        "risk_adjusted": scores.get("risk_adjusted"),
        "risk": scores.get("risk"),
        "technical": scores.get("technical"),
        "industry": scores.get("industry"),
        "total": None,  # 详情未保存 total，前端可自行融合
    }


def _load_kline_for_code(code: str) -> Optional[tuple]:
    """读 K 线缓存（docs/data/kline/{code}.json），返回 (dates, closes)。"""
    path = os.path.join(DATA_DIR, "kline", f"{code}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return None
    dates = data.get("dates", [])
    rows = data.get("kline", [])
    if not dates or len(dates) != len(rows):
        return None
    return ([str(d) for d in dates], [r[1] for r in rows])  # 列序 [开, 收, 低, 高]


def _record_market_feedback(
    tracker: MarketFeedbackTracker,
    detail: dict,
    sentiment_scores: list[Optional[float]],
) -> None:
    """
    把新闻情感与真实已实现收益关联，记录 RLSP 市场反馈样本（spec-kit 004）。

    契约：ret_3d/ret_5d 只放真实收益（event_date 之后 3/5 个交易日收盘口径，
    由 K 线计算）；KNN 预测值独立保存到 forecast_ret_5d；收益不可算 → None 标注。
    """
    code = detail.get("code", "")
    name = detail.get("name", "")
    trade_date = detail.get("trade_date", "")
    forecast = detail.get("forecast", {}) or {}
    forecast_5d = forecast.get("return_5d_pct")

    # 用新闻情感平均分（LLM 或规则）
    valid = [s for s in sentiment_scores if s is not None]
    avg_sentiment = sum(valid) / len(valid) if valid else None
    if avg_sentiment is None:
        logger.info("%s(%s) 无情感分，跳过市场反馈记录", name, code)
        return

    # 从 K 线计算真实已实现收益（无前视：只用 event_date 之后的交易日）
    r3 = r5 = None
    loaded = _load_kline_for_code(code)
    if loaded is not None:
        dates, closes = loaded
        try:
            t = dates.index(str(trade_date))
            r3 = realized_return(closes, t, 3)
            r5 = realized_return(closes, t, 5)
        except ValueError:
            pass  # event_date 不在 K 线中 → 不可算，如实标注

    tracker.record_event(
        code=code,
        name=name,
        event_date=trade_date,
        event_type="daily_analysis",
        ret_3d=r3,
        ret_5d=r5,
        benchmark_ret_3d=None,
        benchmark_ret_5d=None,
        sentiment_score=avg_sentiment,
        sentiment_confidence=1.0,
        forecast_ret_5d=forecast_5d,
    )


def generate_reports(
    codes: Optional[list[str]] = None,
    top_k: Optional[int] = None,
    use_llm: bool = True,
    news_enabled: bool = NEWS_ENABLED,
    feedback_path: Optional[str] = None,
    skip_existing: bool = False,
    require_live_llm: bool = False,
) -> dict:
    """
    主入口：为指定标的生成研究报告。

    feedback_path: 市场反馈保存路径（测试时可注入临时路径，默认真实路径）。
    skip_existing: True 时跳过已有报告（避免重复 API 调用）。
    require_live_llm: True 时仅在 DeepSeek V4 Flash 可调用时执行；否则不抓取新闻、
        不写模板报告，直接返回安全的 skipped 状态；API 失败后生成的模板也会被拒绝
        保存与记录市场反馈。主分析流水线使用此模式，避免把旧的深度报告覆盖为模板报告。
    """
    # 0. 单实例锁：防止多个进程同时运行互相覆盖报告文件
    _lock = None
    if not feedback_path or feedback_path == FEEDBACK_PATH:
        lock_path = os.path.join(REPORT_DIR, ".generate.lock")
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        try:
            _lock = open(lock_path, "x")
            _lock.write(str(os.getpid()))
            _lock.flush()
            os.fsync(_lock.fileno())
        except FileExistsError:
            # 检查锁是否过期（进程已死或锁文件空）
            try:
                content = open(lock_path).read().strip()
                if not content:
                    # 空锁文件：视为残留，删除重试
                    os.remove(lock_path)
                    try:
                        _lock = open(lock_path, "x")
                        _lock.write(str(os.getpid()))
                        _lock.flush()
                        os.fsync(_lock.fileno())
                    except FileExistsError:
                        logger.error("锁文件竞争，退出")
                        return {"total": 0, "generated": 0, "failed": ["locked"], "report_dir": REPORT_DIR}
                else:
                    pid = int(content)
                    os.kill(pid, 0)  # 进程存在则不抛异常
                    logger.error("已有 generate_reports 进程 (PID=%d) 在运行，退出避免覆盖", pid)
                    return {"total": 0, "generated": 0, "failed": ["locked"], "report_dir": REPORT_DIR}
            except (ProcessLookupError, ValueError):
                os.remove(lock_path)
                try:
                    _lock = open(lock_path, "x")
                    _lock.write(str(os.getpid()))
                    _lock.flush()
                    os.fsync(_lock.fileno())
                except FileExistsError:
                    logger.error("锁文件竞争，退出")
                    return {"total": 0, "generated": 0, "failed": ["locked"], "report_dir": REPORT_DIR}

    try:
        return _generate_reports_inner(
            codes=codes, top_k=top_k, use_llm=use_llm,
            news_enabled=news_enabled, feedback_path=feedback_path,
            skip_existing=skip_existing, require_live_llm=require_live_llm,
        )
    finally:
        if _lock is not None:
            try:
                _lock.close()
                os.remove(os.path.join(REPORT_DIR, ".generate.lock"))
            except OSError:
                pass


def _generate_reports_inner(
    codes: Optional[list[str]] = None,
    top_k: Optional[int] = None,
    use_llm: bool = True,
    news_enabled: bool = NEWS_ENABLED,
    feedback_path: Optional[str] = None,
    skip_existing: bool = False,
    require_live_llm: bool = False,
) -> dict:
    """generate_reports 的实际逻辑（由锁保护）。"""
    # 1. 确定处理哪些标的
    if codes:
        details = _load_all_details(codes)
    else:
        all_files = [
            f for f in os.listdir(os.path.join(DATA_DIR, ANALYSIS_DIR_NAME))
            if f.endswith(".json") and f != "ranking.json"
        ]
        all_codes = sorted(f[:-5] for f in all_files)
        details = _load_all_details(all_codes)

    if top_k and not codes:
        # 按排名排序后取前 K（ranking.json 中有 rank）。
        # top_k=0 表示全部自选股（v2.5 默认）。
        ranking_path = os.path.join(DATA_DIR, ANALYSIS_DIR_NAME, "ranking.json")
        if os.path.exists(ranking_path):
            try:
                with open(ranking_path, "r", encoding="utf-8") as f:
                    ranking = json.load(f)
                ranked_codes = [item["code"] for item in ranking.get("items", [])]
                top_codes = ranked_codes[:top_k]
                # 保留详情顺序，只保留 top
                details = [d for d in details if d["code"] in set(top_codes)]
            except Exception:
                logger.warning("读取 ranking.json 失败，忽略 top-k 过滤", exc_info=True)

    if not details:
        logger.warning("没有可处理的标的详情")
        return {"total": 0, "generated": 0, "failed": [], "report_dir": REPORT_DIR}

    # 2. 初始化组件
    # 在线模式显式走 FinGPT 风格 + DeepSeek V4 Flash 适配器；
    # 离线模式明确禁用，既不读取本地 key，也不会调用外部 API。
    if use_llm:
        llm_client = FinGPTDeepSeekAdapter()
        if require_live_llm and not llm_client.is_available:
            reason = llm_client.unavailable_reason or "llm_unavailable"
            logger.info("DeepSeek 不可用，跳过本次报告调度（原因=%s）", reason)
            return {
                "total": len(details),
                "generated": 0,
                "failed": [],
                "report_dir": REPORT_DIR,
                "status": "skipped",
                "reason": reason,
            }
    elif require_live_llm:
        logger.info("LLM 已显式关闭，跳过本次报告调度")
        return {
            "total": len(details),
            "generated": 0,
            "failed": [],
            "report_dir": REPORT_DIR,
            "status": "skipped",
            "reason": "llm_disabled",
        }
    else:
        llm_client = LLMClient.disabled()

    fetcher = NewsFetcher(enabled=news_enabled)
    generator = ReportGenerator(llm_client=llm_client)
    generator.report_dir = REPORT_DIR  # 使用本模块的 REPORT_DIR（测试可 patch）
    # 启用 RAG（hash 嵌入，离线可复现），让报告带来源引用
    rag = RAGEngine(enabled=True, embedder=Embedder(backend="hash"))
    generator.rag = rag
    tracker = MarketFeedbackTracker(path=feedback_path or FEEDBACK_PATH)

    generated = 0
    failed = []
    for detail in details:
        code = detail.get("code", "")
        name = detail.get("name", "")
        trade_date = detail.get("trade_date", "")

        # 跳过已有报告（断点续跑，省 API）
        if skip_existing:
            existing = os.path.join(REPORT_DIR, f"{code}_{trade_date}.json")
            if os.path.exists(existing):
                # 只跳过 LLM 深度报告（>=5 章节）；模板报告（降级产物）需要重跑
                try:
                    with open(existing, "r", encoding="utf-8") as f:
                        old = json.load(f)
                    sections = old.get("research_report", {}).get("sections", [])
                    metadata = old.get("llm_metadata", {}) or {}
                    is_deepseek_report = (
                        metadata.get("mode") == "deepseek_api"
                        and metadata.get("model") == "deepseek-v4-flash"
                    )
                    if is_deepseek_report or (
                        not metadata and len(sections) >= 5
                    ):
                        logger.info("报告已是 LLM 深度报告，跳过: %s", code)
                        continue
                    logger.info("报告是模板（降级产物），重新生成: %s", code)
                except Exception:
                    logger.info("报告读取失败，重新生成: %s", code)

        try:
            # 抓新闻
            news_items = fetcher.fetch_stock(code, name)
            # 转 dict
            news_dicts = [it.to_dict() for it in news_items]

            # 生成报告
            report = generator.generate(
                code=code,
                name=name,
                scores=_scores_from_detail(detail),
                news_items=news_dicts,
                trade_date=trade_date,
            )
            if report is None:
                raise RuntimeError("报告生成为空")
            if require_live_llm and not _is_verified_deepseek_report(report):
                failed.append(code)
                logger.warning(
                    "DeepSeek 深度报告未生成，拒绝保存降级产物: %s(%s)",
                    name,
                    code,
                )
                continue

            path = generator.save(report)

        except Exception:
            failed.append(code)
            logger.warning("报告生成失败: %s(%s)", name, code, exc_info=True)
            continue

        generated += 1
        logger.info("报告已保存: %s (%s)", name, path)

        # 复用报告阶段已经采样并批量分析的情感结果，避免第二次 API 调用。
        try:
            sent_scores = [
                result.score for result in generator.last_sentiment_results
            ]
            _record_market_feedback(tracker, detail, sent_scores)
        except Exception:
            logger.warning(
                "报告已保存，但市场反馈记录失败: %s(%s)",
                name,
                code,
                exc_info=True,
            )

    # 3. 保存市场反馈。核心 live 模式没有真实报告时绝不重写反馈文件。
    if generated or not require_live_llm:
        try:
            tracker.save()
            logger.info("市场反馈已保存，共 %d 条", len(tracker.samples))
        except Exception:
            logger.warning("市场反馈保存失败", exc_info=True)
    else:
        logger.info("没有经验证的 DeepSeek 报告，跳过市场反馈写入")

    return {
        "total": len(details),
        "generated": generated,
        "failed": failed,
        "report_dir": REPORT_DIR,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 LLM 研究报告")
    parser.add_argument("--codes", nargs="*", help="指定股票代码列表")
    parser.add_argument("--top-k", type=int, default=None, help="只处理排名前 K")
    parser.add_argument("--no-llm", action="store_true", help="强制使用模板报告（离线）")
    parser.add_argument("--no-news", action="store_true", help="跳过新闻抓取")
    parser.add_argument("--skip-existing", action="store_true", help="跳过已有报告（断点续跑）")
    parser.add_argument(
        "--require-live-llm",
        action="store_true",
        help="无可用 DeepSeek V4 Flash 时跳过，不生成模板报告",
    )
    args = parser.parse_args()

    use_llm = not args.no_llm
    news_enabled = not args.no_news
    result = generate_reports(
        codes=args.codes,
        top_k=args.top_k,
        use_llm=use_llm,
        news_enabled=news_enabled,
        skip_existing=args.skip_existing,
        require_live_llm=args.require_live_llm,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
