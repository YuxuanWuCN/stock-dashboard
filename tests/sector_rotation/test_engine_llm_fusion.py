# -*- coding: utf-8 -*-
"""tests/sector_rotation/test_engine_llm_fusion.py —— 阶段3 决策融合（任务 2.2 遗留）

覆盖方案要求的三条路径：
1. LLM 同意   -> llm_validation.status='agreed'，量化结论原样保留
2. LLM 反对   -> 记录分歧（diverged），绝不推翻量化 should_rotate
3. LLM 异常/超时/不可用 -> 量化结论保留 + status='unavailable'（禁止静默伪造）
外加：默认参数（advisor=None）零行为变化。
"""

import json

import pytest

from src.sector_rotation.llm_decision_advisor import LLMDecisionAdvisor
from src.sector_rotation.sector_rotation_engine import SectorRotationEngine
from src.sector_rotation.utils.sector_utils import SectorState


# ----------------------------------------------------------------------------
# 夹具：storage 下沉、green 强景气 -> 量化必然给出 rotate storage->green
# ----------------------------------------------------------------------------

def _sector_states():
    return {
        "storage": SectorState(
            sector="storage", sentiment_score=-0.6, sentiment_trend="declining",
            volatility=0.2, stock_count=10, confidence=0.9),
        "green": SectorState(
            sector="green", sentiment_score=0.8, sentiment_trend="rising",
            volatility=0.1, stock_count=10, confidence=0.9),
        "gold": SectorState(
            sector="gold", sentiment_score=0.1, sentiment_trend="stable",
            volatility=0.05, stock_count=10, confidence=0.9),
    }


class _MockClient:
    """固定返回预置 JSON 文本的 LLM 客户端（走 advisor.complete 契约）。"""

    def __init__(self, response_text: str):
        self.response_text = response_text
        self.calls = 0

    def complete(self, system_prompt="", user_prompt="", max_tokens=0, temperature=0.0):
        self.calls += 1
        return self.response_text


class _TimeoutClient:
    """模拟网络超时的客户端。"""

    def complete(self, **kwargs):
        raise TimeoutError("LLM request timed out after 30s")


def _quant_decision(engine):
    """未注入 advisor 的纯量化基线决策。"""
    return engine.evaluate(
        current_sector="storage", sector_states=_sector_states(),
        holding_days=10, monthly_rotations=0, days_since_last_rotation=10,
    )


AGREE = json.dumps({
    "should_rotate": True, "target_sector": "green",
    "reason": "存储情绪持续下沉，新能源强景气，轮动合理", "confidence": 0.85,
})
DISAGREE = json.dumps({
    "should_rotate": False, "target_sector": None,
    "reason": "下沉尚属震荡，追高新能源风险更大", "confidence": 0.7,
})
DIFF_TARGET = json.dumps({
    "should_rotate": True, "target_sector": "gold",
    "reason": "应避险而非追涨", "confidence": 0.6,
})


