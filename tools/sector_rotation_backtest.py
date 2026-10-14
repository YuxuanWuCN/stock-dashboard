# -*- coding: utf-8 -*-
"""tools/sector_rotation_backtest.py —— 板块轮动回测 CLI

用法：
    python tools/sector_rotation_backtest.py --provider proxy --start 2025-09-08 --end 2026-08-27
    python tools/sector_rotation_backtest.py --provider llm --news-fixture path/to/news.json --mock-llm
    python tools/sector_rotation_backtest.py --provider fixture --fixture-file path/to/states.json

产物（禁止覆盖既有目录）：
    data/processed/sector_rotation/backtest/{start}_{end}/{provider}/
        nav.csv trades.csv decisions.csv sector_states.csv metrics.json run_manifest.json

provider 与 sentiment_source 对应关系（DATA_FEASIBILITY.md §5）：
    proxy   -> price_breadth_proxy（机制/成本链路验证，禁入报告结论）
    llm     -> llm_news_replay（结论性场景，仅限 W_real）
    fixture -> fixture_only（测试夹具，硬禁报告路径）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.sector_rotation.backtest import (  # noqa: E402
    BacktestEngine,
    FrozenFixturesSentimentProvider,
    KlineStore,
    LLMReplaySentimentProvider,
    ProxyBreadthSentimentProvider,
)
from src.sector_rotation.config import SECTORS, get_all_tickers  # noqa: E402

KLINE_DIR = ROOT_DIR / "docs" / "data" / "kline"
DEFAULT_OUT_ROOT = ROOT_DIR / "data" / "processed" / "sector_rotation" / "backtest"


# ============================================================================
# provider 构造
# ============================================================================

def build_proxy_provider(store: KlineStore, calendar: List[str], args) -> ProxyBreadthSentimentProvider:
    return ProxyBreadthSentimentProvider(
        store=store, calendar=calendar,
        return_window=args.return_window, breadth_window=args.breadth_window,
    )


def build_llm_provider(store: KlineStore, calendar: List[str], args) -> LLMReplaySentimentProvider:
    if args.news_fixture:
        raw = json.loads(Path(args.news_fixture).read_text(encoding="utf-8"))

        def loader(code: str, trade_date: str) -> List[Dict[str, Any]]:
            return list(raw.get(code, []))
        news_loader = loader
    else:
        from src.llm.news_fetcher import NewsFetcher
        fetcher = NewsFetcher()

        def loader(code: str, trade_date: str) -> List[Any]:
            return [n for n in fetcher.fetch_stock(code)
                    if str(n.publish_time)[:10] <= trade_date]
        news_loader = loader

    if args.mock_llm:
        class _MockAnalyzer:
            """确定性降级分析器（规则词典均值，离线可复现，非 LLM 结论）。"""

            def analyze_batch(self, texts: List[str]):
                from src.llm.llm_sentiment import LLMSentimentAnalyzer
                return LLMSentimentAnalyzer().analyze_batch(texts)
        analyzer: Any = _MockAnalyzer()
    else:
        from src.llm.llm_sentiment import LLMSentimentAnalyzer
        analyzer = LLMSentimentAnalyzer()

    return LLMReplaySentimentProvider(
        news_loader=news_loader, analyzer=analyzer, calendar=calendar,
        lookback_days=args.lookback_days,
    )


def build_fixture_provider(args) -> FrozenFixturesSentimentProvider:
    if not args.fixture_file:
        raise SystemExit("--provider fixture 需要 --fixture-file（{date: {sector: state}} JSON）")
    raw = json.loads(Path(args.fixture_file).read_text(encoding="utf-8"))
    return FrozenFixturesSentimentProvider(raw)


# ============================================================================
# main
# ============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="板块轮动回测")
    parser.add_argument("--provider", choices=["proxy", "llm", "fixture"], required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--capital", type=float, default=1_000_000.0)
    parser.add_argument("--initial-sector", default="gold")
    parser.add_argument("--out", default=None, help="产物根目录（默认 data/processed/...）")
    parser.add_argument("--params-json", default=None,
                        help="阈值覆盖 JSON（敏感性场景），内联字符串或文件路径")
    parser.add_argument("--for-report", action="store_true",
                        help="报告级运行：拒绝代理/夹具 provider")
    parser.add_argument("--allow-overwrite", action="store_true", default=False,
                        help="显式允许覆盖同名产物目录（默认禁止）")
    # provider 专属参数
    parser.add_argument("--return-window", type=int, default=20)
    parser.add_argument("--breadth-window", type=int, default=5)
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--news-fixture", default=None)
    parser.add_argument("--mock-llm", action="store_true")
    parser.add_argument("--fixture-file", default=None)
    args = parser.parse_args()

    params: Dict[str, Any] = {}
    if args.params_json:
        p = Path(args.params_json)
        params = json.loads(p.read_text(encoding="utf-8")) if p.exists() else json.loads(args.params_json)

    store = KlineStore.from_dir(KLINE_DIR, get_all_tickers())
    missing = [t for t in get_all_tickers() if not store.has(t)]
    if missing:
        print(f"[warn] K 线缺失成分股（按可用子集估值，manifest 已登记）: {missing}")

    calendar = store.common_dates(args.start, args.end)
    if len(calendar) < 2:
        raise SystemExit(f"区间 {args.start}~{args.end} 无公共交易日历（{len(calendar)} 天）")
    print(f"[info] provider={args.provider} 日历 {calendar[0]}~{calendar[-1]} "
          f"({len(calendar)} 交易日)")

    if args.provider == "proxy":
        provider = build_proxy_provider(store, calendar, args)
    elif args.provider == "llm":
        provider = build_llm_provider(store, calendar, args)
    else:
        provider = build_fixture_provider(args)

    engine = BacktestEngine(store=store, kline_dir=KLINE_DIR, sectors=SECTORS)
    result = engine.run(
        start_date=args.start, end_date=args.end,
        provider=provider, initial_capital=args.capital,
        initial_sector=args.initial_sector,
        advisor=None, params=params, for_report=args.for_report,
    )

    out_root = Path(args.out) if args.out else DEFAULT_OUT_ROOT
    window_tag = f"{calendar[0]}_{calendar[-1]}"
    out_dir = out_root / window_tag / provider.name
    saved = result.save(out_dir, allow_overwrite=args.allow_overwrite)

    m = result.metrics["strategy"]
    b = result.metrics["benchmark_equal_weight_buy_hold"]
    print(f"[done] sentiment_source={provider.sentiment_source} -> {saved}")
    print(f"  策略: 总收益={m['total_return']:+.2%} Sharpe={m['sharpe']} "
          f"最大回撤={m['max_drawdown']:.2%} 轮动={m['rotations']}次 成本占比={m['cost_ratio']:.4%}")
    print(f"  基准: 总收益={b['total_return']:+.2%} Sharpe={b['sharpe']} 最大回撤={b['max_drawdown']:.2%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
