# -*- coding: utf-8 -*-
"""src/sector_rotation/backtest/backtest_engine.py —— 板块轮动回测引擎

时序纪律（AGENTS.md 第2条）：
- 严格 as-of：T 日决策只使用 provider.get_sector_states(T)（其内部只用 <= T-1 收盘
  的情绪与价格），成交与成本发生在 T 日收盘（即决策后下一步进日）；
- 交易日历来自 K 线真实日期，禁止随机打乱/插值/外推。

决策链：SectorRotationEngine.decide() -> should_rotate 时 PositionManager.plan_reallocation()
-> 随后 ROTATION_EXECUTION_DAYS 个交易日每日 execute_step() 推进 50/30/20 渐进切换
-> 成本超限 (MAX_TOTAL_ROTATION_COST) 抛 CostLimitExceededError 并中断当次切换。

净值口径：
- 策略净值按当日持仓板块权重 × 板块等权成分日收益累计，交易成本在步进执行日扣减；
- 基准为全程持有 3 板块等权的 buy-and-hold（另存 benchmark_nav）。
"""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import (
    BUY_FEE_RATE,
    COOLDOWN_DAYS,
    DEFENSIVE_SECTOR,
    MAX_ROTATION_PER_MONTH,
    MAX_TOTAL_ROTATION_COST,
    MIN_HOLDING_DAYS,
    MIN_TARGET_SENTIMENT,
    ROTATION_EXECUTION_DAYS,
    SECTORS,
    SELL_FEE_RATE,
    SENTIMENT_DECLINE_THRESHOLD,
    TRANSACTION_COST_RATE,
)
from ..position_manager import CostLimitExceededError, PortfolioState, PositionManager
from ..sector_rotation_engine import SectorRotationEngine
from ..utils.sector_utils import SectorState
from .performance_metrics import compute_metrics
from .sentiment_providers import (
    KlineStore,
    SentimentProvider,
    sector_daily_return,
)


# ============================================================================
# 1. 回测结果契约
# ============================================================================

