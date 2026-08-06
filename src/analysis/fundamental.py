# fundamental.py —— 基本面（财务面）分析：数据抓取、四维度评分、辩证解读
#
# 框架源自用户研究成果（会计学大作业2.pdf）：
#   从资产端、负债端、权益端交叉验证，同一指标在扩张期/收缩期解读相反。
# 四个维度：资产质量、负债安全、盈利质量、现金健康。
# 纯规则引擎，不依赖任何 LLM API。
#
# 用法：
#   from analysis.fundamental import FundamentalAnalyzer
#   analyzer = FundamentalAnalyzer()
#   result = analyzer.analyze(code, name, category)

import logging
import time
import traceback
from typing import Optional

import akshare as ak
import pandas as pd

from .fundamental_config import (
    FUNDAMENTAL_WEIGHTS,
    ASSET_CONFIG,
    LIABILITY_CONFIG,
    PROFIT_CONFIG,
    CASH_CONFIG,
    CYCLE_LOOKBACK_DAYS,
    CYCLE_MIN_OBSERVATIONS,
    CYCLE_EXPANSION_THRESHOLD,
    CYCLE_CONTRACTION_THRESHOLD,
    FINANCIAL_CATEGORIES,
    BASELINE_SCORE,
    SCORE_MAX,
)

logger = logging.getLogger("stock-dashboard.fundamental")


# ============================================================
# 1. 数据抓取
# ============================================================

def _exchange_prefix(code: str) -> str:
    """根据代码前缀返回交易所前缀（东方财富接口需要）。"""
    if code.startswith(("5", "6", "9", "688")):
        return "SH"
    return "SZ"


def _safe_fetch(fn, *args, **kwargs) -> Optional[pd.DataFrame]:
    """包装抓取调用，失败返回 None 并记录日志。"""
    try:
        df = fn(*args, **kwargs)
        if df is None or df.empty:
            return None
        return df
    except Exception:
        logger.warning("财务数据抓取失败: %s", traceback.format_exc())
        return None


def fetch_balance_sheet(code: str) -> Optional[pd.DataFrame]:
    """资产负债表（东方财富，按报告期）。"""
    return _safe_fetch(ak.stock_balance_sheet_by_report_em, symbol=_exchange_prefix(code) + code)


def fetch_profit_sheet(code: str) -> Optional[pd.DataFrame]:
    """利润表（东方财富，按报告期）。"""
    return _safe_fetch(ak.stock_profit_sheet_by_report_em, symbol=_exchange_prefix(code) + code)


def fetch_cash_flow(code: str) -> Optional[pd.DataFrame]:
    """现金流量表（东方财富，按报告期）。"""
    return _safe_fetch(ak.stock_cash_flow_sheet_by_report_em, symbol=_exchange_prefix(code) + code)


def _latest_row(df: pd.DataFrame) -> pd.Series:
    """取最新报告期的一行（接口已按日期倒序）。"""
    return df.iloc[0] if len(df) > 0 else None


