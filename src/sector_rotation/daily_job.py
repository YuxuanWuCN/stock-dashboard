# -*- coding: utf-8 -*-
"""src/sector_rotation/daily_job.py —— 板块轮动每日决策与归档（阶段5，任务 5.1）

职责：
1. 读取当日个股情绪（优先真实新闻 + LLM 重放分支，缺失时降级为价格宽度代理）；
2. 聚合三板块状态 -> `SectorRotationEngine.decide()` 产出量化决策；
3. 输出 `docs/data/sector_rotation/latest_rotation.json`
   （generated_at / trade_date / 板块评分 / 决策 / 理由 / 置信度 / sentiment_source / 审计记录）；
4. 追加 `docs/data/sector_rotation/history.jsonl`——本仓库此前没有个股日频情绪历史，
   该文件即为前向累积的真实情绪历史序列（解决 DATA_FEASIBILITY 指出的归档缺口，
   累积足够交易日后回测 S2 场景才能产出结论性指标）。

数据诚实性约束（AGENTS.md 第2条）：
- 每份产物强制携带 `sentiment_source`；LLM 情绪不可用而降级代理时，
  必须写 `price_breadth_proxy` 并在 `notes` 说明降级原因，禁止把代理标注为 LLM。
- 未通过 S2 覆盖门槛前，产物带 `strategy_validated=False`，前端卡片只作决策参考展示，
  不构成业绩结论。
- 无未来函数：T 日决策只使用 <= T-1 的情绪与价格（由 provider 的 as-of 规则保证）。
"""

from __future__ import annotations

import json
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .backtest.sentiment_providers import (
    KlineStore,
    LLMReplaySentimentProvider,
    ProxyBreadthSentimentProvider,
)
from .config import (
    COOLDOWN_DAYS,
    DEFENSIVE_SECTOR,
    SECTORS,
    get_all_tickers,
)
from .llm_decision_advisor import LLMDecisionAdvisor
from .sector_rotation_engine import SectorRotationEngine
from .utils.sector_utils import SectorState

ROOT_DIR = Path(__file__).resolve().parents[2]
KLINE_DIR = ROOT_DIR / "docs" / "data" / "kline"
OUT_DIR = ROOT_DIR / "docs" / "data" / "sector_rotation"
LATEST_NAME = "latest_rotation.json"
HISTORY_NAME = "history.jsonl"
SCHEMA_VERSION = "1.0"

# 首次运行（无历史）时的宽松状态：不让风控门禁误拦截首日决策
FIRST_RUN_STATE: Dict[str, Any] = {
    "current_sector": DEFENSIVE_SECTOR,
    "holding_days": COOLDOWN_DAYS + 3,
    "monthly_rotations": 0,
    "days_since_last_rotation": COOLDOWN_DAYS + 3,
}


# ============================================================================
# 1. 持仓状态推断（纯函数，可手算复核）
# ============================================================================

def _effective_holding(row: Dict[str, Any]) -> str:
    """一行的「决策后持仓板块」：轮动行以 target_sector 为准（容忍行内字段不一致），
    非轮动行取 holding_sector，缺失时回落 current_sector。"""
    if bool(row.get("should_rotate")) and row.get("target_sector"):
        return str(row["target_sector"]).strip().lower()
    return str(row.get("holding_sector") or row.get("current_sector") or "").strip().lower()


def infer_portfolio_state(history_rows: List[Dict[str, Any]], trade_date: str) -> Dict[str, Any]:
    """由 `history.jsonl` 反推当日决策所需的持仓状态。

    规则（确定性、无未来信息）：
    - holding_sector：末行若发生轮动（should_rotate=True）则为其 target_sector，
      否则为末行 holding_sector；
    - holding_days：自末尾向前连续同一 holding_sector 的行数；
    - days_since_last_rotation：末行之后经过的交易日数（含当日，故轮动次日为 1）；
      等价于「最后一行日期到 trade_date 的间隔 + 1」，无历史时取宽松默认；
    - monthly_rotations：与 trade_date 同自然月内 should_rotate=True 的行数。
    """
    if not history_rows:
        return dict(FIRST_RUN_STATE)

    last = history_rows[-1]
    holding = _effective_holding(last) or DEFENSIVE_SECTOR

    # 持仓天数：从末行向前数同一 holding_sector 的连续行数
    holding_days = 0
    for row in reversed(history_rows):
        if _effective_holding(row) != holding:
            break
        holding_days += 1

    # 距上次轮动：自末行向前找到最近一次 should_rotate=True 的行，
    # 其间隔的行数 +1（当日也算一个交易日）；全程无轮动则视为冷却期已过。
    days_since_last_rotation = 0
    rotated_idx = None
    for idx in range(len(history_rows) - 1, -1, -1):
        if bool(history_rows[idx].get("should_rotate")):
            rotated_idx = idx
            break
    if rotated_idx is None:
        days_since_last_rotation = COOLDOWN_DAYS + 3
    else:
        days_since_last_rotation = len(history_rows) - rotated_idx  # 含当日

    month = str(trade_date)[:7]
    monthly_rotations = sum(
        1 for row in history_rows
        if bool(row.get("should_rotate")) and str(row.get("trade_date", ""))[:7] == month
    )

    return {
        "current_sector": holding,
        "holding_days": holding_days,
        "monthly_rotations": monthly_rotations,
        "days_since_last_rotation": days_since_last_rotation,
    }