@dataclass
class BacktestResult:
    """回测全量产物（可落盘为 nav/trades/decisions/states/metrics/manifest）"""
    days: List[str]
    nav: List[float]
    benchmark_nav: List[float]
    trades: List[Dict[str, Any]] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    states_rows: List[Dict[str, Any]] = field(default_factory=list)
    segments: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    manifest: Dict[str, Any] = field(default_factory=dict)

    def save(self, out_dir: Path, allow_overwrite: bool = False) -> Path:
        """落盘产物。默认禁止覆盖既有目录（AGENTS.md：不覆盖原始数据）。"""
        out_dir = Path(out_dir)
        if out_dir.exists() and any(out_dir.iterdir()) and not allow_overwrite:
            raise FileExistsError(
                f"产物目录非空: {out_dir}（禁止覆盖，请换新目录或显式 allow_overwrite）")
        out_dir.mkdir(parents=True, exist_ok=True)

        with (out_dir / "nav.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["date", "nav", "benchmark_nav"])
            for d, v, b in zip(self.days, self.nav, self.benchmark_nav):
                w.writerow([d, round(v, 4), round(b, 6)])

        for fname, rows in (("trades.csv", self.trades),
                            ("decisions.csv", self.decisions),
                            ("sector_states.csv", self.states_rows)):
            with (out_dir / fname).open("w", newline="", encoding="utf-8") as f:
                if not rows:
                    f.write("")
                    continue
                cols = sorted({k for r in rows for k in r.keys()})
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                for r in rows:
                    w.writerow({c: (json.dumps(r[c], ensure_ascii=False)
                                    if isinstance(r.get(c), (dict, list))
                                    else r.get(c, ""))
                                for c in cols})

        (out_dir / "metrics.json").write_text(
            json.dumps(self.metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "run_manifest.json").write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return out_dir


# ============================================================================
# 2. 回测引擎
# ============================================================================

class BacktestEngine:
    """逐日事件循环的板块轮动回测引擎。"""

    def __init__(
        self,
        store: Optional[KlineStore] = None,
        kline_dir: Optional[Path] = None,
        sectors: Optional[Dict[str, Any]] = None,
    ) -> None:
        # store 可缺省仅为兼容契约验证（如 hasattr Smoke）；真实回测必须提供
        # 合成或 repo K 线日历，run() 入口处强制校验。
        self.store = store
        self.kline_dir = Path(kline_dir) if kline_dir else None
        self.sectors = sectors if sectors is not None else SECTORS

    # ------------------------------------------------------------------

    def _build_rotation_engine(self, params: Dict[str, Any]) -> SectorRotationEngine:
        return SectorRotationEngine(
            weights=params.get("weights"),
            decline_threshold=float(params.get("decline_threshold", SENTIMENT_DECLINE_THRESHOLD)),
            target_threshold=float(params.get("target_threshold", MIN_TARGET_SENTIMENT)),
            min_holding_days=int(params.get("min_holding_days", MIN_HOLDING_DAYS)),
            max_monthly_rotations=int(params.get("max_monthly_rotations", MAX_ROTATION_PER_MONTH)),
            cooldown_days=int(params.get("cooldown_days", COOLDOWN_DAYS)),
            defensive_sector=str(params.get("defensive_sector", DEFENSIVE_SECTOR)),
        )

    def _build_position_manager(self, params: Dict[str, Any]) -> PositionManager:
        return PositionManager(
            buy_fee_rate=float(params.get("buy_fee_rate", BUY_FEE_RATE)),
            sell_fee_rate=float(params.get("sell_fee_rate", SELL_FEE_RATE)),
            total_cost_ceiling=float(params.get("max_total_rotation_cost", MAX_TOTAL_ROTATION_COST)),
            min_holding_days=int(params.get("min_holding_days", MIN_HOLDING_DAYS)),
            max_rotation_per_month=int(params.get("max_monthly_rotations", MAX_ROTATION_PER_MONTH)),
            cooldown_days=int(params.get("cooldown_days", COOLDOWN_DAYS)),
        )

    # ------------------------------------------------------------------

    def run(
        self,
        start_date: str,
        end_date: str,
        provider: SentimentProvider,
        initial_capital: float = 1_000_000.0,
        initial_sector: str = DEFENSIVE_SECTOR,
        advisor: Any = None,
        params: Optional[Dict[str, Any]] = None,
        for_report: bool = False,
    ) -> BacktestResult:
        """执行回测主循环。

        Args:
            start_date/end_date: 回测区间（YYYY-MM-DD，按 K 线公共日历截断）
            provider: 情绪 provider（决定 sentiment_source 标注）
            initial_capital: 初始资金
            initial_sector: 建仓板块（默认防御板块 gold，manifest 记录）
            advisor: 可选 LLMDecisionAdvisor，仅在轮动触发时复核并回填 llm_validation
            params: 阈值覆盖（供敏感性场景）
            for_report: True 时拒绝非报告级 provider（代理/夹具禁止生成报告产物）
        """
        if for_report and not getattr(provider, "report_usable", False):
            raise ValueError(
                f"provider '{getattr(provider, 'name', '?')}' 的 sentiment_source="
                f"'{getattr(provider, 'sentiment_source', '?')}' 禁止进入报告路径"
                "（仅 llm_news_replay 可支撑结论性报告）")

        if self.store is None:
            raise ValueError("回测必须提供 KlineStore（合成或 docs/data/kline 加载）")

        params = dict(params or {})
        days = self.store.common_dates(start_date, end_date)
        if len(days) < 2:
            raise ValueError(f"回测区间无公共交易日历: {start_date}~{end_date}")

        rot_engine = self._build_rotation_engine(params)
        pos_mgr = self._build_position_manager(params)
        slippage = float(params.get("slippage", 0.0))

        initial_sector = str(initial_sector).strip().lower()
        pstate = PortfolioState(
            current_sector=initial_sector,
            sector_weights={initial_sector: 1.0},
            portfolio_value=initial_capital,
            holding_days=0,
            days_since_last_rotation=COOLDOWN_DAYS + 1,  # 起点视为冷却期已过
        )

        nav = initial_capital
        nav_rows: List[float] = [initial_capital]
        bench_rows: List[float] = [1.0]
        bench_val = 1.0
        trades: List[Dict[str, Any]] = []
        decisions_rows: List[Dict[str, Any]] = []
        states_rows: List[Dict[str, Any]] = []
        segments: List[Dict[str, Any]] = []
        seg_start_nav: Optional[float] = None
        seg_start_day: Optional[str] = None
        total_cost = 0.0
        current_month = days[0][:7]
        pending_schedule = None  # 决策日规划、次日起执行的计划

        for i, day in enumerate(days):
            prev_day = days[i - 1] if i >= 1 else None

            # --------------------------------------------------------
            # 1) 估值：当日板块收益（按昨日收盘权重，真实 K 线）
            # --------------------------------------------------------
            if prev_day is not None:
                day_ret = 0.0
                for sid, w in pstate.sector_weights.items():
                    if w <= 0:
                        continue
                    cfg = self.sectors.get(sid)
                    if cfg is None:
                        continue
                    r = sector_daily_return(self.store, cfg.tickers, day, prev_day)
                    if r is not None:
                        day_ret += w * r
                nav *= (1.0 + day_ret)
                bench_sec_returns = [
                    sector_daily_return(self.store, cfg.tickers, day, prev_day)
                    for cfg in self.sectors.values()
                ]
                valid = [r for r in bench_sec_returns if r is not None]
                bench_val *= (1.0 + (sum(valid) / len(valid) if valid else 0.0))

            if i >= 1:
                nav_rows.append(nav)
                bench_rows.append(bench_val)

            # 自然月边界重置轮动计数
            if day[:7] != current_month:
                current_month = day[:7]
                pstate.rotation_count_this_month = 0

            # --------------------------------------------------------
            # 2) 执行渐进式调仓步进（决策次日开始）
            # --------------------------------------------------------
            schedule = pos_mgr.get_active_schedule()
            if schedule is not None and schedule.is_active:
                try:
                    step = pos_mgr.execute_step(
                        portfolio_value=nav,
                        current_weights=dict(pstate.sector_weights),
                        slippage=slippage,
                        strict_cost_limit=True,
                        portfolio_state=pstate,
                    )
                    cost = float(step.get("cost", 0.0))
                    nav -= cost
                    total_cost += cost
                    row = {"date": day, "rotation_id": len(segments) + 1,
                           "sentiment_source": provider.sentiment_source, **step}
                    row["nav_after"] = nav
                    trades.append(row)
                    if step.get("is_complete"):
                        # 完成轮动：结算上一段（自上次轮动完成/期初至本次完成）
                        if seg_start_day is not None:
                            segments.append({
                                "start": seg_start_day, "end": day,
                                "sector": schedule.to_sector,
                                "days": len([d for d in days if seg_start_day <= d <= day]),
                                "return": nav / seg_start_nav - 1.0 if seg_start_nav else 0.0,
                            })
                        seg_start_nav = nav
                        seg_start_day = day
                        pstate.days_since_last_rotation = 0
                    nav_rows[-1] = nav
                except CostLimitExceededError as err:
                    pos_mgr.cancel_schedule(f"回测中成本超限中断: {err}")
                    trades.append({"date": day, "event": "cost_limit_exceeded_aborted",
                                   "detail": str(err),
                                   "sentiment_source": provider.sentiment_source})
                    nav_rows[-1] = nav

            # --------------------------------------------------------
            # 3) 决策（provider 内部保证只用 <= day-1 数据）
            # --------------------------------------------------------
            try:
                states: Dict[str, SectorState] = provider.get_sector_states(day)
            except KeyError:
                states = {}
            if states:
                decision = rot_engine.decide(
                    sector_sentiments=states,
                    portfolio_state=pstate,
                    timestamp=f"{day} 00:00:00",
                )
                for sid, st in states.items():
                    states_rows.append({
                        "date": day, "sector": sid,
                        "sentiment_score": st.sentiment_score,
                        "sentiment_trend": st.sentiment_trend,
                        "volatility": st.volatility,
                        "stock_count": st.stock_count,
                        "confidence": st.confidence,
                        "sentiment_source": provider.sentiment_source,
                    })
                if decision.should_rotate and advisor is not None:
                    decision = advisor.validate_decision(
                        quantitative_decision=decision,
                        sector_data=states,
                        current_sector=pstate.current_sector,
                    )
                row = {"date": day, "sentiment_source": provider.sentiment_source,
                       **decision.to_dict()}
                decisions_rows.append(row)

                # 无活跃计划时接受新轮动决策（计划自次日起执行）
                if (decision.should_rotate
                        and pos_mgr.get_active_schedule() is None
                        and decision.target_sector
                        and i + 1 < len(days)):
                    from_sec = pstate.current_sector or max(
                        pstate.sector_weights, key=pstate.sector_weights.get)
                    if from_sec != decision.target_sector:
                        pending_schedule = pos_mgr.plan_reallocation(
                            from_sector=from_sec,
                            to_sector=decision.target_sector,
                            start_date=days[i + 1],
                        )
                        # 诚实口径：仅被接受并实际开始执行的轮动计入 rotation_count
                        row["rotation_accepted"] = True

            # --------------------------------------------------------
            # 4) 状态推进
            # --------------------------------------------------------
            if pos_mgr.get_active_schedule() is None:
                pstate.holding_days += 1
            pstate.days_since_last_rotation += 1
            pstate.portfolio_value = nav

        # 期末结算最后一个持仓段
        if seg_start_day is not None and seg_start_nav:
            segments.append({
                "start": seg_start_day, "end": days[-1],
                "sector": pstate.current_sector,
                "days": len([d for d in days if seg_start_day <= d <= days[-1]]),
                "return": nav / seg_start_nav - 1.0,
            })

        # --------------------------------------------------------
        # 5) 指标与 manifest
        # --------------------------------------------------------
        trade_returns = [s["return"] for s in segments if s.get("sector") is not None]
        holding_segments = [s["days"] for s in segments]
        strategy_metrics = compute_metrics(
            nav=nav_rows, decisions=decisions_rows,
            trade_returns=trade_returns, holding_segments=holding_segments,
            total_cost=total_cost, initial_capital=initial_capital,
        )
        from .performance_metrics import daily_returns as _dr, sharpe_ratio as _sr
        bench_total = (bench_rows[-1] / bench_rows[0] - 1.0) if bench_rows and bench_rows[0] else 0.0
        bench_dict = {
            "total_return": bench_total,
            "sharpe": _sr(_dr(bench_rows)),
            "max_drawdown": _mdd(bench_rows),
        }

        manifest = self._build_manifest(
            provider=provider, start_date=days[0], end_date=days[-1],
            initial_capital=initial_capital, initial_sector=initial_sector,
            params=params, advisor=advisor, missing=self._missing_tickers(),
            n_days=len(days),
        )

        return BacktestResult(
            days=days,
            nav=nav_rows,
            benchmark_nav=bench_rows,
            trades=trades,
            decisions=decisions_rows,
            states_rows=states_rows,
            segments=segments,
            metrics={
                "strategy": strategy_metrics.to_dict(),
                "benchmark_equal_weight_buy_hold": {
                    "total_return": round(float(bench_dict["total_return"]), 6),
                    "sharpe": round(bench_dict["sharpe"], 4) if bench_dict["sharpe"] is not None else None,
                    "max_drawdown": round(float(bench_dict["max_drawdown"]), 6),
                },
                "cost_model": {
                    "buy_fee_rate": BUY_FEE_RATE, "sell_fee_rate": SELL_FEE_RATE,
                    "transaction_cost_rate_reference": TRANSACTION_COST_RATE,
                    "max_total_rotation_cost": MAX_TOTAL_ROTATION_COST,
                    "slippage": slippage,
                },
                "execution_days": ROTATION_EXECUTION_DAYS,
            },
            manifest=manifest,
        )

    # ------------------------------------------------------------------

    def _missing_tickers(self) -> List[str]:
        missing: List[str] = []
        for cfg in self.sectors.values():
            for t in cfg.tickers:
                if not self.store.has(t):
                    missing.append(t)
        return missing

    def _build_manifest(self, provider: Any, start_date: str, end_date: str,
                        initial_capital: float, initial_sector: str,
                        params: Dict[str, Any], advisor: Any,
                        missing: List[str], n_days: int) -> Dict[str, Any]:
        git_commit = ""
        try:
            git_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                timeout=5, cwd=str(Path(__file__).resolve().parents[3]),
            ).stdout.strip()
        except Exception:  # noqa: BLE001 —— 环境缺失不阻断回测
            pass
        input_hashes: Dict[str, str] = {}
        if self.kline_dir is not None:
            input_hashes = self.store.file_sha256_map(self.kline_dir)
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "provider": getattr(provider, "name", type(provider).__name__),
            "sentiment_source": getattr(provider, "sentiment_source", "unknown"),
            "report_usable": bool(getattr(provider, "report_usable", False)),
            "window": {"start": start_date, "end": end_date, "n_trading_days": n_days},
            "initial_capital": initial_capital,
            "initial_sector": initial_sector,
            "params": params,
            "advisor_enabled": advisor is not None,
            "missing_tickers": missing,
            "sector_universe": {sid: list(cfg.tickers) for sid, cfg in self.sectors.items()},
            "valuation": "sector equal-weight constituents, daily close-to-close",
            "benchmark": "3-sector equal-weight buy-and-hold over same calendar",
            "git_commit": git_commit,
            "python": platform.python_version(),
            "input_file_sha256": input_hashes,
        }


def _mdd(nav: List[float]) -> float:
    from .performance_metrics import max_drawdown
    return max_drawdown(nav)
