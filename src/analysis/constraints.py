"""src/analysis/constraints.py —— 组合约束监管（005 融合 US5 / Damodaran 层）

对应师叔 claw-quant 的 Damodaran 横切监管：组合构建时施加 7 类横切约束，
超限候选被截断/标记并记录理由，防止单一暴露失控。
"""

from typing import Dict, List, Optional

DEFAULT_CONSTRAINTS: Dict[str, float] = {
    "max_single_position": 0.20,          # 1) 单标的暴露上限 20%
    "max_industry_concentration": 0.40,   # 2) 单一行业集中上限 40%
    "max_monthly_turnover": 0.30,         # 3) 月换手上限 30%
    "min_daily_liquidity": 0.0,           # 4) 日成交额下限（0 = 不强制）
    "max_market_cap_billions": 0.0,       # 5) 市值上限（亿元；0 = 不强制）
    "max_valuation_percentile": 1.0,      # 6) 估值分位上限（1.0 = 不强制）
    "min_cash_ratio": 0.05,               # 7) 现金仓位下限 5%
    "max_cash_ratio": 0.95,               # 7) 现金仓位上限 95%
}


def apply_constraints(
    candidates: List[dict],
    constraints: Optional[Dict[str, float]] = None,
    industry_of: Optional[Dict[str, str]] = None,
    liquidity_of: Optional[Dict[str, float]] = None,
    market_cap_of: Optional[Dict[str, float]] = None,
    valuation_pct_of: Optional[Dict[str, float]] = None,
    turnover_of: Optional[Dict[str, float]] = None,
) -> dict:
    """对候选组合施加 7 类约束。

    candidates: [{"code": ..., "weight": ...}, ...]（weight 为 0-1 占比）
    返回 {"adjusted": [...], "violations": [...], "constraints_used": [...]}。
    超限的单标的权重被截断到上限；其余超限项被标记 _flagged + _flag_reason；
    全部通过时无副作用。
    """
    cfg = {**DEFAULT_CONSTRAINTS, **(constraints or {})}
    adjusted = [dict(c) for c in candidates]
    violations: List[dict] = []

    # 1) 单标的暴露上限（截断）
    max_pos = cfg["max_single_position"]
    for item in adjusted:
        w = float(item.get("weight", 0.0))
        if w > max_pos:
            violations.append({
                "type": "single_position",
                "code": item["code"],
                "limit": max_pos,
                "original": w,
                "adjusted": max_pos,
            })
            item["weight"] = max_pos
            item["_truncated"] = True

    # 2) 行业集中上限（标记）
    if industry_of and cfg["max_industry_concentration"] < 1.0:
        ind_w: Dict[str, float] = {}
        for item in adjusted:
            ind = industry_of.get(item["code"], "unknown")
            ind_w[ind] = ind_w.get(ind, 0.0) + float(item.get("weight", 0.0))
        for ind, w in ind_w.items():
            if w > cfg["max_industry_concentration"]:
                violations.append({
                    "type": "industry_concentration",
                    "industry": ind,
                    "limit": cfg["max_industry_concentration"],
                    "actual": round(w, 4),
                })
                for item in adjusted:
                    if industry_of.get(item["code"]) == ind:
                        item["_flagged"] = True
                        item["_flag_reason"] = f"行业 {ind} 集中度超限"

    # 3) 换手上限（标记）
    if turnover_of and cfg["max_monthly_turnover"] < 1.0:
        for item in adjusted:
            t = turnover_of.get(item["code"])
            if t is not None and t > cfg["max_monthly_turnover"]:
                violations.append({
                    "type": "turnover",
                    "code": item["code"],
                    "limit": cfg["max_monthly_turnover"],
                    "actual": t,
                })
                item["_flagged"] = True
                item["_flag_reason"] = "月度换手超限"

    # 4) 流动性下限（标记）
    if liquidity_of and cfg["min_daily_liquidity"] > 0:
        for item in adjusted:
            liq = liquidity_of.get(item["code"], 0.0)
            if liq < cfg["min_daily_liquidity"]:
                violations.append({
                    "type": "liquidity",
                    "code": item["code"],
                    "limit": cfg["min_daily_liquidity"],
                    "actual": liq,
                })
                item["_flagged"] = True
                item["_flag_reason"] = "流动性低于下限"

    # 5) 市值上限（标记）
    if market_cap_of and cfg["max_market_cap_billions"] > 0:
        for item in adjusted:
            mc = market_cap_of.get(item["code"])
            if mc is not None and mc > cfg["max_market_cap_billions"]:
                violations.append({
                    "type": "market_cap",
                    "code": item["code"],
                    "limit": cfg["max_market_cap_billions"],
                    "actual": mc,
                })
                item["_flagged"] = True
                item["_flag_reason"] = "市值超上限"

    # 6) 估值分位上限（标记）
    if valuation_pct_of and cfg["max_valuation_percentile"] < 1.0:
        for item in adjusted:
            vp = valuation_pct_of.get(item["code"])
            if vp is not None and vp > cfg["max_valuation_percentile"]:
                violations.append({
                    "type": "valuation",
                    "code": item["code"],
                    "limit": cfg["max_valuation_percentile"],
                    "actual": vp,
                })
                item["_flagged"] = True
                item["_flag_reason"] = "估值分位超上限"

    # 7) 现金仓位边界（组合级）
    total_weight = sum(float(item.get("weight", 0.0)) for item in adjusted)
    cash_ratio = 1.0 - total_weight
    if cash_ratio < cfg["min_cash_ratio"] or cash_ratio > cfg["max_cash_ratio"]:
        violations.append({
            "type": "cash_ratio",
            "limit": [cfg["min_cash_ratio"], cfg["max_cash_ratio"]],
            "actual": round(cash_ratio, 4),
        })

    return {"adjusted": adjusted, "violations": violations, "constraints_used": sorted(cfg)}
