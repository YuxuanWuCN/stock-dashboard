# -*- coding: utf-8 -*-
"""src/nowcasting/triangle_validator.py —— Nowcasting 高频证据三角互证与二次减值惩罚 (Week 7)

依据规范：
1. 《StockDashboard v3.0 & Serenity Chokepoint 12-Week Roadmap》Phase II: Week 7
2. 击穿 1-3 个月财报滞后：
   - 宏观先行指标：韩国海关半导体出口额同比/环比 (Korea Customs Export)
   - 中观高频现货价：InSpectrum / TrendForce DRAM/NAND 现货 DXI 指数
   - 微观企业动作：下游预付款项 (Prepayments) 与晶圆采购锁价
3. 二次非对称减值惩罚公式 (Clarification Q3):
   Drift_{GFCA} = -0.5 * (max(0, (P_{prepay} - P_{spot}) / P_{prepay}))^2
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("nowcasting_triangle")


@dataclass
class TriangulationSignal:
    """三角互证信号输出。"""
    ticker: str
    macro_korea_export_yoy: float
    spot_dx_price: float
    lockin_prepay_cost: float
    price_spread_ratio: float  # (P_spot - P_prepay) / P_prepay
    impairment_penalty_drift: float  # GFCA 坐标负漂移惩罚项
    is_impaired: bool  # 现货价是否跌破锁价发生减值
    triangulation_confidence: float  # 0.0 - 1.0 置信度评分
    status_summary: str


class NowcastingTriangleValidator:
    """Nowcasting 宏观-中观-微观三维证据互证器。"""

    def __init__(self, penalty_lambda: float = 0.5):
        self.penalty_lambda = penalty_lambda

    def calculate_impairment_penalty(self, spot_price: float, prepay_cost: float) -> float:
        r"""计算二次非对称减值惩罚项 (Asymmetric Quadratic Impairment Penalty)。
        
        公式:
        Drift = -\lambda \cdot \left(\max\left(0, \frac{P_{\text{prepay}} - P_{\text{spot}}}{P_{\text{prepay}}}\right)\right)^2
        """
        if prepay_cost <= 0.0 or spot_price >= prepay_cost:
            return 0.0

        drop_ratio = (prepay_cost - spot_price) / prepay_cost
        penalty = -self.penalty_lambda * (drop_ratio ** 2)
        return float(np.clip(penalty, -1.0, 0.0))

    def evaluate_asset_nowcasting(
        self,
        ticker: str,
        korea_customs_export_yoy: float,
        spot_dxi_price: float,
        lockin_prepay_cost: float,
        downstream_capex_growth: float = 0.35
    ) -> TriangulationSignal:
        """多源证据三角互证评估。"""
        spread_ratio = (spot_dxi_price - lockin_prepay_cost) / (lockin_prepay_cost + 1e-8)
        penalty_drift = self.calculate_impairment_penalty(spot_dxi_price, lockin_prepay_cost)
        is_impaired = (spot_dxi_price < lockin_prepay_cost)

        # 综合置信度推导
        macro_score = np.clip((korea_customs_export_yoy + 0.20) / 0.80, 0.0, 1.0)
        micro_score = 1.0 if not is_impaired else max(0.0, 1.0 - abs(spread_ratio) * 2)
        confidence = float(0.4 * macro_score + 0.3 * (1.0 if spread_ratio > 0 else 0.2) + 0.3 * np.clip(downstream_capex_growth, 0.0, 1.0))

        if is_impaired:
            summary = f"⚠️ 减值预警：现货价 ({spot_dxi_price:.2f}) 跌破锁价 ({lockin_prepay_cost:.2f})，触发二次惩罚漂移 {penalty_drift:.4f}"
        else:
            summary = f"✅ 景气共振：现货溢价率 {spread_ratio*100:.1f}%，韩国海关出口 YoY {korea_customs_export_yoy*100:.1f}%，无减值风险"

        return TriangulationSignal(
            ticker=ticker,
            macro_korea_export_yoy=korea_customs_export_yoy,
            spot_dx_price=spot_dxi_price,
            lockin_prepay_cost=lockin_prepay_cost,
            price_spread_ratio=spread_ratio,
            impairment_penalty_drift=penalty_drift,
            is_impaired=is_impaired,
            triangulation_confidence=confidence,
            status_summary=summary
        )