def _val(row, col: str) -> Optional[float]:
    """安全取值：NaN / 缺失 / 非数值 → None。"""
    if row is None or col not in row.index:
        return None
    v = row[col]
    try:
        f = float(v)
        if pd.isna(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


# ============================================================
# 2. 指标计算
# ============================================================

def _safe_div(num, den) -> Optional[float]:
    if num is None or den is None or den == 0:
        return None
    return num / den


class FundamentalMetrics:
    """一次分析所需的全部财务指标（跨三张表）。"""

    def __init__(self, balance: pd.DataFrame, profit: pd.DataFrame, cashflow: pd.DataFrame):
        bl = _latest_row(balance)
        pl = _latest_row(profit)
        cf = _latest_row(cashflow)

        # ---- 资产负债表 ----
        self.total_assets = _val(bl, "TOTAL_ASSETS")
        self.total_assets_yoy = _val(bl, "TOTAL_ASSETS_YOY")
        self.inventory = _val(bl, "INVENTORY")
        self.prepayment = _val(bl, "PREPAYMENT")
        self.receivable = _val(bl, "ACCOUNTS_RECE")
        self.note_receivable = _val(bl, "NOTE_ACCOUNTS_RECE")
        self.goodwill = _val(bl, "GOODWILL")
        self.total_liabilities = _val(bl, "TOTAL_LIABILITIES")
        self.total_equity = _val(bl, "TOTAL_EQUITY")
        self.total_parent_equity = _val(bl, "TOTAL_PARENT_EQUITY")
        self.short_loan = _val(bl, "SHORT_LOAN")
        self.short_fin_payable = _val(bl, "SHORT_FIN_PAYABLE")
        self.noncurrent_liab_1year = _val(bl, "NONCURRENT_LIAB_1YEAR")
        self.long_loan = _val(bl, "LONG_LOAN")
        self.bond_payable = _val(bl, "BOND_PAYABLE")
        self.capital_reserve = _val(bl, "CAPITAL_RESERVE")
        self.unassigned_profit = _val(bl, "UNASSIGN_RPOFIT")
        self.report_date = str(bl.get("REPORT_DATE", "")).split(" ")[0] if bl is not None else ""

        # ---- 利润表 ----
        self.operate_income = _val(pl, "TOTAL_OPERATE_INCOME") or _val(pl, "OPERATE_INCOME")
        self.operate_cost = _val(pl, "TOTAL_OPERATE_COST") or _val(pl, "OPERATE_COST")
        self.net_profit = _val(pl, "NETPROFIT") or _val(pl, "PARENT_NETPROFIT")
        self.parent_net_profit = _val(pl, "PARENT_NETPROFIT")
        self.deduct_parent_netprofit = _val(pl, "DEDUCT_PARENT_NETPROFIT")
        self.netprofit_yoy = _val(pl, "NETPROFIT_YOY") or _val(pl, "PARENT_NETPROFIT_YOY")

        # ---- 现金流量表 ----
        self.ocf = _val(cf, "NETCASH_OPERATE")
        self.icf = _val(cf, "NETCASH_INVEST")
        self.fcf = _val(cf, "NETCASH_FINANCE")

        # ---- 派生比率 ----
        self.debt_ratio = _safe_div(self.total_liabilities, self.total_assets)
        self.inventory_prepay_ratio = _safe_div(
            (self.inventory or 0) + (self.prepayment or 0), self.total_assets
        )
        self.receivable_revenue = _safe_div(
            (self.receivable or 0) + (self.note_receivable or 0), self.operate_income
        )
        self.goodwill_equity = _safe_div(self.goodwill, self.total_parent_equity)
        self.roe = _safe_div(self.parent_net_profit, self.total_parent_equity)
        self.gross_margin = (
            _safe_div(self.operate_income - self.operate_cost, self.operate_income) * 100.0
            if self.operate_income and self.operate_cost is not None
            else None
        )
        self.deduct_ratio = _safe_div(self.deduct_parent_netprofit, self.parent_net_profit)
        self.ocf_np_ratio = _safe_div(self.ocf, self.parent_net_profit)
        self.retained_profit_equity = _safe_div(
            self.unassigned_profit, self.total_parent_equity
        )

        # 短期有息负债 = 短期借款 + 一年内到期非流动负债 + 交易性金融负债（简化）
        self.short_debt = (
            (self.short_loan or 0) + (self.noncurrent_liab_1year or 0) + (self.short_fin_payable or 0)
        ) or None
        self.short_debt_ratio = _safe_div(self.short_debt, self.total_liabilities)
        self.financing_debt = _safe_div(self.fcf, self.total_liabilities)

        # 资产负债率同比变化（百分点），用最新两期
        self.debt_ratio_prev = None
        if len(balance) >= 2:
            prev = balance.iloc[1]
            prev_liab = _val(prev, "TOTAL_LIABILITIES")
            prev_asset = _val(prev, "TOTAL_ASSETS")
            self.debt_ratio_prev = _safe_div(prev_liab, prev_asset)

        self.valid = any(v is not None for v in [
            self.total_assets, self.net_profit, self.total_liabilities
        ])


# ============================================================
# 3. 分维度评分
# ============================================================

def _interpolate(
    value: float,
    lower_value: float,
    upper_value: float,
    lower_result: float,
    upper_result: float,
) -> float:
    """将数值线性映射到区间结果，并在边界外截断。"""
    if upper_value <= lower_value:
        raise ValueError("upper_value must be greater than lower_value")
    progress = (value - lower_value) / (upper_value - lower_value)
    progress = max(0.0, min(1.0, progress))
    return lower_result + (upper_result - lower_result) * progress


def _reason(rtype: str, title: str, detail: str, contribution: float = 0.0) -> dict:
    """构造 reason dict（与现有 scoring.py 的 reason 格式一致）。"""
    return {"type": rtype, "title": title, "detail": detail, "contribution": round(contribution, 1)}


def score_asset_quality(m: FundamentalMetrics, cycle_phase: str) -> dict:
    """资产质量：规模扩张 + 周期敏感资产 + 回款效率。"""
    score = BASELINE_SCORE
    reasons = []

    # 1. 总资产 YoY：理想区间 [10%, 50%]
    if m.total_assets_yoy is not None:
        yoy = m.total_assets_yoy
        if ASSET_CONFIG["asset_yoy_best_min"] <= yoy <= ASSET_CONFIG["asset_yoy_best_max"]:
            score += 10.0
            reasons.append(_reason("positive", "资产稳步扩张", f"总资产同比 +{yoy:.1f}%，处于健康扩张区间。", 10.0))
        elif yoy > ASSET_CONFIG["asset_yoy_best_max"]:
            if cycle_phase == "expansion":
                score += 4.0
                reasons.append(_reason(
                    "positive",
                    "顺周期扩张",
                    f"总资产同比 +{yoy:.1f}%，行业扩张阶段的激进投入可能转化为供给与成本优势。",
                    4.0,
                ))
            else:
                pen = min(
                    ASSET_CONFIG["asset_yoy_excess_penalty"],
                    (yoy - ASSET_CONFIG["asset_yoy_best_max"]) * 0.5,
                )
                score -= pen
                reasons.append(_reason(
                    "warning",
                    "资产扩张过快",
                    f"总资产同比 +{yoy:.1f}%，尚未确认行业扩张时，需警惕激进扩张伴随的减值风险。",
                    -pen,
                ))
        else:
            score -= 8.0
            reasons.append(_reason("negative", "资产增长乏力", f"总资产同比 +{yoy:.1f}%，规模停滞。", -8.0))

    # 2. 存货+预付 / 总资产：PDF 的核心辩证逻辑。
    #    高占用只在已验证的行业扩张期可视作战略储备；不能用宽基指数替代。
    if m.inventory_prepay_ratio is not None:
        ratio = m.inventory_prepay_ratio
        if ratio > ASSET_CONFIG["inventory_prepay_ratio_watch"]:
            exposure = _interpolate(
                ratio,
                ASSET_CONFIG["inventory_prepay_ratio_watch"],
                ASSET_CONFIG["inventory_prepay_ratio_high"],
                0.0,
                1.0,
            )
            if cycle_phase == "expansion":
                bonus = ASSET_CONFIG["strategic_reserve_bonus"] * exposure
                score += bonus
                reasons.append(_reason(
                    "positive",
                    "顺周期战略储备",
                    f"存货+预付占总资产 {ratio*100:.1f}%；已验证行业扩张，备货与预付可能带来供给和成本优势。",
                    bonus,
                ))
            elif cycle_phase == "contraction":
                pen = ASSET_CONFIG["contraction_cycle_penalty"] * exposure
                score -= pen
                reasons.append(_reason(
                    "negative",
                    "收缩期高周期敞口",
                    f"存货+预付占总资产 {ratio*100:.1f}%；行业收缩时，高成本库存和预付款可能触发减值及毛利率压力。",
                    -pen,
                ))
            elif cycle_phase == "neutral":
                pen = ASSET_CONFIG["neutral_cycle_penalty"] * exposure
                score -= pen
                reasons.append(_reason(
                    "warning",
                    "高周期敞口待观察",
                    f"存货+预付占总资产 {ratio*100:.1f}%；行业未确认扩张，高占用仍有跌价与成本刚性风险。",
                    -pen,
                ))
            else:
                reasons.append(_reason(
                    "warning",
                    "周期数据不足",
                    f"存货+预付占总资产 {ratio*100:.1f}%；未取得真实行业周期数据，不将其计为利好。",
                    0.0,
                ))
        else:
            score += 5.0
            reasons.append(_reason("positive", "存货结构健康", f"存货+预付占总资产 {ratio*100:.1f}%，风险可控。", 5.0))

    # 3. 应收账款 / 营收：回款风险
    if m.receivable_revenue is not None:
        ratio = m.receivable_revenue
        if ratio > ASSET_CONFIG["receivable_revenue_warn"]:
            pen = _interpolate(
                ratio,
                ASSET_CONFIG["receivable_revenue_warn"],
                ASSET_CONFIG["receivable_revenue_max"],
                0.0,
                ASSET_CONFIG["receivable_penalty"],
            )
            score -= pen
            reasons.append(_reason("negative", "应收占比偏高", f"应收账款/营收 {ratio*100:.1f}%，现金回收存在时滞。", -pen))
        else:
            score += 3.0
            reasons.append(_reason("positive", "回款效率良好", f"应收账款/营收 {ratio*100:.1f}%，回款健康。", 3.0))

    # 4. 商誉 / 净资产：减值风险
    if m.goodwill_equity is not None:
        ratio = m.goodwill_equity
        if ratio > ASSET_CONFIG["goodwill_equity_warn"]:
            pen = _interpolate(
                ratio,
                ASSET_CONFIG["goodwill_equity_warn"],
                ASSET_CONFIG["goodwill_equity_max"],
                0.0,
                ASSET_CONFIG["goodwill_penalty"],
            )
            score -= pen
            reasons.append(_reason("warning", "商誉占比偏高", f"商誉/净资产 {ratio*100:.1f}%，存在商誉减值隐患。", -pen))

    return {"score": round(max(0, min(SCORE_MAX, score)), 1), "reasons": reasons[:5]}


def score_liability_safety(m: FundamentalMetrics) -> dict:
    """负债安全：杠杆水平 + 期限结构 + 变化方向。"""
    score = BASELINE_SCORE
    reasons = []

    # 1. 资产负债率
    if m.debt_ratio is not None:
        ratio = m.debt_ratio * 100.0
        if m.debt_ratio <= LIABILITY_CONFIG["debt_ratio_optimal"]:
            score += 10.0
            reasons.append(_reason("positive", "杠杆适中", f"资产负债率 {ratio:.1f}%，财务结构稳健。", 10.0))
        elif m.debt_ratio >= LIABILITY_CONFIG["debt_ratio_high"]:
            pen = LIABILITY_CONFIG["debt_ratio_penalty"]
            score -= pen
            reasons.append(_reason("negative", "杠杆偏高", f"资产负债率 {ratio:.1f}%，债务压力大。", -pen))
        else:
            pen = _interpolate(
                ratio,
                LIABILITY_CONFIG["debt_ratio_optimal"] * 100.0,
                LIABILITY_CONFIG["debt_ratio_high"] * 100.0,
                0.0,
                LIABILITY_CONFIG["debt_ratio_penalty"],
            )
            score -= pen * 0.5
            reasons.append(_reason("warning", "杠杆中等", f"资产负债率 {ratio:.1f}%，处于中间区间。", -pen * 0.5))

    # 2. 短期有息负债 / 总负债
    if m.short_debt_ratio is not None:
        ratio = m.short_debt_ratio
        if ratio > LIABILITY_CONFIG["short_debt_ratio_warn"]:
            pen = _interpolate(
                ratio,
                LIABILITY_CONFIG["short_debt_ratio_warn"],
                LIABILITY_CONFIG["short_debt_ratio_max"],
                0.0,
                LIABILITY_CONFIG["short_debt_penalty"],
            )
            score -= pen
            reasons.append(_reason("negative", "短债占比高", f"短期有息负债占总负债 {ratio*100:.1f}%，流动性压力大。", -pen))
        else:
            score += 3.0
            reasons.append(_reason("positive", "债务期限合理", f"短期有息负债占总负债 {ratio*100:.1f}%，期限结构良好。", 3.0))

    # 3. 资产负债率同比变化
    if m.debt_ratio is not None and m.debt_ratio_prev is not None:
        delta_pp = (m.debt_ratio - m.debt_ratio_prev) * 100.0
        threshold = LIABILITY_CONFIG["debt_ratio_yoy_threshold_pp"]
        if delta_pp > threshold:
            score -= LIABILITY_CONFIG["debt_ratio_yoy_increase_penalty"]
            reasons.append(_reason("negative", "杠杆上升", f"资产负债率同比上升 {delta_pp:.1f}pp，杠杆快速累积。", -LIABILITY_CONFIG["debt_ratio_yoy_increase_penalty"]))
        elif delta_pp < -threshold:
            score += LIABILITY_CONFIG["debt_ratio_yoy_decrease_bonus"]
            reasons.append(_reason("positive", "杠杆下降", f"资产负债率同比下降 {abs(delta_pp):.1f}pp，去杠杆改善。", LIABILITY_CONFIG["debt_ratio_yoy_decrease_bonus"]))

    return {"score": round(max(0, min(SCORE_MAX, score)), 1), "reasons": reasons[:5]}


def score_profit_quality(m: FundamentalMetrics) -> dict:
    """盈利质量：ROE + 成长性 + 盈利真实性。"""
    score = BASELINE_SCORE
    reasons = []

    # 1. ROE（百分数）
    if m.roe is not None:
        roe = m.roe * 100.0
        if roe >= PROFIT_CONFIG["roe_optimal"]:
            score += 12.0
            reasons.append(_reason("positive", "ROE 优秀", f"净资产收益率 {roe:.1f}%，股东回报突出。", 12.0))
        elif roe >= PROFIT_CONFIG["roe_mid"]:
            score += 5.0
            reasons.append(_reason("positive", "ROE 良好", f"净资产收益率 {roe:.1f}%，盈利水平正常。", 5.0))
        else:
            pen = PROFIT_CONFIG["roe_penalty"]
            score -= pen
            reasons.append(_reason("negative", "ROE 偏低", f"净资产收益率 {roe:.1f}%，盈利能力弱。", -pen))

    # 2. 净利润同比
    if m.netprofit_yoy is not None:
        yoy = m.netprofit_yoy
        if yoy > 0:
            score += PROFIT_CONFIG["netprofit_yoy_positive_bonus"]
            reasons.append(_reason("positive", "利润高增", f"净利润同比 +{yoy:.1f}%，盈利动能强。", PROFIT_CONFIG["netprofit_yoy_positive_bonus"]))
        else:
            score -= PROFIT_CONFIG["netprofit_yoy_negative_penalty"]
            reasons.append(_reason("negative", "利润下滑", f"净利润同比 {yoy:.1f}%，盈利收缩。", -PROFIT_CONFIG["netprofit_yoy_negative_penalty"]))

    # 3. 扣非 / 归母净利润
    if m.deduct_ratio is not None:
        ratio = m.deduct_ratio
        if ratio < PROFIT_CONFIG["deduct_ratio_warn"]:
            score -= PROFIT_CONFIG["deduct_ratio_penalty"]
            reasons.append(_reason("warning", "依赖非经常损益", f"扣非净利润占归母净利润 {ratio*100:.1f}%，利润含金量低。", -PROFIT_CONFIG["deduct_ratio_penalty"]))
        else:
            score += 3.0
            reasons.append(_reason("positive", "利润含金量高", f"扣非净利润占归母净利润 {ratio*100:.1f}%，主业盈利扎实。", 3.0))

    # 4. 毛利率下限
    if m.gross_margin is not None:
        gm = m.gross_margin
        if gm < PROFIT_CONFIG["gross_margin_warn"]:
            score -= PROFIT_CONFIG["gross_margin_penalty"]
            reasons.append(_reason("negative", "毛利率偏低", f"毛利率 {gm:.1f}%，产品竞争力或成本控制存疑。", -PROFIT_CONFIG["gross_margin_penalty"]))

    # 5. 未分配利润 / 归母权益：对应 PDF 中“利润沉淀形成资本垫”的观察。
    if m.retained_profit_equity is not None:
        ratio = m.retained_profit_equity
        if ratio >= PROFIT_CONFIG["retained_profit_equity_good"]:
            bonus = PROFIT_CONFIG["retained_profit_equity_bonus"]
            score += bonus
            reasons.append(_reason(
                "positive",
                "利润留存形成资本垫",
                f"未分配利润/归母权益 {ratio*100:.1f}%，内生资本积累较充分。",
                bonus,
            ))
        elif ratio < 0:
            pen = PROFIT_CONFIG["retained_profit_equity_negative_penalty"]
            score -= pen
            reasons.append(_reason(
                "negative",
                "累计未弥补亏损",
                f"未分配利润/归母权益 {ratio*100:.1f}%，历史亏损削弱资本缓冲。",
                -pen,
            ))

    return {"score": round(max(0, min(SCORE_MAX, score)), 1), "reasons": reasons[:5]}


def score_cash_health(m: FundamentalMetrics) -> dict:
    """现金健康：经营现金流支撑 + 融资依赖度。"""
    score = BASELINE_SCORE
    reasons = []

    # 1. 经营现金流 / 净利润
    if m.ocf_np_ratio is not None:
        ratio = m.ocf_np_ratio
        if ratio >= CASH_CONFIG["ocf_np_ratio_optimal"]:
            score += 12.0
            reasons.append(_reason("positive", "现金流强劲", f"经营现金流/净利润 {ratio:.2f}，利润有真金白银支撑。", 12.0))
        elif ratio >= CASH_CONFIG["ocf_np_ratio_min"]:
            pen = _interpolate(
                ratio,
                CASH_CONFIG["ocf_np_ratio_min"],
                CASH_CONFIG["ocf_np_ratio_optimal"],
                CASH_CONFIG["ocf_np_ratio_penalty"],
                0.0,
            )
            score -= pen
            reasons.append(_reason("warning", "现金流偏弱", f"经营现金流/净利润 {ratio:.2f}，利润兑现能力一般。", -pen))
        else:
            score -= CASH_CONFIG["ocf_np_ratio_penalty"] + CASH_CONFIG["ocf_negative_penalty"]
            reasons.append(_reason("negative", "经营现金流为负", f"经营现金流/净利润 {ratio:.2f}，账面利润缺乏现金支撑，警惕应收与存货占款。", -(CASH_CONFIG["ocf_np_ratio_penalty"] + CASH_CONFIG["ocf_negative_penalty"])))

    # 2. 筹资现金流 / 总负债（对外部输血依赖）
    if m.financing_debt is not None:
        ratio = m.financing_debt
        if ratio > CASH_CONFIG["financing_debt_warn"]:
            pen = _interpolate(
                ratio,
                CASH_CONFIG["financing_debt_warn"],
                CASH_CONFIG["financing_debt_max"],
                0.0,
                CASH_CONFIG["financing_debt_penalty"],
            )
            score -= pen
            reasons.append(_reason("warning", "依赖外部融资", f"筹资现金流占总负债 {ratio*100:.1f}%，依赖再融资支撑扩张。", -pen))
        else:
            score += 3.0
            reasons.append(_reason("positive", "融资依赖度低", f"筹资现金流占总负债 {ratio*100:.1f}%，扩张主要靠内生。", 3.0))

    return {"score": round(max(0, min(SCORE_MAX, score)), 1), "reasons": reasons[:5]}


# ============================================================
# 4. 周期判断（辩证逻辑核心）
# ============================================================

def judge_cycle(industry_close: Optional[pd.Series]) -> tuple[str, Optional[float], int]:
    """
    判断行业当前所处周期阶段。

    Returns:
        (cycle_phase, industry_return_pct, observation_days)
        cycle_phase: expansion | contraction | neutral | unknown
        industry_return_pct: 行业近 N 日涨幅（%），无法计算时为 None
        observation_days: 实际使用的行业交易日数量
    """
    if industry_close is None:
        return "unknown", None, 0
    valid = industry_close.dropna()
    if len(valid) < CYCLE_MIN_OBSERVATIONS:
        return "unknown", None, len(valid)
    lookback = min(CYCLE_LOOKBACK_DAYS, len(valid))
    first = valid.iloc[-lookback]
    last = valid.iloc[-1]
    if first <= 0:
        return "unknown", None, lookback
    ret_pct = (last / first - 1.0) * 100.0
    rounded_return = round(ret_pct, 2)
    if ret_pct >= CYCLE_EXPANSION_THRESHOLD:
        return "expansion", rounded_return, lookback
    if ret_pct <= CYCLE_CONTRACTION_THRESHOLD:
        return "contraction", rounded_return, lookback
    return "neutral", rounded_return, lookback


# ============================================================
# 5. 辩证解读文本（规则模板）
# ============================================================

def build_dual_view(
    m: FundamentalMetrics,
    cycle_phase: str,
    industry_ret: Optional[float],
    observation_days: int,
) -> dict:
    """生成'两面解读'文本：正面逻辑 + 风险警示。"""
    positive_parts = []
    negative_parts = []

    # 正面
    if m.total_assets_yoy is not None and m.total_assets_yoy > 10:
        positive_parts.append(f"总资产同比 +{m.total_assets_yoy:.1f}%，规模扩张有力")
    if m.inventory_prepay_ratio is not None and cycle_phase == "expansion":
        positive_parts.append(f"存货+预付占总资产 {m.inventory_prepay_ratio*100:.1f}%，在扩张期是抢占先机的战略储备")
    if m.roe is not None and m.roe * 100 >= 15:
        positive_parts.append(f"ROE {m.roe*100:.1f}%，股东回报出色")
    if m.netprofit_yoy is not None and m.netprofit_yoy > 0:
        positive_parts.append(f"净利润同比 +{m.netprofit_yoy:.1f}%")
    if m.ocf_np_ratio is not None and m.ocf_np_ratio >= 1:
        positive_parts.append(f"经营现金流/净利润 {m.ocf_np_ratio:.2f}，利润含金量高")

    # 反面
    if m.inventory_prepay_ratio is not None and m.inventory_prepay_ratio > ASSET_CONFIG["inventory_prepay_ratio_watch"]:
        if cycle_phase == "expansion":
            negative_parts.append(f"存货+预付占总资产 {m.inventory_prepay_ratio*100:.1f}%，一旦周期反转将面临巨额跌价减值")
        elif cycle_phase == "contraction":
            negative_parts.append(f"存货+预付占总资产 {m.inventory_prepay_ratio*100:.1f}%，收缩期高库存是'减值炸弹'")
        elif cycle_phase == "neutral":
            negative_parts.append(f"存货+预付占总资产 {m.inventory_prepay_ratio*100:.1f}%，行业未确认扩张，需防范价格与毛利率反转")
        else:
            negative_parts.append(f"存货+预付占总资产 {m.inventory_prepay_ratio*100:.1f}%，缺少行业周期数据，不能判断备货是否受益")
    if m.debt_ratio is not None and m.debt_ratio > 0.60:
        negative_parts.append(f"资产负债率 {m.debt_ratio*100:.1f}%，杠杆偏高")
    if m.ocf_np_ratio is not None and m.ocf_np_ratio < 1:
        negative_parts.append(f"经营现金流/净利润 {m.ocf_np_ratio:.2f}，利润兑现存疑")
    if m.receivable_revenue is not None and m.receivable_revenue > 0.30:
        negative_parts.append(f"应收账款/营收 {m.receivable_revenue*100:.1f}%，现金回收存在时滞")
    if m.financing_debt is not None and m.financing_debt > 0.30:
        negative_parts.append(f"筹资现金流占总负债 {m.financing_debt*100:.1f}%，依赖外部输血")

    phase_labels = {
        "expansion": "扩张期",
        "contraction": "收缩期",
        "neutral": "中性期",
        "unknown": "周期未知",
    }
    cycle_note = ""
    if industry_ret is not None:
        cycle_note = (
            f"（行业近{observation_days}日 {'上涨' if industry_ret >= 0 else '下跌'} "
            f"{abs(industry_ret):.1f}%，判断为{phase_labels[cycle_phase]}）"
        )
    else:
        cycle_note = "（未取得足够的真实行业周期数据，高库存不计为利好）"

    return {
        "positive_view": "；".join(positive_parts) if positive_parts else "未发现明显扩张逻辑",
        "negative_view": "；".join(negative_parts) if negative_parts else "暂未发现显著风险",
        "cycle_phase": cycle_phase,
        "industry_return_60d_pct": industry_ret,
        "cycle_observation_days": observation_days,
        "cycle_note": cycle_note,
    }


# ============================================================
# 6. 主入口
# ============================================================

class FundamentalAnalyzer:
    """基本面分析器：抓取三张表 → 计算指标 → 四维度评分 → 综合分 + 辩证解读。"""

    def __init__(self, industry_provider=None):
        self._industry_provider = industry_provider

    def analyze(
        self,
        code: str,
        name: str,
        category: str = "",
        industry_close: Optional[pd.Series] = None,
    ) -> Optional[dict]:
        """
        完整基本面分析。

        industry_close: 行业收盘价序列（来自 IndustryProvider），用于周期判断。
        失败返回 None（不阻断主流程）。
        """
        logger.info("基本面分析 %s(%s) ...", name, code)

        if category.strip() in FINANCIAL_CATEGORIES:
            logger.info("%s(%s) 属于金融机构，不套用实体企业存货周期模型", name, code)
            return None

        balance = fetch_balance_sheet(code)
        profit = fetch_profit_sheet(code)
        cashflow = fetch_cash_flow(code)

        if balance is None or profit is None or cashflow is None:
            logger.warning("%s(%s) 财务三表抓取不完整，跳过基本面分析", name, code)
            return None

        m = FundamentalMetrics(balance, profit, cashflow)
        if not m.valid:
            logger.warning("%s(%s) 财务指标为空，跳过", name, code)
            return None

        # 周期判断
        cycle_phase, industry_ret, observation_days = judge_cycle(industry_close)

        # 四维度评分
        asset = score_asset_quality(m, cycle_phase)
        liab = score_liability_safety(m)
        profit_score = score_profit_quality(m)
        cash = score_cash_health(m)

        # 综合分
        composite = (
            FUNDAMENTAL_WEIGHTS["asset_quality"] * asset["score"]
            + FUNDAMENTAL_WEIGHTS["liability_safety"] * liab["score"]
            + FUNDAMENTAL_WEIGHTS["profit_quality"] * profit_score["score"]
            + FUNDAMENTAL_WEIGHTS["cash_health"] * cash["score"]
        )

        # 辩证解读
        dual_view = build_dual_view(
            m,
            cycle_phase,
            industry_ret,
            observation_days,
        )

        result = {
            "schema_version": "2.0",
            "report_date": m.report_date,
            "score": round(composite, 1),
            "dimensions": {
                "asset_quality": asset["score"],
                "liability_safety": liab["score"],
                "profit_quality": profit_score["score"],
                "cash_health": cash["score"],
            },
            "weights": FUNDAMENTAL_WEIGHTS,
            "metrics": {
                "total_assets": m.total_assets,
                "total_assets_yoy": m.total_assets_yoy,
                "inventory": m.inventory,
                "prepayment": m.prepayment,
                "receivable": m.receivable,
                "inventory_prepay_ratio": m.inventory_prepay_ratio,
                "receivable_revenue": m.receivable_revenue,
                "goodwill_equity": m.goodwill_equity,
                "debt_ratio": m.debt_ratio,
                "short_debt_ratio": m.short_debt_ratio,
                "roe": m.roe,
                "gross_margin": m.gross_margin,
                "deduct_ratio": m.deduct_ratio,
                "netprofit_yoy": m.netprofit_yoy,
                "ocf_np_ratio": m.ocf_np_ratio,
                "financing_debt": m.financing_debt,
                "retained_profit_equity": m.retained_profit_equity,
            },
            "reasons": {
                "asset_quality": asset["reasons"],
                "liability_safety": liab["reasons"],
                "profit_quality": profit_score["reasons"],
                "cash_health": cash["reasons"],
            },
            "dual_view": dual_view,
        }
        logger.info("%s(%s) 基本面评分 %.1f", name, code, result["score"])
        return result


# 单只快速入口
def analyze_fundamental(
    code: str,
    name: str,
    category: str = "",
    industry_close: Optional[pd.Series] = None,
) -> Optional[dict]:
    return FundamentalAnalyzer().analyze(code, name, category, industry_close)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    code = sys.argv[1] if len(sys.argv) > 1 else "688525"
    result = analyze_fundamental(code, code)
    if result:
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print("分析失败")
