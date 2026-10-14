# -*- coding: utf-8 -*-
"""src/sector_rotation/backtest/sentiment_providers.py —— 回测情绪输入可插拔 provider

数据诚实性约束（AGENTS.md 第2条 / DATA_FEASIBILITY.md）：
- 个股日频 LLM 情绪历史在本仓库不存在，回测情绪输入必须区分来源并强制标注：
  * ProxyBreadthSentimentProvider  -> sentiment_source="price_breadth_proxy"（代理，禁入报告结论）
  * LLMReplaySentimentProvider     -> sentiment_source="llm_news_replay"（真实，仅 W_real 内）
  * FrozenFixturesSentimentProvider-> sentiment_source="fixture_only"（仅测试夹具）
- 所有 provider 输出统一为 Dict[str, SectorState]，供
  SectorRotationEngine.decide() 直接消费；T 日状态只允许使用 <= T-1 的数据（无未来函数）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from ..config import (
    EXPECTED_STOCKS_PER_SECTOR,
    SECTORS,
    SENTIMENT_BOUND_MAX,
    SENTIMENT_BOUND_MIN,
    TREND_CONFIRM_DAYS,
)
from ..sector_sentiment_aggregator import SectorSentimentAggregator
from ..utils.sector_utils import SectorState, StockSentimentInput

# 代理情绪的单票置信度（代理信号应显著低于 LLM 情绪置信）
PROXY_STOCK_CONFIDENCE = 0.5

# 新闻加载器契约：(code, trade_date) -> 新闻列表（dict 或 NewsItem，含 publish_time）
NewsLoader = Callable[[str, str], List[Any]]


# ============================================================================
# 1. K 线数据访问层（providers 与 engine 共用）
# ============================================================================

class KlineStore:
    """docs/data/kline/{code}.json 只读访问层。

    结构：{"dates": [...], "kline": [[open, close, high, low, volume?], ...]}。
    本层仅解析收盘价序列（kline[1]）。
    """

    def __init__(self, prices: Dict[str, Tuple[List[str], Dict[str, float]]]) -> None:
        """prices: {code: (dates升序, {date: close})}"""
        self._prices = prices
        self.codes = sorted(prices.keys())

    @classmethod
    def from_dir(cls, kline_dir: Path, codes: List[str]) -> "KlineStore":
        prices: Dict[str, Tuple[List[str], Dict[str, float]]] = {}
        for code in codes:
            path = Path(kline_dir) / f"{code}.json"
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            dates = [str(d)[:10] for d in data.get("dates", [])]
            kline = data.get("kline") or []
            close_map: Dict[str, float] = {}
            for d, row in zip(dates, kline):
                try:
                    close_map[d] = float(row[1])
                except (TypeError, ValueError, IndexError):
                    continue
            if close_map:
                prices[code] = (sorted(close_map.keys()), close_map)
        return cls(prices)

    @classmethod
    def from_dict(cls, raw: Dict[str, Dict[str, float]]) -> "KlineStore":
        """测试注入：{code: {date: close}}"""
        return cls({c: (sorted(m.keys()), dict(m)) for c, m in raw.items()})

    def has(self, code: str) -> bool:
        return code in self._prices

    def close(self, code: str, date: str) -> Optional[float]:
        entry = self._prices.get(code)
        return entry[1].get(date) if entry else None

    def common_dates(self, start: str, end: str) -> List[str]:
        """所有已加载 code 的日期交集，截断到 [start, end]（回测交易日历）。"""
        common: Optional[set] = None
        for dates, _ in self._prices.values():
            s = set(dates)
            common = s if common is None else (common & s)
        if not common:
            return []
        return sorted(d for d in common if start <= d <= end)

    def file_sha256_map(self, kline_dir: Path) -> Dict[str, str]:
        """输出所用 kline 文件的 sha256（供 run_manifest 追溯）。"""
        import hashlib
        out: Dict[str, str] = {}
        for code in self.codes:
            path = Path(kline_dir) / f"{code}.json"
            if path.exists():
                out[code] = hashlib.sha256(path.read_bytes()).hexdigest()
        return out


def sector_daily_return(store: KlineStore, tickers, date: str, prev_date: str) -> Optional[float]:
    """板块日收益：成分股 (close[date]/close[prev_date] - 1) 的等权均值（等权成分，manifest 声明）。

    Args:
        store: K 线数据层
        tickers: 成分股代码序列（调用方传入，不依赖全局 SECTORS，便于测试注入）
        date/prev_date: 相邻两个交易日

    成分股缺价格（停牌/缺数据）时跳过该股；全部缺失返回 None。
    """
    rets: List[float] = []
    for code in tickers:
        p_now = store.close(code, date)
        p_prev = store.close(code, prev_date)
        if p_now is None or p_prev is None or p_prev == 0.0:
            continue
        rets.append(p_now / p_prev - 1.0)
    if not rets:
        return None
    return sum(rets) / len(rets)


# ============================================================================
# 2. Provider 协议
# ============================================================================

class SentimentProvider(Protocol):
    """回测情绪 provider 协议：按交易日返回板块状态表（内部保证 as-of）。"""

    name: str
    sentiment_source: str
    report_usable: bool

    def get_sector_states(self, trade_date: str) -> Dict[str, SectorState]:
        ...


# ============================================================================
# 3. 代理情绪：价格宽度 provider
# ============================================================================

class ProxyBreadthSentimentProvider:
    """由 K 线派生的板块代理情绪（N 日收益截面标准化 + 涨跌家数宽度）。

    as-of 规则：T 日分数只使用 <= T-1 收盘的价格
    （收益区间 [t-1-N, t-1]，t-1 = 日历中 T 的前一交易日）。

    单票分数（可手算）：
    - rank_score_i = 2 * rank_i/(n-1) - 1（板块内按 N 日收益升序名次，n==1 时为 0）
    - breadth = 2 * (近 breadth_window 日上涨家数 / n) - 1
    - stock_score_i = clip(0.5*rank_score_i + 0.5*breadth, -1, 1)
    板块分数经 SectorSentimentAggregator.aggregate 聚合（与线上一致）。
    """

    name = "proxy"
    sentiment_source = "price_breadth_proxy"
    report_usable = False  # 代理情绪禁止支撑报告结论

    def __init__(
        self,
        store: KlineStore,
        calendar: List[str],
        return_window: int = 20,
        breadth_window: int = 5,
        sectors: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.store = store
        self.calendar = list(calendar)
        self.return_window = int(return_window)
        self.breadth_window = int(breadth_window)
        self.sectors = sectors if sectors is not None else SECTORS
        self.aggregator = SectorSentimentAggregator(
            expected_stocks_per_sector=EXPECTED_STOCKS_PER_SECTOR,
        )
        self._precomputed: Dict[str, Dict[str, SectorState]] = {}
        self._precompute()

    # ------------------------------------------------------------------

    def _prev_date(self, idx: int) -> Optional[str]:
        return self.calendar[idx - 1] if idx >= 1 else None

    def _stock_scores_on(self, asof_date: str) -> Dict[str, List[StockSentimentInput]]:
        """按 as-of 收盘日（<= T-1）计算各板块成分代理分数。"""
        out: Dict[str, List[StockSentimentInput]] = {}
        for sector_id, cfg in self.sectors.items():
            inputs: List[StockSentimentInput] = []
            rets: List[float] = []
            for code in cfg.tickers:
                series_dates, series_map = self.store._prices.get(code, ([], {}))  # noqa: SLF001
                # 定位 <= asof_date 的最后两个价格点
                valid_idx = [i for i, d in enumerate(series_dates) if d <= asof_date]
                if len(valid_idx) < 2:
                    continue
                i_last = valid_idx[-1]
                i_base = max(0, i_last - self.return_window)
                p_last = series_map[series_dates[i_last]]
                p_base = series_map[series_dates[i_base]]
                if p_base == 0.0:
                    continue
                r = p_last / p_base - 1.0
                p_breadth_ref = series_map[series_dates[max(0, i_last - self.breadth_window)]]
                up = p_last > p_breadth_ref
                rets.append(r)
                inputs.append(StockSentimentInput(
                    code=code, sector=sector_id,
                    sentiment_score=0.0,  # 占位，下面统一按截面标准化
                    sentiment_confidence=PROXY_STOCK_CONFIDENCE,
                    news_count=1, timestamp=asof_date,
                ))
                inputs[-1]._up_flag = up  # type: ignore[attr-defined]
            if not inputs:
                out[sector_id] = []
                continue
            n = len(inputs)
            # 截面名次标准化
            order = sorted(range(n), key=lambda k: rets[k])
            ranks = [0] * n
            for rank_pos, k in enumerate(order):
                ranks[k] = rank_pos
            breadth_up = sum(1 for x in inputs if getattr(x, "_up_flag", False))
            breadth = 2.0 * breadth_up / n - 1.0
            for k, item in enumerate(inputs):
                rank_score = (2.0 * ranks[k] / (n - 1) - 1.0) if n > 1 else 0.0
                raw = 0.5 * rank_score + 0.5 * breadth
                item.sentiment_score = max(SENTIMENT_BOUND_MIN, min(SENTIMENT_BOUND_MAX, raw))
            out[sector_id] = inputs
        return out

    def _precompute(self) -> None:
        """全日历逐日预计算（严格 as-of：T 用 T-1 收盘）。"""
        history: Dict[str, List[float]] = {sid: [] for sid in self.sectors}
        for idx, day in enumerate(self.calendar):
            asof = self._prev_date(idx)
            if asof is None:
                # 日历首日无 T-1 数据：中性状态（无未来函数）
                states: Dict[str, SectorState] = {}
                for sid in self.sectors:
                    states[sid] = SectorState(
                        sector=sid, sentiment_score=0.0, stock_count=0,
                        confidence=0.0, last_updated=day,
                    )
                self._precomputed[day] = states
                continue
            per_sector = self._stock_scores_on(asof)
            states = {}
            for sid in self.sectors:
                inputs = per_sector.get(sid, [])
                state = self.aggregator.aggregate(
                    stocks=inputs, sector=sid,
                    historical_scores=list(history[sid]),
                    timestamp=f"{day} (as-of {asof})",
                )
                states[sid] = state
                history[sid].append(state.sentiment_score)
            self._precomputed[day] = states

    # ------------------------------------------------------------------

    def get_sector_states(self, trade_date: str) -> Dict[str, SectorState]:
        if trade_date not in self._precomputed:
            raise KeyError(f"代理情绪无该交易日: {trade_date}")
        return self._precomputed[trade_date]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "sentiment_source": self.sentiment_source,
            "report_usable": self.report_usable,
            "return_window": self.return_window,
            "breadth_window": self.breadth_window,
        }


# ============================================================================
# 4. 真实情绪：LLM 新闻重放 provider
# ============================================================================

class LLMReplaySentimentProvider:
    """在 W_real 内用真实新闻 + LLM 逐票打分，再经 SectorSentimentAggregator 聚合。

    可注入依赖（离线可复现）：
    - news_loader(code, trade_date) -> List[NewsItem/dict]：必须只返回 <= trade_date 的新闻；
      离线模式用 JSON 夹具 loader，在线模式薄封装 src/llm/news_fetcher.NewsFetcher。
    - analyzer：具备 analyze_batch(texts) -> List[带 .score 属性结果] 的对象
      （生产为 src/llm/llm_sentiment.LLMSentimentAnalyzer，测试注入 mock）。
    """

    name = "llm"
    sentiment_source = "llm_news_replay"
    report_usable = True

    def __init__(
        self,
        news_loader: NewsLoader,
        analyzer: Any,
        calendar: List[str],
        lookback_days: int = 7,
        sectors: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.news_loader = news_loader
        self.analyzer = analyzer
        self.calendar = list(calendar)
        self.lookback_days = int(lookback_days)
        self.sectors = sectors if sectors is not None else SECTORS
        self.aggregator = SectorSentimentAggregator(
            expected_stocks_per_sector=EXPECTED_STOCKS_PER_SECTOR,
        )
        self._cache: Dict[str, Dict[str, SectorState]] = {}

    # ------------------------------------------------------------------

    def _prev_date(self, idx: int) -> Optional[str]:
        return self.calendar[idx - 1] if idx >= 1 else None

    def _news_text(self, item: Any) -> str:
        if isinstance(item, dict):
            return f"{item.get('title', '')}。{item.get('content', '')}"[:500]
        return f"{getattr(item, 'title', '')}。{getattr(item, 'content', '')}"[:500]

    def _news_time(self, item: Any) -> str:
        raw = item.get("publish_time", "") if isinstance(item, dict) else str(getattr(item, "publish_time", ""))
        return str(raw)[:10]

    def get_sector_states(self, trade_date: str) -> Dict[str, SectorState]:
        if trade_date in self._cache:
            return self._cache[trade_date]
        idx = self.calendar.index(trade_date)
        asof = self._prev_date(idx)
        if asof is None:
            states = {sid: SectorState(sector=sid, stock_count=0, confidence=0.0,
                                        last_updated=trade_date)
                      for sid in self.sectors}
            self._cache[trade_date] = states
            return states

        # as-of 窗口：(asof - lookback_days, asof] 内的新闻
        from datetime import datetime, timedelta
        win_start = (datetime.strptime(asof, "%Y-%m-%d")
                     - timedelta(days=self.lookback_days)).strftime("%Y-%m-%d")

        history: Dict[str, List[float]] = {sid: [] for sid in self.sectors}
        for prev_day in self.calendar[:idx]:
            cached = self._cache.get(prev_day)
            if cached:
                for sid, st in cached.items():
                    if sid in history:
                        history[sid].append(st.sentiment_score)

        states: Dict[str, SectorState] = {}
        for sid, cfg in self.sectors.items():
            inputs: List[StockSentimentInput] = []
            for code in cfg.tickers:
                news = [n for n in self.news_loader(code, asof)
                        if win_start <= self._news_time(n) <= asof] if self.news_loader else []
                if not news:
                    continue
                texts = [self._news_text(n) for n in news]
                results = self.analyzer.analyze_batch(texts)
                if not results:
                    continue
                score = sum(float(getattr(r, "score", 0.0)) for r in results) / len(results)
                inputs.append(StockSentimentInput(
                    code=code, sector=sid,
                    sentiment_score=max(SENTIMENT_BOUND_MIN, min(SENTIMENT_BOUND_MAX, score)),
                    sentiment_confidence=0.8,
                    news_count=len(news), timestamp=asof,
                ))
            states[sid] = self.aggregator.aggregate(
                stocks=inputs, sector=sid,
                historical_scores=history.get(sid, []),
                timestamp=f"{trade_date} (as-of {asof})",
            )
        self._cache[trade_date] = states
        return states

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "sentiment_source": self.sentiment_source,
            "report_usable": self.report_usable,
            "lookback_days": self.lookback_days,
        }


# ============================================================================
# 5. 测试夹具 provider（禁止进入报告路径）
# ============================================================================

class FrozenFixturesSentimentProvider:
    """从固定 {date: {sector: state_dict}} 表直接返回板块状态。

    仅供单元测试注入确定性情绪；report_usable=False 使
    BacktestEngine.run(for_report=True) 拒绝其进入报告产物路径。
    """

    name = "fixture"
    sentiment_source = "fixture_only"
    report_usable = False

    def __init__(self, states_by_date: Dict[str, Dict[str, Any]]) -> None:
        self._states: Dict[str, Dict[str, SectorState]] = {}
        for day, row in states_by_date.items():
            self._states[day] = {
                sid: (st if isinstance(st, SectorState) else SectorState(**st))
                for sid, st in row.items()
            }

    def get_sector_states(self, trade_date: str) -> Dict[str, SectorState]:
        if trade_date not in self._states:
            raise KeyError(f"夹具情绪无该交易日: {trade_date}")
        return self._states[trade_date]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "sentiment_source": self.sentiment_source,
            "report_usable": self.report_usable,
            "n_dates": len(self._states),
        }
