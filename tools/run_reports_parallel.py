# tools/run_reports_parallel.py —— 多进程并行生成 LLM 研报（提速）
#
# 原理：
# - generate_reports 默认带单实例锁（防止互相覆盖）
# - 本工具给每个 worker 传入独立的 feedback_path 绕过该锁，
#   每个 worker 只处理互不重叠的股票代码，写各自的报告文件（按 code 命名，不冲突）
#
# 用法：
#   python tools/run_reports_parallel.py --workers 3
#   python tools/run_reports_parallel.py --workers 3 --codes 600519 00700

import argparse
import json
import os
import sys
import tempfile
from multiprocessing import Process

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis.config import ANALYSIS_DIR_NAME
from src.config import DATA_DIR
from src.llm.config import REPORT_DIR


def _existing_report_codes() -> set:
    """已有研报的股票代码集合（报告文件名 {code}_{trade_date}.json）。"""
    codes = set()
    if not os.path.isdir(REPORT_DIR):
        return codes
    for name in os.listdir(REPORT_DIR):
        if not name.endswith(".json"):
            continue
        code = name.split("_")[0]
        if code:
            codes.add(code)
    return codes


def _pending_codes(explicit_codes=None) -> list:
    """需要生成研报的股票代码（排除已有报告的）。"""
    if explicit_codes:
        return list(dict.fromkeys(explicit_codes))
    analysis_dir = os.path.join(DATA_DIR, ANALYSIS_DIR_NAME)
    codes = []
    if os.path.isdir(analysis_dir):
        for name in sorted(os.listdir(analysis_dir)):
            if name.endswith(".json") and name != "ranking.json":
                codes.append(name[:-5])
    existing = _existing_report_codes()
    pending = [c for c in codes if c not in existing]
    print(f"待生成研报：{len(pending)} 只（已有 {len(existing)} 只）", flush=True)
    return pending


def _worker(codes: list, feedback_path: str, worker_idx: int) -> None:
    from src.llm.generate_reports import generate_reports

    result = generate_reports(
        codes=codes,
        use_llm=True,
        news_enabled=True,
        skip_existing=True,
        require_live_llm=True,
        feedback_path=feedback_path,
    )
    summary = {k: result.get(k) for k in ("total", "generated", "failed", "status", "reason")}
    print(f"[worker {worker_idx}] 完成 {len(codes)} 只: {json.dumps(summary, ensure_ascii=False)}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="多进程并行生成 LLM 研报")
    parser.add_argument("--workers", type=int, default=3, help="并行进程数（建议 3-4）")
    parser.add_argument("--codes", nargs="*", default=None, help="只处理指定代码")
    args = parser.parse_args()

    pending = _pending_codes(args.codes)
    if not pending:
        print("没有待生成的研报。", flush=True)
        return 0

    n = min(args.workers, len(pending))
    chunks = [pending[i::n] for i in range(n)]
    processes = []
    tmp_dir = tempfile.gettempdir()
    for i, chunk in enumerate(chunks):
        feedback_path = os.path.join(tmp_dir, f"stock_dash_feedback_worker{i}.json")
        p = Process(target=_worker, args=(chunk, feedback_path, i), daemon=False)
        p.start()
        processes.append(p)
        print(f"启动 worker {i}: {len(chunk)} 只", flush=True)

    failed = 0
    for p in processes:
        p.join()
        if p.exitcode != 0:
            failed += 1
            print(f"worker 异常退出 code={p.exitcode}", flush=True)

    print(f"全部完成，异常 worker 数：{failed}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())