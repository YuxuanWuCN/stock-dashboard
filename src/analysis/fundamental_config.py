# fundamental_config.py —— 基本面评分参数与权重
#
# 所有阈值集中在此，评分逻辑见 fundamental.py。
# 框架来源：用户研究成果《会计学大作业2》中的“资产占用—融资—周期反转”逻辑。
# 除“存货+预付接近总资产 60% 属于高周期敞口”外，其他阈值均为待回测的
# 建模假设，不能理解为研究原文给出的普遍规律。

# ============================================================
# 综合权重（四项合计 = 1.0）
# ============================================================

FUNDAMENTAL_WEIGHTS = {
    "asset_quality":   0.30,   # 资产质量：扩张是否健康
    "liability_safety": 0.25,   # 负债安全：杠杆与流动性
    "profit_quality":  0.25,   # 盈利质量：利润真实性
    "cash_health":     0.20,   # 现金健康：现金流支撑
}

# ============================================================
# 资产质量（Asset Quality）
# ============================================================

ASSET_CONFIG = {
    # 总资产同比增速参考区间（不是 PDF 的直接阈值）
    "asset_yoy_best_min": 10.0,      # 低于此值扣分（增长不足）
    "asset_yoy_best_max": 50.0,      # 高于此值扣分（过快扩张）
    "asset_yoy_excess_penalty": 15.0,  # 超限扣分上限

    # 存货+预付 / 总资产：研究原文明确指出接近 60% 时周期敞口很高。
    # 35% 是用于提前提示的建模假设；60% 是高敞口观察线，而非跨行业通用红线。
    "inventory_prepay_ratio_watch": 0.35,
    "inventory_prepay_ratio_high": 0.60,
    "strategic_reserve_bonus": 8.0,
    "neutral_cycle_penalty": 6.0,
    "contraction_cycle_penalty": 25.0,

    # 应收账款 / 营收 比例（回款风险）
    "receivable_revenue_warn": 0.30,
    "receivable_revenue_max":  0.60,
    "receivable_penalty":      15.0,

    # 商誉 / 净资产 比例（减值风险）
    "goodwill_equity_warn": 0.10,
    "goodwill_equity_max":  0.30,
    "goodwill_penalty":     10.0,
}

# ============================================================
# 负债安全（Liability Safety）
# ============================================================

LIABILITY_CONFIG = {
    # 资产负债率分段（越低越安全）
    "debt_ratio_optimal":  0.40,   # <= 此值满分
    "debt_ratio_mid":      0.60,   # 此值到 0.70 线性下降
    "debt_ratio_high":     0.70,   # >= 此值扣满
    "debt_ratio_penalty":  35.0,   # 最高扣分

    # 短期有息负债 / 总负债（流动性风险，高则危险）
    "short_debt_ratio_warn": 0.60,
    "short_debt_ratio_max":  0.90,
    "short_debt_penalty":    15.0,

    # 资产负债率同比变化：上升扣分，下降加分
    "debt_ratio_yoy_increase_penalty": 10.0,   # 同比上升超过 5pp 扣分
    "debt_ratio_yoy_decrease_bonus":    8.0,   # 同比下降超过 5pp 加分

    # 资产负债率同比变化阈值（百分点）
    "debt_ratio_yoy_threshold_pp": 5.0,
}

# ============================================================
# 盈利质量（Profit Quality）
# ============================================================

PROFIT_CONFIG = {
    # 净资产收益率 ROE 分段（百分数）
    "roe_optimal":  15.0,    # >= 15% 满分
    "roe_mid":      8.0,     # 8%~15% 线性
    "roe_low":      3.0,     # < 3% 扣满
    "roe_penalty":  30.0,

    # 净利润同比增速（百分数）
    "netprofit_yoy_positive_bonus": 10.0,   # 正增长加分
    "netprofit_yoy_negative_penalty": 12.0,  # 负增长扣分

    # 扣非净利润 / 净利润 比例（低于此值说明盈利依赖非经常项）
    "deduct_ratio_warn": 0.70,
    "deduct_ratio_penalty": 12.0,

    # 毛利率（百分数，行业差异大，仅做下限检查）
    "gross_margin_warn": 10.0,
    "gross_margin_penalty": 8.0,

    # 未分配利润 / 归母权益：反映利润留存形成的资本缓冲。
    # 30% 为建模假设；PDF 未提供跨行业的统一阈值。
    "retained_profit_equity_good": 0.30,
    "retained_profit_equity_bonus": 5.0,
    "retained_profit_equity_negative_penalty": 8.0,
}

# ============================================================
# 现金健康（Cash Health）
# ============================================================

CASH_CONFIG = {
    # 经营现金流 / 净利润（>1 利润有现金支撑，<0 非常危险）
    "ocf_np_ratio_optimal": 1.0,     # >= 此值满分
    "ocf_np_ratio_min":     0.0,     # 0~1 线性下降；<0 扣满
    "ocf_np_ratio_penalty": 35.0,

    # 经营现金流为负时的额外扣分
    "ocf_negative_penalty": 10.0,

    # 筹资现金流 / 总负债（过高说明依赖外部输血）
    "financing_debt_warn": 0.30,
    "financing_debt_max":  0.60,
    "financing_debt_penalty": 15.0,
}

# ============================================================
# 周期敏感指标（辩证逻辑：扩张期 vs 收缩期）
# ============================================================

# 行业周期判断：只接受真实行业板块数据，不能以宽基指数代替供需周期。
# 阈值为待回测假设，不是 PDF 的直接结论。
CYCLE_LOOKBACK_DAYS = 60
CYCLE_MIN_OBSERVATIONS = 21
CYCLE_EXPANSION_THRESHOLD = 3.0
CYCLE_CONTRACTION_THRESHOLD = -3.0

# 本研究使用的是实体企业“备货—预付—融资”框架，不适用于金融机构报表。
FINANCIAL_CATEGORIES = frozenset({"银行", "保险", "券商"})

# 基准分
BASELINE_SCORE = 50.0
SCORE_MAX = 100.0

# ============================================================
# 输出权重（技术面 + 基本面 融合）
# ============================================================

# total_score = technical_composite * TECHNICAL_WEIGHT + fundamental * FUNDAMENTAL_WEIGHT
TECHNICAL_WEIGHT = 0.5
FUNDAMENTAL_WEIGHT = 0.5