# ============================================================================
# 2. 情绪输入装配（新闻夹具 / 实时新闻 / 代理）
# ============================================================================

def make_fixture_news_loader(path: Path) -> Callable[[str, str], List[Any]]:
    """离线新闻夹具：{code: [{title, content, publish_time}, ...]}"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    def loader(code: str, trade_date: str) -> List[Any]:
        return list(raw.get(code, []))

    return loader


def make_live_news_loader() -> Callable[[str, str], List[Any]]:
    """实时新闻 loader（薄封装 src.llm.news_fetcher.NewsFetcher）。

    外部请求失败一律返回空列表（不伪造情绪），由调用方据此判定是否降级代理。
    """
    try:
        from src.llm.news_fetcher import NewsFetcher  # 延迟导入：离线测试不应触发 akshare
    except Exception:  # noqa: BLE001 - 依赖缺失时按"无新闻"处理
        return lambda code, trade_date: []

    fetcher = NewsFetcher()
    cache: Dict[str, List[Any]] = {}

    def loader(code: str, trade_date: str) -> List[Any]:
        if code not in cache:
            try:
                cache[code] = list(fetcher.fetch_stock(code))
            except Exception:  # noqa: BLE001 - 网络/接口异常视为无新闻
                cache[code] = []
        return cache[code]

    return loader


def build_provider(
    mode: str,
    store: KlineStore,
    calendar: List[str],
    news_loader: Optional[Callable[[str, str], List[Any]]] = None,
    analyzer: Any = None,
    lookback_days: int = 7,
) -> Any:
    """按模式构造情绪 provider。mode: 'llm' | 'proxy'。"""
    if mode == "proxy":
        return ProxyBreadthSentimentProvider(store=store, calendar=calendar)
    if mode != "llm":
        raise ValueError(f"未知 sentiment_mode: {mode}")
    from src.llm.llm_sentiment import LLMSentimentAnalyzer
    return LLMReplaySentimentProvider(
        news_loader=news_loader or make_live_news_loader(),
        analyzer=analyzer if analyzer is not None else LLMSentimentAnalyzer(),
        calendar=calendar,
        lookback_days=lookback_days,
    )


# ============================================================================
# 3. 历史读写
# ============================================================================

def load_history(history_path: Path) -> List[Dict[str, Any]]:
    """读取 history.jsonl（缺文件返回空列表；坏行跳过但不中断）。"""
    path = Path(history_path)
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def append_history(row: Dict[str, Any], history_path: Path) -> None:
    """追加一行历史（不覆盖既有内容）。同一 trade_date 重复运行会追加多条，
    以最后一次运行为准（读取时按末行判定）。"""
    path = Path(history_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


# ============================================================================
# 4. 主任务
# ============================================================================

def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            timeout=5, cwd=str(ROOT_DIR),
        ).stdout.strip()
    except Exception:  # noqa: BLE001 - 环境缺失不阻断每日任务
        return ""


def run_daily(
    trade_date: Optional[str] = None,
    sentiment_mode: str = "auto",
    news_fixture: Optional[Path] = None,
    analyzer: Any = None,
    use_advisor: bool = False,
    out_dir: Optional[Path] = None,
    store: Optional[KlineStore] = None,
    engine: Optional[SectorRotationEngine] = None,
    history_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """执行每日轮动决策并落盘产物，返回写入 `latest_rotation.json` 的完整字典。

    Args:
        trade_date: 决策日（YYYY-MM-DD）；缺省取 K 线日历最后一个交易日
        sentiment_mode: 'auto'（优先 LLM 新闻，无新闻降级代理）| 'llm' | 'proxy'
        news_fixture: 离线新闻夹具路径（提供则不发起外部请求）
        analyzer: 可注入的情绪分析器（测试 mock）
        use_advisor: 是否启用 LLM 决策复核（只回填 llm_validation，不推翻量化）
        out_dir / store / engine / history_rows: 依赖注入（测试与自定义路径）
    """
    out_root = Path(out_dir) if out_dir else OUT_DIR
    latest_path = out_root / LATEST_NAME
    history_path = out_root / HISTORY_NAME

    store = store if store is not None else KlineStore.from_dir(KLINE_DIR, get_all_tickers())
    full_calendar = store.common_dates("2000-01-01", "2099-12-31")
    if not full_calendar:
        raise ValueError("K 线日历为空，无法执行每日决策")
    trade_date = str(trade_date or full_calendar[-1])[:10]
    # provider 只能在既有日历日内 as-of；非交易日回落到最近交易日
    effective_date = trade_date if trade_date in full_calendar else full_calendar[-1]
    calendar = [d for d in full_calendar if d <= effective_date]

    notes: List[str] = []
    news_loader: Optional[Callable[[str, str], List[Any]]] = None
    if news_fixture is not None:
        news_loader = make_fixture_news_loader(Path(news_fixture))
    elif sentiment_mode in ("auto", "llm"):
        news_loader = make_live_news_loader()

    def _news_available() -> bool:
        if news_loader is None:
            return False
        try:
            probe_date = calendar[-2] if len(calendar) >= 2 else calendar[-1]
            return any(len(news_loader(code, probe_date)) > 0 for code in get_all_tickers())
        except Exception:  # noqa: BLE001
            return False

    mode = sentiment_mode
    if mode == "auto":
        mode = "llm" if _news_available() else "proxy"
        if mode == "proxy":
            notes.append("当日无可用新闻（离线/接口不可达/无夹具），情绪降级为价格宽度代理。")
    if mode == "llm" and not _news_available():
        notes.append("LLM 新闻不可用，本次结果不可作为结论性情绪。")

    provider = build_provider(mode, store, calendar, news_loader=news_loader, analyzer=analyzer)

    history = history_rows if history_rows is not None else load_history(history_path)
    pstate = infer_portfolio_state(history, effective_date)

    states: Dict[str, SectorState] = provider.get_sector_states(effective_date)
    rot_engine = engine if engine is not None else SectorRotationEngine()
    advisor = LLMDecisionAdvisor() if use_advisor else None

    decision = rot_engine.decide(
        sector_sentiments=states,
        current_sector=pstate["current_sector"],
        holding_days=int(pstate["holding_days"]),
        monthly_rotations=int(pstate["monthly_rotations"]),
        days_since_last_rotation=int(pstate["days_since_last_rotation"]),
        timestamp=f"{effective_date} 00:00:00",
        advisor=advisor,
        llm_validation_enabled=advisor is not None,
    )

    holding_sector = (decision.target_sector or decision.current_sector) if decision.should_rotate \
        else decision.current_sector

    audit: Dict[str, Any] = {
        "engine": "SectorRotationEngine",
        "engine_version": SCHEMA_VERSION,
        "decision_path_ms": round(decision.execution_time_ms, 3),
        "python": platform.python_version(),
        "git_commit": _git_commit(),
        "portfolio_state_used": pstate,
        "provider": provider.to_dict(),
        "sector_inputs": {
            sid: {
                "stock_count": st.stock_count,
                "sentiment_score": st.sentiment_score,
                "sentiment_trend": st.sentiment_trend,
                "confidence": st.confidence,
            } for sid, st in states.items()
        },
        "advisor_audit": (advisor.audit_log[-1].to_dict()
                          if (advisor is not None and advisor.audit_log) else None),
    }

    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "trade_date": effective_date,
        "requested_trade_date": trade_date,
        "sentiment_source": provider.sentiment_source,
        "report_usable": bool(getattr(provider, "report_usable", False)),
        "strategy_validated": False,  # S2 覆盖门槛未确认前恒为 False（见 BACKTEST_REPORT §5）
        "holding_sector": holding_sector,
        "portfolio_state": pstate,
        "sectors": {
            sid: {"name": SECTORS[sid].name if sid in SECTORS else sid, **st.to_dict()}
            for sid, st in states.items()
        },
        "decision": decision.to_dict(),
        "reason": decision.reason,
        "confidence": round(float(decision.confidence), 4),
        "llm_validation": decision.llm_validation,
        "audit": audit,
        "notes": notes,
        "history_days_recorded": len(history) + 1,
    }

    out_root.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                           encoding="utf-8")

    history_row = {
        "trade_date": effective_date,
        "sentiment_source": provider.sentiment_source,
        "current_sector": decision.current_sector,
        "holding_sector": holding_sector,
        "should_rotate": decision.should_rotate,
        "target_sector": decision.target_sector,
        "is_fallback": decision.is_fallback,
        "confidence": round(float(decision.confidence), 4),
        "sector_scores": {sid: round(float(st.sentiment_score), 4) for sid, st in states.items()},
        "sector_trends": {sid: st.sentiment_trend for sid, st in states.items()},
        "llm_validation_status": (decision.llm_validation or {}).get("status"),
        "generated_at": payload["generated_at"],
    }
    append_history(history_row, history_path)

    return payload
