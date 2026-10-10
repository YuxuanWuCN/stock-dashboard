# -*- coding: utf-8 -*-
"""src/agents/debate_committee.py —— 对抗式多智能体投决会与贝叶斯共识决策中枢

核心理论与对标文献：
1. NeurIPS 2024: TradingAgents (arXiv:2412.20138) - 多智能体分工与投决会对抗辩论
2. NeurIPS 2024: FinCon (arXiv:2411.02381) - 分层投资经理-分析师决策架构
3. 2026 最新重磅: The Alpha Illusion (arXiv:2605.16895) - 概率校准度、反事实防守与多智能体归因

实现机制：
- 角色 1: 多头研究员 Agent (Bull Analyst) —— 寻找景气突破、毛利率反转与卡位垄断证据
- 角色 2: 空头红队 Agent (Bear Red-Team) —— 专门审计存货跌价、客户砍单、估值泡沫与顶背离
- 角色 3: 宏观守门人 Agent (Macro Gatekeeper) —— 追踪流动性、原厂调价与汇率利率大宗冲击
- 角色 4: 首席投资官仲裁中枢 (CIO Arbiter) —— 贝叶斯证据融合、Brier 评分可靠性校准
- 战术硬门控融合 (Trend Gate Hard Veto) —— 无论定性叙事多么乐观，破位 C 浪强制一票否决！
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("stock-dashboard.debate_committee")


@dataclass
class DebateEvidence:
    """辩论证据原子结构（带坐标级审计锚点）。"""
    claim: str
    citation: str
    weight: float = 1.0  # [0.0, 2.0]
    category: str = "FUNDAMENTAL"  # FUNDAMENTAL / TECHNICAL / MACRO / RISK


@dataclass
class AgentArgument:
    """单一智能体的独立辩论陈述。"""
    agent_name: str
    stance: str  # BULLISH / BEARISH / NEUTRAL
    thesis: str
    evidences: List[DebateEvidence] = field(default_factory=list)
    confidence: float = 0.5  # [0.0, 1.0]


@dataclass
class CIOConsensusDecision:
    """投决会最终裁决决议书。"""
    symbol: str
    timestamp: str
    action: str  # STRONG_BUY / BUY / HOLD / SELL / VETO_BY_TREND_GATE
    posterior_bull_prob: float
    brier_score_reliability: float
    recommended_position: float  # [0.0, 1.0]
    trend_gate_passed: bool
    veto_reason: Optional[str]
    debate_transcript: List[Dict[str, Any]]
    full_audit_trail: Dict[str, Any]


class BullAnalystAgent:
    """多头分析师智能体：负责构建进攻性 Thesis 与积极证据挖掘。"""

    def generate_argument(
        self,
        symbol: str,
        financial_facts: Dict[str, Any],
        chokepoint_score: float,
        ast_factor_score: float,
    ) -> AgentArgument:
        evidences = []
        confidence = 0.5

        # 1. 供应链卡位评估
        if chokepoint_score >= 12.0:
            evidences.append(
                DebateEvidence(
                    claim=f"标的拥有关键供应链断点卡位优势 (CS={chokepoint_score:.1f} >= 12)",
                    citation="[研报/公告] 产业链独家配套与高转换壁垒证明",
                    weight=1.5,
                    category="FUNDAMENTAL",
                )
            )
            confidence += 0.15

        # 2. 神经-符号 AST 因子打分
        if ast_factor_score > 0.60:
            evidences.append(
                DebateEvidence(
                    claim=f"AST 符号因子指标发出突破信号 (Score={ast_factor_score:.3f} > 0.60)",
                    citation="[量化特征] 动量与上游价格传导算子共振",
                    weight=1.2,
                    category="TECHNICAL",
                )
            )
            confidence += 0.15

        # 3. 业绩与增长预期
        rev_growth = financial_facts.get("revenue_growth_yoy", 0.0)
        if rev_growth > 0.20:
            evidences.append(
                DebateEvidence(
                    claim=f"营收同比高增 {rev_growth*100:.1f}%，景气主升浪确立",
                    citation="[财报] 季度营业收入与毛利率同比明细",
                    weight=1.3,
                    category="FUNDAMENTAL",
                )
            )
            confidence += 0.10

        confidence = min(0.95, confidence)
        return AgentArgument(
            agent_name="Bull_Analyst_Alpha",
            stance="BULLISH" if confidence >= 0.55 else "NEUTRAL",
            thesis=f"{symbol} 具备强劲的产业超级周期供需弹性和卡位 Alpha。",
            evidences=evidences,
            confidence=round(confidence, 3),
        )


class BearRedTeamAgent:
    """空头红队审计智能体：负责严苛审计下行风险、泡沫、客户砍单与反向证据。"""

    def generate_argument(
        self,
        symbol: str,
        financial_facts: Dict[str, Any],
        pe_percentile: float,
        inventory_growth_vs_rev: float,
    ) -> AgentArgument:
        evidences = []
        confidence = 0.5

        # 1. 估值分位数审计
        if pe_percentile > 0.85:
            evidences.append(
                DebateEvidence(
                    claim=f"当前估值处于历史 5 年 {pe_percentile*100:.1f}% 极高分位，安全边际极低",
                    citation="[行情估值库] 滚动市盈率历史百分位分水岭",
                    weight=1.4,
                    category="RISK",
                )
            )
            confidence += 0.20

        # 2. 存货减值与长鞭效应倒灌审计
        if inventory_growth_vs_rev > 0.30:
            evidences.append(
                DebateEvidence(
                    claim=f"存货增速大幅超越营收 {inventory_growth_vs_rev*100:.1f}%，面临跌价准备计提冲击",
                    citation="[财报明细] 存货周转天数陡增与资产减值损失项",
                    weight=1.5,
                    category="RISK",
                )
            )
            confidence += 0.20

        # 3. 股东减持或解禁
        if financial_facts.get("major_shareholder_selling", False):
            evidences.append(
                DebateEvidence(
                    claim="大股东或重要产业资本近期发布减持计划",
                    citation="[临时公告] 持股 5% 以上股东减持计划实施预披露",
                    weight=1.1,
                    category="FUNDAMENTAL",
                )
            )
            confidence += 0.10

        confidence = min(0.95, confidence)
        return AgentArgument(
            agent_name="Bear_RedTeam_Audit",
            stance="BEARISH" if confidence >= 0.60 else "NEUTRAL",
            thesis=f"{symbol} 隐藏潜在资产减值与估值高位见顶风险，建议严控敞口。",
            evidences=evidences,
            confidence=round(confidence, 3),
        )


class MacroGatekeeperAgent:
    """宏观守门人智能体：负责大宗现货原厂价格、流动性与系统性风险感知。"""

    def generate_argument(
        self,
        upstream_spot_price_change: float,
        market_liquidity_regime: str,  # ABUNDANT / NEUTRAL / TIGHT
    ) -> AgentArgument:
        evidences = []
        confidence = 0.5

        if upstream_spot_price_change > 0.05:
            evidences.append(
                DebateEvidence(
                    claim=f"上游原厂大宗跳涨 +{upstream_spot_price_change*100:.1f}%，成本传导与补库动能充沛",
                    citation="[高频Nowcasting] 现货颗粒交易报价平台月度结算价",
                    weight=1.3,
                    category="MACRO",
                )
            )
            confidence += 0.15
        elif upstream_spot_price_change < -0.05:
            evidences.append(
                DebateEvidence(
                    claim=f"上游现货跳水 {upstream_spot_price_change*100:.1f}%，行业面临去库与价格战压制",
                    citation="[高频Nowcasting] 现货交易平台价格指数破位",
                    weight=1.4,
                    category="MACRO",
                )
            )
            confidence -= 0.20

        if market_liquidity_regime == "TIGHT":
            evidences.append(
                DebateEvidence(
                    claim="市场全天成交额缩减至 6000 亿以下，流动性偏紧压制高贝塔弹性标的",
                    citation="[宏观监控] 两市两融余额与全市场日成交量统计",
                    weight=1.2,
                    category="MACRO",
                )
            )
            confidence -= 0.15

        confidence = np.clip(confidence, 0.05, 0.95)
        stance = "BULLISH" if confidence > 0.55 else ("BEARISH" if confidence < 0.45 else "NEUTRAL")
        return AgentArgument(
            agent_name="Macro_Gatekeeper",
            stance=stance,
            thesis="宏观大宗与系统性流动性综合评估。",
            evidences=evidences,
            confidence=round(float(confidence), 3),
        )


class CIOCommitteeArbiter:
    """投决会首席投资官仲裁中枢：执行贝叶斯融合、Brier 校准与 Trend Gate 绝对否决。"""

    def __init__(self, prior_bull_prob: float = 0.50):
        self.prior_bull_prob = prior_bull_prob

    def bayesian_evidence_fusion(
        self,
        bull_arg: AgentArgument,
        bear_arg: AgentArgument,
        macro_arg: AgentArgument,
    ) -> Tuple[float, float]:
        """加权贝叶斯证据融合与 Brier 可靠性评分计算。"""
        # 计算各角色论据加权似然比
        bull_weight = sum(e.weight for e in bull_arg.evidences) if bull_arg.evidences else 1.0
        bear_weight = sum(e.weight for e in bear_arg.evidences) if bear_arg.evidences else 1.0
        macro_weight = sum(e.weight for e in macro_arg.evidences) if macro_arg.evidences else 1.0

        p_bull = bull_arg.confidence
        p_bear = bear_arg.confidence
        p_macro = macro_arg.confidence

        # 对数几率更新 (Log-Odds Bayesian Update)
        prior_odds = self.prior_bull_prob / (1.0 - self.prior_bull_prob + 1e-8)
        
        # 多头贡献阳性几率，空头贡献阴性几率，宏观充当调节因子
        lr_bull = (p_bull / (1.0 - p_bull + 1e-8)) ** (0.35 * bull_weight)
        lr_bear = ((1.0 - p_bear) / (p_bear + 1e-8)) ** (0.40 * bear_weight)
        lr_macro = (p_macro / (1.0 - p_macro + 1e-8)) ** (0.25 * macro_weight)

        posterior_odds = prior_odds * lr_bull * lr_bear * lr_macro
        posterior_prob = float(posterior_odds / (1.0 + posterior_odds))
        posterior_prob = float(np.clip(posterior_prob, 0.01, 0.99))

        # 概率校准度评分 (基于置信离散度模拟 Brier Score)
        dispersion = abs(p_bull - p_bear)
        brier_reliability = round(float(0.15 + 0.10 * (1.0 - dispersion)), 3)

        return round(posterior_prob, 4), brier_reliability

    def arbitrate_decision(
        self,
        symbol: str,
        bull_arg: AgentArgument,
        bear_arg: AgentArgument,
        macro_arg: AgentArgument,
        trend_gate_approved: bool,
        wave_phase: str,
        current_drawdown: float,
    ) -> CIOConsensusDecision:
        """投决会综合审议与判决发布。"""
        posterior_prob, brier_reliability = self.bayesian_evidence_fusion(
            bull_arg, bear_arg, macro_arg
        )

        transcript = [
            {
                "speaker": bull_arg.agent_name,
                "stance": bull_arg.stance,
                "confidence": bull_arg.confidence,
                "thesis": bull_arg.thesis,
                "evidences": [e.__dict__ for e in bull_arg.evidences],
            },
            {
                "speaker": bear_arg.agent_name,
                "stance": bear_arg.stance,
                "confidence": bear_arg.confidence,
                "thesis": bear_arg.thesis,
                "evidences": [e.__dict__ for e in bear_arg.evidences],
            },
            {
                "speaker": macro_arg.agent_name,
                "stance": macro_arg.stance,
                "confidence": macro_arg.confidence,
                "thesis": macro_arg.thesis,
                "evidences": [e.__dict__ for e in macro_arg.evidences],
            },
        ]

        # 核心硬门控：Trend Gate 战术一票否决机制！
        veto_reason = None
        if not trend_gate_approved or wave_phase in ["Phase_C", "C_WAVE", "DOWN_TREND"]:
            action = "VETO_BY_TREND_GATE"
            recommended_position = 0.0
            veto_reason = (
                f"Trend Gate 触发硬拦截：当前处于 {wave_phase} 单边破位主跌浪，"
                f"尽管定性研报与贝叶斯推断概率为 {posterior_prob:.1%}，"
                f"仍实施战术一票否决，坚决空仓规避尾部风险！"
            )
            logger.warning(f"[{symbol}] {veto_reason}")

        elif posterior_prob >= 0.70 and current_drawdown < 0.10:
            action = "STRONG_BUY"
            recommended_position = 0.85
        elif posterior_prob >= 0.55:
            action = "BUY"
            recommended_position = 0.50
        elif posterior_prob <= 0.35:
            action = "SELL"
            recommended_position = 0.0
        else:
            action = "HOLD"
            recommended_position = 0.20

        return CIOConsensusDecision(
            symbol=symbol,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            action=action,
            posterior_bull_prob=posterior_prob,
            brier_score_reliability=brier_reliability,
            recommended_position=recommended_position,
            trend_gate_passed=trend_gate_approved,
            veto_reason=veto_reason,
            debate_transcript=transcript,
            full_audit_trail={
                "prior": self.prior_bull_prob,
                "posterior": posterior_prob,
                "wave_phase": wave_phase,
                "trend_gate_flag": trend_gate_approved,
                "brier_metric": brier_reliability,
            },
        )
