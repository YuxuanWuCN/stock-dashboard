# -*- coding: utf-8 -*-
r"""tools/sector_rotation_daily.py —— 板块轮动每日决策 CLI（阶段5，任务 5.1）

薄封装 `src.sector_rotation.daily_job.run_daily`，供每日流水线（daily_routine）调用。

用法：
  python tools/sector_rotation_daily.py                       # auto：有新闻用 LLM，否则降级代理
  python tools/sector_rotation_daily.py --mode proxy          # 强制代理（机制演练，禁作结论）
  python tools/sector_rotation_daily.py --news-fixture news.json --use-advisor
  python tools/sector_rotation_daily.py --trade-date 2026-10-14

退出码：
  0 成功；2 参数/数据错误（无 K 线日历等）；3 存在 severity=critical 监控告警
  （由 monitoring 判定，经 daily_routine 日志机制体现）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.sector_rotation.daily_job import LATEST_NAME, run_daily  # noqa: E402
from src.sector_rotation.monitoring import run_monitoring  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="板块轮动每日决策与归档")
    ap.add_argument("--trade-date", default=None, help="决策日 YYYY-MM-DD（缺省=K线日历最后交易日）")
    ap.add_argument("--mode", default="auto", choices=["auto", "llm", "proxy"],
                    help="情绪来源模式（默认 auto：优先真实新闻，缺失降级代理）")
    ap.add_argument("--news-fixture", default=None, help="离线新闻夹具 JSON（提供则不发起外部请求）")
    ap.add_argument("--use-advisor", action="store_true", help="启用 LLM 决策复核（不推翻量化结论）")
    ap.add_argument("--out-dir", default=None, help="产物目录（默认 docs/data/sector_rotation）")
    ap.add_argument("--no-monitor", action="store_true",
                    help="跳过监控告警检查（仅调试用；不产出 alerts 报告，也不会返回退出码 3）")
    args = ap.parse_args()

    try:
        payload = run_daily(
            trade_date=args.trade_date,
            sentiment_mode=args.mode,
            news_fixture=Path(args.news_fixture) if args.news_fixture else None,
            use_advisor=args.use_advisor,
            out_dir=Path(args.out_dir) if args.out_dir else None,
        )
    except Exception as exc:  # noqa: BLE001 - CLI 出口需给出明确失败原因
        print(f"[sector_rotation_daily] 失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    decision = payload["decision"]
    out_root = args.out_dir or "docs/data/sector_rotation"
    print(f"[sector_rotation_daily] trade_date={payload['trade_date']} "
          f"sentiment_source={payload['sentiment_source']} "
          f"holding={payload['holding_sector']} "
          f"should_rotate={decision['should_rotate']} "
          f"target={decision.get('target_sector')} conf={payload['confidence']:.4f}")
    for note in payload.get("notes") or []:
        print(f"  note: {note}")
    print(f"  -> {out_root}/{LATEST_NAME}")

    if args.no_monitor:
        return 0
    report = run_monitoring(out_dir=Path(args.out_dir) if args.out_dir else None)
    summary = report["summary"]
    print(f"[monitoring] critical={summary['critical']} warning={summary['warning']} "
          f"info={summary['info']} -> reports/sector_rotation/alerts_*.json")
    for alert in report["alerts"]:
        if alert["severity"] in ("critical", "warning"):
            print(f"  [{alert['severity']}] {alert['check']}: {alert['message']}")
    return 3 if report["has_critical"] else 0


if __name__ == "__main__":
    sys.exit(main())
