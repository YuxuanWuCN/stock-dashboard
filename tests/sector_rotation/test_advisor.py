# -*- coding: utf-8 -*-
"""tests/sector_rotation/test_advisor.py —— LLMDecisionAdvisor 单元测试套件

测试覆盖：
1. 结构化 Prompt 确定性构建测试 (包含持仓、目标、150字、JSON 格式规范)
2. 确定性执行参数测试 (temperature=0.2, timeout=30)
3. 纯净与多种包裹形式的 JSON 鲁棒解析 (Markdown 代码块、文本内嵌、多行格式)
4. 正常 Mock LLM 响应下的建议与验证处理流程
5. 异常降级能力测试 (LLMUnavailableError、网络超时 TimeoutError、通用 Exception)
6. 损坏/垃圾输出降级测试 (损坏括号、非 JSON 文本、缺失必填字段、空响应)
7. 无 LLM 客户端时的极速非阻塞降级测试 (即时回退、保留量化决策、耗时 < 5ms)
8. 结构化审计记录格式、留痕生命周期与历史查询 (AuditRecord, audit_log, clear_audit_log)
9. 辅助方法兼容性测试 (validate_decision, generate_reasoning)
"""

import json
import time
from typing import Any, Dict, Optional

import pytest

from src.sector_rotation.config import LLM_TIMEOUT
from src.sector_rotation.llm_decision_advisor import (
    AuditRecord,
    LLMDecisionAdvisor,
)
from src.sector_rotation.sector_rotation_engine import RotationDecision
from src.sector_rotation.utils.sector_utils import SectorState


# ============================================================================
# Mock 客户端工具
# ============================================================================

class MockSuccessfulLLMClient:
    """模拟返回合规 JSON 的正常大模型客户端"""

    def __init__(self, response_json_str: str) -> None:
        self.response_json_str = response_json_str
        self.call_count = 0
        self.last_system_prompt = ""
        self.last_user_prompt = ""
        self.last_temperature = 0.0

    @property
    def is_available(self) -> bool:
        return True

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.2,
    ) -> str:
        self.call_count += 1
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt
        self.last_temperature = temperature
        return self.response_json_str


class MockFailingLLMClient:
    """模拟抛出指定异常的网络或不可用大模型客户端"""

    def __init__(self, exception_to_raise: Exception) -> None:
        self.exception_to_raise = exception_to_raise
        self.call_count = 0

    @property
    def is_available(self) -> bool:
        return True

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.2,
    ) -> str:
        self.call_count += 1
        raise self.exception_to_raise


# ============================================================================
# 1. 结构化 Prompt 构建与确定性参数测试
# ============================================================================

def test_advisor_prompt_deterministic_construction() -> None:
    """验证 Prompt 能够正确组装持仓、候选目标、情绪指标与 150 字约束要求。"""
    advisor = LLMDecisionAdvisor(temperature=0.2)
    assert advisor.temperature == pytest.approx(0.2)
    assert advisor.timeout == LLM_TIMEOUT

    states = {
        "green": SectorState(sector="green", sentiment_score=-0.35, sentiment_trend="declining", confidence=0.85),
        "storage": SectorState(sector="storage", sentiment_score=0.65, sentiment_trend="rising", confidence=0.90, volatility=0.10),
    }
    quant_decision = RotationDecision(
        should_rotate=True,
        current_sector="green",
        target_sector="storage",
        reason="Quantitative decline threshold breach",
        confidence=0.85,
    )

    prompt = advisor.build_prompt(
        current_sector="green",
        target_sector="storage",
        sector_states=states,
        quant_decision=quant_decision,
    )

    assert "green" in prompt
    assert "storage" in prompt
    assert "should_rotate" in prompt
    assert "150" in prompt
    assert "JSON" in prompt


def test_advisor_prompt_positional_arguments_compatibility() -> None:
    """验证 build_prompt 在简写位置参数形式下的兼容性 (对齐 Tier 测试)。"""
    advisor = LLMDecisionAdvisor()
    prompt = advisor.build_prompt("green", "storage", -0.35, 0.65)
    assert "green" in prompt
    assert "storage" in prompt
    assert "should_rotate" in prompt


# ============================================================================
# 2. JSON 解析鲁棒性测试 (多种代码块与自由文本包裹)
# ============================================================================

