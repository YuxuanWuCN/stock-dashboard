# src/analysis/alpha_gate.py —— Alpha 门控判定与激进候选选择（spec-kit 003 / US3）
#
# 职责（对应 FR-006/007/011 与 contracts/alpha-gate-output.md）：
#   1. 回归结果 → 门控判定：p < ALPHA_P_THRESHOLD 且 IR >= IR_THRESHOLD 才 pass
#   2. 候选选择：候选 = 原候选 ∩ pass 集合；不足 min_size 时按原机会分回退补齐
#      （fallback 标记 + 调用方告警），绝不产生空组合
#   3. 因子库不可用 → 诚实降级为 data_unavailable，不伪造 pass
#
# 拒绝原因枚举：statistical（统计不显著）/ economical（经济不显著）/
#               insufficient_data（数据不足）/ data_unavailable（数据不可用）

import logging
from pathlib import Path
from typing import Dict, Optional, Sequence

import pandas as pd

from .config import ALPHA_P_THRESHOLD, IR_THRESHOLD
from . import factor_db, fama_macbeth

logger = logging.getLogger("stock-dashboard.alpha_gate")

VERDICT_PASS = "pass"
VERDICT_REJECT = "reject"
REJECT_STATISTICAL = "statistical"
REJECT_ECONOMICAL = "economical"
REJECT_INSUFFICIENT = "insufficient_data"
REJECT_UNAVAILABLE = "data_unavailable"
VALID_REJECT_REASONS = {
    REJECT_STATISTICAL, REJECT_ECONOMICAL, REJECT_INSUFFICIENT, REJECT_UNAVAILABLE,
}

DEFAULT_TOP_N = 8
DEFAULT_MIN_SIZE = 5


def evaluate_gate(regression: dict) -> dict:
    """回归结果 → 门控判定（契约见 contracts/alpha-gate-output.md）。

    返回 dict: {verdict, reject_reason, alpha, alpha_p_value, information_ratio,
                betas, window_end}
    reject_reason 仅 reject 时非空；pass 时为 None。
    """
    status = regression.get("status")
    if status == "insufficient_data":
        return {
            "verdict": VERDICT_REJECT,
            "reject_reason": REJECT_INSUFFICIENT,
            "alpha": None,
            "alpha_p_value": None,
            "information_ratio": None,
            "betas": None,
            "window_end": regression.get("window_end"),
        }
    if status != "ok":
        return {
            "verdict": VERDICT_REJECT,
            "reject_reason": REJECT_UNAVAILABLE,
            "alpha": None,
            "alpha_p_value": None,
            "information_ratio": None,
            "betas": None,
            "window_end": regression.get("window_end"),
        }

    alpha_p = regression["alpha_p_value"]
    ir = regression["information_ratio"]
    statistically = alpha_p is not None and alpha_p < ALPHA_P_THRESHOLD
    economically = ir is not None and ir >= IR_THRESHOLD
    if statistically and economically:
        verdict, reason = VERDICT_PASS, None
    else:
        verdict = VERDICT_REJECT
        reason = REJECT_STATISTICAL if not statistically else REJECT_ECONOMICAL

    return {
        "verdict": verdict,
        "reject_reason": reason,
        "alpha": regression["alpha"],
        "alpha_p_value": alpha_p,
        "information_ratio": ir,
        "betas": regression["betas"],
        "window_end": regression["window_end"],
    }


def _load_factors() -> Optional[pd.DataFrame]:
    """加载因子库全量序列；库不存在返回 None（诚实降级）。"""
    db = str(factor_db.default_db_path())
    if not Path(db).exists():
        return None
    return factor_db.query_range(db, "1900-01-01", "2999-12-31")


def run_alpha_gate(
    klines: Dict[str, pd.DataFrame],
    factors_df: Optional[pd.DataFrame] = None,
    returns_by_code: Optional[Dict[str, Sequence]] = None,
    analysis_date: Optional[str] = None,
) -> Dict[str, dict]:
    """对全部标的跑回归 + 门控，返回 {code: gate_entry}。

    factors_df 缺省时从 SQLite 因子库加载；库不可用 → 全部 data_unavailable。
    """
    if factors_df is None:
        factors_df = _load_factors()
    if factors_df is None:
        return {
            code: {
                "verdict": VERDICT_REJECT,
                "reject_reason": REJECT_UNAVAILABLE,
                "alpha": None,
                "alpha_p_value": None,
                "information_ratio": None,
                "betas": None,
                "window_end": None,
            }
            for code in klines
        }
    results = fama_macbeth.run_all(
        factors_df, klines, returns_by_code=returns_by_code,
        analysis_date=analysis_date,
    )
    return {code: evaluate_gate(res) for code, res in results.items()}


def select_gated_candidates(
    ranked_items: list,
    gates: Dict[str, dict],
    top_n: int = DEFAULT_TOP_N,
    min_size: int = DEFAULT_MIN_SIZE,
):
    """从已排序候选中选择通过门控的标的。

    返回 (selected_items, fallback_applied)。
    通过数 >= min_size → 只取 pass 的前 top_n；
    否则按原序回退补齐 top_n（调用方应告警标注），绝不返回空组合。
    """
    passed = [
        it for it in ranked_items
        if (gates.get(it["code"]) or {}).get("verdict") == VERDICT_PASS
    ]
    if len(passed) >= min_size:
        return passed[:top_n], False
    return ranked_items[:top_n], True


def gate_summary(items: list, min_size: int = DEFAULT_MIN_SIZE,
                 top_n: int = DEFAULT_TOP_N) -> dict:
    """排行榜级门控汇总（ranking.json 的 alpha_gate_summary 字段）。"""
    gates = {it["code"]: it.get("alpha_gate") or {} for it in items}
    passed_codes = [
        c for c, g in gates.items() if g.get("verdict") == VERDICT_PASS
    ]
    candidates, fallback = select_gated_candidates(
        items, gates, top_n=top_n, min_size=min_size,
    )
    return {
        "passed_codes": passed_codes,
        "passed_count": len(passed_codes),
        "fallback_applied": fallback,
        "min_size": min_size,
        "aggressive_candidates": [it["code"] for it in candidates],
        "thresholds": {
            "alpha_p_threshold": ALPHA_P_THRESHOLD,
            "ir_threshold": IR_THRESHOLD,
        },
    }