class TestEngineLLMFusion:
    def setup_method(self):
        self.engine = SectorRotationEngine()

    # ------------------------------ 路径 1：同意 ------------------------------
    def test_llm_agreed(self):
        advisor = LLMDecisionAdvisor(llm_client=_MockClient(AGREE))
        decision = self.engine.evaluate(
            current_sector="storage", sector_states=_sector_states(),
            holding_days=10, monthly_rotations=0, days_since_last_rotation=10,
            advisor=advisor, llm_validation_enabled=True,
        )
        assert decision.should_rotate is True
        assert decision.target_sector == "green"
        assert decision.llm_validation["status"] == "agreed"
        assert decision.llm_validation["llm_target_sector"] == "green"
        assert decision.llm_rationale == "存储情绪持续下沉，新能源强景气，轮动合理"
        assert len(advisor.audit_log) == 1 and advisor.audit_log[0].success

    # ------------------------------ 路径 2：反对 ------------------------------
    def test_llm_disagreed_records_divergence_without_overriding(self):
        advisor = LLMDecisionAdvisor(llm_client=_MockClient(DISAGREE))
        decision = self.engine.evaluate(
            current_sector="storage", sector_states=_sector_states(),
            holding_days=10, monthly_rotations=0, days_since_last_rotation=10,
            advisor=advisor, llm_validation_enabled=True,
        )
        # 量化结论不被推翻（方案硬约束）
        assert decision.should_rotate is True
        assert decision.target_sector == "green"
        assert decision.llm_validation["status"] == "diverged"
        assert decision.llm_validation["llm_should_rotate"] is False
        # 分歧内容保留可审计
        assert "追高新能源" in decision.llm_validation["llm_reason"]

    def test_llm_diverged_on_different_target(self):
        advisor = LLMDecisionAdvisor(llm_client=_MockClient(DIFF_TARGET))
        decision = self.engine.evaluate(
            current_sector="storage", sector_states=_sector_states(),
            holding_days=10, monthly_rotations=0, days_since_last_rotation=10,
            advisor=advisor, llm_validation_enabled=True,
        )
        assert decision.should_rotate is True
        assert decision.target_sector == "green"  # 不采纳 LLM 的 gold
        assert decision.llm_validation["status"] == "diverged"

    # ------------------------------ 路径 3：降级 ------------------------------
    def test_llm_timeout_degrades_to_unavailable(self):
        advisor = LLMDecisionAdvisor(llm_client=_TimeoutClient())
        decision = self.engine.evaluate(
            current_sector="storage", sector_states=_sector_states(),
            holding_days=10, monthly_rotations=0, days_since_last_rotation=10,
            advisor=advisor, llm_validation_enabled=True,
        )
        # 量化结论保留
        assert decision.should_rotate is True
        assert decision.target_sector == "green"
        assert decision.llm_validation["status"] == "unavailable"
        # 降级原因如实记录（禁止静默）
        assert "TimeoutError" in (decision.llm_rationale or "")

    def test_llm_client_missing_degrades_to_unavailable(self):
        advisor = LLMDecisionAdvisor(llm_client=None)
        decision = self.engine.evaluate(
            current_sector="storage", sector_states=_sector_states(),
            holding_days=10, monthly_rotations=0, days_since_last_rotation=10,
            advisor=advisor, llm_validation_enabled=True,
        )
        assert decision.should_rotate is True
        assert decision.llm_validation["status"] == "unavailable"

    def test_advisor_raising_exception_does_not_break_pipeline(self):
        class _BoomClient:
            def complete(self, **kwargs):
                raise RuntimeError("boom")

        advisor = LLMDecisionAdvisor(llm_client=_BoomClient())
        decision = self.engine.evaluate(
            current_sector="storage", sector_states=_sector_states(),
            holding_days=10, monthly_rotations=0, days_since_last_rotation=10,
            advisor=advisor, llm_validation_enabled=True,
        )
        assert decision.should_rotate is True
        assert decision.llm_validation["status"] == "unavailable"

    # ------------------------------ 兼容性与门禁路径 ------------------------------
    def test_default_parameters_keep_behavior_unchanged(self):
        """advisor=None（默认）时 llm_validation 必须为 None，与旧行为逐字段一致。"""
        baseline = _quant_decision(self.engine)
        advisor = LLMDecisionAdvisor(llm_client=_MockClient(AGREE))
        same = self.engine.evaluate(
            current_sector="storage", sector_states=_sector_states(),
            holding_days=10, monthly_rotations=0, days_since_last_rotation=10,
            advisor=advisor,  # 传了 advisor 但未开启开关
        )
        assert baseline.llm_validation is None
        assert same.llm_validation is None
        assert baseline.to_dict()["should_rotate"] == same.to_dict()["should_rotate"]

    def test_gate_blocked_decisions_also_support_validation(self):
        """风控门禁拦截路径（持仓不足）同样可注入复核：LLM 同意 noop。"""
        noop_agree = json.dumps({
            "should_rotate": False, "target_sector": None,
            "reason": "持仓期不足，不宜频繁调仓", "confidence": 0.8,
        })
        advisor = LLMDecisionAdvisor(llm_client=_MockClient(noop_agree))
        decision = self.engine.evaluate(
            current_sector="storage", sector_states=_sector_states(),
            holding_days=2, monthly_rotations=0, days_since_last_rotation=10,
            advisor=advisor, llm_validation_enabled=True,
        )
        assert decision.should_rotate is False
        assert "Holding period too short" in decision.reason
        assert decision.llm_validation["status"] == "agreed"

    def test_decide_passthrough(self):
        """decide() 适配层必须把 advisor 参数透传到 evaluate()。"""
        advisor = LLMDecisionAdvisor(llm_client=_MockClient(AGREE))
        decision = self.engine.decide(
            sector_sentiments=_sector_states(), current_sector="storage",
            holding_days=10, advisor=advisor, llm_validation_enabled=True,
        )
        assert decision.llm_validation["status"] == "agreed"