def test_parse_llm_response_clean_json() -> None:
    """验证纯净 JSON 字符串的正常解析。"""
    advisor = LLMDecisionAdvisor()
    raw = json.dumps({
        "should_rotate": True,
        "target_sector": "storage",
        "reason": "存储芯片处于高景气周期，建议从下沉的绿电切换至存储。",
        "confidence": 0.92,
    })
    parsed = advisor._parse_llm_response(raw)
    assert parsed["should_rotate"] is True
    assert parsed["target_sector"] == "storage"
    assert "存储芯片" in parsed["reason"]
    assert parsed["confidence"] == pytest.approx(0.92)


def test_parse_llm_response_markdown_code_fences() -> None:
    """验证带 ```json ... ``` 和 ``` ... ``` 代码块包裹的文本解析。"""
    advisor = LLMDecisionAdvisor()
    raw_markdown = """这里是我的风控复核意见：
```json
{
    "should_rotate": true,
    "target_sector": "storage",
    "reason": "景气度大幅领先。",
    "confidence": 0.88
}
```
请遵照执行。"""
    parsed = advisor._parse_llm_response(raw_markdown)
    assert parsed["should_rotate"] is True
    assert parsed["target_sector"] == "storage"
    assert parsed["confidence"] == pytest.approx(0.88)


def test_parse_llm_response_string_booleans_and_long_reason_truncation() -> None:
    """验证布尔值作为字符串 ('true') 的自适应转换以及超过 150 字理由的优雅截断。"""
    advisor = LLMDecisionAdvisor()
    long_reason = "理由" * 100  # 200 字
    raw = json.dumps({
        "should_rotate": "true",
        "target_sector": "gold",
        "reason": long_reason,
        "confidence": 0.75,
    })
    parsed = advisor._parse_llm_response(raw)
    assert parsed["should_rotate"] is True
    assert parsed["target_sector"] == "gold"
    assert len(parsed["reason"]) <= 150
    assert parsed["reason"].endswith("...")


def test_parse_llm_response_invalid_json_raises_value_error() -> None:
    """验证非 JSON 格式、截断 JSON、空内容时抛出 ValueError。"""
    advisor = LLMDecisionAdvisor()
    with pytest.raises(ValueError):
        advisor._parse_llm_response("")

    with pytest.raises(ValueError):
        advisor._parse_llm_response("这只是一段普通文本，没有任何 JSON 结构。")

    with pytest.raises(ValueError):
        advisor._parse_llm_response('{"should_rotate": true, "target_sector": "storage"')  # 括号未闭合


# ============================================================================
# 3. 正常 Mock LLM 响应处理流程测试
# ============================================================================

def test_advise_successful_llm_response() -> None:
    """验证在 Mock LLM 正常返回时的决策合并与参数更新。"""
    mock_json = json.dumps({
        "should_rotate": True,
        "target_sector": "storage",
        "reason": "大模型风控确认：存储芯片迎来超级周期上行趋势。",
        "confidence": 0.89,
    })
    mock_client = MockSuccessfulLLMClient(mock_json)
    advisor = LLMDecisionAdvisor(llm_client=mock_client)

    states = {
        "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend="declining"),
        "storage": SectorState(sector="storage", sentiment_score=0.68, sentiment_trend="rising"),
    }
    quant_decision = RotationDecision(
        should_rotate=True,
        current_sector="green",
        target_sector="storage",
        reason="Quantitative decline breach",
        confidence=0.85,
    )

    final_decision = advisor.advise("green", states, quant_decision)

    assert final_decision.should_rotate is True
    assert final_decision.current_sector == "green"
    assert final_decision.target_sector == "storage"
    assert final_decision.confidence == pytest.approx(0.89)
    assert final_decision.is_fallback is False
    assert final_decision.llm_rationale == "大模型风控确认：存储芯片迎来超级周期上行趋势。"
    assert mock_client.call_count == 1
    assert mock_client.last_temperature == pytest.approx(0.2)

    # 验证审计日志记录
    assert len(advisor.audit_log) == 1
    last_audit = advisor.last_audit_record
    assert last_audit is not None
    assert last_audit.success is True
    assert last_audit.fallback_reason is None
    assert last_audit.parsed_decision["target_sector"] == "storage"


# ============================================================================
# 4. 异常非阻塞降级能力测试 (Non-Blocking Fallback)
# ============================================================================

def test_advise_fallback_on_network_timeout() -> None:
    """验证当 LLM 抛出 TimeoutError 时，优雅回退至量化决策，不抛异常。"""
    failing_client = MockFailingLLMClient(TimeoutError("Request timed out after 30 seconds"))
    advisor = LLMDecisionAdvisor(llm_client=failing_client)

    states = {
        "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend="declining"),
        "storage": SectorState(sector="storage", sentiment_score=0.65, sentiment_trend="rising"),
    }
    quant_decision = RotationDecision(
        should_rotate=True,
        current_sector="green",
        target_sector="storage",
        reason="Quantitative decline breach",
        confidence=0.85,
    )

    t0 = time.perf_counter()
    res = advisor.advise("green", states, quant_decision)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert elapsed_ms < 100.0
    assert res.should_rotate == quant_decision.should_rotate
    assert res.target_sector == quant_decision.target_sector
    assert res.is_fallback is True
    assert "TimeoutError" in res.llm_rationale

    # 验证审计日志
    last_audit = advisor.last_audit_record
    assert last_audit is not None
    assert last_audit.success is False
    assert "TimeoutError" in str(last_audit.fallback_reason)


def test_advise_fallback_on_custom_llm_unavailable_error() -> None:
    """验证当抛出 LLMUnavailableError 或 RuntimeError 时安全回退。"""
    class LLMUnavailableError(RuntimeError):
        pass

    failing_client = MockFailingLLMClient(LLMUnavailableError("API rate limit reached (429)"))
    advisor = LLMDecisionAdvisor(llm_client=failing_client)

    states = {
        "green": SectorState(sector="green", sentiment_score=-0.35, sentiment_trend="declining"),
        "storage": SectorState(sector="storage", sentiment_score=0.70, sentiment_trend="rising"),
    }
    quant_decision = RotationDecision(
        should_rotate=True,
        current_sector="green",
        target_sector="storage",
        reason="Quant trigger",
        confidence=0.80,
    )

    res = advisor.advise("green", states, quant_decision)
    assert res.should_rotate is True
    assert res.target_sector == "storage"
    assert res.is_fallback is True
    assert "LLMUnavailableError" in res.llm_rationale


def test_advise_fallback_on_malformed_garbage_json() -> None:
    """验证当 LLM 返回损坏的 JSON 或非格式化垃圾内容时安全回退。"""
    garbage_client = MockSuccessfulLLMClient("I am sorry, as an AI model I cannot decide: {broken_json")
    advisor = LLMDecisionAdvisor(llm_client=garbage_client)

    states = {
        "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend="declining"),
        "storage": SectorState(sector="storage", sentiment_score=0.65, sentiment_trend="rising"),
    }
    quant_decision = RotationDecision(
        should_rotate=True,
        current_sector="green",
        target_sector="storage",
        reason="Quant trigger",
        confidence=0.82,
    )

    res = advisor.advise("green", states, quant_decision)
    assert res.should_rotate is True
    assert res.target_sector == "storage"
    assert res.is_fallback is True
    assert "LLM degraded" in res.llm_rationale


# ============================================================================
# 5. 无客户端即时降级测试 (Sub-1ms Immediate Fallback)
# ============================================================================

def test_advise_immediate_fallback_when_no_client_provided() -> None:
    """验证当未传入 LLM 客户端时，立即非阻塞降级，完全不阻塞流水线。"""
    advisor = LLMDecisionAdvisor(llm_client=None)

    states = {
        "green": SectorState(sector="green", sentiment_score=-0.40, sentiment_trend="declining"),
        "storage": SectorState(sector="storage", sentiment_score=0.65, sentiment_trend="rising"),
    }
    quant_decision = RotationDecision(
        should_rotate=True,
        current_sector="green",
        target_sector="storage",
        reason="Quant trigger",
        confidence=0.85,
    )

    t0 = time.perf_counter()
    res = advisor.advise("green", states, quant_decision)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    # 严格验证：无客户端降级耗时应小于 5.0ms (远小于 100ms)
    assert elapsed_ms < 5.0
    assert res.should_rotate == quant_decision.should_rotate
    assert res.target_sector == quant_decision.target_sector
    assert res.is_fallback is True
    assert "LLM client not provided" in res.llm_rationale

    # 审计日志应正常沉淀
    assert len(advisor.audit_log) == 1
    audit = advisor.last_audit_record
    assert audit is not None
    assert audit.success is False
    assert "LLM client not provided" in audit.fallback_reason


# ============================================================================
# 6. 审计日志全生命周期与方法测试 (Audit Trail)
# ============================================================================

def test_advisor_audit_trail_lifecycle() -> None:
    """测试审计日志的累积、结构化字典导出与清空功能。"""
    advisor = LLMDecisionAdvisor()
    states = {"green": SectorState(sector="green", sentiment_score=-0.40)}
    quant_decision = RotationDecision(
        should_rotate=False,
        current_sector="green",
        target_sector=None,
        reason="Holding",
        confidence=0.80,
    )

    # 产生 3 次调用
    for _ in range(3):
        advisor.advise("green", states, quant_decision)

    assert len(advisor.audit_log) == 3
    history = advisor.get_audit_history()
    assert len(history) == 3
    assert isinstance(history[0], dict)
    assert "timestamp" in history[0]
    assert "prompt" in history[0]
    assert "final_decision" in history[0]

    # 清空审计日志
    advisor.clear_audit_log()
    assert len(advisor.audit_log) == 0
    assert advisor.last_audit_record is None


# ============================================================================
# 7. 辅助方法与规范兼容测试
# ============================================================================

def test_advisor_validate_decision_and_generate_reasoning() -> None:
    """验证 validate_decision 兼容适配与 generate_reasoning 文本生成能力。"""
    advisor = LLMDecisionAdvisor()
    quant_decision = RotationDecision(
        should_rotate=True,
        current_sector="green",
        target_sector="storage",
        reason="Quant decline",
        confidence=0.85,
    )
    states = {
        "green": SectorState(sector="green", sentiment_score=-0.40),
        "storage": SectorState(sector="storage", sentiment_score=0.65),
    }

    # validate_decision 契约兼容
    res = advisor.validate_decision(quant_decision, states)
    assert res.should_rotate is True
    assert res.target_sector == "storage"

    # generate_reasoning 归因生成
    reasoning = advisor.generate_reasoning({"storage": 0.75, "gold": 0.45})
    assert "存储芯片" in reasoning or "storage" in reasoning
    assert "0.75" in reasoning

    # generate_reasoning 空字典分支
    empty_reasoning = advisor.generate_reasoning({})
    assert "暂无有效" in empty_reasoning


def test_advisor_parser_edge_cases_and_null_target() -> None:
    """验证解析器在非字典 JSON、字段缺失及 null 目标板块时的行为。"""
    advisor = LLMDecisionAdvisor()

    # 1. 根对象为列表
    with pytest.raises(ValueError, match="必须为字典"):
        advisor._parse_llm_response("[1, 2, 3]")

    # 2. 缺失 should_rotate
    with pytest.raises(ValueError, match="缺失关键字段"):
        advisor._parse_llm_response('{"target_sector": "gold", "reason": "test"}')

    # 3. 目标板块为 "null", "none", 空字符串
    for null_val in ["null", "none", "", "NULL"]:
        parsed = advisor._parse_llm_response(
            json.dumps({"should_rotate": False, "target_sector": null_val, "reason": "Hold"})
        )
        assert parsed["target_sector"] is None


def test_advisor_disabled_clients_and_alternate_call_interfaces() -> None:
    """验证客户端禁用属性 (is_available=False, enabled=False) 与多种调用协议接口。"""
    states = {"green": SectorState(sector="green", sentiment_score=-0.40)}
    quant_decision = RotationDecision(
        should_rotate=True,
        current_sector="green",
        target_sector="storage",
        reason="Trigger",
        confidence=0.85,
    )

    # 1. is_available 为 False
    class UnavailableClient:
        is_available = False

    adv1 = LLMDecisionAdvisor(llm_client=UnavailableClient())
    r1 = adv1.advise("green", states, quant_decision)
    assert r1.is_fallback is True

    # 2. enabled 为 False
    class DisabledClient:
        enabled = False

    adv2 = LLMDecisionAdvisor(llm_client=DisabledClient())
    r2 = adv2.advise("green", states, quant_decision)
    assert r2.is_fallback is True

    # 3. 具备 generate() 接口的客户端
    class GenerateClient:
        def generate(self, prompt: str) -> str:
            return json.dumps({"should_rotate": True, "target_sector": "storage", "reason": "via generate", "confidence": 0.88})

    adv3 = LLMDecisionAdvisor(llm_client=GenerateClient())
    r3 = adv3.advise("green", states, quant_decision)
    assert r3.should_rotate is True
    assert r3.llm_rationale == "via generate"

    # 4. 可调用对象 Callable 客户端
    def callable_client(prompt: str) -> str:
        return json.dumps({"should_rotate": True, "target_sector": "storage", "reason": "via callable", "confidence": 0.86})

    adv4 = LLMDecisionAdvisor(llm_client=callable_client)
    r4 = adv4.advise("green", states, quant_decision)
    assert r4.should_rotate is True
    assert r4.llm_rationale == "via callable"

    # 5. 未知调用协议对象
    class UnknownClient:
        pass

    adv5 = LLMDecisionAdvisor(llm_client=UnknownClient())
    r5 = adv5.advise("green", states, quant_decision)
    assert r5.is_fallback is True
    assert "未知的 LLM 客户端调用契约" in r5.llm_rationale

